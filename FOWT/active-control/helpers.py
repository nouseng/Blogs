"""Active-control utilities -- physics/environment layer for blog_notebook.ipynb.

Self-contained: everything this module needs lives alongside it in
public/ (models/*.fmu, data/*.onnx). See controller.py for the pitch PI
controller, the mooring-reposition solver, and the run_simulation-style
orchestration API that ties them to the physics below.

Consolidates (unmodified logic, just relocated so the notebook doesn't
reach outside public/): environment/wind_model.py, environment/wave_model.py,
environment/loads.py, mooring/line_geometry.py, mooring/catenary_mooring.py,
mooring/onnx_mooring.py, simulation/cosim_runner.py.

Required: numpy, scipy, onnxruntime, fmpy
"""
import json
import os
import sys
import warnings
from dataclasses import dataclass

import numpy as np
import onnxruntime as rt
from fmpy import extract, read_model_description
from fmpy.fmi2 import FMU2Slave
from scipy.optimize import brentq

_HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# environment/wind_model.py
# ---------------------------------------------------------------------------

def kaimal_spectrum(U_hub: float, TI: float, L: float = 340.2,
                     n_freqs: int = 256, f_min: float = 0.001,
                     f_max: float = 2.0) -> tuple[np.ndarray, np.ndarray]:
    """Kaimal longitudinal wind turbulence spectrum (IEC 61400-1 Ed.3).

    U_hub: mean wind speed at hub height [m/s]
    TI: turbulence intensity [-]
    L: integral length scale [m] (IEC: 340.2 m for hub > 60m)
    """
    freqs = np.linspace(f_min, f_max, n_freqs)
    sigma = TI * U_hub
    f_L = freqs * L / U_hub
    S = (4 * sigma ** 2 * L / U_hub) / (1 + 6 * f_L) ** (5 / 3)
    return freqs, S


def generate_wind_timeseries(U_hub: float, TI: float, duration: float = 600.0,
                              dt: float = 0.05, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    """Generate longitudinal wind speed time series from a Kaimal spectrum.

    Returns: (time [s], wind speed [m/s])
    """
    rng = np.random.default_rng(seed)
    freqs, S = kaimal_spectrum(U_hub, TI)
    df = freqs[1] - freqs[0]
    amplitudes = np.sqrt(2 * S * df)
    phases = rng.uniform(0, 2 * np.pi, len(freqs))
    t = np.arange(0, duration, dt)
    turbulence = sum(
        a * np.cos(2 * np.pi * f * t + phi)
        for a, f, phi in zip(amplitudes, freqs, phases)
    )
    turbulence = turbulence - turbulence.mean()  # kill the low-freq DC leak so mean == U_hub
    return t, U_hub + turbulence


# ---------------------------------------------------------------------------
# environment/wave_model.py
# ---------------------------------------------------------------------------

def jonswap_spectrum(Hs: float, Tp: float, gamma: float = 3.3,
                      n_freqs: int = 256, f_min: float = 0.02,
                      f_max: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
    """JONSWAP wave energy spectrum.

    Hs: significant wave height [m]
    Tp: peak period [s]
    Returns: (frequencies [Hz], spectral density [m^2/Hz])
    """
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
    """Generate irregular wave elevation time series from a JONSWAP spectrum.

    Returns: (time [s], surface elevation eta [m])
    """
    rng = np.random.default_rng(seed)
    freqs, S = jonswap_spectrum(Hs, Tp)
    df = freqs[1] - freqs[0]
    amplitudes = np.sqrt(2 * S * df)
    phases = rng.uniform(0, 2 * np.pi, len(freqs))
    t = np.arange(0, duration, dt)
    eta = sum(
        a * np.cos(2 * np.pi * f * t + phi)
        for a, f, phi in zip(amplitudes, freqs, phases)
    )
    return t, eta


# ---------------------------------------------------------------------------
# environment/loads.py
# ---------------------------------------------------------------------------

def wave_loads(eta: np.ndarray, dt: float, rho: float = 1025.0,
               A_wp: float = 40.0, moment_arm: float = 10.0) -> tuple[np.ndarray, np.ndarray]:
    """Simplified Morison-type surge force and pitch moment from wave elevation."""
    deta_dt = np.gradient(eta, dt)
    f_wave = rho * 9.81 * A_wp * eta + 1.0e6 * deta_dt
    m_wave = f_wave * moment_arm
    return f_wave, m_wave


# ---------------------------------------------------------------------------
# mooring/line_geometry.py
# ---------------------------------------------------------------------------

R_ANCHOR = 837.6     # m, OC4 anchor radius from platform centerline
R_FAIRLEAD = 40.868  # m, OC4 fairlead radius from platform centerline
ANCHOR_DEPTH = -200.0   # m, OC4 anchor depth (world z)
FAIRLEAD_DEPTH = -14.0  # m, OC4 fairlead depth below platform CG

# Lines at 0/120/240 deg; each anchor lies on the same azimuth as its fairlead
AZIMUTHS = (0.0, 2 * np.pi / 3, 4 * np.pi / 3)


def anchor_position(line_index: int) -> np.ndarray:
    """World-frame (x, y, z) position of the anchor for the given line index (0-2).

    Sway (y) sign is negated relative to a naive sin(az): PlatformBody.mo's
    mooringLineNRotation (FixedRotation about the heave/Y axis) maps local
    (R, -depth, 0) -> world (R*cos(az), -depth, -R*sin(az)), confirmed empirically
    in OpenModelica (AbsoluteSensor, resolveInFrame=world). Matching that sign here
    keeps the anchor on the same azimuth as its fairlead in the FMU's actual frame.
    """
    az = AZIMUTHS[line_index]
    return np.array([R_ANCHOR * np.cos(az), -R_ANCHOR * np.sin(az), ANCHOR_DEPTH])


def fairlead_world_position(platform_state: dict, line_index: int) -> np.ndarray:
    """World-frame (x, y, z) position of the fairlead for the given line index (0-2).

    `platform_state` has keys surge, sway, heave (m) and roll, pitch, yaw (rad),
    matching FOWT.mo's FreeMotion outputs. Small-angle rotation matrix.
    """
    az = AZIMUTHS[line_index]
    local = np.array([R_FAIRLEAD * np.cos(az), -R_FAIRLEAD * np.sin(az), FAIRLEAD_DEPTH])
    roll = platform_state["roll"]
    pitch = platform_state["pitch"]
    yaw = platform_state["yaw"]
    rotation = np.array([
        [1.0, -yaw, pitch],
        [yaw, 1.0, -roll],
        [-pitch, roll, 1.0],
    ])
    rotated = rotation @ local
    translation = np.array([platform_state["surge"], platform_state["sway"], platform_state["heave"]])
    return rotated + translation


def resolve_line_force(anchor_xyz: np.ndarray, fairlead_xyz: np.ndarray, mooring_model) -> tuple[float, float, float, float]:
    """Resolve a mooring line's force on the fairlead into world-frame (Fx, Fy, Fz, tension_N).

    `mooring_model` implements `.compute(horizontal_offset) -> dict` with keys
    `fairlead_tension_N`, `horizontal_force_N`, `vertical_force_N`.
    """
    dx = fairlead_xyz[0] - anchor_xyz[0]
    dy = fairlead_xyz[1] - anchor_xyz[1]
    horizontal_offset = float(np.hypot(dx, dy))
    azimuth = float(np.arctan2(dy, dx))

    result = mooring_model.compute(horizontal_offset)

    fx = -result["horizontal_force_N"] * np.cos(azimuth)
    fy = -result["horizontal_force_N"] * np.sin(azimuth)
    # vertical_force_N is an unsigned magnitude (sqrt(T^2 - H^2)); the anchor is always
    # deeper than the fairlead (ANCHOR_DEPTH < FAIRLEAD_DEPTH for every line), so the line
    # always pulls the fairlead downward.
    fz = -result["vertical_force_N"]
    return fx, fy, fz, result["fairlead_tension_N"]


# ---------------------------------------------------------------------------
# mooring/catenary_mooring.py
# ---------------------------------------------------------------------------

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


_H_MIN_1D = 1e-3  # lower bracket for the 1-D horizontal-tension root find [N]


def _x_end_1d(H: float, vertical_span: float, line_length: float, w: float) -> float:
    """Horizontal fairlead reach for horizontal tension H, given the vertical
    constraint (suspended length is fixed in closed form by vertical_span)."""
    L_s = min(np.sqrt(vertical_span ** 2 + 2.0 * vertical_span * H / w), line_length)
    return (line_length - L_s) + (H / w) * np.arcsinh(w * L_s / H)


def _brackets_1d(horizontal_span: float, vertical_span: float,
                 line_length: float, w: float, x_max: float) -> bool:
    """True when a root of x_end(H) = horizontal_span exists in (0, H_taut] --
    i.e. the line is taut enough for the reach to be tension-controlled. The
    slack regime (horizontal_span below the H->0 reach) has no such root."""
    if horizontal_span >= x_max:
        return False
    lo = _x_end_1d(_H_MIN_1D, vertical_span, line_length, w) - horizontal_span
    return lo < 0.0


def _solve_catenary(horizontal_span: float, vertical_span: float,
                     line_length: float, w: float) -> dict:
    """Solve static catenary with seabed contact.

    When horizontal_span exceeds the taut-line limit (Lb=0 case), the line is
    effectively fully extended; the function returns the taut solution so
    the caller receives a finite (high) tension rather than a solver failure.
    """
    if line_length <= 0 or w <= 0:
        raise ValueError("line_length and w must be positive")

    # Maximum feasible horizontal span at Lb=0
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
        # Line fully extended / taut: return maximum-tension catenary (Lb=0)
        return taut
    elif _brackets_1d(horizontal_span, vertical_span, line_length, w, x_max):
        # Well-conditioned 1-D solve: the vertical constraint fixes the
        # suspended length L_s(H) = sqrt(vspan^2 + 2*vspan*H/w) in closed
        # form, leaving one monotonic equation x_end(H) = horizontal_span to
        # solve for H. Stable right up to the taut limit (L_b -> 0), unlike the
        # 2-D (H, L_b) Newton solve, whose Jacobian went singular there and
        # occasionally fell back to an Lb=0 approximation.
        H_taut = w * (line_length ** 2 - vertical_span ** 2) / (2.0 * vertical_span)
        H = brentq(lambda H: _x_end_1d(H, vertical_span, line_length, w) - horizontal_span,
                   _H_MIN_1D, H_taut, xtol=1e-8, rtol=1e-12)
        L_s = min(np.sqrt(vertical_span ** 2 + 2.0 * vertical_span * H / w), line_length)
        L_b = line_length - L_s
    else:
        # Deep-slack regime: horizontal_span is below the H->0 reach
        # (line_length - vertical_span); the excess line lies slack on the
        # seabed and the suspended part hangs near-vertically. Horizontal
        # restoring force ~0, fairlead tension is just the suspended weight.
        H = _H_MIN_1D
        L_s = vertical_span
        L_b = line_length - L_s

    return {
        "horizontal_tension": float(H),
        "fairlead_tension": float(np.sqrt(H ** 2 + (w * L_s) ** 2)),
        "seabed_length": float(L_b),
    }


def _force_components(offset_m: float, tension_N: float, cfg: _OC4Mooring) -> tuple[float, float]:
    w = cfg.mass_per_length * cfg.gravity
    try:
        res = _solve_catenary(offset_m, abs(cfg.fairlead_depth - cfg.anchor_depth),
                               cfg.unstretched_length, w)
        H, T_cat = res["horizontal_tension"], res["fairlead_tension"]
        if T_cat < 1.0:
            raise ValueError("near-zero tension")
        V = float(np.sqrt(max(T_cat ** 2 - H ** 2, 0.0)))
        scale = tension_N / float(np.sqrt(H ** 2 + V ** 2))
        return float(H * scale), float(V * scale)
    except (ValueError, RuntimeError, ArithmeticError) as exc:
        warnings.warn(f"_solve_catenary failed at offset={offset_m}m ({exc}); using fallback.")
        theta = np.arctan2(0.8, 0.6)
        return float(tension_N * np.cos(theta)), float(tension_N * np.sin(theta))


class CatenaryMooring:
    """Analytical OC4 catenary mooring model — solved fresh on every call."""

    def __init__(self, cfg: _OC4Mooring = OC4_MOORING):
        self.cfg = cfg

    def compute(self, horizontal_offset: float) -> dict:
        w = self.cfg.mass_per_length * self.cfg.gravity
        res = _solve_catenary(horizontal_offset,
                               abs(self.cfg.fairlead_depth - self.cfg.anchor_depth),
                               self.cfg.unstretched_length, w)
        tension = res["fairlead_tension"]
        fx, fz = _force_components(horizontal_offset, tension, self.cfg)
        return {
            "fairlead_tension_N": tension,
            "horizontal_force_N": fx,
            "vertical_force_N": fz,
        }


# ---------------------------------------------------------------------------
# mooring/onnx_mooring.py -- wraps Part 1's ONNX mooring surrogate
# ---------------------------------------------------------------------------

_ONNX_FILENAMES = {
    "horizontal_force_N": "mooring_surrogate_fx.onnx",
    "vertical_force_N": "mooring_surrogate_fz.onnx",
    "fairlead_tension_N": "mooring_surrogate_t.onnx",
}
_METADATA_FILE = "surrogate_metadata.json"

# Physical taut limit for OC4 catenary — clip ONNX input at this to match catenary behaviour
_w = OC4_MOORING.mass_per_length * OC4_MOORING.gravity
_vs = abs(OC4_MOORING.fairlead_depth - OC4_MOORING.anchor_depth)
_TAUT = _taut_solution(_vs, OC4_MOORING.unstretched_length, _w)
_X_MAX = _TAUT["x_max"]  # ≈ 807.6 m


class OnnxMooring:
    """Part 1 ONNX mooring surrogate, cached at construction (no per-call solve).

    Inputs are clipped to the catenary's physical taut limit so the surrogate
    cannot extrapolate into the fully-extended regime where its training data
    is sparse and the catenary itself returns a capped value.
    """

    def __init__(self, data_dir: str, pretension_factor: float = 1.0,
                 water_depth: float = 200.0):
        self.pretension_factor = pretension_factor
        self.water_depth = water_depth

        paths = {t: os.path.join(data_dir, f) for t, f in _ONNX_FILENAMES.items()}
        self.sessions = {
            t: rt.InferenceSession(p, providers=["CPUExecutionProvider"])
            for t, p in paths.items()
        }

        self.y_scale = 1.0
        meta_path = os.path.join(data_dir, _METADATA_FILE)
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
        x = np.array([[horizontal_offset, self.pretension_factor, self.water_depth]],
                      dtype=np.float32)
        return {
            t: float(s.run(None, {"input": x})[0].ravel()[0]) * self.y_scale
            for t, s in self.sessions.items()
        }


# ---------------------------------------------------------------------------
# simulation/cosim_runner.py -- steps the 6DOF/3-line FOWT FMU
# ---------------------------------------------------------------------------

FMU_DIR = os.path.join(_HERE, "models")


def fmu_path() -> str:
    # win64 and linux64 binaries come from different OMC builds with different
    # GUIDs, so they can't share one FMU — pick the platform's own file.
    name = "FOWT_linux.fmu" if sys.platform.startswith("linux") else "FOWT.fmu"
    return os.path.join(FMU_DIR, name)


# NREL 5MW Region-3 steady operating-pitch schedule (Jonkman et al. 2009,
# NREL/TP-500-38060, Table 7-1): collective pitch (deg) vs hub-height wind
# speed (m/s), the turbine's published steady operating point above rated --
# same table as part2_dynamic_mooring/simulation/cosim_runner.py's
# NREL_PITCH_SCHEDULE, duplicated here since each part is a self-contained
# package. Replaces the per-step Ct-table-inversion feedforward this file
# used to compute, which held thrust constant by construction (Ct ~ V^-2)
# regardless of wind speed, and had drifted from Part 2's baseline.
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


# Mooring inputs: forceML{line}[{component}], components 1=x(surge), 2=y(heave), 3=z(sway)
MOORING_INPUT_NAMES = [f"forceML{i}[{j}]" for i in (1, 2, 3) for j in (1, 2, 3)]
WAVE_INPUT_NAMES = ["waveForces[1]", "waveForces[2]", "waveForces[3]"]
WAVE_MOMENT_INPUT_NAMES = ["waveMoments[1]", "waveMoments[2]", "waveMoments[3]"]
MOTION_OUTPUT_NAMES = ["surge", "sway", "heave", "roll", "pitch", "yaw"]

_SEA_STATES = {
    "operational": {"Hs": 2.5, "Tp": 10.0, "U_hub": 12.0, "TI": 0.06},
    "storm":       {"Hs": 6.0, "Tp": 14.0, "U_hub": 20.0, "TI": 0.12},
}


def run_cosim(mooring_model, sea_state: str = "operational",
              duration: float = 600.0, dt: float = 0.02,
              env: dict | None = None, pitch_controller=None) -> dict:
    """Step the FOWT FMU for `sea_state`, computing 3 mooring line forces each step.

    The FMU embeds a CVODE internal solver, so `dt` need not resolve the stiff
    blade-pitch loop (sub-stepped internally). It still bounds everything set
    from outside the FMU -- the external pitch controller and the 3 mooring-line
    forces are recomputed once per `dt` and held across the internal solve --
    so it must resolve the platform/wave motion and that external coupling;
    0.02 is a good default (step-converged, see make_blog_figures timestep study).

    `mooring_model` must implement `.compute(horizontal_offset) -> dict` with keys
    `fairlead_tension_N`, `horizontal_force_N`, `vertical_force_N` -- pass a single
    model (applied to all 3 lines) or a list/tuple of 3, one per line.

    Collective pitch is `pitch_schedule(env["U_hub"])` -- the sea state's mean
    wind speed's published steady operating point, fixed for the whole run --
    plus `pitch_controller.step(platform_pitch, wind_speed, dt)`'s rate-feedback
    trim when a controller is given. Matches part2_dynamic_mooring's baseline
    exactly so any difference between an uncontrolled and a controlled run is
    attributable to the trim alone (see docs/KNOWN_ISSUES.md).

    Returns dict of time series: time, surge, sway, heave, roll, pitch, yaw,
    tension1, tension2, tension3, pitch_command (phi_ref sent each step, rad).
    """
    env = env if env is not None else _SEA_STATES[sea_state]
    _, eta = generate_wave_timeseries(env["Hs"], env["Tp"], duration=duration, dt=dt)
    _, u_wind = generate_wind_timeseries(env["U_hub"], env["TI"], duration=duration, dt=dt)
    f_wave, m_wave = wave_loads(eta, dt)     # surge force + pitch moment; sway/heave wave = 0
    phi_ref_base = pitch_schedule(env["U_hub"])

    path = fmu_path()
    description = read_model_description(path)
    unzipdir = extract(path)
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

    series = {key: np.zeros(n) for key in MOTION_OUTPUT_NAMES}
    tensions = {f"tension{i}": np.zeros(n) for i in (1, 2, 3)}
    pitch_command_series = np.zeros(n)

    anchors = [anchor_position(i) for i in range(3)]
    mooring_models = (list(mooring_model) if isinstance(mooring_model, (list, tuple))
                      else [mooring_model, mooring_model, mooring_model])
    mooring_vrs = [vrs[name] for name in MOORING_INPUT_NAMES]
    wave_vrs    = [vrs[name] for name in WAVE_INPUT_NAMES]
    wave_moment_vrs = [vrs[name] for name in WAVE_MOMENT_INPUT_NAMES]
    wind_vr     = vrs["windSpeed"]
    pitch_vr    = vrs["pitchCollective"]
    motion_vrs  = [vrs[name] for name in MOTION_OUTPUT_NAMES]
    # All FMU inputs share one setReal per step: 9 mooring + 3 wave + 3 wave moment + wind + pitch.
    input_vrs   = mooring_vrs + wave_vrs + wave_moment_vrs + [wind_vr, pitch_vr]

    for i in range(1, n):
        platform_state = {key: series[key][i - 1] for key in MOTION_OUTPUT_NAMES}

        # Mooring forces
        forces = []
        for line_index in range(3):
            fairlead = fairlead_world_position(platform_state, line_index)
            fx, fy, fz, tension = resolve_line_force(
                anchors[line_index], fairlead, mooring_models[line_index])
            # fx=surge, fy=sway, fz=heave (line_geometry.py convention) -> FMU slots are
            # forceML{line}[1]=surge, [2]=heave, [3]=sway, so fz/fy must swap order here.
            forces.extend([fx, fz, fy])
            tensions[f"tension{line_index + 1}"][i] = tension

        V = float(u_wind[i])
        if pitch_controller is not None:
            phi_ref = pitch_controller.step(platform_state["pitch"], V, dt)
        else:
            phi_ref = phi_ref_base
        pitch_command_series[i] = phi_ref

        fmu.setReal(input_vrs, forces + [float(f_wave[i]), 0.0, 0.0,
                                         0.0, 0.0, float(m_wave[i]), V, phi_ref])
        fmu.doStep(currentCommunicationPoint=t[i - 1], communicationStepSize=dt)

        values = fmu.getReal(motion_vrs)
        for key, value in zip(MOTION_OUTPUT_NAMES, values):
            series[key][i] = value

    fmu.terminate()
    # no freeInstance: crashes on the CVODE FMU's SUNDIALS teardown

    return {"time": t, **series, **tensions, "pitch_command": pitch_command_series}
