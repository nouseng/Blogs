"""Self-contained support code for part2_dynamic_mooring_notebook.ipynb.

Everything the notebook needs -- mooring models, wind/wave generators, FMU
stepping, plotting -- lives in this one file, so the notebook only ever
does `from notebook_helpers import *`. No other module in this repo is
imported; only third-party packages (numpy, pandas, plotly, scipy,
onnxruntime, fmpy) and the data files under ../models and
../../part1_mooring_surrogate/public/data.
"""
import json
import os
import time
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.optimize import brentq, fsolve

HERE = os.path.dirname(__file__)
FMU_PATH = os.path.join(HERE, "..", "models", "FOWT.fmu")
ONNX_DATA_DIR = os.path.join(HERE, "..", "..", "part1_mooring_surrogate", "public", "data")

SEA_STATES = {
    "operational": {"Hs": 2.5, "Tp": 10.0, "U_hub": 12.0, "TI": 0.06},
    "storm": {"Hs": 6.0, "Tp": 14.0, "U_hub": 20.0, "TI": 0.12},
}
# 200s, not 600s: the OpenModelica-generated FOWT FMU's C runtime leaks memory
# per doStep() and aborts (gc/memory_pool.c pool_expand assertion) somewhere
# between 200s and 300s of simulated time at dt=0.1.
DURATION = 200.0  # s
# Communication step for the CVODE FMU; pass to run_cosim.
COSIM_DT = 0.02  # s

TENSION_KEYS = ["tension1", "tension2", "tension3"]


# ── mooring geometry (3-line OC4 layout) ─────────────────────────────────────

R_ANCHOR = 837.6     # m, OC4 anchor radius from platform centerline
R_FAIRLEAD = 40.868  # m, OC4 fairlead radius from platform centerline
ANCHOR_DEPTH = -200.0   # m, OC4 anchor depth (world z)
FAIRLEAD_DEPTH = -14.0  # m, OC4 fairlead depth below platform CG
AZIMUTHS = (0.0, 2 * np.pi / 3, 4 * np.pi / 3)


def anchor_position(line_index: int) -> np.ndarray:
    """World-frame (x, y, z) position of the anchor for the given line index (0-2).

    Sway (y) sign is negated relative to a naive sin(az): PlatformBody.mo's
    mooringLineNRotation maps local (R, -depth, 0) -> world (R*cos(az), -depth,
    -R*sin(az)), confirmed empirically in OpenModelica. Matching that sign here
    keeps the anchor on the same azimuth as its fairlead in the FMU's frame.
    """
    az = AZIMUTHS[line_index]
    return np.array([R_ANCHOR * np.cos(az), -R_ANCHOR * np.sin(az), ANCHOR_DEPTH])


def fairlead_world_position(platform_state: dict, line_index: int) -> np.ndarray:
    """World-frame (x, y, z) position of the fairlead, small-angle rotation."""
    az = AZIMUTHS[line_index]
    local = np.array([R_FAIRLEAD * np.cos(az), -R_FAIRLEAD * np.sin(az), FAIRLEAD_DEPTH])
    roll, pitch, yaw = platform_state["roll"], platform_state["pitch"], platform_state["yaw"]
    rotation = np.array([
        [1.0, -yaw, pitch],
        [yaw, 1.0, -roll],
        [-pitch, roll, 1.0],
    ])
    rotated = rotation @ local
    translation = np.array([platform_state["surge"], platform_state["sway"], platform_state["heave"]])
    return rotated + translation


def resolve_line_force(anchor_xyz, fairlead_xyz, mooring_model) -> tuple[float, float, float, float]:
    """Resolve a mooring line's force on the fairlead into world-frame (Fx, Fy, Fz, tension_N)."""
    dx = fairlead_xyz[0] - anchor_xyz[0]
    dy = fairlead_xyz[1] - anchor_xyz[1]
    horizontal_offset = float(np.hypot(dx, dy))
    azimuth = float(np.arctan2(dy, dx))

    result = mooring_model.compute(horizontal_offset)

    fx = -result["horizontal_force_N"] * np.cos(azimuth)
    fy = -result["horizontal_force_N"] * np.sin(azimuth)
    # Anchor is always deeper than the fairlead, so the line always pulls down.
    fz = -result["vertical_force_N"]
    return fx, fy, fz, result["fairlead_tension_N"]


# ── mooring models: same compute(offset) -> dict interface ──────────────────

@dataclass(frozen=True)
class _OC4Mooring:
    fairlead_depth: float = -14.0
    anchor_depth: float = -200.0
    unstretched_length: float = 835.5
    mass_per_length: float = 108.63      # kg/m in water (submerged, apparent mass — Robertson et al. 2014 Table 5-1; NOT the 113.35 kg/m dry mass density)
    gravity: float = 9.81


OC4_MOORING = _OC4Mooring()


def _taut_solution(vertical_span: float, line_length: float, w: float) -> dict:
    """Return the Lb=0 catenary solution (maximum horizontal extent)."""
    a = (line_length ** 2 - vertical_span ** 2) / (2.0 * vertical_span)
    H = a * w
    x_max = a * np.arcsinh(line_length / a)
    T = float(np.sqrt(H ** 2 + (w * line_length) ** 2))
    return {"horizontal_tension": float(H), "fairlead_tension": T,
            "seabed_length": 0.0, "x_max": x_max}


def _solve_catenary(horizontal_span: float, vertical_span: float,
                     line_length: float, w: float) -> dict:
    """Solve static catenary with seabed contact (Newton/Powell hybrid via fsolve)."""
    if line_length <= 0 or w <= 0:
        raise ValueError("line_length and w must be positive")

    taut = _taut_solution(vertical_span, line_length, w)
    x_max = taut["x_max"]
    is_near_vertical = horizontal_span < 1.0 and vertical_span > 10.0

    if is_near_vertical:
        def residual_1d(H):
            if H <= 0:
                return 1e10
            return (H / w) * np.arcsinh(w * line_length / H) - horizontal_span

        try:
            H = brentq(residual_1d, 0.001, 1e9, xtol=0.1)
        except (ValueError, RuntimeError):
            H = w * horizontal_span if horizontal_span > 0 else 0.1
        L_b, L_s = 0.0, line_length
    elif horizontal_span >= x_max:
        return taut
    else:
        def residuals(params):
            H, L_b = params
            if H <= 0 or L_b < 0 or L_b >= line_length:
                return [1e10, 1e10]
            L_s = line_length - L_b
            z_end = np.sqrt((H / w) ** 2 + L_s ** 2) - H / w
            x_end = L_b + (H / w) * np.arcsinh(w * L_s / H)
            return [z_end - vertical_span, x_end - horizontal_span]

        H0 = (w * (line_length ** 2 - vertical_span ** 2) / (2.0 * vertical_span)
              if vertical_span > 0 else w * horizontal_span)
        H0 = max(H0, w * horizontal_span, w)
        L_b0 = max(line_length - np.sqrt(horizontal_span ** 2 + vertical_span ** 2), 0.0)
        result, _, ier, _msg = fsolve(residuals, [H0, L_b0], full_output=True)
        res_norm = float(np.linalg.norm(residuals(result)))
        if ier not in (1, 2, 3, 4) and res_norm > 2.0:
            # Jacobian gets ill-conditioned near taut; a perturbed guess finds the same root.
            result, _, ier, _msg = fsolve(residuals, [H0 * 1.05, L_b0], full_output=True)
            res_norm = float(np.linalg.norm(residuals(result)))
        if ier not in (1, 2, 3, 4) and res_norm > 2.0:
            if horizontal_span > 0.98 * x_max:
                return taut
            warnings.warn(
                f"_solve_catenary did not converge at offset={horizontal_span}m "
                f"(residual={res_norm:.3g}, not near taut); using Lb=0 approximation.",
                stacklevel=2,
            )
            return taut
        H, L_b = result
        L_b = max(L_b, 0.0)
        L_s = line_length - L_b

    return {
        "horizontal_tension": float(H),
        "fairlead_tension": float(np.sqrt(H ** 2 + (w * L_s) ** 2)),
        "seabed_length": float(L_b),
    }


class CatenaryMooring:
    """Analytical OC4 catenary mooring model -- solved fresh on every call."""

    def __init__(self, cfg: _OC4Mooring = OC4_MOORING):
        self.cfg = cfg

    def compute(self, horizontal_offset: float) -> dict:
        w = self.cfg.mass_per_length * self.cfg.gravity
        res = _solve_catenary(horizontal_offset,
                               abs(self.cfg.fairlead_depth - self.cfg.anchor_depth),
                               self.cfg.unstretched_length, w)
        H, T = res["horizontal_tension"], res["fairlead_tension"]
        V = float(np.sqrt(max(T * T - H * H, 0.0)))
        return {
            "fairlead_tension_N": T,
            "horizontal_force_N": H,
            "vertical_force_N": V,
        }


_ONNX_FILENAMES = {
    "horizontal_force_N": "mooring_surrogate_fx.onnx",
    "vertical_force_N": "mooring_surrogate_fz.onnx",
    "fairlead_tension_N": "mooring_surrogate_t.onnx",
}
_ONNX_METADATA_FILE = "surrogate_metadata.json"

_w = OC4_MOORING.mass_per_length * OC4_MOORING.gravity
_vs = abs(OC4_MOORING.fairlead_depth - OC4_MOORING.anchor_depth)
_TAUT = _taut_solution(_vs, OC4_MOORING.unstretched_length, _w)
_X_MAX = _TAUT["x_max"]  # ~= 807.6 m


class OnnxMooring:
    """Part 1 ONNX mooring surrogate, cached at construction (no per-call solve).

    Inputs are clipped to the catenary's physical taut limit so the surrogate
    cannot extrapolate into the fully-extended regime where its training data
    is sparse and the catenary itself returns a capped value.
    """

    def __init__(self, data_dir: str = ONNX_DATA_DIR, pretension_factor: float = 1.0,
                 water_depth: float = 200.0):
        import onnxruntime as rt

        self.pretension_factor = pretension_factor
        self.water_depth = water_depth

        paths = {t: os.path.join(data_dir, f) for t, f in _ONNX_FILENAMES.items()}
        self.sessions = {
            t: rt.InferenceSession(p, providers=["CPUExecutionProvider"])
            for t, p in paths.items()
        }

        self.y_scale = 1.0
        meta_path = os.path.join(data_dir, _ONNX_METADATA_FILE)
        if os.path.exists(meta_path):
            with open(meta_path) as f:
                self.y_scale = json.load(f).get("y_scale", 1.0)

    def compute(self, horizontal_offset: float) -> dict:
        if horizontal_offset >= _X_MAX:
            return {
                "fairlead_tension_N": _TAUT["fairlead_tension"],
                "horizontal_force_N": _TAUT["horizontal_tension"],
                "vertical_force_N": float(
                    np.sqrt(max(_TAUT["fairlead_tension"] ** 2
                                - _TAUT["horizontal_tension"] ** 2, 0.0))
                ),
            }
        x = np.array([[horizontal_offset, self.pretension_factor, self.water_depth]], dtype=np.float32)
        return {
            t: float(s.run(None, {"input": x})[0].ravel()[0]) * self.y_scale
            for t, s in self.sessions.items()
        }


# ── wind / wave generators ───────────────────────────────────────────────────

def jonswap_spectrum(Hs: float, Tp: float, gamma: float = 3.3,
                      n_freqs: int = 256, f_min: float = 0.02,
                      f_max: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
    """JONSWAP wave energy spectrum. Returns: (frequencies [Hz], spectral density [m^2/Hz])."""
    freqs = np.linspace(f_min, f_max, n_freqs)
    fp = 1.0 / Tp
    alpha = 0.0624 / (0.230 + 0.0336 * gamma - 0.185 / (1.9 + gamma))
    sigma = np.where(freqs <= fp, 0.07, 0.09)
    r = np.exp(-((freqs - fp) ** 2) / (2 * sigma ** 2 * fp ** 2))
    S_pm = (alpha * Hs ** 2 * fp ** 4 / freqs ** 5) * np.exp(-1.25 * (fp / freqs) ** 4)
    S = S_pm * gamma ** r
    m0 = np.trapezoid(S, freqs)
    if m0 > 0:
        S *= (Hs / 4.0) ** 2 / m0
    return freqs, S


def generate_wave_timeseries(Hs: float, Tp: float, duration: float = 600.0,
                              dt: float = 0.05, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    """Irregular wave elevation time series from a JONSWAP spectrum. Returns (time, eta)."""
    rng = np.random.default_rng(seed)
    freqs, S = jonswap_spectrum(Hs, Tp)
    df = freqs[1] - freqs[0]
    amplitudes = np.sqrt(2 * S * df)
    phases = rng.uniform(0, 2 * np.pi, len(freqs))
    t = np.arange(0, duration, dt)
    eta = sum(a * np.cos(2 * np.pi * f * t + phi) for a, f, phi in zip(amplitudes, freqs, phases))
    return t, eta


def kaimal_spectrum(U_hub: float, TI: float, L: float = 340.2,
                     n_freqs: int = 256, f_min: float = 0.001,
                     f_max: float = 2.0) -> tuple[np.ndarray, np.ndarray]:
    """Kaimal longitudinal wind turbulence spectrum (IEC 61400-1 Ed.3)."""
    freqs = np.linspace(f_min, f_max, n_freqs)
    sigma = TI * U_hub
    f_L = freqs * L / U_hub
    S = (4 * sigma ** 2 * L / U_hub) / (1 + 6 * f_L) ** (5 / 3)
    return freqs, S


def generate_wind_timeseries(U_hub: float, TI: float, duration: float = 600.0,
                              dt: float = 0.05, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    """Longitudinal wind speed time series from a Kaimal spectrum. Returns (time, wind speed)."""
    rng = np.random.default_rng(seed)
    freqs, S = kaimal_spectrum(U_hub, TI)
    df = freqs[1] - freqs[0]
    amplitudes = np.sqrt(2 * S * df)
    phases = rng.uniform(0, 2 * np.pi, len(freqs))
    t = np.arange(0, duration, dt)
    turbulence = sum(a * np.cos(2 * np.pi * f * t + phi) for a, f, phi in zip(amplitudes, freqs, phases))
    turbulence = turbulence - turbulence.mean()  # kill the low-freq DC leak so mean == U_hub
    return t, U_hub + turbulence


def wave_loads(eta: np.ndarray, dt: float, rho: float = 1025.0,
               A_wp: float = 40.0, moment_arm: float = 10.0) -> tuple[np.ndarray, np.ndarray]:
    """Simplified Morison-type surge force and pitch moment from wave elevation."""
    deta_dt = np.gradient(eta, dt)
    f_wave = rho * 9.81 * A_wp * eta + 1.0e6 * deta_dt
    m_wave = f_wave * moment_arm
    return f_wave, m_wave


# ── FMU co-simulation loop ───────────────────────────────────────────────────

# Mooring inputs: forceML{line}[{component}], components 1=x(surge), 2=y(heave), 3=z(sway)
MOORING_INPUT_NAMES = [f"forceML{i}[{j}]" for i in (1, 2, 3) for j in (1, 2, 3)]
WAVE_INPUT_NAMES = ["waveForces[1]", "waveForces[2]", "waveForces[3]"]
WAVE_MOMENT_INPUT_NAMES = ["waveMoments[1]", "waveMoments[2]", "waveMoments[3]"]
MOTION_OUTPUT_NAMES = ["surge", "sway", "heave", "roll", "pitch", "yaw"]
SCALAR_OUTPUT_NAMES = ["rotorThrust", "bladePitchActual"]

# NREL 5MW Region-3 gain schedule (Jonkman et al. 2009, NREL/TP-500-38060,
# Table 7-1): collective pitch (deg) vs hub-height wind speed (m/s), the
# turbine's published steady operating point above rated. Replaces the
# earlier per-step Ct-table inversion, which held thrust constant by
# construction (Ct ~ V^-2) regardless of wind speed.
NREL_PITCH_SCHEDULE = (
    (11.4, 0.00), (12.0, 3.83), (13.0, 6.60), (14.0, 8.70), (15.0, 10.45),
    (16.0, 12.06), (17.0, 13.54), (18.0, 14.92), (19.0, 16.23), (20.0, 17.47),
    (21.0, 18.70), (22.0, 19.94), (23.0, 21.18), (24.0, 22.35), (25.0, 23.47),
)


def pitch_schedule(wind_speed: float) -> float:
    """Collective pitch (rad) from `NREL_PITCH_SCHEDULE`, linearly interpolated
    at `wind_speed` (clamped to 0 deg below 11.4 m/s, 23.47 deg above 25 m/s).
    Meant to be evaluated once per run at the sea state's mean wind speed and
    held fixed -- the real ROSCO generator-speed feedback loop that would track
    turbulence gust-by-gust isn't modelled here."""
    speeds, pitches_deg = zip(*NREL_PITCH_SCHEDULE)
    return float(np.radians(np.interp(wind_speed, speeds, pitches_deg)))


def run_cosim(mooring_model, sea_state: str, duration: float = 600.0,
              dt: float = 0.02) -> dict:
    """Step the FOWT FMU for `sea_state`, computing 3 mooring line forces each step.

    The FMU embeds a CVODE internal solver, so the communication `dt` only needs
    to resolve the platform/wave dynamics; 0.02 is a good default.

    Wave elevation and wind speed are generated from the sea state parameters
    and fed into the FMU as external inputs each step. `mooring_model` must
    implement `.compute(horizontal_offset) -> dict` with keys
    `fairlead_tension_N`, `horizontal_force_N`, `vertical_force_N`.

    Collective pitch is fixed for the whole run at `pitch_schedule(env["U_hub"])`
    -- the sea state's mean wind speed's published steady operating point, not
    re-targeted every step -- so turbulence produces natural thrust variation
    instead of being cancelled by an idealized per-step controller.

    Returns dict of time series: time, surge, sway, heave, roll, pitch, yaw,
    rotorThrust, bladePitchActual, tension1, tension2, tension3.
    """
    from fmpy import extract, read_model_description
    from fmpy.fmi2 import FMU2Slave

    env = SEA_STATES[sea_state]
    _, eta = generate_wave_timeseries(env["Hs"], env["Tp"], duration=duration, dt=dt)
    _, u_wind = generate_wind_timeseries(env["U_hub"], env["TI"], duration=duration, dt=dt)
    f_wave, m_wave = wave_loads(eta, dt)  # surge force + Z pitch moment; sway/heave wave = 0
    phi_ref = pitch_schedule(env["U_hub"])

    description = read_model_description(FMU_PATH)
    unzipdir = extract(FMU_PATH)
    vrs = {v.name: v.valueReference for v in description.modelVariables}

    fmu = FMU2Slave(
        guid=description.guid,
        unzipDirectory=unzipdir,
        modelIdentifier=description.coSimulation.modelIdentifier,
        instanceName="FOWT",
    )
    fmu.instantiate()
    fmu.setupExperiment(startTime=0.0)
    fmu.enterInitializationMode()
    fmu.exitInitializationMode()

    n = round(duration / dt)
    t = np.arange(n) * dt

    output_names = MOTION_OUTPUT_NAMES + SCALAR_OUTPUT_NAMES
    series = {key: np.zeros(n) for key in output_names}
    tensions = {f"tension{i}": np.zeros(n) for i in (1, 2, 3)}

    anchors = [anchor_position(i) for i in range(3)]
    mooring_vrs = [vrs[name] for name in MOORING_INPUT_NAMES]
    wave_vrs = [vrs[name] for name in WAVE_INPUT_NAMES]
    wave_moment_vrs = [vrs[name] for name in WAVE_MOMENT_INPUT_NAMES]
    wind_vr = vrs["windSpeed"]
    pitch_vr = vrs["pitchCollective"]
    output_vrs = [vrs[name] for name in output_names]

    for i in range(1, n):
        platform_state = {key: series[key][i - 1] for key in MOTION_OUTPUT_NAMES}

        forces = []
        for line_index in range(3):
            fairlead = fairlead_world_position(platform_state, line_index)
            fx, fy, fz, tension = resolve_line_force(anchors[line_index], fairlead, mooring_model)
            # fx=surge, fy=sway, fz=heave (line_geometry convention) -> FMU slots are
            # forceML{line}[1]=surge, [2]=heave, [3]=sway, so fz/fy must swap order here.
            forces.extend([fx, fz, fy])
            tensions[f"tension{line_index + 1}"][i] = tension

        V = float(u_wind[i])

        fmu.setReal(mooring_vrs, forces)
        fmu.setReal(wave_vrs, [float(f_wave[i]), 0.0, 0.0])
        fmu.setReal(wave_moment_vrs, [0.0, 0.0, float(m_wave[i])])
        fmu.setReal([wind_vr], [V])
        fmu.setReal([pitch_vr], [phi_ref])

        fmu.doStep(currentCommunicationPoint=t[i - 1], communicationStepSize=dt)

        values = fmu.getReal(output_vrs)
        for key, value in zip(output_names, values):
            series[key][i] = value

    fmu.terminate()
    # no freeInstance: crashes on the CVODE FMU's SUNDIALS teardown

    return {"time": t, **series, **tensions}


def run_sea_state_timed(name: str) -> dict:
    """Run the FOWT FMU once per mooring model for `name`, timed.

    This is the actual fmu run + mooring coupling: run_cosim resolves each
    line's fairlead position from the platform state, feeds it through
    `mooring_model.compute(offset)`, and steps the FMU with the resulting
    forces -- once with CatenaryMooring, once with OnnxMooring.
    """
    catenary = CatenaryMooring()
    onnx = OnnxMooring()

    t0 = time.perf_counter()
    result_catenary = run_cosim(catenary, sea_state=name, duration=DURATION, dt=COSIM_DT)
    t_catenary = time.perf_counter() - t0

    t0 = time.perf_counter()
    result_onnx = run_cosim(onnx, sea_state=name, duration=DURATION, dt=COSIM_DT)
    t_onnx = time.perf_counter() - t0

    errs = np.concatenate([np.abs(result_catenary[k] - result_onnx[k]) for k in TENSION_KEYS])
    return {
        "catenary": result_catenary,
        "onnx": result_onnx,
        "runtime_catenary_s": t_catenary,
        "runtime_onnx_s": t_onnx,
        "mean_abs_error_kN": float(errs.mean()) / 1e3,
        "max_abs_error_kN": float(errs.max()) / 1e3,
    }


# ── plotting / summary helpers ───────────────────────────────────────────────

def plot_environment(sea_states: dict = SEA_STATES, duration: float = DURATION) -> go.Figure:
    fig = make_subplots(rows=2, cols=2, shared_xaxes=True,
                         subplot_titles=list(sea_states.keys()), vertical_spacing=0.08)
    for col, (name, params) in enumerate(sea_states.items(), start=1):
        t_wind, wind = generate_wind_timeseries(params["U_hub"], params["TI"], duration=duration)
        t_wave, eta = generate_wave_timeseries(params["Hs"], params["Tp"], duration=duration)
        fig.add_trace(go.Scatter(x=t_wind, y=wind, line={"color": "#1f77b4"}), row=1, col=col)
        fig.add_trace(go.Scatter(x=t_wave, y=eta, line={"color": "#2ca02c"}), row=2, col=col)
    fig.update_yaxes(title_text="Wind speed (m/s)", row=1, col=1)
    fig.update_yaxes(title_text="Wave elevation (m)", row=2, col=1)
    fig.update_xaxes(title_text="Time (s)", row=2, col=1)
    fig.update_xaxes(title_text="Time (s)", row=2, col=2)
    fig.update_layout(height=500, showlegend=False,
                       title="Wind speed and wave elevation, both sea states")
    return fig


def plot_tension(results: dict, title: str) -> go.Figure:
    fig = go.Figure()
    t = results["catenary"]["time"]
    for i in (1, 2, 3):
        key = f"tension{i}"
        fig.add_trace(go.Scatter(x=t, y=results["catenary"][key] / 1e3, name=f"Line {i} catenary"))
        fig.add_trace(go.Scatter(x=t, y=results["onnx"][key] / 1e3, name=f"Line {i} ONNX",
                                  line={"dash": "dot"}))
    fig.update_layout(title=title, xaxis_title="Time (s)", yaxis_title="Fairlead tension (kN)", height=400)
    return fig


def plot_angles(results: dict, title: str) -> go.Figure:
    fig = go.Figure()
    t = results["catenary"]["time"]
    for key, label in [("roll", "Roll (heel)"), ("pitch", "Pitch (trim)"), ("yaw", "Yaw")]:
        fig.add_trace(go.Scatter(x=t, y=results["catenary"][key] * 180.0 / np.pi, name=label))
    fig.update_layout(title=title, xaxis_title="Time (s)", yaxis_title="Angle (deg)", height=400)
    return fig


SETTLE_SECONDS = 20.0  # skip initial-condition transient in headline stats


def summary_table(results: dict) -> pd.Series:
    """Dynamic-response summary: catenary trajectory, first SETTLE_SECONDS excluded.

    Raw first-step peak tensions are reported alongside the settled range so
    initial-condition contamination doesn't dominate the headline numbers.
    """
    cat = results["catenary"]
    t = cat["time"]
    mask = t >= SETTLE_SECONDS
    heave0 = cat["heave"][1]  # first real FMU sample (t=0 is a Python-side placeholder)
    surge = cat["surge"][mask]
    heave = cat["heave"][mask] - heave0
    rows = {
        "Surge, mean (m)": surge.mean(),
        "Surge, max abs (m)": np.abs(surge).max(),
        "Heave, dynamic range (m)": heave.max() - heave.min(),
        "Roll, max abs (deg)": np.abs(cat["roll"][mask] * 180 / np.pi).max(),
        "Pitch, max abs (deg)": np.abs(cat["pitch"][mask] * 180 / np.pi).max(),
        "Yaw, max abs (deg)": np.abs(cat["yaw"][mask] * 180 / np.pi).max(),
    }
    for i in (1, 2, 3):
        key = f"tension{i}"
        settled = cat[key][mask] / 1e3
        raw = cat[key][1:] / 1e3
        rows[f"Tension {i}, settled range (kN)"] = f"{settled.min():.0f} - {settled.max():.0f}"
        rows[f"Tension {i}, raw peak (kN)"] = f"{raw.max():.0f}"
    return pd.Series(rows)


def motion_diff_table(results_by_sea_state: dict) -> pd.DataFrame:
    """RMSE and max |ONNX - catenary| for surge, heave, pitch across sea states."""
    rows = []
    for name, r in results_by_sea_state.items():
        row = {"sea_state": name}
        for key, unit, scale in [("surge", "m", 1.0), ("heave", "m", 1.0),
                                  ("pitch", "deg", 180.0 / np.pi)]:
            d = (r["onnx"][key] - r["catenary"][key]) * scale
            row[f"{key} RMSE ({unit})"] = float(np.sqrt((d * d).mean()))
            row[f"{key} max|d| ({unit})"] = float(np.abs(d).max())
        rows.append(row)
    return pd.DataFrame(rows).set_index("sea_state")


def benchmark_table(results: dict) -> pd.DataFrame:
    return pd.DataFrame([
        {"sea_state": name,
         "runtime_catenary_s": r["runtime_catenary_s"],
         "runtime_onnx_s": r["runtime_onnx_s"],
         "mean_abs_error_kN": r["mean_abs_error_kN"],
         "max_abs_error_kN": r["max_abs_error_kN"]}
        for name, r in results.items()
    ]).set_index("sea_state")
