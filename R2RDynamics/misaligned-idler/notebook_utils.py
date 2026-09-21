"""Run the article FMU, draw the notebook figures, and provide the nip-load
and nip-friction sweep CLIs (combines the former fmu_plots.py,
nip_load_sweep.py and nip_friction_sweep.py into one module)."""

import argparse  # CLI parsing for the two sweep subcommands
import csv  # write sweep results as CSV reports
import hashlib  # hash FMU bytes + settings into a cache key
import json  # serialize the cache-key signature deterministically
import tempfile  # extract each FMU into a scratch directory before simulating
from pathlib import Path
from typing import TYPE_CHECKING

import fmpy
import matplotlib
import numpy as np
from fmpy import extract, read_model_description, simulate_fmu
from fmpy.simulation import instantiate_fmu

matplotlib.use("Agg")  # headless backend: no display needed to save PNGs
import matplotlib.pyplot as plt

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "BUILD_DIR",
    "CASES",
    "check_result",
    "plot_friction_result",
    "plot_runout",
    "plot_unparallel_results",
    "run_cases",
    "summary_table",
]


# ---------------------------------------------------------------------------
# Shared FMU simulation library (formerly fmu_plots.py)
# ---------------------------------------------------------------------------

STUDY_DIR = Path(__file__).resolve().parent
FMU_DIR = STUDY_DIR / "FMUs"
BUILD_DIR = STUDY_DIR / "build/notebook-fmu"
SLIP = "idler.rollerVariables.slipVelocity"
DEG = np.pi/180
LINE_OUTPUTS = [
    "appliedYaw", "appliedTram", "nipCrossing", "nipWedge", "minimumFaceMargin",
    "idlerSlipDistance", SLIP, "idlerLateralOffset", "idlerSpanTension",
    "outgoingSpanTension", "controlledTension", "idlerNipLoad",
    "nip.nipContact.edgeLift", "nip.nipContact.endOpening",
    "nip.nipContact.contactWidth",
    "nip.nipContact.loadCentre", "nip.nipContact.contactStart",
    "nip.nipContact.contactEnd",
]
# One FMU; the idler fault and the nip compression are run-time parameters.
CASES = {
    "BearingOnly": {"idlerYaw": 0.02, "idlerTram": 0, "nipCompression": -0.001},
    "Yaw0": {"idlerYaw": 0, "idlerTram": 0},
    "Yaw1.15": {"idlerYaw": 0.02, "idlerTram": 0},
    "Yaw2": {"idlerYaw": 2*DEG, "idlerTram": 0},
    "Yaw3": {"idlerYaw": 3*DEG, "idlerTram": 0},
    "Tram0.2": {"idlerYaw": 0, "idlerTram": 0.2*DEG},
    "Tram0.4": {"idlerYaw": 0, "idlerTram": 0.4*DEG},
    "Tram0.6": {"idlerYaw": 0, "idlerTram": 0.6*DEG},
    "Runout": {"idlerYaw": 0, "idlerTram": 0, "nipRunout": 0.3e-3},
}
# 40 s so the slow tension-loop ringing has settled before slip and offset
# are read at the end; 5 s ramp to 2 m/s is a realistic converting-line start
CASES = {
    name: {
        "fmu": "UnparallelIdler.fmu",
        "parameters": {"startupDuration": 5, **parameters},
        "stop_time": 40,
        "tolerance": 1e-8, "interval": 2e-4, "outputs": LINE_OUTPUTS,
    }
    for name, parameters in CASES.items()
}


plt.rcParams.update(
    {
        "font.family": ["Segoe UI", "DejaVu Sans"],
        "font.size": 10,
        "axes.labelsize": 10,
        "axes.titlesize": 11,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "legend.fontsize": 9,
        "svg.fonttype": "path",
    }
)

NOMINAL, SOFTER, ALIGNED = "#d55e00", "#0072b2", "0.45"


def _save(fig, destination: Path, filename: str) -> Path:
    """Save fig as a PNG under destination and close it."""
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"{filename}.png"
    fig.savefig(path, metadata={"Software": None})
    plt.close(fig)
    return path


def _style(ax, xlabel: str | None = None, ylabel: str | None = None,
           title: str | None = None) -> None:
    """Apply the shared grid/spine/label styling to one axes."""
    ax.grid(True, alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    if title:
        ax.set_title(title, loc="left")


def plot_friction_result(run: dict[str, np.ndarray], destination: Path) -> Path:
    """Save the Triple S and dry Stribeck coefficient comparison.

    Args:
        run: Friction sweep arrays in Modelica column names.
        destination: Directory for the generated PNG.

    Returns:
        Path to the saved image.
    """
    velocity = 1000*run["slipVelocity"]
    triple = run["tripleSCoefficient"]
    classical = run["stribeckCoefficient"].copy()
    classical[np.abs(velocity) < 1e-10] = np.nan  # Stribeck sign is undefined at zero slip
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.3), dpi=140)
    for ax, limit, title in zip(
        axes, [6, 1.5], ["Adhesion and sliding", "Near zero slip"], strict=True,
    ):
        ax.plot(velocity, triple, color="#0072b2", label="Triple S")
        ax.plot(velocity, classical, "--", color="#d55e00", label="Stribeck")
        ax.set(xlim=(-limit, limit), xlabel="Slip velocity [mm/s]", title=title)
        ax.grid(True, alpha=0.25)
    axes[0].set_ylabel("Signed friction coefficient [1]")
    fig.legend(*axes[0].get_legend_handles_labels(), loc="upper center",
               ncol=2, frameon=False)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "triple-s-stribeck.png"
    fig.savefig(path, metadata={"Software": None})
    plt.close(fig)
    return path


YAW_COLOURS = {
    "Yaw0": ALIGNED, "Yaw1.15": "#009e73", "Yaw2": "#0072b2", "Yaw3": "#d55e00",
}
TRAM_COLOURS = {"Tram0.2": "#009e73", "Tram0.4": "#0072b2", "Tram0.6": "#d55e00"}
RUNOUT_LABELS = {"Runout": "0.3 mm runout"}
RUNOUT_COLOURS = {"Yaw0": ALIGNED, "Runout": "#d55e00"}


def _label(name: str) -> str:
    """Return the legend label of a yaw, tram or runout case."""
    if name in RUNOUT_LABELS:
        return RUNOUT_LABELS[name]
    return name.replace("Yaw", "yaw ").replace("Tram", "tram ") + " deg"


def plot_bearing_vs_nip(
    runs: dict[str, dict[str, np.ndarray]], destination: Path
) -> Path:
    """Local and accumulated idler slip with the nip clear and loaded, 1.15 deg yaw."""
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.4), dpi=140)
    for name, label, colour in (
        ("BearingOnly", "Nip clear", NOMINAL),
        ("Yaw1.15", "Nip loaded", SOFTER),
    ):
        run = runs[name]
        axes[0].plot(run["time"], 1000*run[SLIP], color=colour, lw=1.2, label=label)
        axes[1].plot(
            run["time"], 1000*run["idlerSlipDistance"], color=colour, lw=1.4,
            label=label,
        )
    _style(axes[0], "Time [s]", "Local slip [mm/s]", "Web minus idler surface")
    _style(axes[1], "Time [s]", "Accumulated slip [mm]", "Sliding distance")
    axes[0].legend(frameon=False)
    fig.tight_layout()
    return _save(fig, destination, "bearing-vs-nip")


def _footprint(ax, runs: dict[str, dict[str, np.ndarray]], names: dict[str, str],
               title: str) -> None:
    """Draw the touching interval of the nip face and the load resultant per case."""
    for row, (name, colour) in enumerate(names.items()):
        run = runs[name]
        start = 1000*run["nip.nipContact.contactStart"][-1]
        end = 1000*run["nip.nipContact.contactEnd"][-1]
        centre = 1000*run["nip.nipContact.loadCentre"][-1]
        ax.barh(row, end - start, left=start, height=0.55, color=colour, alpha=0.85)
        ax.plot(centre, row, "kv", ms=6)
        ax.text(centre, row + 0.36, f"{run['idlerNipLoad'][-1]:.0f} N",
                ha="center", va="bottom", fontsize=8.5)
    half = 500*runs["Yaw0"]["nip.nipContact.contactWidth"][-1]
    ax.axvline(-half, color="0.6", lw=0.8)
    ax.axvline(half, color="0.6", lw=0.8)
    ax.set_yticks(
        range(len(names)),
        [_label(name) if name != "Yaw0" else "aligned" for name in names],
    )
    ax.set_ylim(-0.6, len(names) - 0.2)
    ax.invert_yaxis()
    _style(ax, "Position along the face [mm]", None, title)
    ax.grid(False)


def plot_yaw_sweep(runs: dict[str, dict[str, np.ndarray]], destination: Path) -> Path:
    """Nip footprint, idler slip and web walk as the idler yaw grows."""
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.6), dpi=140)
    _footprint(
        axes[0], runs, YAW_COLOURS, "Face in contact and steady load, yawed idler",
    )
    for name, colour in YAW_COLOURS.items():
        run = runs[name]
        axes[1].plot(run["time"], 1000*run[SLIP], color=colour, lw=1.1,
                     label=_label(name))
        axes[2].plot(run["time"], 1000*run["idlerLateralOffset"], color=colour, lw=1.2,
                     label=_label(name))
    _style(axes[1], "Time [s]", "Local slip [mm/s]", "Idler slip through startup")
    _style(axes[2], "Time [s]", "Lateral offset [mm]", "Web walk at the idler")
    axes[1].set_xlim(0, 20)
    axes[1].legend(frameon=False)
    axes[2].legend(frameon=False)
    fig.tight_layout()
    return _save(fig, destination, "yaw-sweep")


def plot_tram_sweep(runs: dict[str, dict[str, np.ndarray]], destination: Path) -> Path:
    """Web walk, nip footprint and slip when the idler is trammed instead of yawed."""
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.6), dpi=140)
    for name, colour in TRAM_COLOURS.items():
        run = runs[name]
        axes[0].plot(run["time"], 1000*run["idlerLateralOffset"], color=colour, lw=1.2,
                     label=_label(name))
        axes[2].plot(run["time"], 1000*run["idlerSlipDistance"], color=colour, lw=1.2,
                     label=_label(name))
    base = runs["Yaw0"]
    axes[2].plot(base["time"], 1000*base["idlerSlipDistance"], color=ALIGNED, lw=1.2,
                 label="aligned")
    _footprint(axes[1], runs, {"Yaw0": ALIGNED, **TRAM_COLOURS},
               "Face in contact and steady load, trammed idler")
    _style(axes[0], "Time [s]", "Lateral offset [mm]", "Web walk, trammed idler")
    _style(axes[2], "Time [s]", "Accumulated slip [mm]", "Idler creep over 40 s")
    axes[0].legend(frameon=False)
    axes[2].legend(frameon=False)
    fig.tight_layout()
    return _save(fig, destination, "tram-sweep")


def _minus_aligned(run: dict[str, np.ndarray], base: dict[str, np.ndarray],
                   column: str) -> np.ndarray:
    """Return the run's column minus the aligned case on the base time grid."""
    return np.interp(base["time"], run["time"], run[column]) - base[column]


def plot_runout(runs: dict[str, dict[str, np.ndarray]], destination: Path) -> Path:
    """Nip load and the span tensions around the idler with nip runout."""
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.6), dpi=140)
    base = runs["Yaw0"]
    window = (base["time"] >= 10) & (base["time"] <= 10.5)
    for name, colour in RUNOUT_COLOURS.items():
        run = runs[name]
        t, load = _window(run, "idlerNipLoad", 10, 10.5)
        axes[0].plot(t, load, color=colour, lw=1.2,
                     label="aligned" if name == "Yaw0" else _label(name))
        if name == "Yaw0":
            continue
        for ax, column in zip(
            axes[1:], ("idlerSpanTension", "outgoingSpanTension"), strict=True,
        ):
            ax.plot(base["time"][window], _minus_aligned(run, base, column)[window],
                    color=colour, lw=1.2, label=_label(name))
    _style(axes[0], "Time [s]", "Nip normal load [N]",
           "Nip load, half a second at speed")
    _style(axes[1], "Time [s]", "Tension minus aligned case [N]",
           "Span entering the idler")
    _style(axes[2], "Time [s]", "Tension minus aligned case [N]",
           "Span leaving the idler")
    axes[0].set_ylim(bottom=0)
    axes[2].sharey(axes[1])
    axes[0].legend(frameon=False)
    axes[2].legend(frameon=False)
    fig.tight_layout()
    return _save(fig, destination, "runout")


def _window(run: dict[str, np.ndarray], column: str, start: float,
            end: float) -> tuple[np.ndarray, np.ndarray]:
    """Return the time and column slices where start <= time <= end."""
    mask = (run["time"] >= start) & (run["time"] <= end)
    return run["time"][mask], run[column][mask]


def plot_unparallel_results(runs: dict[str, dict[str, np.ndarray]],
                            destination: Path) -> list[Path]:
    """Save the four winding figures of the unparallel-idler study."""
    return [plot_bearing_vs_nip(runs, destination), plot_yaw_sweep(runs, destination),
            plot_tram_sweep(runs, destination), plot_runout(runs, destination)]


def check_result(name: str, run: dict[str, np.ndarray]) -> None:
    """Check completeness and that the FMU applied the requested fault.

    Args:
        name: A case key from CASES.
        run: FMU results, with SI units and a time column.
    """
    case = CASES[name]
    settings = case["parameters"]
    assert all(np.isfinite(values).all() for values in run.values()), name
    assert abs(run["time"][0]) < 1e-10, f"Missing start: {name}"
    assert abs(run["time"][-1] - case["stop_time"]) < 1e-8, name
    assert np.all(np.diff(run["time"]) >= -1e-10), f"Unordered times: {name}"
    assert np.max(np.abs(run["appliedYaw"] - settings["idlerYaw"])) < 1e-12, name
    assert np.max(np.abs(run["appliedTram"] - settings["idlerTram"])) < 1e-12, name
    lateral = run["idlerLateralOffset"]
    if settings["idlerYaw"] == 0 and settings["idlerTram"] == 0:
        # Allow 10 nm of solver noise around the exactly aligned geometry.
        assert np.max(np.abs(lateral)) < 1e-8, f"Geometry not aligned: {name}"
    elif "nipFrictionScale" not in settings:
        # The friction sweep may suppress offset despite correctly applied yaw.
        assert np.max(np.abs(lateral)) > 1e-3, f"Fault not applied: {name}"
    late = run["time"] > 10
    if settings.get("nipRunout", 0) > 0:
        assert np.ptp(run["idlerNipLoad"][late]) > 100, f"Runout not applied: {name}"
    assert np.min(run["idlerSpanTension"]) > 0, name
    if settings.get("nipCompression", 0.001) <= 0:
        assert np.max(np.abs(run["idlerNipLoad"])) < 1e-6, f"Nip not clear: {name}"
    else:
        assert np.max(run["idlerNipLoad"]) > 100, f"Nip not loaded: {name}"


def _simulate_case(path: Path, case: dict, description) -> np.ndarray:
    """Run Model Exchange, restarting CVode after dynamic model events."""
    settings = {
        "fmi_type": "ModelExchange", "solver": "CVode",
        "stop_time": case["stop_time"], "relative_tolerance": case["tolerance"],
        "output_interval": case["interval"], "start_values": case["parameters"],
        "output": case["outputs"], "record_events": True,
    }
    with tempfile.TemporaryDirectory() as folder:
        extract(str(path), folder)
        fmu = instantiate_fmu(folder, description, fmi_type="ModelExchange")
        original_update = fmu.newDiscreteStates

        def restart_after_event():
            # FMPy 0.3.29 resets CVode only for changed states or nominals.
            # Contact and ramps change derivatives; request a reset at events.
            event_info = list(original_update())
            event_info[3] = True
            return tuple(event_info)

        fmu.newDiscreteStates = restart_after_event
        try:
            return simulate_fmu(
                folder, model_description=description, fmu_instance=fmu, **settings,
            )
        finally:
            fmu.freeInstance()


def run_cases(
    names: "Iterable[str]",
    cache_dir: Path = BUILD_DIR / "cache",
    fmu_dir: Path = FMU_DIR,
    force: bool = False,
) -> dict[str, dict[str, np.ndarray]]:
    """Simulate selected FMU cases or load matching, checked simulation caches.

    Args:
        names: Keys from CASES, in execution order.
        cache_dir: Directory for numerical results, independent of native CSVs.
        fmu_dir: Directory containing the prepared FMUs.
        force: Rerun even when the FMU and solver settings match a cache.

    Returns:
        Result columns grouped by case name, ready for the plotting functions.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    runs = {}
    for name in names:
        case = CASES[name]
        path = fmu_dir / case["fmu"]
        if not path.is_file():
            raise FileNotFoundError(f"Missing {path}; restore the supplied FMUs folder")
        signature = {  # cache key: same FMU bytes + same solver settings = reusable
            "case": case, "fmu_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "fmpy": fmpy.__version__, "interface": "ModelExchange", "solver": "CVode",
        }
        signature["restart_cvode_after_events"] = True
        encoded = json.dumps(signature, sort_keys=True).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        cached = cache_dir / f"{name}-{digest[:20]}.npz"
        if cached.exists() and not force:
            with np.load(cached, allow_pickle=False) as archive:
                run = {column: archive[column] for column in archive.files}
            print(f"Cached: {name}")
        else:
            description = read_model_description(str(path))
            available = {variable.name for variable in description.modelVariables}
            if missing := set(case["outputs"]) - available:
                raise ValueError(
                    f"Missing FMU signals in {path.name}: {sorted(missing)}"
                )
            print(f"Running: {name} to {case['stop_time']} s", flush=True)
            result = _simulate_case(path, case, description)
            run = {column: result[column] for column in result.dtype.names}
            check_result(name, run)
            temporary = cached.with_suffix(".tmp.npz")  # atomic write: avoid a half-saved cache
            np.savez_compressed(temporary, **run)
            temporary.replace(cached)
        check_result(name, run)
        runs[name] = run
    return runs


def summary_table(runs: dict[str, dict[str, np.ndarray]]) -> str:
    """Return a compact Markdown table of the unparallel-idler findings.

    Args:
        runs: FMU results keyed by case name.

    Returns:
        A Markdown table with crossing, nip load, slip and lateral position.
    """
    rows = [
        (
            "| Case | Crossing [deg] | Wedge [deg] | Edge lift [mm] | "
            "End opening [mm] | Contact width [mm] | Load centre [mm] | "
            "Nip load at speed [N] | Peak slip [mm/s] | Slip, end [mm] | "
            "Min tension [N] | Tension vs aligned in, out [N] | "
            "Final offset [mm] | Face margin [mm] |"
        ),
        (
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
            "---: | ---: | ---: | ---: | ---: | ---: |"
        ),
    ]
    base = runs["Yaw0"]
    for name, run in runs.items():
        late = run["time"] > 10
        load = run["idlerNipLoad"][late]
        ripple = [np.ptp(_minus_aligned(run, base, column)[base["time"] > 10])
                  for column in ("idlerSpanTension", "outgoingSpanTension")]
        rows.append(
            f"| {name} | {run['nipCrossing'][-1]/DEG:.2f} | "
            f"{run['nipWedge'][-1]/DEG:.2f} | "
            f"{1000*run['nip.nipContact.edgeLift'][-1]:.3f} | "
            f"{1000*run['nip.nipContact.endOpening'][-1]:.2f} | "
            f"{1000*run['nip.nipContact.contactWidth'][-1]:.0f} | "
            f"{1000*run['nip.nipContact.loadCentre'][-1]:.1f} | "
            f"{load.min():.0f} to {load.max():.0f} | "
            f"{1000*np.max(np.abs(run[SLIP])):.3f} | "
            f"{1000*run['idlerSlipDistance'][-1]:.2f} | "
            f"{np.min(run['idlerSpanTension']):.1f} | "
            f"{ripple[0]:.2f}, {ripple[1]:.2f} | "
            f"{1000*run['idlerLateralOffset'][-1]:.2f} | "
            f"{1000*np.min(run['minimumFaceMargin']):.1f} |"
        )
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Nip-load sweep CLI (formerly nip_load_sweep.py) -- produces Figure 2
# ---------------------------------------------------------------------------

LOAD_SWEEP = ("BearingOnly", "Nip025", "Nip050", "Nip075", "Yaw1.15")
for _case_name, _compression in zip(LOAD_SWEEP[1:4], (0.00025, 0.0005, 0.00075)):
    CASES[_case_name] = {  # intermediate compression cases reuse the Yaw1.15 baseline
        **CASES["Yaw1.15"],
        "parameters": {
            **CASES["Yaw1.15"]["parameters"],
            "nipCompression": _compression,
        },
    }


def summarize_load_sweep(name: str, run: dict[str, np.ndarray]) -> dict[str, float]:
    """Measure load and web response, checking the compression took effect.

    Args:
        name: Sweep case name.
        run: Validated FMU output arrays in SI units.

    Returns:
        Compression, load, slip and tracking metrics in display units.
    """
    compression = CASES[name]["parameters"].get("nipCompression", 0.001)
    late = run["time"] >= 30
    load = float(np.mean(run["idlerNipLoad"][late]))
    # All loaded cases exceed edge lift, so the full parabolic face touches.
    edge_lift = float(run["nip.nipContact.edgeLift"][-1])
    if compression > 0:
        assert compression > edge_lift, f"Partial footprint in {name}"
    expected = 1e6 * max(0, compression - edge_lift / 3)
    assert abs(load - expected) < 1e-5, (
        f"{name}: load {load} N differs from expected {expected} N"
    )
    assert np.ptp(run["idlerNipLoad"][late]) < 1e-5, (
        f"{name}: nip load is not steady at fixed geometry"
    )
    return {
        "compression_mm": 1000 * compression,
        "nip_load_N": load,
        "accumulated_slip_mm": 1000 * float(run["idlerSlipDistance"][-1]),
        "peak_slip_mm_s": 1000 * float(np.max(np.abs(run[SLIP]))),
        "final_offset_mm": 1000 * float(run["idlerLateralOffset"][-1]),
    }


def main_load_sweep(argv: list[str] | None = None) -> None:
    """Run selected load-sweep cases, or draw the complete five-point comparison."""
    parser = argparse.ArgumentParser(description="Sweep nip compression at fixed yaw.")
    parser.add_argument("--case", choices=LOAD_SWEEP)
    parser.add_argument("--cache-dir", type=Path, default=BUILD_DIR / "cache")
    args = parser.parse_args(argv)
    names = (args.case,) if args.case else LOAD_SWEEP
    runs = run_cases(names, cache_dir=args.cache_dir)
    rows = [summarize_load_sweep(name, runs[name]) for name in names]
    for name, row in zip(names, rows):
        print(f"{name}: {row}", flush=True)
    if args.case:
        return  # single-case run: skip the CSV/figure written for the full sweep

    destination = Path(__file__).resolve().parent
    report = destination / "build" / "nip-load-sweep.csv"
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)

    loads = [row["nip_load_N"] for row in rows]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), layout="constrained")
    series = (
        ("accumulated_slip_mm", "Accumulated slip [mm]", "Slip over 40 s"),
        ("final_offset_mm", "Lateral offset [mm]", "Web offset at 40 s"),
    )
    for ax, (key, label, title) in zip(axes, series):
        values = [row[key] for row in rows]
        ax.plot(loads, values, "o-", color="#0072b2")
        for load, value in zip(loads, values):
            ax.annotate(f"{value:.2f}", (load, value), xytext=(0, 8),
                        textcoords="offset points", ha="center", fontsize=9)
        ax.set(xlabel="Actual nip load [N]", ylabel=label, title=title)
        ax.set_ylim(0, max(values) * 1.2)
        ax.grid(True, alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Nip loading at fixed 20 mrad yaw; zero tram and runout")
    image = destination / "images" / "MisalignedIdler" / "nip-load-sweep.png"
    fig.savefig(image, dpi=160, metadata={"Software": None})
    plt.close(fig)
    print(f"Wrote {report}\nWrote {image}")


# ---------------------------------------------------------------------------
# Nip-friction sweep CLI (formerly nip_friction_sweep.py) -- produces Figure 6
# ---------------------------------------------------------------------------

FRICTION_SCALES = {"NipFriction1": 1.0, "NipFriction2": 2.0, "NipFriction3": 3.0}
FRICTION_DIAGNOSTICS = [
    "nipFrictionScale", "nip.traction.muAdhesion", "nip.traction.muSliding",
    "idler.traction.muAdhesion", "idler.traction.muSliding",
    "world.innerTraction.muAdhesion", "world.innerTraction.muSliding",
    "world.outerTraction.muAdhesion", "world.outerTraction.muSliding",
    "nip.nipContact.frictionCoefficient", "nip.nipContact.lateralForce",
    "nip.nipContact.slipMagnitude", "nip.nipContact.frictionLoss",
]
for _case_name, _scale in FRICTION_SCALES.items():
    CASES[_case_name] = {  # each scale reuses Yaw1.15 with fixed compression, no runout
        **CASES["Yaw1.15"],
        "parameters": {
            **CASES["Yaw1.15"]["parameters"],
            "nipCompression": 0.001,
            "nipRunout": 0.0,
            "nipFrictionScale": _scale,
        },
        "outputs": [*CASES["Yaw1.15"]["outputs"], *FRICTION_DIAGNOSTICS],
    }


def summarize_friction_sweep(name: str, run: dict[str, np.ndarray]) -> dict[str, float]:
    """Check isolated friction changes and measure the line response.

    Args:
        name: Friction sweep case name.
        run: Validated FMU output arrays in SI units.

    Returns:
        Applied friction, contact and response metrics in display units.
    """
    scale = FRICTION_SCALES[name]
    expected_parameters = {
        "nipFrictionScale": scale,
        "nip.traction.muAdhesion": 0.35 * scale,
        "nip.traction.muSliding": 0.22 * scale,
        "idler.traction.muAdhesion": 0.35,
        "idler.traction.muSliding": 0.22,
        "world.innerTraction.muAdhesion": 0.35,
        "world.innerTraction.muSliding": 0.22,
        "world.outerTraction.muAdhesion": 0.35,
        "world.outerTraction.muSliding": 0.22,
    }
    for parameter, expected in expected_parameters.items():
        error = float(np.max(np.abs(run[parameter] - expected)))
        assert error < 1e-12, f"{name}: {parameter} differs by {error}"

    late = run["time"] >= 30
    assert np.max(np.abs(run["nipCrossing"] - 0.02)) < 1e-10, (
        f"{name}: contact crossing does not match the requested yaw"
    )
    assert np.max(np.abs(run["nipWedge"])) < 1e-10, (
        f"{name}: unexpected contact wedge"
    )
    load = float(np.mean(run["idlerNipLoad"][late]))
    edge_lift = float(run["nip.nipContact.edgeLift"][-1])
    expected_load = 1e6 * (0.001 - edge_lift / 3)
    assert abs(load - expected_load) < 1e-5, (
        f"{name}: load {load} N differs from {expected_load} N"
    )
    assert np.ptp(run["idlerNipLoad"][late]) < 1e-5, (
        f"{name}: fixed geometry produces a changing nip load"
    )
    # Check the evaluated law too: exported parameter readback alone can mislead.
    velocity = run["nip.nipContact.slipMagnitude"]
    central = np.clip((velocity + 0.001) / 0.002, 0, 1)
    sliding = np.clip((velocity - 0.001) / 0.002, 0, 1)
    central_mu = 0.35 * (2 * central**2 * (3 - 2 * central) - 1)
    sliding_mu = 0.35 + (0.22 - 0.35) * sliding**2 * (3 - 2 * sliding)
    expected_mu = scale * np.where(velocity <= 0.001, central_mu, sliding_mu)
    coefficient = run["nip.nipContact.frictionCoefficient"]
    assert np.max(np.abs(coefficient - expected_mu)) < 1e-10, (
        f"{name}: reported parameters did not change the actual friction law"
    )
    assert np.min(run["nip.nipContact.frictionLoss"]) > -1e-8, (
        f"{name}: nip friction generated energy"
    )
    return {
        "nip_friction_scale": scale,
        "nip_mu_adhesion": 0.35 * scale,
        "nip_mu_sliding": 0.22 * scale,
        "nip_load_N": load,
        "nip_lateral_force_N": float(
            np.mean(run["nip.nipContact.lateralForce"][late])
        ),
        "accumulated_slip_mm": 1000 * float(run["idlerSlipDistance"][-1]),
        "peak_slip_mm_s": 1000 * float(np.max(np.abs(run[SLIP]))),
        "final_offset_mm": 1000 * float(run["idlerLateralOffset"][-1]),
        "outgoing_tension_mean_N": float(np.mean(run["outgoingSpanTension"][late])),
        "outgoing_tension_peak_to_peak_N": float(
            np.ptp(run["outgoingSpanTension"][late])
        ),
    }


def main_friction_sweep(argv: list[str] | None = None) -> None:
    """Run selected friction-sweep cases, or write the complete comparison and figure."""
    parser = argparse.ArgumentParser(
        description="Compare nip-only friction at fixed yaw and compression."
    )
    parser.add_argument("--case", choices=FRICTION_SCALES)
    parser.add_argument("--cache-dir", type=Path, default=BUILD_DIR / "cache")
    args = parser.parse_args(argv)
    names = (args.case,) if args.case else tuple(FRICTION_SCALES)
    runs = run_cases(names, cache_dir=args.cache_dir)
    rows = [summarize_friction_sweep(name, runs[name]) for name in names]
    for name, row in zip(names, rows):
        print(f"{name}: {row}", flush=True)
    if args.case:
        return  # single-case run: skip the CSV/figure written for the full sweep

    destination = Path(__file__).resolve().parent
    report = destination / "build" / "nip-friction-sweep.csv"
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)

    scales = list(FRICTION_SCALES.values())
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), layout="constrained")
    series = (
        ("accumulated_slip_mm", "Accumulated slip [mm]", "Slip over 40 s"),
        ("final_offset_mm", "Lateral offset [mm]", "Web offset at 40 s"),
    )
    for ax, (key, label, title) in zip(axes, series):
        values = [row[key] for row in rows]
        ax.plot(scales, values, "o-", color="#0072b2")
        for scale, value in zip(scales, values):
            ax.annotate(
                f"{value:.2f}", (scale, value), xytext=(0, 8),
                textcoords="offset points", ha="center", fontsize=9,
            )
        ax.set(
            xlabel="Nip friction multiplier [1]", ylabel=label, title=title,
            xticks=scales,
            ylim=(min(0, min(values) * 1.2), max(1e-9, max(values) * 1.2)),
        )
        ax.grid(True, alpha=0.25)
        if key == "final_offset_mm":
            ax.axhline(0, color="0.45", linewidth=0.8)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Nip friction at fixed 20 mrad yaw and 1 mm compression")
    image = destination / "images" / "MisalignedIdler" / "nip-friction-sweep.png"
    fig.savefig(image, dpi=160, metadata={"Software": None})
    plt.close(fig)
    print(f"Wrote {report}\nWrote {image}")


# ---------------------------------------------------------------------------
# Combined CLI entry point: `python notebook_utils.py load-sweep|friction-sweep`
# ---------------------------------------------------------------------------

def main() -> None:
    """Dispatch to the load-sweep or friction-sweep CLI by subcommand."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("load-sweep", add_help=False)
    subparsers.add_parser("friction-sweep", add_help=False)
    command, remaining = parser.parse_known_args()
    if command.command == "load-sweep":
        main_load_sweep(remaining)
    else:
        main_friction_sweep(remaining)


if __name__ == "__main__":
    main()
