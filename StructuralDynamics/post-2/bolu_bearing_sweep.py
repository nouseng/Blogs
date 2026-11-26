"""Bearing design sweep on the portable Bolu hospital FMUs under TBDY 2018 Chapter 14.

Runs directly on fmu/BoluFrictionPendulum.fmu and fmu/BoluLeadRubber.fmu with
FMPy while holding the 64 nonlinear viscous dampers fixed at their nominal,
upper-bound, and lower-bound properties. Neither OpenModelica nor the
StructuralDynamics library is required.
"""

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor
from itertools import product

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import numpy as np

try:
    from fmpy import simulate_fmu
except ImportError:
    simulate_fmu = None

import bolu_time_history as t

OUT = t.DATA / "bearing_sweep.json"
# Catalogue ranges: Maurer SIP-D R 1.5-5 m with mu 3.0 / 5.5 %, CPA mu 2-10 %; Turkish
# makers (Arsan, TIS, Fago) size friction pendulums per project
FPS_GRID = {"radius": (2.0, 2.65, 3.0, 4.0, 5.0, 6.0, 7.4),
            "friction": (0.02, 0.03, 0.055, 0.08, 0.10)}
# Bridgestone LH: Do 600-1500 mm, lead Do/5 +- 70 mm, G 0.385 MPa, lead 7.97 MPa;
# Arsan ATLAS: G 0.4 or 0.6 MPa, sized per project; Fago LRB700: G 0.38, lead 8 MPa
LRB_GRID = {"diameter": (1.0, 1.1, 1.2, 1.3, 1.4, 1.5), "lead_ratio": (0.20, 0.25),
            "thickness": (0.25, 0.30, 0.45), "modulus": (0.4e6, 0.6e6)}
LEAD_YIELD_CATALOGUE = 8e6
# Report Table 11: bonded rubber area and lead area as compiled into BoluLeadRubber
REPORT_LRB = {"rubber_area": 1.490764, "lead_area": 0.070686, "thickness": 0.45,
              "modulus": t.RUBBER_SHEAR_MODULUS, "lead_stress": t.LEAD_YIELD_STRESS,
              "label": "LRB report D1450 L300 Tr450 G0.6"}
STRAIN_LIMIT = 2.5
MAX_PERIOD = 6.0
RESTORING = 0.025
SHEAR_LIMIT = 0.20
# Feasible friction pendulums marked on the plot, lowest floor acceleration first
BEST = 3
N_BEARINGS = 184
# 1e-4 lets the hysteretic bearings excite the condensed frame's modes up to 19 Hz and
# doubles lead-rubber floor accelerations; 1e-6 matches bolu_time_history
TOLERANCE = 1e-6
STEP = 0.04


def run(case: dict) -> dict:
    """One record pair in one orientation; absolute peaks for the checks."""
    result = simulate_fmu(
        t.unpacked(case["fmu"]),
        fmi_type="ModelExchange", stop_time=case["stop"], output_interval=STEP,
        relative_tolerance=TOLERANCE, start_values=case["values"],
        output=t.fmu_outputs(case["fmu"]))

    def get(name: str) -> np.ndarray:
        return result[name]

    ext = t.model_extents(case["fmu"])
    out, _ = t.plan_peaks(get, True, ext)
    pts = [float(np.hypot(*t.corner_travel(get, x, y)).max())
           for x, y in t.MONITORED_POINTS]
    out["points"] = pts
    out["travel"] = float(np.mean(pts))
    out["shear"] = max(np.abs(result["isolationForceX"]).max(),
                       np.abs(result["isolationForceY"]).max()) / t.weight(ext)
    return {k: np.asarray(x).tolist() for k, x in out.items()}


def pair_cases(fmu: str, values: dict, offset: int) -> list[dict]:
    """The eleven pairs in both orientations."""
    table = t.ensure_record_table().as_posix()
    common = {"pairFile": table, "dampingRatio": t.DAMPING,
              "isolationDampingRatio": t.ISOLATION_DAMPING,
              "verticalScale": 1.0 if offset == t.DD1 else 0.0, **t.building_values(fmu)}
    return [{"fmu": fmu, "stop": min(t.stop_of(k + offset), 90.0 if k in (6, 8) else 60.0),
             "values": common | values | {"pairIndex": k + offset, "rotated": rotated}}
            for k in t.PAIRS for rotated in (False, True)]


def mean_of_pairs(runs: list[dict]) -> dict:
    """Per pair the larger orientation, then the mean over the pairs."""
    keys = runs[0].keys()
    return {k: np.mean([np.maximum(np.asarray(runs[2 * j][k]), np.asarray(runs[2 * j + 1][k]))
                        for j in range(len(runs) // 2)], axis=0) for k in keys}


def fps_effective_period(radius: float, friction_bound: float, d_ref: float) -> float:
    """Effective secant period of an FPS isolator at reference travel d_ref."""
    return float(2 * np.pi / np.sqrt(t.GRAVITY * (1.0 / radius + friction_bound / d_ref)))


def fps_design(radius: float, friction: float) -> dict:
    """Bounds of one friction pendulum design (with fixed dampers) and its analytic checks."""
    if (round(radius, 3), round(friction, 4)) == (7.4, 0.055):
        p_nom, p_up, p_lo = t.PERIOD_NOMINAL, t.PERIOD_UPPER, t.PERIOD_LOWER
    else:
        p_nom = fps_effective_period(radius, friction, 0.65)
        p_up = fps_effective_period(radius, 1.5 * friction, 0.65)
        p_lo = fps_effective_period(radius, 0.8 * friction, 1.04)
    base = {"radius": radius, "slidingYield": t.SLIP}
    bounds = {"nominal": (base | {"friction": friction,
                                  "damperCoefficient": t.DAMPER_NOMINAL,
                                  "isolationPeriod": p_nom}, 0),
              "upper": (base | {"friction": 1.5 * friction,
                                "damperCoefficient": t.DAMPER_UPPER,
                                "isolationPeriod": p_up}, 0),
              "lower": (base | {"friction": 0.8 * friction,
                                "damperCoefficient": t.DAMPER_LOWER,
                                "isolationPeriod": p_lo}, t.DD1)}
    period = 2 * np.pi * np.sqrt(radius / t.GRAVITY)
    return {"fmu": "BoluFrictionPendulum", "label": f"FPS R {radius:g} m, mu {friction:g}",
            "bounds": bounds, "period": float(period),
            "wind_ok": bool(0.8 * friction * t.weight(t.fps_extents()) >= t.WIND_LOAD),
            "restoring": lambda d: d / (2 * radius)}


def catalogue_lrb(diameter: float, lead_ratio: float, thickness: float,
                  modulus: float) -> dict:
    """Catalogue LRB geometry: bonded diameter, lead core Do * ratio, catalogue lead."""
    lead = lead_ratio * diameter
    return {"rubber_area": np.pi / 4 * (diameter ** 2 - lead ** 2),
            "lead_area": np.pi / 4 * lead ** 2, "thickness": thickness,
            "modulus": modulus, "lead_stress": LEAD_YIELD_CATALOGUE,
            "label": (f"LRB D{diameter * 1e3:.0f} L{lead * 1e3:.0f} "
                      f"Tr{thickness * 1e3:.0f} G{modulus / 1e6:g}")}


def lrb_design(rubber_area: float, lead_area: float, thickness: float, modulus: float,
               lead_stress: float, label: str) -> dict:
    """Bounds of one lead rubber design (with fixed dampers) and its analytic checks."""
    mass = t.WEIGHT / t.GRAVITY
    kd_nom = N_BEARINGS * modulus * rubber_area / thickness
    strength = N_BEARINGS * lead_stress * lead_area / t.WEIGHT
    period = float(2 * np.pi * np.sqrt(mass / kd_nom))
    if label == REPORT_LRB["label"]:
        periods = (t.LRB_PERIOD_NOMINAL, t.LRB_PERIOD_UPPER, t.LRB_PERIOD_LOWER)
    else:
        periods = tuple(
            float(2 * np.pi * np.sqrt(mass / (k * kd_nom + q * strength * t.WEIGHT / d_ref)))
            for (q, k), d_ref in (((1.0, 1.0), 0.40), (t.LRB_UPPER, 0.40), (t.LRB_LOWER, 0.65))
        )
    geometry = {"rubberArea": rubber_area, "leadArea": lead_area,
                "rubberThickness": thickness}
    bounds = {
        name: (geometry | {"leadYieldStress": lead_stress * q,
                           "rubberShearModulus": modulus * k,
                           "damperCoefficient": c_bound,
                           "isolationPeriod": p_bound}, offset)
        for name, (q, k), c_bound, p_bound, offset in (
            ("nominal", (1.0, 1.0), t.DAMPER_NOMINAL, periods[0], 0),
            ("upper", t.LRB_UPPER, t.DAMPER_UPPER, periods[1], 0),
            ("lower", t.LRB_LOWER, t.DAMPER_LOWER, periods[2], t.DD1),
        )
    }
    return {"fmu": "BoluLeadRubber", "label": label, "bounds": bounds, "period": period,
            "strength": float(strength), "thickness": thickness,
            "wind_ok": bool(t.LRB_LOWER[0] * strength * t.WEIGHT >= t.WIND_LOAD),
            "restoring": lambda d: (2 * np.pi / period) ** 2 * d / (2 * t.GRAVITY)}


def capacity(label: str) -> float:
    """Displacement capacity of Report §10.3.1: 1.04 m for FPS, 0.75 m for LRB designs."""
    return t.LRB_DISPLACEMENT_CAPACITY if label.startswith("LRB") else t.DISPLACEMENT_CAPACITY


def feasible(r: dict) -> bool:
    """Meets drift, shear, restoring force, D_TM capacity and (LRB) rubber strain."""
    return ((r["drift"] <= t.DRIFT_LIMIT) and (r["restoring"] >= RESTORING)
            and (r["shear"] <= SHEAR_LIMIT) and (r["travel"] <= capacity(r["design"]))
            and r.get("strain_ok", True))


def finalize_row(design: dict, split: dict[str, list[dict]]) -> dict:
    """Assemble check row from nominal, upper, and lower bound runs."""
    row = {"design": design["label"], "period": design["period"],
           "period_ok": design["period"] <= MAX_PERIOD, "wind_ok": design["wind_ok"]}
    nominal, upper, lower = (mean_of_pairs(split[n]) for n in ("nominal", "upper", "lower"))
    # TBDY 2018 §14.3.6: upper bound for the force on the superstructure, hence drift;
    # §14.3.10: nominal values for floor acceleration
    row["drift"] = t.occupied_peak(upper, "drift", t.OCCUPIED_DRIFT)
    row["acceleration"] = t.occupied_peak(nominal, "acc", t.OCCUPIED_ACCELERATION)
    row["drift_nominal"] = t.occupied_peak(nominal, "drift", t.OCCUPIED_DRIFT)
    row["acceleration_upper"] = t.occupied_peak(upper, "acc", t.OCCUPIED_ACCELERATION)
    row["shear"] = float(upper["shear"])
    # TBDY 2018 §14.14.4.4-14.14.4.5: per bearing and direction, the mean over the 11
    # pairs of the peak vector travel. D_TM is the worst corner and orientation; the
    # pair cases alternate _X and _Y.
    points = np.array([r["points"] for r in split["lower"]])
    row["cornersX"], row["cornersY"] = points[0::2].mean(axis=0).tolist(), points[1::2].mean(axis=0).tolist()
    row["travel"] = float(max(max(row["cornersX"]), max(row["cornersY"])))
    row["restoring"] = float(design["restoring"](row["travel"]))
    row["restoring_ok"] = row["restoring"] >= RESTORING
    row["shear_ok"] = row["shear"] <= SHEAR_LIMIT
    row["drift_ok"] = row["drift"] <= t.DRIFT_LIMIT
    row["acceleration_ok"] = row["acceleration"] <= t.ACCELERATION_LIMIT
    row["travel_ok"] = row["travel"] <= capacity(design["label"])
    if "thickness" in design:
        row["strength"] = design["strength"]
        row["strain"] = row["travel"] / design["thickness"]
        row["strain_ok"] = row["strain"] <= STRAIN_LIMIT
    return row


def evaluate(design: dict, workers: int = 8, pool: ProcessPoolExecutor | None = None) -> dict:
    """Simulate the three bounds on the FMU and apply every check."""
    row = {"design": design["label"], "period": design["period"],
           "period_ok": design["period"] <= MAX_PERIOD, "wind_ok": design["wind_ok"]}
    if not (row["period_ok"] and row["wind_ok"]):
        return row
    cases = {name: pair_cases(design["fmu"], values, offset)
             for name, (values, offset) in design["bounds"].items()}
    flat = [c for name in cases for c in cases[name]]
    order = np.argsort([-c["stop"] for c in flat])
    sorted_flat = [flat[i] for i in order]
    if pool is not None:
        sorted_res = list(pool.map(run, sorted_flat))
    else:
        with ProcessPoolExecutor(workers) as local_pool:
            sorted_res = list(local_pool.map(run, sorted_flat))
    results = [None] * len(flat)
    for idx, res in zip(order, sorted_res):
        results[idx] = res
    split = {}
    for name in cases:
        split[name], results = results[:len(cases[name])], results[len(cases[name]):]
    return finalize_row(design, split)


def plot(extra_rows: list[dict] | None = None) -> Path:
    """Upper-bound base shear and drift and nominal floor acceleration against DD-1 travel."""
    t.IMAGES.mkdir(parents=True, exist_ok=True)
    rows = {}
    for folder in (t.DATA, t.RUNS):
        for path in sorted(folder.glob("bearing_sweep*.json")):
            for r in json.loads(path.read_text(encoding="utf-8")):
                if "drift" in r:
                    rows[r["design"]] = r
    for r in extra_rows or ():
        if "drift" in r:
            rows[r["design"]] = r
    path = t.IMAGES / "BearingSweep.png"
    if "FPS R 7.4 m, mu 0.055" not in rows:
        return path
    fig, (ax_v, ax_a, ax_d) = t.plt.subplots(1, 3, figsize=(10.8, 4.0), layout="constrained")
    # Drift is plotted in percent
    panels = ((ax_v, "shear", 1.0), (ax_a, "acceleration", 1.0), (ax_d, "drift", 100.0))
    ax_v.axvspan(0.55, t.DISPLACEMENT_CAPACITY, ymin=0,
                 ymax=(SHEAR_LIMIT - 0.10) / (0.33 - 0.10),
                 color=t.ACCENT, alpha=0.08, label="FPS meets shear & travel limits")
    for kind, colour, marker in (("FPS", t.ACCENT, "o"), ("LRB", t.GOLD, "s")):
        sel = [r for r in rows.values() if r["design"].startswith(kind)]
        ok = [feasible(r) for r in sel]
        limits = "0.20 W, 0.5 % or 1.04 m" if kind == "FPS" else "0.20 W, 0.5 %, 0.75 m or 250 % strain"
        for flag, fill in ((True, colour), (False, "none")):
            pts = [r for r, f in zip(sel, ok) if f == flag]
            label = (f"{'Friction pendulum' if kind == 'FPS' else 'Lead rubber'}"
                     f"{'' if flag else f' (exceeds {limits})'}" if pts else None)
            ax_v.scatter([r["travel"] for r in pts], [r["shear"] for r in pts],
                         marker=marker, s=36, edgecolors=colour, facecolors=fill,
                         zorder=3, label=label)
            for ax, ykey, scale in panels[1:]:
                ax.scatter([r["travel"] for r in pts], [scale * r[ykey] for r in pts],
                           marker=marker, s=36, edgecolors=colour, facecolors=fill, zorder=3)
    rep_fps = rows["FPS R 7.4 m, mu 0.055"]
    for ax, ykey, scale in panels:
        ax.scatter(rep_fps["travel"], scale * rep_fps[ykey], marker="*", s=150,
                   color=t.REFERENCE, zorder=4,
                   label="Report FPS (R 7.4 m, μ 0.055)" if ax is ax_v else None)
    if REPORT_LRB["label"] in rows:
        rep_lrb = rows[REPORT_LRB["label"]]
        for ax, ykey, scale in panels:
            ax.scatter(rep_lrb["travel"], scale * rep_lrb[ykey], marker="D", s=65,
                       color=t.REFERENCE, zorder=4,
                       label="Report LRB (D 1450, Tr 450 mm, G 0.6)" if ax is ax_v else None)

    # The best feasible friction pendulums: lowest nominal floor acceleration
    best = sorted((r for r in rows.values() if r["design"].startswith("FPS") and feasible(r)),
                  key=lambda r: r["acceleration"])[:BEST]
    for k, r in enumerate(best):
        for ax, ykey, scale in panels:
            ax.annotate(f"{k + 1}", (r["travel"], scale * r[ykey]), xytext=(0, -11), ha="center",
                        textcoords="offset points", fontsize=7, fontweight="bold", color=t.ACCENT)
    if best:
        lines = [f"{k + 1}: {r['design'].removeprefix('FPS ').replace('mu', 'μ')}, "
                 f"{r['travel']:.2f} m, {r['shear']:.3f} W, {r['acceleration']:.2f} g"
                 for k, r in enumerate(best)]
        ax_a.text(0.98, 0.91, "\n".join(["Best feasible FPS", *lines]), transform=ax_a.transAxes,
                  ha="right", va="top", multialignment="left", fontsize=6,
                  bbox={"boxstyle": "round", "facecolor": "white", "edgecolor": "0.7"})

    ax_v.axhline(SHEAR_LIMIT, color="0.55", linestyle="--", linewidth=0.8)
    for ax, top in ((ax_v, 0.32), (ax_a, 1.03)):
        ax.axvline(t.LRB_DISPLACEMENT_CAPACITY, color=t.GOLD, linestyle=":", linewidth=0.8)
        ax.text(t.LRB_DISPLACEMENT_CAPACITY - 0.01, top, "0.75 m LRB", ha="right", va="top",
                fontsize="x-small", color=t.GOLD)
    ax_v.axvline(t.DISPLACEMENT_CAPACITY, color="0.55", linestyle="--", linewidth=0.8)
    ax_v.set_xlim(0.55, 1.35)
    ax_v.set_ylim(0.10, 0.33)
    ax_v.text(1.33, SHEAR_LIMIT + 0.004, "0.20 W limit", ha="right", va="bottom",
              fontsize="x-small", color="0.4")
    ax_v.text(t.DISPLACEMENT_CAPACITY + 0.01, 0.32, "1.04 m FPS", ha="left",
              va="top", fontsize="x-small", color="0.4")
    ax_v.set_xlabel("DD-1 travel D$_{TM}$, lower bound [m]")
    ax_v.set_ylabel("DD-2 base shear, upper bound [V/W]")
    ax_v.grid(True, alpha=0.3)

    ax_a.axhline(t.ACCELERATION_LIMIT, color="0.55", linestyle="--", linewidth=0.8)
    ax_a.axvline(t.DISPLACEMENT_CAPACITY, color="0.55", linestyle="--", linewidth=0.8)
    ax_a.set_xlim(0.55, 1.35)
    ax_a.set_ylim(0.25, 1.05)
    ax_a.text(0.57, t.ACCELERATION_LIMIT + 0.01, "0.30 g target", va="bottom",
              fontsize="x-small", color="0.4")
    ax_a.text(t.DISPLACEMENT_CAPACITY + 0.01, 1.03, "1.04 m FPS", ha="left",
              va="top", fontsize="x-small", color="0.4")
    ax_a.set_xlabel("DD-1 travel D$_{TM}$, lower bound [m]")
    ax_a.set_ylabel("Peak floor acceleration, nominal [g]")
    ax_a.grid(True, alpha=0.3)

    drift_top = max(0.65, 1.1 * max(100 * r["drift"] for r in rows.values()))
    ax_d.axhline(100 * t.DRIFT_LIMIT, color="0.55", linestyle="--", linewidth=0.8)
    ax_d.axvline(t.DISPLACEMENT_CAPACITY, color="0.55", linestyle="--", linewidth=0.8)
    ax_d.axvline(t.LRB_DISPLACEMENT_CAPACITY, color=t.GOLD, linestyle=":", linewidth=0.8)
    ax_d.set_xlim(0.55, 1.35)
    ax_d.set_ylim(0.0, drift_top)
    ax_d.text(1.33, 100 * t.DRIFT_LIMIT + 0.01, "0.50 % limit", ha="right", va="bottom",
              fontsize="x-small", color="0.4")
    ax_d.set_xlabel("DD-1 travel D$_{TM}$, lower bound [m]")
    ax_d.set_ylabel("DD-2 storey drift, upper bound [%]")
    ax_d.grid(True, alpha=0.3)

    handles, labels = ax_v.get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside upper center", ncol=3, frameon=False,
               fontsize="x-small")
    fig.savefig(path, metadata={"Software": None})
    t.plt.close(fig)
    return path


def main() -> None:
    """Sweep both bearing types on the FMUs and print the check table."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--fps-radius", type=float, nargs="*", default=FPS_GRID["radius"])
    parser.add_argument("--fps-friction", type=float, nargs="*", default=FPS_GRID["friction"])
    for key, values in LRB_GRID.items():
        parser.add_argument(f"--lrb-{key.replace('_', '-')}", type=float, nargs="*",
                            default=values)
    parser.add_argument("--plot", action="store_true")
    args = parser.parse_args()
    if args.plot:
        print(f"Wrote {plot()}")
        return
    existing = ({r["design"]: r for r in json.loads(OUT.read_text(encoding="utf-8"))}
                if OUT.exists() else {})
    def print_row(r: dict) -> None:
        if "drift" in r:
            ok = all(r[k] for k in r if k.endswith("_ok"))
            print(f"{r['design']:30s} {100 * r['drift']:6.3f}  {r['acceleration']:5.3f}  "
                  f"{r['shear']:.4f}  {r['travel']:7.3f}   {r['restoring']:.3f}    "
                  f"{r['period']:.2f}  {r.get('strain', 0):5.2f}  {'yes' if ok else 'no'}",
                  flush=True)

    todo = []
    if simulate_fmu is None:
        print("Note: fmpy is not installed (run: pip install fmpy); "
              "using pre-computed results from data/bearing_sweep.json.")
        rows = list(existing.values())
    else:
        t.RUNS.mkdir(parents=True, exist_ok=True)
        designs = ([fps_design(r, mu) for r, mu in product(args.fps_radius, args.fps_friction)]
                   + [lrb_design(**REPORT_LRB)]
                   + [lrb_design(**catalogue_lrb(*p)) for p in product(
                       args.lrb_diameter, args.lrb_lead_ratio, args.lrb_thickness,
                       args.lrb_modulus)])
        todo = [d for d in designs
                if (d["label"] not in existing or "drift" not in existing[d["label"]])
                and d["period"] <= MAX_PERIOD and d["wind_ok"]]
        for d in todo:
            row = evaluate(d, args.workers)
            existing[row["design"]] = row
            OUT.write_text(json.dumps(list(existing.values()), indent=1, default=float),
                           encoding="utf-8")
            print_row(row)
        rows = [existing[d["label"]] for d in designs if d["label"] in existing]
    if not todo:
        for r in rows:
            print_row(r)


if __name__ == "__main__":
    main()
