"""Pitch controller, mooring equilibrium solver, and the run_simulation-style
orchestration API -- the "control" layer for blog_notebook.ipynb.

Imports its physics/environment/FMU layer from helpers.py (same directory,
also self-contained in public/). Consolidates (unmodified logic, just
relocated so the notebook doesn't reach outside public/): control/pitch_pi.py,
control/mooring_solver.py, api/tools.py.

Required: numpy, scipy, plotly (plus everything helpers.py requires)
"""
import math
import os
from dataclasses import dataclass
from dataclasses import replace as dc_replace

import numpy as np
import plotly.graph_objects as go
from helpers import (
    OC4_MOORING,
    CatenaryMooring,
    OnnxMooring,
    anchor_position,
    fairlead_world_position,
    pitch_schedule,
    resolve_line_force,
    run_cosim,
)
from scipy.optimize import minimize

_HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# control/pitch_pi.py -- gain-scheduled pitch controller regulating platform
# pitch motion.
#
# Feedforward is `helpers.pitch_schedule`, evaluated once per run at the
# run's mean wind speed and held fixed for the whole run -- the same fixed
# NREL Region-3 operating-pitch table part2_dynamic_mooring uses, so a
# controlled run's baseline matches an uncontrolled one exactly and any
# difference is attributable to the rate-feedback trim below (see
# docs/KNOWN_ISSUES.md; this replaces an earlier per-step Ct-table-inversion
# feedforward that had drifted from Part 2's baseline). Output is the same
# `pitchCollective` command the FMU expects (rad, in [0, pi/2] -- see
# Blades.mo's `phi_ref` range).
#
# Previously this controller also integrated absolute platform pitch to zero
# (a PI term). That was removed: a floating turbine has a static mean heel
# under thrust, and driving absolute pitch to zero changes the mean blade
# pitch/thrust to fight that natural heel, confounding any pitch-variance
# improvement with de-loading. What real floating-wind controllers (ROSCO)
# add on top of a generator-torque/feedforward base is "floating feedback"
# on platform pitch RATE only, which is what fl_kp below does -- it damps
# the wave-frequency oscillation without touching the mean operating point.
# ---------------------------------------------------------------------------

PITCH_LIMIT = math.pi / 2
# No Python-side rate limit: Blades.mo already applies an 8 deg/s
# pitchRateLimiter plus a 2 Hz actuator filter to phi_ref inside the FMU
# (see part2_dynamic_mooring/models/WindTurbines/Components/Blades.mo).
# Limiting here too would stack two actuator models on the same command.
FL_KP_DEFAULT = 40.0  # floating-feedback gain, rad command per rad/s platform pitch rate
# tuned empirically against the real cosim (Hs=3, Tp=9, U_hub=15, TI=0.10):
# pitch RMS improves monotonically from fl_kp=1 (~no effect) through 40 (best,
# beats feedforward-only), then degrades again by 60 -- a coarse manual sweep,
# not a rigorously optimized gain. This tuning predates the fixed-schedule
# feedforward swap; not re-verified against it (see docs/KNOWN_ISSUES.md).
FL_FILTER_TAU_S = 0.1  # low-pass time constant on the finite-difference rate estimate
WIND_FILTER_TAU_S = 2.0  # low-pass time constant on the wind-speed signal that
# drives fl_kp_at()'s gain schedule -- mirrors real turbine practice of using
# a filtered/estimated wind speed rather than a raw instantaneous reading.
# No longer drives the feedforward pitch itself (that's fixed per run).

DEFAULT_FL_KP_SCHEDULE = [
    (11.4, FL_KP_DEFAULT),
    (25.0, FL_KP_DEFAULT),
]
# Flat across the operating range. Previously tapered to 10.0/5.0 at
# 20/25 m/s because fl_kp=40 there "destabilized surge" against the old,
# pre-fix plant (clustered/mis-inertia'd rotor, old linear thrust law, old
# yaw spring -- see docs/KNOWN_ISSUES.md). Re-swept against the corrected
# plant (Hs=3, Tp=9, TI=0.10): pitch std improves monotonically with fl_kp
# at 15/20/25 m/s alike (e.g. 20 m/s: 0.362 deg at fl_kp=0 down to 0.095 at
# fl_kp=150; see public/figures/demo_results.json), and surge std keeps
# climbing at 15/20 m/s throughout the sweep with no instability -- the old
# taper was compensating for a rotor bug, not a real control limit. Kept at
# 40 (not pushed higher) since that's the value already validated at
# 15 m/s; a coarse choice, not a rigorous optimum.


class GainScheduledPitchRateFeedback:
    """command = base_pitch + fl_kp*filtered_rate(platform_pitch), where
    base_pitch is `pitch_schedule(base_wind_speed)` fixed at construction
    time, and the rate term is ROSCO's "floating feedback" (Fl_Kp on
    platform pitch velocity), added to actively damp the wave-frequency
    platform pitch oscillation, low-pass filtered (time constant
    FL_FILTER_TAU_S) since a raw finite-difference derivative amplifies
    per-step numerical noise. fl_kp is itself wind-speed-scheduled
    (`fl_kp_schedule`, default DEFAULT_FL_KP_SCHEDULE, looked up against a
    filtered instantaneous wind speed) since a gain tuned to damp pitch at
    one wind speed can destabilize surge at another; pass a scalar `fl_kp`
    to override with a constant.

    The output command is amplitude-clamped to `[0, PITCH_LIMIT]`. Rate
    limiting is left to the FMU's own actuator model (Blades.mo's
    pitchRateLimiter + phiFilter) rather than duplicated here. There is no
    integral state -- unlike a real PI, this controller has no memory
    across `step()` calls other than the rate/wind filters, so `reset()`
    only needs to clear those.
    """

    def __init__(self, base_wind_speed: float, fl_kp: float | None = None,
                fl_kp_schedule: list[tuple[float, float]] | None = None):
        schedule = list(fl_kp_schedule) if fl_kp_schedule is not None else list(DEFAULT_FL_KP_SCHEDULE)
        if not schedule:
            raise ValueError("fl_kp_schedule must have at least one breakpoint")
        speeds = [pt[0] for pt in schedule]
        if speeds != sorted(speeds):
            raise ValueError("fl_kp_schedule wind speeds must be sorted ascending")
        if any(gain < 0 for _, gain in schedule):
            raise ValueError("fl_kp gains must be non-negative")
        self.fl_kp_schedule = schedule
        self._fl_kp_override = fl_kp
        self._base_pitch = pitch_schedule(base_wind_speed)
        self._prev_pitch = 0.0
        self._filtered_rate = 0.0
        self._filtered_wind_speed = 0.0

    def reset(self) -> None:
        self._prev_pitch = 0.0
        self._filtered_rate = 0.0
        self._filtered_wind_speed = 0.0

    def fl_kp_at(self, wind_speed: float) -> float:
        if self._fl_kp_override is not None:
            return self._fl_kp_override
        speeds = [pt[0] for pt in self.fl_kp_schedule]
        if wind_speed <= speeds[0]:
            return self.fl_kp_schedule[0][1]
        if wind_speed >= speeds[-1]:
            return self.fl_kp_schedule[-1][1]
        for i in range(len(speeds) - 1):
            lo, hi = speeds[i], speeds[i + 1]
            if lo <= wind_speed <= hi:
                frac = (wind_speed - lo) / (hi - lo)
                return self.fl_kp_schedule[i][1] + frac * (
                    self.fl_kp_schedule[i + 1][1] - self.fl_kp_schedule[i][1])
        raise AssertionError("unreachable: speeds sorted, bounds checked above")

    def step(self, platform_pitch: float, wind_speed: float, dt: float) -> float:
        alpha_wind = dt / (WIND_FILTER_TAU_S + dt)
        filtered_wind_speed = self._filtered_wind_speed + alpha_wind * (
            wind_speed - self._filtered_wind_speed)

        fl_kp = self.fl_kp_at(filtered_wind_speed)

        raw_rate = (platform_pitch - self._prev_pitch) / dt
        alpha = dt / (FL_FILTER_TAU_S + dt)
        filtered_rate = self._filtered_rate + alpha * (raw_rate - self._filtered_rate)

        raw_command = self._base_pitch + fl_kp * filtered_rate
        command = max(0.0, min(PITCH_LIMIT, raw_command))

        self._prev_pitch = platform_pitch
        self._filtered_rate = filtered_rate
        self._filtered_wind_speed = filtered_wind_speed
        return command


# ---------------------------------------------------------------------------
# control/mooring_solver.py -- quasi-static mooring-repositioning solver.
#
# Given a sustained environmental horizontal force on the platform, finds
# the 3 line lengths that let the platform sit in equilibrium back at its
# nominal station, while minimizing the spread of tension across the 3
# lines. Reuses helpers.CatenaryMooring as the per-line forward force
# model -- one instance per line, each with its own `unstretched_length` --
# rather than reimplementing the catenary physics.
# ---------------------------------------------------------------------------

_N_LINES = 3
_PLATFORM_CENTERED = {"surge": 0.0, "sway": 0.0, "heave": 0.0,
                      "roll": 0.0, "pitch": 0.0, "yaw": 0.0}
_RESIDUAL_TOLERANCE_N = 1000.0  # accept as converged even if scipy's success
# flag is False, as long as the actual force-balance residual is negligible
# against the ~1e5-1e6 N force scale here -- observed empirically: SLSQP can
# report success=False despite landing on a residual as small as 0.01 N.


def _net_force_and_tensions(lengths, target_position):
    platform_state = {**_PLATFORM_CENTERED,
                      "surge": target_position[0], "sway": target_position[1]}
    fx_total, fy_total, tensions = 0.0, 0.0, []
    for i in range(_N_LINES):
        model = CatenaryMooring(cfg=dc_replace(OC4_MOORING, unstretched_length=lengths[i]))
        anchor = anchor_position(i)
        fairlead = fairlead_world_position(platform_state, i)
        fx, fy, _fz, tension = resolve_line_force(anchor, fairlead, model)
        fx_total += fx
        fy_total += fy
        tensions.append(tension)
    return fx_total, fy_total, tensions


def solve_equilibrium_lengths(env_force_xy: tuple[float, float],
                              target_position: tuple[float, float] = (0.0, 0.0),
                              nominal_lengths: tuple[float, float, float] =
                              (835.5, 835.5, 835.5),
                              minimize_length_change: bool = False,
                              max_tension_n: float | None = None) -> dict:
    """Solve for 3 line lengths balancing `env_force_xy` at `target_position`.

    `env_force_xy` is the net steady horizontal force (Fx, Fy) [N] the
    environment applies on the platform -- the mooring lines must supply
    the opposite force for the platform to sit in equilibrium there.
    By default minimizes the variance of fairlead tension across the 3
    lines subject to that force-balance equality constraint, via SLSQP.
    With `minimize_length_change=True`, instead minimizes the sum of
    squared deviations from `nominal_lengths` -- useful when `env_force_xy`
    is (0, 0): tension variance alone is trivially satisfied by slack lines,
    which can elongate lines far past nominal for no physical reason.

    If `max_tension_n` is given, an inequality constraint keeps every line's
    predicted fairlead tension below it, so the solver cannot return a
    configuration that violates the caller's own tension guardrail (a
    proposal above it is reported infeasible instead).
    """
    env_force_xy = np.asarray(env_force_xy, dtype=float)

    platform_state = {**_PLATFORM_CENTERED,
                      "surge": target_position[0], "sway": target_position[1]}
    chords = []
    for i in range(_N_LINES):
        anchor = anchor_position(i)
        fairlead = fairlead_world_position(platform_state, i)
        chords.append(float(np.linalg.norm(fairlead - anchor)))

    def constraint(lengths):
        fx, fy, _ = _net_force_and_tensions(lengths, target_position)
        return [fx + env_force_xy[0], fy + env_force_xy[1]]

    def objective(lengths):
        if minimize_length_change:
            return float(sum((L - nominal_lengths[i]) ** 2
                             for i, L in enumerate(lengths)))
        _, _, tensions = _net_force_and_tensions(lengths, target_position)
        return float(np.var(tensions))

    constraints = [{"type": "eq", "fun": constraint}]
    if max_tension_n is not None:
        constraints.append({
            "type": "ineq",  # >= 0 feasible: slack of the tightest line
            "fun": lambda lengths: max_tension_n - max(
                _net_force_and_tensions(lengths, target_position)[2]),
        })

    bounds = [(c * 1.01, nominal_lengths[i] * 2.0) for i, c in enumerate(chords)]
    result = minimize(
        objective, x0=list(nominal_lengths), method="SLSQP",
        constraints=constraints,
        bounds=bounds, options={"maxiter": 200, "ftol": 1e-6},
    )

    fx, fy, tensions = _net_force_and_tensions(result.x, target_position)
    residual = float(np.hypot(fx + env_force_xy[0], fy + env_force_xy[1]))
    # Accept on the residual itself, not scipy's success flag: SLSQP reports
    # success=False at residuals as small as 0.01 N, and (the dangerous case)
    # can report success=True while an independently computed residual still
    # exceeds tolerance -- so the residual is the sole arbiter of convergence.
    if not np.isfinite(residual) or residual > _RESIDUAL_TOLERANCE_N:
        return {"converged": False, "best_residual_n": residual}
    if max_tension_n is not None and max(tensions) > max_tension_n * 1.001:
        # small relative slack: SLSQP satisfies its inequality to ftol and can
        # land a few tens of N over the cap; a genuine breach is far larger.
        return {"converged": False, "best_residual_n": residual,
                "max_tension_n": float(max(tensions))}

    return {
        "converged": True,
        "lengths": [float(L) for L in result.x],
        "predicted_tensions_n": [float(t) for t in tensions],
    }


# ---------------------------------------------------------------------------
# api/tools.py -- session state and the run_simulation-style orchestration
# API tying the controller and mooring solver above to helpers.run_cosim.
# ---------------------------------------------------------------------------

_ONNX_DIR = os.path.join(_HERE, "data")
_TENSION_LIMIT_N = 1_800_000.0  # fixed engineering safety threshold; not derived from
# chain MBL -- the chain grade is undocumented and unverifiable, see docs/KNOWN_ISSUES.md
_OFFSET_LIMIT_M = 50.0


@dataclass
class ControlConfig:
    """Per-session control state. `run_simulation` reads it every call;
    `configure_pitch_controller` is the only function that mutates it."""
    pitch_mode: str = "off"
    pitch_schedule: list = None


class RunStore:
    def __init__(self):
        self.runs = {}
        self._counter = 0
        self.pending_figures = []

    def add_run(self, params: dict, result: dict, summary: dict) -> str:
        self._counter += 1
        run_id = f"run{self._counter}"
        self.runs[run_id] = {"params": params, "result": result,
                             "summary": summary}
        return run_id

    def get(self, run_id: str):
        return self.runs.get(run_id)

    def add_figure(self, fig):
        self.pending_figures.append(fig)

    def drain_figures(self) -> list:
        figs, self.pending_figures = self.pending_figures, []
        return figs


def summarize(result: dict) -> dict:
    surge_rms = float(np.sqrt(np.mean(result["surge"] ** 2)))
    pitch_rms_deg = float(np.degrees(np.sqrt(np.mean(result["pitch"] ** 2))))
    max_tension = float(max(result["tension1"].max(),
                            result["tension2"].max(),
                            result["tension3"].max()))
    max_offset = float(np.abs(result["surge"]).max())
    ok = max_tension < _TENSION_LIMIT_N and max_offset < _OFFSET_LIMIT_M
    return {
        "surge_rms_m": surge_rms,
        "pitch_rms_deg": pitch_rms_deg,
        "max_tension_mn": max_tension / 1e6,
        "constraint_ok": bool(ok),
    }


def _mooring_model(name: str):
    if name == "onnx":
        return OnnxMooring(_ONNX_DIR)
    if name == "catenary":
        return CatenaryMooring()
    raise ValueError(f"mooring_model must be 'catenary' or 'onnx', got {name!r}")


def _build_pitch_controller(config: "ControlConfig", U_hub: float = 11.4):
    """Map a pitch mode to the controller object stepped inside run_cosim.

    - "off": None -> run_cosim's own fixed-schedule feedforward.
    - "pi":  fixed-schedule feedforward + wind-speed-scheduled floating
      (rate) feedback. (Mode name kept for API/notebook compatibility;
      there is no integral term on absolute platform pitch -- see class
      docstring.)

    `U_hub` fixes the feedforward base pitch (via `pitch_schedule`) at
    construction time -- pass the run's actual mean wind speed; the default
    only matters for the "off" case, which doesn't build a controller.
    """
    if config.pitch_mode == "pi":
        return GainScheduledPitchRateFeedback(U_hub, fl_kp_schedule=config.pitch_schedule or DEFAULT_FL_KP_SCHEDULE)
    return None


def run_simulation(store: RunStore, config: ControlConfig, Hs: float, Tp: float,
                   U_hub: float, TI: float, mooring_model: str = "catenary",
                   duration: float = 60.0, dt: float = 0.02) -> dict:
    model = _mooring_model(mooring_model)
    pitch_controller = _build_pitch_controller(config, U_hub)

    env = {"Hs": Hs, "Tp": Tp, "U_hub": U_hub, "TI": TI}
    result = run_cosim(model, env=env, duration=duration, dt=dt,
                       pitch_controller=pitch_controller)
    summary = summarize(result)
    params = {**env, "mooring_model": mooring_model, "duration": duration, "dt": dt}
    run_id = store.add_run(params, result, summary)
    return {"run_id": run_id, **summary}


_SIGNAL_UNITS = {
    "surge": "m", "sway": "m", "heave": "m",
    "roll": "rad", "pitch": "rad", "yaw": "rad",
    "tension1": "N", "tension2": "N", "tension3": "N",
}


def plot_results(store: RunStore, config: ControlConfig, run_id: str,
                 signals: list) -> dict:
    rec = store.get(run_id)
    if rec is None:
        return {"error": f"no run named {run_id!r}; run a simulation first"}
    result = rec["result"]
    t = result["time"]

    plotted = [s for s in signals if s in result]
    if not plotted:
        return {"error": f"none of {signals} are valid signals"}

    # group by unit so each figure has a coherent y-axis label
    groups: dict[str, list] = {}
    for sig in plotted:
        unit = _SIGNAL_UNITS.get(sig, "")
        groups.setdefault(unit, []).append(sig)

    for unit, sigs in groups.items():
        fig = go.Figure()
        for sig in sigs:
            fig.add_trace(go.Scatter(x=t, y=result[sig], mode="lines", name=sig))
        fig.update_layout(
            title=f"{run_id}: {', '.join(sigs)}",
            xaxis_title="time [s]",
            yaxis_title=unit,
        )
        store.add_figure(fig)

    return {"ok": True, "run_id": run_id, "plotted": plotted}


def compare_runs(store: RunStore, config: ControlConfig, run_ids: list,
                 metric: str) -> dict:
    values = {}
    for run_id in run_ids:
        rec = store.get(run_id)
        if rec is not None and metric in rec["summary"]:
            values[run_id] = rec["summary"][metric]
    if not values:
        return {"error": f"no runs in {run_ids} have metric {metric!r}"}
    return {"metric": metric, "values": values}


def configure_pitch_controller(store: RunStore, config: ControlConfig, mode: str,
                               schedule: list | None = None) -> dict:
    if mode not in ("off", "pi"):
        return {"error": f"mode must be 'off' or 'pi', got {mode!r}"}
    if schedule is not None:
        try:
            GainScheduledPitchRateFeedback(11.4, fl_kp_schedule=schedule)  # validates sorted speeds, non-negative gains
        except ValueError as exc:
            return {"error": str(exc)}
    config.pitch_mode = mode
    config.pitch_schedule = schedule
    return {"ok": True, "pitch_mode": mode,
           "pitch_schedule": schedule if schedule is not None else list(DEFAULT_FL_KP_SCHEDULE)}
