"""Deterministic FOWT simulation used by the public agent demo.

The agent never touches the FMU directly. It calls ``run_cosim()``, which owns
the environment generation, catenary mooring forces and FMU stepping.

For the private monorepo this file finds the FMU in ``../models``. For a
standalone public copy, place ``FOWT.fmu`` (Windows) and/or
``FOWT_linux.fmu`` (Linux) beside this file.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import sys
from dataclasses import dataclass

import numpy as np
from fmpy import extract, read_model_description
from fmpy.fmi2 import FMU2Slave
from fmu_signals import (
    MOORING_FORCE_INPUTS,
    MOTION_OUTPUTS,
    PITCH_COLLECTIVE_INPUT,
    WAVE_FORCE_INPUTS,
    WAVE_MOMENT_INPUTS,
    WIND_SPEED_INPUT,
    pack_line_force,
)
from scipy.optimize import brentq, fsolve

DT = 0.02
GRAVITY = 9.81

R_ANCHOR = 837.6
R_FAIRLEAD = 40.868
ANCHOR_DEPTH = -200.0
FAIRLEAD_DEPTH = -14.0
AZIMUTHS = (0.0, 2 * np.pi / 3, 4 * np.pi / 3)

# Simplified linear Froude-Krylov + added-mass surrogate coefficients (demo).
# Production integrations use full BEM hydrodynamics on the FMU side.
WATER_DENSITY_KG_M3 = 1025.0
WAVE_FORCE_AREA_M2 = 40.0
WAVE_ADDED_MASS_KG = 1.0e6
WAVE_MOMENT_ARM_M = 10.0

# NREL 5MW Region-3 steady operating-pitch schedule (Jonkman et al. 2009,
# NREL/TP-500-38060, Table 7-1): collective pitch (deg) vs hub-height wind
# speed (m/s), the turbine's published steady operating point above rated --
# same table as part2_dynamic_mooring/simulation/cosim_runner.py's
# NREL_PITCH_SCHEDULE, duplicated here since each part is a self-contained
# package. Replaces the per-step Ct(tipSpeedRatio, pitch)-table inversion this
# file used to compute, which held thrust constant by construction instead of
# matching the turbine's published operating point.
NREL_PITCH_SCHEDULE = (
    (11.4, 0.00), (12.0, 3.83), (13.0, 6.60), (14.0, 8.70), (15.0, 10.45),
    (16.0, 12.06), (17.0, 13.54), (18.0, 14.92), (19.0, 16.23), (20.0, 17.47),
    (21.0, 18.70), (22.0, 19.94), (23.0, 21.18), (24.0, 22.35), (25.0, 23.47),
)


def pitch_schedule(wind_speed: float) -> float:
    """Collective pitch (rad) from `NREL_PITCH_SCHEDULE`, linearly interpolated
    at `wind_speed` (clamped to 0 deg below 11.4 m/s, 23.47 deg above 25 m/s).
    Meant to be evaluated once per run at the run's mean wind speed and held
    fixed -- the real ROSCO generator-speed feedback loop that would track
    turbulence gust-by-gust isn't modelled here."""
    speeds, pitches_deg = zip(*NREL_PITCH_SCHEDULE)
    return float(np.radians(np.interp(wind_speed, speeds, pitches_deg)))


def _fmu_path() -> str:
    name = "FOWT_linux.fmu" if sys.platform.startswith("linux") else "FOWT.fmu"
    here = os.path.dirname(__file__)
    candidates = (
        os.path.join(here, name),
        os.path.join(here, "..", "models", name),
    )
    for path in candidates:
        if os.path.isfile(path):
            return os.path.abspath(path)
    raise FileNotFoundError(
        f"{name} not found. Place it beside simulation.py or in ../models."
    )


@dataclass(frozen=True)
class Mooring:
    fairlead_depth: float = -14.0
    anchor_depth: float = -200.0
    unstretched_length: float = 835.5
    mass_per_length: float = 108.63
    gravity: float = 9.81


MOORING = Mooring()


def _taut_solution(vertical_span: float, line_length: float, w: float) -> dict:
    a = (line_length**2 - vertical_span**2) / (2.0 * vertical_span)
    H = a * w
    x_max = a * np.arcsinh(line_length / a)
    T = float(np.hypot(H, w * line_length))
    return {"H": float(H), "T": T, "Lb": 0.0, "x_max": float(x_max)}


def _solve_catenary(horizontal_span: float) -> dict:
    cfg = MOORING
    vertical_span = abs(cfg.fairlead_depth - cfg.anchor_depth)
    line_length = cfg.unstretched_length
    w = cfg.mass_per_length * cfg.gravity
    taut = _taut_solution(vertical_span, line_length, w)

    if horizontal_span < 1.0:
        def residual(H):
            if H <= 0:
                return 1e10
            return (H / w) * np.arcsinh(w * line_length / H) - horizontal_span

        H = brentq(residual, 0.001, 1e9, xtol=0.1)
        Lb = 0.0
        Ls = line_length
    elif horizontal_span >= taut["x_max"]:
        return taut
    else:
        def residuals(values):
            H, Lb = values
            if H <= 0 or Lb < 0 or Lb >= line_length:
                return (1e10, 1e10)
            Ls = line_length - Lb
            z_end = np.sqrt((H / w) ** 2 + Ls**2) - H / w
            x_end = Lb + (H / w) * np.arcsinh(w * Ls / H)
            return (z_end - vertical_span, x_end - horizontal_span)

        H0 = max(
            w * (line_length**2 - vertical_span**2) / (2.0 * vertical_span),
            w * horizontal_span,
            w,
        )
        Lb0 = max(
            line_length - np.hypot(horizontal_span, vertical_span),
            0.0,
        )
        values, _, ier, msg = fsolve(residuals, [H0, Lb0], full_output=True)
        if ier not in (1, 2, 3, 4):
            raise RuntimeError(f"Catenary solve did not converge: {msg}")
        H, Lb = float(values[0]), max(float(values[1]), 0.0)
        Ls = line_length - Lb

    T = float(np.hypot(H, w * Ls))
    return {"H": float(H), "T": T, "Lb": float(Lb), "x_max": taut["x_max"]}


def _anchor(line_index: int) -> np.ndarray:
    az = AZIMUTHS[line_index]
    return np.array(
        [R_ANCHOR * np.cos(az), -R_ANCHOR * np.sin(az), ANCHOR_DEPTH]
    )


def _fairlead(state: dict, line_index: int) -> np.ndarray:
    az = AZIMUTHS[line_index]
    local = np.array(
        [R_FAIRLEAD * np.cos(az), -R_FAIRLEAD * np.sin(az), FAIRLEAD_DEPTH]
    )
    roll, pitch, yaw = state["roll"], state["pitch"], state["yaw"]
    rotation = np.array(
        [
            [1.0, -yaw, pitch],
            [yaw, 1.0, -roll],
            [-pitch, roll, 1.0],
        ]
    )
    translation = np.array([state["surge"], state["sway"], state["heave"]])
    return rotation @ local + translation


def _line_force(anchor: np.ndarray, fairlead: np.ndarray) -> tuple[float, ...]:
    dx, dy = fairlead[0] - anchor[0], fairlead[1] - anchor[1]
    offset = float(np.hypot(dx, dy))
    azimuth = float(np.arctan2(dy, dx))
    cat = _solve_catenary(offset)
    H, T = cat["H"], cat["T"]
    V = float(np.sqrt(max(T * T - H * H, 0.0)))
    fx = -H * np.cos(azimuth)
    fy = -H * np.sin(azimuth)
    fz = -V
    return float(fx), float(fy), float(fz), T


def _jonswap(Hs: float, Tp: float) -> tuple[np.ndarray, np.ndarray]:
    freqs = np.linspace(0.02, 0.5, 256)
    fp, gamma = 1.0 / Tp, 3.3
    alpha = 0.0624 / (0.230 + 0.0336 * gamma - 0.185 / (1.9 + gamma))
    sigma = np.where(freqs <= fp, 0.07, 0.09)
    r = np.exp(-((freqs - fp) ** 2) / (2 * sigma**2 * fp**2))
    S = (
        alpha
        * Hs**2
        * fp**4
        / freqs**5
        * np.exp(-1.25 * (fp / freqs) ** 4)
        * gamma**r
    )
    m0 = np.trapezoid(S, freqs)
    if m0 > 0:
        S *= (Hs / 4.0) ** 2 / m0
    return freqs, S


def _wave_series(Hs: float, Tp: float, duration: float) -> np.ndarray:
    rng = np.random.default_rng(42)
    freqs, S = _jonswap(Hs, Tp)
    df = freqs[1] - freqs[0]
    amps = np.sqrt(2 * S * df)
    phases = rng.uniform(0, 2 * np.pi, len(freqs))
    t = np.arange(0, duration, DT)
    return sum(
        a * np.cos(2 * np.pi * f * t + phase)
        for a, f, phase in zip(amps, freqs, phases)
    )


def _wind_series(U_hub: float, TI: float, duration: float) -> np.ndarray:
    rng = np.random.default_rng(42)
    freqs = np.linspace(0.001, 2.0, 256)
    L = 340.2
    sigma = TI * U_hub
    fL = freqs * L / U_hub
    S = (4 * sigma**2 * L / U_hub) / (1 + 6 * fL) ** (5 / 3)
    df = freqs[1] - freqs[0]
    amps = np.sqrt(2 * S * df)
    phases = rng.uniform(0, 2 * np.pi, len(freqs))
    t = np.arange(0, duration, DT)
    turbulence = sum(
        a * np.cos(2 * np.pi * f * t + phase)
        for a, f, phase in zip(amps, freqs, phases)
    )
    return U_hub + turbulence


def run_cosim(
    Hs: float,
    Tp: float,
    U_hub: float,
    TI: float,
    duration: float = 30.0,
) -> dict[str, np.ndarray]:
    """Run the real FOWT FMU with JONSWAP wind/wave and catenary moorings."""
    eta = _wave_series(Hs, Tp, duration)
    wind = _wind_series(U_hub, TI, duration)
    wave_force = (
        WATER_DENSITY_KG_M3 * GRAVITY * WAVE_FORCE_AREA_M2 * eta
        + WAVE_ADDED_MASS_KG * np.gradient(eta, DT)
    )
    wave_moment = wave_force * WAVE_MOMENT_ARM_M
    phi_ref = pitch_schedule(U_hub)

    path = _fmu_path()
    description = read_model_description(path)
    unzipdir = extract(path)
    vrs = {v.name: v.valueReference for v in description.modelVariables}
    fmu = FMU2Slave(
        guid=description.guid,
        unzipDirectory=unzipdir,
        modelIdentifier=description.coSimulation.modelIdentifier,
        instanceName="FOWT",
    )

    n = round(duration / DT)
    t = np.arange(n) * DT
    series = {name: np.zeros(n) for name in MOTION_OUTPUTS}
    tensions = {f"tension{i}": np.zeros(n) for i in (1, 2, 3)}
    anchors = [_anchor(i) for i in range(3)]

    try:
        fmu.instantiate()
        fmu.setupExperiment(startTime=0.0)
        fmu.enterInitializationMode()
        fmu.exitInitializationMode()

        mooring_vrs = [vrs[name] for name in MOORING_FORCE_INPUTS]
        wave_vrs = [vrs[name] for name in WAVE_FORCE_INPUTS]
        wave_moment_vrs = [vrs[name] for name in WAVE_MOMENT_INPUTS]
        wind_vr = vrs[WIND_SPEED_INPUT]
        pitch_vr = vrs[PITCH_COLLECTIVE_INPUT]
        motion_vrs = [vrs[name] for name in MOTION_OUTPUTS]

        for i in range(1, n):
            state = {name: series[name][i - 1] for name in MOTION_OUTPUTS}
            forces = []
            for line in range(3):
                fx, fy, fz, tension = _line_force(
                    anchors[line], _fairlead(state, line)
                )
                forces.extend(pack_line_force(fx, fy, fz))
                tensions[f"tension{line + 1}"][i] = tension

            V = float(wind[i])
            fmu.setReal(mooring_vrs, forces)
            fmu.setReal(wave_vrs, [float(wave_force[i]), 0.0, 0.0])
            fmu.setReal(wave_moment_vrs, [0.0, 0.0, float(wave_moment[i])])
            fmu.setReal([wind_vr], [V])
            fmu.setReal([pitch_vr], [phi_ref])
            fmu.doStep(
                currentCommunicationPoint=t[i - 1],
                communicationStepSize=DT,
            )

            values = fmu.getReal(motion_vrs)
            for name, value in zip(MOTION_OUTPUTS, values):
                series[name][i] = value
    finally:
        with contextlib.suppress(Exception):
            fmu.terminate()
        # no freeInstance: crashes on the CVODE FMU's SUNDIALS teardown
        shutil.rmtree(unzipdir, ignore_errors=True)

    return {"time": t, **series, **tensions}
