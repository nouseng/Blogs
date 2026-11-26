"""Time-history verification of the Bolu FTR hospital isolation on portable FMUs.

Runs the 11 three-component DD-2 and DD-1 report records on the exported
Model-Exchange FMUs (fmu/BoluFrictionPendulum.fmu, fmu/BoluLeadRubber.fmu,
fmu/BoluFixedBase.fmu) with FMPy. Neither OpenModelica nor the
StructuralDynamics Modelica library is required. Pre-computed 11-pair summary
results are also bundled in data/report_match.json for instant plotting.
"""

import argparse
import csv
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from functools import cache
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from scipy.linalg import eigh

if "IPython" not in sys.modules:
    matplotlib.use("Agg")

import bolu_record_pairs as rp

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
FMUS = HERE / "fmu"
RUNS = HERE / "runs"
IMAGES = HERE / "images"
# Checks against the Python full model on the ETABS matrices; not used in the blog
VERIFICATION = HERE / "verification"

ACCENT = "#0072B2"
GOLD = "#aa823c"
REFERENCE = "#c0392b"

GRAVITY = rp.GRAVITY
_EXTENTS = json.loads((DATA / "extents.json").read_text(encoding="utf-8"))
# Isolated weight as compiled into the FMUs: slab and floor masses of the condensed ETABS model
WEIGHT = (_EXTENTS["isolationMass"] + sum(_EXTENTS["mass"])) * GRAVITY
REPORT_WEIGHT = 1_078_806e3
FRICTION_NOMINAL = 0.055
FRICTION_UPPER = 0.0825
FRICTION_LOWER = 0.044
PENDULUM_RADIUS = 7.4
DAMPER_NOMINAL = 2.35e6
DAMPER_UPPER = 2.825e6
DAMPER_LOWER = 2.00e6
PERIOD_NOMINAL = 3.96
PERIOD_UPPER = 3.37
PERIOD_LOWER = 4.74
LRB_PERIOD_NOMINAL = 3.46
LRB_PERIOD_UPPER = 1.57
LRB_PERIOD_LOWER = 2.98
LEAD_YIELD_STRESS = 11e6
RUBBER_SHEAR_MODULUS = 0.6e6

PAIR_RECORDS = rp.RECORDS["DD-1"]
STOREYS = 8
OCCUPIED_DRIFT = slice(0, 8)
OCCUPIED_ACCELERATION = slice(0, 9)
STOPS_FILE = "stops_report.json"
FIGURES_ON = True
DAMPING = 0.02
RETAINED_MODES = 24
TRUNCATED_DAMPING = 0.02
FIXED_DAMPING = 0.02
ISOLATION_DAMPING = 0.005
SLIP = 1e-3

with (DATA / "isolator_groups.csv").open(encoding="utf-8") as _fh:
    _GROUPS = list(csv.DictReader(_fh))
# Load-weighted bearing centroid, the isolation centre compiled into the FMUs
ISOLATION_CENTRE = tuple(
    round(sum(float(g[a]) * float(g["load_kN"]) for g in _GROUPS)
          / sum(float(g["load_kN"]) for g in _GROUPS), 3) for a in "xy")
with (DATA / "monitored_points.csv").open(encoding="utf-8") as _fh:
    MONITORED_POINTS = tuple((float(r["x"]), float(r["y"])) for r in csv.DictReader(_fh))

REPORT_LEVELS = np.array([0.0, 4.5, 9.0, 13.5, 18.0, 22.5, 27.0, 31.5, 35.5])
REPORT_ACCELERATION_XY = np.array([
    [0.70, 0.67], [0.74, 0.83], [0.78, 0.81], [0.69, 0.70], [0.70, 0.53],
    [0.61, 0.52], [0.61, 0.81], [0.76, 0.95], [1.16, 1.47],
])

REPORT_DRIFT_XY = np.array([
    [0.31, 0.30], [0.42, 0.36], [0.42, 0.38], [0.41, 0.40],
    [0.38, 0.40], [0.32, 0.37], [0.38, 0.45], [0.26, 0.30],
]) / 100

# Isolator specification Table 7 (p. 12): DD-2 upper-bound storey shears [kN], Ground to Floor 7.
# Its base shear is exactly 1.077 times report Table 15 in x and y, so it is read as a
# scaled design limit and divided back for the comparison.
SPEC_STOREY_SHEAR_X = np.array([169_279, 173_419, 168_404, 155_016, 139_648, 116_648, 85_855, 53_315])
SPEC_STOREY_SHEAR_Y = np.array([183_590, 185_225, 175_584, 167_816, 148_273, 124_949, 94_590, 57_974])
SPEC_SHEAR_SCALE = 147_232 / 136_656.79

REPORT_POINT_TRAVEL_X = (1.008, 0.906, 0.807, 0.788)
REPORT_POINT_TRAVEL_Y = (1.020, 0.763, 0.981, 0.917)
REPORT_POINT_TRAVEL = (1.020, 0.906, 0.981, 0.917)
REPORT_DISPLACEMENT = 1.020
REPORT_BASE_SHEAR_X = 136_656.79e3 / REPORT_WEIGHT
REPORT_BASE_SHEAR_Y = 166_311.87e3 / REPORT_WEIGHT
REPORT_LRB_ACCELERATION_XY = np.array([
    [0.55, 0.56], [0.54, 1.19], [0.49, 0.49], [0.46, 0.46], [0.47, 0.47],
    [0.48, 0.48], [0.55, 0.55], [0.65, 0.67], [0.74, 0.77],
])
REPORT_LRB_DRIFT_XY = np.array([
    [0.42, 0.42], [0.55, 0.55], [0.53, 0.53], [0.49, 0.49],
    [0.42, 0.42], [0.35, 0.34], [0.32, 0.33], [0.19, 0.19],
]) / 100
REPORT_LRB_BASE_SHEAR_X = 299_469.09e3 / REPORT_WEIGHT
REPORT_LRB_BASE_SHEAR_Y = 299_660.73e3 / REPORT_WEIGHT

DRIFT_LIMIT = 0.005
ACCELERATION_LIMIT = 0.30
# Report design targets, §11 and §10.3.1 (pp. 33-34, 42): FPS D = 1040 mm against DD-1
# lower-bound point means up to 1020 mm and 1.1 x 906 mm = 997 mm at the mass centre;
# LRB D = 750 mm. TBDY 2018 needs capacity >= D_TM (Table 14.4 tests at 1.00 D_TM).
DISPLACEMENT_CAPACITY = 1.04
LRB_DISPLACEMENT_CAPACITY = 0.75

PAIR_STOP = 150
PAIRS = tuple(range(1, len(PAIR_RECORDS) + 1))
DD1 = len(PAIRS)
ISOLATED = "BoluFrictionPendulum"
# Craig-Bampton variant: flexible superstructure from 24 fixed-base Ritz vectors of Superstructure
MODAL = "BoluFrictionPendulumModal"
MODAL_MODES = 24
LEAD_RUBBER = "BoluLeadRubber"
FIXED = "BoluFixedBase"
PREFIX = "bolu"

# Report Table 10 LRB property modification factors (FQ, k2)
LRB_UPPER = (1.1 * 1.3 * 1.15, 1.3 * 1.3 * 1.15)  # (1.6445, 1.9435)
LRB_LOWER = (0.7 * 0.85, 0.9 * 0.85)              # (0.595, 0.765)
WIND_LOAD = 3.74e6
# Figure 4 animation: 0.25 s of record per frame at 12 frames/s
FRAME_STEP = 0.25
FRAME_RATE = 12


@cache
def unpacked(fmu_name: str) -> str:
    """Extract an FMU once per worker process."""
    from fmpy import extract
    return extract(str(FMUS / f"{fmu_name}.fmu"))


def fmu_outputs(fmu_name: str) -> list[str]:
    """Output variable names requested from the FMU."""
    names = []
    if fmu_name == MODAL:
        return [
            "isolationForceX", "isolationForceY",
            "isolationDisplacementX", "isolationDisplacementY", "isolationTwist",
            "building.frameAcceleration[1]", "building.frameAcceleration[2]",
            "building.frameYawAcceleration",
            *(f"building.modal{q}[{i}]" for q in ("Displacement", "Acceleration")
              for i in range(1, MODAL_MODES + 1)),
        ]
    if fmu_name != FIXED:
        names += [
            "base.a_0[1]", "base.a_0[2]", "base.yaw.a",
            "isolationForceX", "isolationForceY",
            "base.forceX", "base.forceY",
            "elasticBaseShearX", "elasticBaseShearY",
            "isolationDisplacementX", "isolationDisplacementY", "isolationTwist",
        ]
    else:
        names += [
            "groundAcceleration", "groundAccelerationY",
            "elasticBaseShearX", "elasticBaseShearY",
        ]
    for i in range(1, STOREYS + 1):
        names += [f"building.interstorey{q}[{i}]" for q in ("X", "Y", "Twist")]
        names += [f"building.floorAcceleration[{i},{a}]" for a in (1, 2)]
        names.append(f"building.rotation[{i}].a")
    return names


def storey_extents() -> dict:
    """Plan extents and storey properties from data/extents.json."""
    return _EXTENTS


FPS_KEYS = ("mass", "inertia", "massCentre", "isolationMass", "isolationInertia",
            "isolationMassCentre", "stiffnessMatrix")


@cache
def fps_extents() -> dict:
    """storey_extents with the condensed Superstructure matrices of the FPS models (keys *Fps)
    in place of the Foundation ones of the lead-rubber and fixed-base models."""
    return _EXTENTS | {key: _EXTENTS[f"{key}Fps"] for key in FPS_KEYS}


def model_extents(fmu_name: str) -> dict:
    """Storey properties of the ETABS model behind one FMU."""
    return fps_extents() if fmu_name in (ISOLATED, MODAL) else storey_extents()


def weight(ext: dict) -> float:
    """Seismic weight [N] carried by the isolators: slab and floors."""
    return (ext["isolationMass"] + sum(ext["mass"])) * GRAVITY


def stop_of(pair: int) -> float:
    """Stop time of a DD-2 or DD-1 pair index from stops_report.json."""
    for folder in (RUNS, DATA):
        path = folder / STOPS_FILE
        if path.exists():
            return float(json.loads(path.read_text(encoding="utf-8"))[str(pair)])
    return float(PAIR_STOP)


def ensure_record_table() -> Path:
    """Return runs/record_pairs.txt, generating it from data/ if needed."""
    RUNS.mkdir(parents=True, exist_ok=True)
    table = RUNS / "record_pairs.txt"
    if not table.exists():
        rp.main()
    return table


def building_values(fmu_name: str = "") -> dict:
    """Condensed ETABS matrices from extents.json as FMU start values.

    The FPS FMUs take the Superstructure stiffness, floor masses and isolation slab, the
    LRB and fixed-base FMUs the compiled Foundation values. This overrides the values
    compiled into the FMUs without a rebuild. The Craig-Bampton FMU takes only the
    slab and the weight; its superstructure is compiled in.
    """
    if fmu_name not in (ISOLATED, MODAL):
        return {f"building.stiffnessMatrix[{i + 1},{j + 1}]": v
                for i, row in enumerate(_EXTENTS["stiffnessMatrix"]) for j, v in enumerate(row)}
    ext = fps_extents()
    values = {"baseMass": ext["isolationMass"], "baseInertia": ext["isolationInertia"],
              "weight": weight(ext)}
    if fmu_name == MODAL:
        return values
    values |= {f"building.stiffnessMatrix[{i + 1},{j + 1}]": v
               for i, row in enumerate(ext["stiffnessMatrix"]) for j, v in enumerate(row)}
    for i, (m, inertia, (cx, cy)) in enumerate(zip(ext["mass"], ext["inertia"], ext["massCentre"])):
        values |= {f"building.floorMass[{i + 1}]": m, f"building.floorInertia[{i + 1}]": inertia,
                   f"building.massCentreX[{i + 1}]": cx, f"building.massCentreY[{i + 1}]": cy}
    return values


def simulate(case: dict) -> Path:
    """Run one FMU simulation via FMPy and cache the trajectories in runs/."""
    from fmpy import simulate_fmu
    RUNS.mkdir(parents=True, exist_ok=True)
    result_path = RUNS / f"{case['name']}.npz"
    if result_path.exists():
        return result_path
    table = ensure_record_table()
    fmu_name = case["class"]
    start_values = {"pairFile": table.as_posix(), **building_values(fmu_name)}
    if "radius" in case:
        start_values |= {"radius": case["radius"], "friction": case["friction"]}
    for k, val in case["extra"].items():
        if isinstance(val, bool):
            start_values[k] = val
        elif val in ("true", "false"):
            start_values[k] = val == "true"
        else:
            start_values[k] = float(val) if isinstance(val, str) else val
    res = simulate_fmu(
        unpacked(fmu_name),
        fmi_type="ModelExchange",
        stop_time=case["stop"],
        output_interval=0.005,
        relative_tolerance=1e-6,
        start_values=start_values,
        output=fmu_outputs(fmu_name),
    )
    np.savez_compressed(result_path, **{name: res[name] for name in res.dtype.names})
    return result_path


def run_all(cases: list[dict], workers: int) -> list[Path]:
    """Run FMU cases in parallel across processes."""
    with ProcessPoolExecutor(workers) as pool:
        return list(pool.map(simulate, cases))


def pair_cases(model: str, tag: str, offset: int,
               extra: dict | None = None, stops: dict | None = None,
               slip: float | None = None, **isolator: float) -> list[dict]:
    """Cases for the 11 record pairs in both orientations."""
    cases = []
    for k in PAIRS:
        for rotated in (False, True):
            label = "_".join(f"{key}{x:g}" for key, x in isolator.items())
            overrides = {
                "pairIndex": k + offset,
                "rotated": "true" if rotated else "false",
                "dampingRatio": f"{FIXED_DAMPING if model == FIXED else DAMPING:g}",
            }
            if model != FIXED:
                overrides["isolationDampingRatio"] = f"{ISOLATION_DAMPING:g}"
            if model not in (FIXED, MODAL):
                overrides["retainedModes"] = RETAINED_MODES
                overrides["truncatedRatio"] = f"{TRUNCATED_DAMPING:g}"
            if model in (ISOLATED, MODAL):
                slip = SLIP if slip is None else slip
                overrides["slidingYield"] = f"{slip:.5g}"
                label += f"_y{slip * 1e3:.4g}"
            cases.append({
                "class": model,
                "stop": stops[k] if stops else stop_of(k + offset),
                "extra": overrides | (extra or {}),
                "name": f"{tag}_{label}_p{k + offset}_r{int(rotated)}".replace("__", "_"),
                **isolator,
            })
    return cases


def result_reader(result: Path) -> tuple[list[str], callable]:
    """Variable names of an NPZ result and a getter."""
    data = np.load(result)
    names = list(data.files)

    def get(name: str) -> np.ndarray:
        return data[name] if name in data else np.zeros(1)

    return names, get


def corner_travel(get: callable, x: float, y: float) -> tuple[np.ndarray, np.ndarray]:
    """Isolator x and y displacement [m] at plan point (x, y) of the base."""
    ux, uy, twist = (get(f"isolation{n}") for n in
                     ("DisplacementX", "DisplacementY", "Twist"))
    return (ux - twist * (y - ISOLATION_CENTRE[1]),
            uy + twist * (x - ISOLATION_CENTRE[0]))


def _to_arrays(obj):
    """Recursively convert nested JSON lists to numpy arrays."""
    if isinstance(obj, dict):
        return {k: _to_arrays(v) for k, v in obj.items()}
    return np.array(obj)


def full_model() -> dict:
    """11-pair means of the full ETABS model with upper-bound properties: joint maxima
    and floor means of acceleration [g] and drift [-], from ../bolu_full_model.py."""
    raw = json.loads((DATA / "full_model_profiles.json").read_text(encoding="utf-8"))
    return _to_arrays(raw)


@cache
def report_curves() -> dict[str, dict[str, np.ndarray]]:
    """Load digitized Figure 26–29 curves from data/report_curves.json."""
    raw = json.loads((DATA / "report_curves.json").read_text(encoding="utf-8"))
    return {
        sys_key: {k: np.asarray(v, dtype=float) for k, v in group.items()}
        for sys_key, group in raw.items()
    }


@cache
def etabs_fps_drifts() -> dict:
    """Load 11-pair mean FPS storey drifts exported from ETABS (Superstructure)."""
    raw = json.loads((DATA / "etabs_fps_drifts.json").read_text(encoding="utf-8"))
    return _to_arrays(raw)


def smooth_profile(
    values: np.ndarray,
    levels: np.ndarray,
    samples_per_seg: int = 32,
) -> tuple[np.ndarray, np.ndarray]:
    """Interpolate storey values with Excel's cardinal cubic Bézier spline.

    Args:
        values: Horizontal profile values at each storey.
        levels: Storey elevations [m] matching values.
        samples_per_seg: Number of samples per storey interval.

    Returns:
        Tuple of smoothed (values, elevations) arrays.
    """
    pts = np.column_stack([values, levels])
    n = len(pts)
    tangents = np.zeros_like(pts)
    tangents[1:-1] = 0.5 * (pts[2:] - pts[:-2])
    tangents[0] = 0.5 * (pts[1] - pts[0])
    tangents[-1] = 0.5 * (pts[-1] - pts[-2])
    segments = []
    for i in range(n - 1):
        b0 = pts[i]
        b1 = pts[i] + tangents[i] / 3.0
        b2 = pts[i + 1] - tangents[i + 1] / 3.0
        b3 = pts[i + 1]
        t = np.linspace(0.0, 1.0, samples_per_seg, endpoint=(i == n - 2))[:, None]
        seg = (
            (1.0 - t) ** 3 * b0
            + 3.0 * (1.0 - t) ** 2 * t * b1
            + 3.0 * (1.0 - t) * t**2 * b2
            + t**3 * b3
        )
        segments.append(seg)
    curve = np.vstack(segments)
    return curve[:, 0], curve[:, 1]


def plan_peaks(get: callable, isolated: bool, extents: dict) -> tuple[dict, list]:
    """Storey drift [-] and floor acceleration [g] peaks, x and y separately.

    `drift` and `acc` are the maxima over the ETABS joints of each floor, as in the
    report's ETABS storey tables (Tables 17 to 20). On a rigid floor the response is
    linear in plan position, so the maximum lies on the extreme joint coordinates in
    `extents["storeys"]`. `centreDrift` and `centreAcc` are read at the mass centre.
    `pointDrift` and `pointAcc` hold one column per report monitored point (Nokta 1-4,
    Report Sekil 17), NaN where the point lies outside the storey plan (setback).
    Also returns the per-level accelerations for the storey shear.
    """
    out = {f"{q}{a}Abs": [] for q in ("drift", "centreDrift", "acc", "centreAcc",
                                      "pointDrift", "pointAcc") for a in "XY"}

    def at_points(sx, sy, alpha, plan, scale):
        lo_x, lo_y, hi_x, hi_y = plan
        for axis in "XY":
            row = []
            for x, y in MONITORED_POINTS:
                inside = lo_x - 1.0 <= x <= hi_x + 1.0 and lo_y - 1.0 <= y <= hi_y + 1.0
                s = sx - alpha * y if axis == "X" else sy + alpha * x
                row.append(np.abs(s).max() / scale if inside else np.nan)
            yield axis, row

    for i in range(STOREYS):
        lo_x, lo_y, hi_x, hi_y = extents["storeys"][i]
        h = extents["height"][i]
        twist = get(f"building.interstoreyTwist[{i + 1}]")
        dx = get(f"building.interstoreyX[{i + 1}]")
        dy = get(f"building.interstoreyY[{i + 1}]")
        cx, cy = extents["massCentre"][i]
        for axis, row in at_points(dx, dy, twist, extents["storeys"][i], h):
            out[f"pointDrift{axis}Abs"].append(row)
        for key, arms in (("drift", ((lo_y, hi_y), (lo_x, hi_x))),
                          ("centreDrift", ((cy,), (cx,)))):
            for axis, signals in (("X", [dx - twist * arm for arm in arms[0]]),
                                  ("Y", [dy + twist * arm for arm in arms[1]])):
                out[f"{key}{axis}Abs"].append(max(np.abs(s).max() for s in signals) / h)
    base_alpha = (
        get("base.yaw.a") if isolated else np.zeros_like(get("groundAcceleration"))
    )
    levels = [
        (
            get("base.a_0[1]") if isolated else get("groundAcceleration"),
            get("base.a_0[2]") if isolated else get("groundAccelerationY"),
            base_alpha,
            extents["storeys"][0],
            extents["isolationMassCentre"],
        )
    ]
    for i in range(STOREYS):
        levels.append((
            get(f"building.floorAcceleration[{i + 1},1]"),
            get(f"building.floorAcceleration[{i + 1},2]"),
            base_alpha + get(f"building.rotation[{i + 1}].a"),
            extents["storeys"][i],
            extents["massCentre"][i],
        ))
    for ax, ay, yaw_acc, (lo_x, lo_y, hi_x, hi_y), (cx, cy) in levels:
        for axis, row in at_points(ax, ay, yaw_acc, (lo_x, lo_y, hi_x, hi_y), GRAVITY):
            out[f"pointAcc{axis}Abs"].append(row)
        for key, arms in (("acc", ((lo_y, hi_y), (lo_x, hi_x))),
                          ("centreAcc", ((cy,), (cx,)))):
            for axis, signals in (("X", [ax - yaw_acc * arm for arm in arms[0]]),
                                  ("Y", [ay + yaw_acc * arm for arm in arms[1]])):
                out[f"{key}{axis}Abs"].append(max(np.abs(s).max() for s in signals) / GRAVITY)
    return out, levels


@cache
def modal_shapes() -> dict:
    """Mode-shape rows of every storey joint for the Craig-Bampton FMU, from data/cb_shapes.npz."""
    return dict(np.load(DATA / "cb_shapes.npz"))


def modal_peaks(get: callable) -> dict:
    """Storey maxima of joint drift and slab acceleration recovered from the modal outputs,
    with the definitions of the full model (all stacked joints, diaphragm slab joints)."""
    sh = modal_shapes()
    shapes, level, axis, plan = sh["shapes"], sh["level"], sh["axis"], sh["plan"]
    q, qa = (np.array([get(f"building.modal{name}[{i}]") for i in range(1, MODAL_MODES + 1)])
             for name in ("Displacement", "Acceleration"))
    frame = np.array([get("building.frameAcceleration[1]"), get("building.frameAcceleration[2]")])
    yaw = get("building.frameYawAcceleration")
    top, bottom = sh["pairs"].T
    drift, acc = np.zeros(len(level)), np.zeros(len(level))
    for s in range(0, len(top), 2000):
        rows = slice(s, s + 2000)
        rel = (shapes[top[rows]] - shapes[bottom[rows]]) @ q
        drift[top[rows]] = np.abs(rel).max(1) / sh["height"][level[top[rows]] - 1]
    lever = np.where(axis == 0, -plan[:, 1], plan[:, 0])
    for s in range(0, len(level), 2000):
        rows = slice(s, s + 2000)
        acc[rows] = np.abs(frame[axis[rows]] + lever[rows, None] * yaw
                           + shapes[rows] @ qa).max(1)
    stacked = np.zeros(len(level), bool)
    stacked[top] = True
    out = {}
    for k, name in enumerate("XY"):
        out[f"drift{name}Abs"] = [drift[stacked & (level == f) & (axis == k)].max()
                                  for f in range(1, STOREYS + 1)]
        out[f"acc{name}Abs"] = [acc[sh["slab"] & (level == f) & (axis == k)].max() / GRAVITY
                                for f in range(STOREYS + 1)]
    return out


def pair_peaks(result: Path, extents: dict) -> dict:
    """Absolute peaks of one pair run, x and y separately."""
    names, get = result_reader(result)
    if "building.modalDisplacement[1]" in names:
        out = {k: np.array(x) for k, x in modal_peaks(get).items()}
        fx, fy = get("isolationForceX"), get("isolationForceY")
        out["points"] = np.array([np.hypot(*corner_travel(get, x, y)).max()
                                  for x, y in MONITORED_POINTS])
        out["travel"] = float(out["points"].max())
        out["shearX"] = float(np.abs(fx).max() / weight(extents))
        out["shearY"] = float(np.abs(fy).max() / weight(extents))
        out["shear"] = float(np.hypot(fx, fy).max() / weight(extents))
        # Storey shears need the floor inertia of every joint, not recovered here
        out["storeyShearX"] = out["storeyShearY"] = np.full(STOREYS, np.nan)
        return out
    out, levels = plan_peaks(get, "base.a_0[1]" in names, extents)
    # Storey shear from floor inertia at the mass centres, comparable with spec Table 7
    # regardless of where on the floor the peak acceleration is read
    mass = np.array(extents["mass"])[:, None]
    floors = levels[1:]
    for axis, acc in (("X", [ax - alpha * cy for ax, _, alpha, _, (_, cy) in floors]),
                      ("Y", [ay + alpha * cx for _, ay, alpha, _, (cx, _) in floors])):
        shear = np.cumsum((mass * np.array(acc))[::-1], axis=0)[::-1]
        out[f"storeyShear{axis}"] = np.abs(shear).max(axis=1) / 1e3
    out = {k: np.array(x) for k, x in out.items()}
    if "isolationForceX" in names:
        fx, fy = get("isolationForceX"), get("isolationForceY")
        pts = np.array([np.hypot(*corner_travel(get, x, y)).max()
                        for x, y in MONITORED_POINTS])
        out["points"] = pts
        out["travel"] = float(pts.max())
    else:
        fx, fy = get("elasticBaseShearX"), get("elasticBaseShearY")
        out["points"] = np.zeros(len(MONITORED_POINTS))
        out["travel"] = 0.0
    out["shearX"] = float(np.abs(fx).max() / weight(extents))
    out["shearY"] = float(np.abs(fy).max() / weight(extents))
    out["shear"] = float(np.hypot(fx, fy).max() / weight(extents))
    return out


def pair_mean(cases: list[dict], extents: dict, workers: int) -> dict:
    """Per pair the larger of both orientations, then the mean over the pairs."""
    files = run_all(cases, workers)
    # Each FMU is post-processed with the storey properties of its own ETABS model
    if cases[0]["class"] in (ISOLATED, MODAL):
        extents = fps_extents()
    rows = [pair_peaks(f, extents) for f in files]
    out = {}
    for key in rows[0]:
        per_pair = [np.maximum(rows[j][key], rows[j + 1][key])
                    for j in range(0, len(rows), 2)]
        out[key] = np.mean(per_pair, axis=0)
    out["pointsX"] = np.mean([rows[j]["points"] for j in range(0, len(rows), 2)], axis=0)
    out["pointsY"] = np.mean([rows[j + 1]["points"] for j in range(0, len(rows), 2)], axis=0)
    for axis in "XY":
        out[f"storeyShear{axis}_X"] = np.mean(
            [rows[j][f"storeyShear{axis}"] for j in range(0, len(rows), 2)], axis=0)
    out["shearX_X"] = float(np.mean([rows[j]["shearX"] for j in range(0, len(rows), 2)]))
    out["shearY_X"] = float(np.mean([rows[j]["shearY"] for j in range(0, len(rows), 2)]))
    return out


def fps_bounds(radius: float, mu: float, slip: float,
               model: str = ISOLATED) -> list[list[dict]]:
    """Nominal, upper and lower bound pair cases of one FPS design."""
    tag = f"{PREFIX}cb" if model == MODAL else PREFIX
    return [
        pair_cases(
            model, f"{tag}nom", 0,
            {"isolationPeriod": PERIOD_NOMINAL, "damperCoefficient": DAMPER_NOMINAL},
            slip=slip, radius=radius, friction=mu,
        ),
        pair_cases(
            model, f"{tag}up", 0,
            {"isolationPeriod": PERIOD_UPPER, "damperCoefficient": DAMPER_UPPER},
            slip=slip, radius=radius, friction=1.5 * mu,
        ),
        pair_cases(
            model, f"{tag}low", DD1,
            {"isolationPeriod": PERIOD_LOWER, "damperCoefficient": DAMPER_LOWER},
            slip=slip, radius=radius, friction=0.8 * mu,
        ),
    ]


def fps_dd1_upper(model: str = ISOLATED) -> list[dict]:
    """DD-1 pair cases of the report FPS design with upper-bound properties, the ETABS basis."""
    tag = f"{PREFIX}cb" if model == MODAL else PREFIX
    return pair_cases(
        model, f"{tag}up1", DD1,
        {"isolationPeriod": PERIOD_UPPER, "damperCoefficient": DAMPER_UPPER},
        slip=SLIP, radius=PENDULUM_RADIUS, friction=1.5 * FRICTION_NOMINAL,
    )


def modal_results(case: str) -> dict | None:
    """Craig-Bampton results of bolu_craig_bampton.py validate: "upper" (DD-2 upper bound,
    data/report_match_modal.json) or "mce" (DD-1 upper bound of the Guyan and the
    Craig-Bampton FMU, data/report_match_mce.json). None before the first validation."""
    path = DATA / ("report_match_modal.json" if case == "upper" else "report_match_mce.json")
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))

    def arrays(r: dict) -> dict:
        return {k: np.array(v) for k, v in r.items()}

    return arrays(raw["upper"]) if case == "upper" else {k: arrays(r) for k, r in raw.items()}


def lrb_bounds() -> list[list[dict]]:
    """Upper and lower bound pair cases of the Report Table 11 LRB design."""
    q_up, k_up = LRB_UPPER
    q_lo, k_lo = LRB_LOWER
    return [
        pair_cases(
            LEAD_RUBBER, f"{PREFIX}lrb_up", 0,
            {
                "leadYieldStress": 11e6 * q_up,
                "rubberShearModulus": 0.6e6 * k_up,
                "damperCoefficient": DAMPER_UPPER,
                "isolationPeriod": LRB_PERIOD_UPPER,
            },
        ),
        pair_cases(
            LEAD_RUBBER, f"{PREFIX}lrb_low", DD1,
            {
                "leadYieldStress": 11e6 * q_lo,
                "rubberShearModulus": 0.6e6 * k_lo,
                "damperCoefficient": DAMPER_LOWER,
                "isolationPeriod": LRB_PERIOD_LOWER,
            },
        ),
    ]


def fixed_cases() -> list[dict]:
    """Fixed-base pair cases, DD-2."""
    return pair_cases(FIXED, f"{PREFIX}fix", 0)


def matrices(ext: dict | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Fixed-base M and K for x, y and yaw of each floor from extents.json (Foundation by
    default, fps_extents() for the FPS models)."""
    ext = ext or storey_extents()
    mass, inertia = np.array(ext["mass"]), np.array(ext["inertia"])
    cx, cy = np.array(ext["massCentre"]).T
    n = len(mass)
    mm = np.zeros((3 * n, 3 * n))
    for i in range(n):
        a = slice(3 * i, 3 * i + 3)
        mm[a, a] = [[mass[i], 0, -mass[i] * cy[i]], [0, mass[i], mass[i] * cx[i]],
                    [-mass[i] * cy[i], mass[i] * cx[i],
                     inertia[i] + mass[i] * (cx[i] ** 2 + cy[i] ** 2)]]
    return mm, np.array(ext["stiffnessMatrix"])


def plot_match_pairs(
    upper: dict,
    prof: dict | None = None,
    tab_drift: np.ndarray | None = None,
    tab_acc: np.ndarray | None = None,
    drift_limit: float | None = None,
    suffix: str = "",
    full: bool = False,
    acc_label: str = "ETABS (Superstructure)",
    modal: dict | None = None,
    acceleration: bool = True,
) -> list[Path]:
    """Plot drift and acceleration profiles of ETABS or the report against the 27-DOF model.

    With `full`, also plot the Python full model and write to verification/. `modal` adds
    the drift of the Craig-Bampton FMU; `acceleration` False skips the acceleration plot.
    """
    out_dir = VERIFICATION if full else IMAGES
    out_dir.mkdir(parents=True, exist_ok=True)
    if prof is None:
        prof = full_model()
    curves = report_curves()["lrb"]
    quantities = (
        ("Drift", 100, tab_drift, REPORT_LEVELS[1:], drift_limit, "Drift [%]"),
        ("Acceleration", 1, tab_acc, REPORT_LEVELS, ACCELERATION_LIMIT, "Acceleration [g]"),
    )
    paths = []
    for name, scale, tabulated, levels, limit, label in quantities:
        if (tabulated is None and not full) or (name == "Acceleration" and not acceleration):
            continue
        key = name.lower()
        short = "Drift" if name == "Drift" else "Acc"
        default_tab = REPORT_LRB_DRIFT_XY if name == "Drift" else REPORT_LRB_ACCELERATION_XY
        rep_xy = None
        ref_label = None
        if tabulated is not None:
            if suffix == "LRB" and np.array_equal(tabulated, default_tab):
                rep_z = curves[f"{key}Z"]
                rep_xy = scale * curves[key]
                ref_label = "Design report"
            else:
                rx, rep_z = smooth_profile(scale * tabulated[:, 0], levels)
                ry, _ = smooth_profile(scale * tabulated[:, 1], levels)
                rep_xy = np.column_stack([rx, ry])
                ref_label = "ETABS (Superstructure)" if name == "Drift" else acc_label
        fig, axes = plt.subplots(
            1, 2, figsize=(6.5, 4.2), sharey=True, layout="constrained"
        )
        for d, (ax, axis) in enumerate(zip(axes, "XY")):
            joint_max = np.asarray(upper[f"{short.lower()}{axis}Abs"])[: len(levels)]
            if rep_xy is not None:
                ax.plot(
                    rep_xy[:, d], rep_z, color=REFERENCE, linewidth=1.6, label=ref_label,
                    zorder=3,
                )
            cen_x, cen_z = smooth_profile(scale * joint_max, levels)
            if full:
                joint_x, joint_z = smooth_profile(scale * prof[f"{key}Joint"][:, d], levels)
                ax.plot(
                    joint_x, joint_z, color=GOLD, linewidth=1.2, linestyle="--",
                    label="Full ETABS matrices (Python)",
                )
                if modal is not None and name == "Drift":
                    cb_x, cb_z = smooth_profile(
                        scale * np.asarray(modal[f"drift{axis}Abs"])[: len(levels)], levels)
                    ax.plot(cb_x, cb_z, color="0.35", linewidth=1.2, linestyle="-.",
                            label="Modelica Craig-Bampton 24 Ritz")
            ax.plot(
                cen_x, cen_z, color=ACCENT, linewidth=1.6, zorder=4,
                label="Modelica 27-DOF with torsion",
            )
            if limit is not None:
                ax.axvline(
                    scale * limit, color="0.55", linewidth=0.8, linestyle="--",
                    label="Design limit",
                )
            if name == "Acceleration" and suffix == "LRB" and axis == "Y" and rep_xy is not None:
                peak_idx = int(np.argmax(rep_xy[:, d]))
                ax.annotate(
                    "Ground\n(canopy)",
                    (float(rep_xy[peak_idx, d]), float(rep_z[peak_idx])),
                    xytext=(-4, 16), textcoords="offset points", ha="center",
                    fontsize=6.5, color="0.3",
                )
            ax.set_xlabel(f"{label}, {axis} direction")
            ax.grid(True, alpha=0.3)
        span = 1.05 * max(ax.get_xlim()[1] for ax in axes)
        for ax in axes:
            ax.set_xlim(0, span)
        axes[0].set_ylabel("Elevation [m]")
        handles, labels = axes[0].get_legend_handles_labels()
        fig.legend(handles, labels, loc="outside upper center", ncol=2, frameon=False)
        path = out_dir / f"Report{name}{suffix}.png"
        fig.savefig(path, metadata={"Software": None})
        plt.close(fig)
        paths.append(path)
    return paths


def plot_levels(prof: dict) -> list[Path]:
    """Plot smooth FPS full-model DD-2 and DD-1 drift profiles against ETABS."""
    IMAGES.mkdir(parents=True, exist_ok=True)
    et = etabs_fps_drifts()
    levels = REPORT_LEVELS[1:]
    fig, axes = plt.subplots(
        1, 2, figsize=(6.5, 4.2), sharey=True, layout="constrained"
    )
    for d, (ax, axis) in enumerate(zip(axes, "XY")):
        dd2_x, dd2_z = smooth_profile(100.0 * prof["driftJoint"][:, d], levels)
        dd1_x, dd1_z = smooth_profile(100.0 * prof["dd1"]["driftJoint"][:, d], levels)
        et2_x, et2_z = smooth_profile(100.0 * et["dbe"]["x"][:, d], levels)
        et1_x, et1_z = smooth_profile(100.0 * et["mce"]["x"][:, d], levels)
        ax.plot(et2_x, et2_z, color=GOLD, linewidth=1.6, label="ETABS DD-2")
        ax.plot(
            dd2_x, dd2_z, color=GOLD, linewidth=1.4, linestyle="--", label="Python DD-2"
        )
        ax.plot(et1_x, et1_z, color=ACCENT, linewidth=1.6, label="ETABS DD-1")
        ax.plot(
            dd1_x, dd1_z, color=ACCENT, linewidth=1.4, linestyle="--", label="Python DD-1"
        )
        ax.set_xlabel(f"Drift [%], {axis} direction")
        ax.grid(True, alpha=0.3)
    span = 1.05 * max(ax.get_xlim()[1] for ax in axes)
    for ax in axes:
        ax.set_xlim(0, span)
    axes[0].set_ylabel("Elevation [m]")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles, labels, loc="outside upper center", ncol=4, frameon=False, fontsize=8
    )
    VERIFICATION.mkdir(parents=True, exist_ok=True)
    path = VERIFICATION / "ReportDriftLevels.png"
    fig.savefig(path, metadata={"Software": None})
    plt.close(fig)
    return [path]


def plot_parity(
    extents: dict,
    prof: dict,
    tab_drift: np.ndarray,
    tab_acc: np.ndarray,
    suffix: str = "",
) -> Path:
    """Model against report, drift and floor acceleration."""
    IMAGES.mkdir(parents=True, exist_ok=True)
    z = np.array(extents["elevation"])
    fig, axes = plt.subplots(1, 2, figsize=(6.5, 3.6), layout="constrained")
    for ax, model, report, levels, top, unit, title in (
        (
            axes[0],
            100 * prof["driftJoint"],
            100 * tab_drift,
            z[:len(tab_drift)],
            0.65,
            "%",
            "Storey drift",
        ),
        (
            axes[1],
            prof["accelerationJoint"],
            tab_acc,
            REPORT_LEVELS,
            1.55,
            "g",
            "Floor acceleration",
        ),
    ):
        line = np.array([0, top])
        ax.fill_between(line, 0.9 * line, 1.1 * line, color=ACCENT, alpha=0.12,
                        linewidth=0, label="Within 10 %")
        ax.plot(line, line, color="k", linewidth=0.8, label="Perfect match")
        setback = np.broadcast_to((levels[:, None] >= 31.0), report.shape)
        canopy = np.zeros_like(report, dtype=bool)
        if suffix == "LRB" and title == "Floor acceleration":
            canopy[1, 1] = True
        for mask, colour, label in (
            (~setback & ~canopy, ACCENT, "Lower wing"),
            (setback & ~canopy, GOLD, "Setback core"),
        ):
            ax.plot(report[mask], model[mask], ls="none", marker="o", ms=4,
                    color=colour, label=label)
        if canopy.any():
            ax.plot(report[canopy], model[canopy], ls="none", marker="o", ms=4.5,
                    mfc="none", mec=ACCENT, mew=1.1)
            pt_xy = (float(report[1, 1]), float(model[1, 1]))
            ax.annotate("Ground Y\n(canopy)", pt_xy, xytext=(0, -22),
                        textcoords="offset points", ha="center",
                        fontsize=6.5, color=ACCENT)
        ax.set_xlim(0, top)
        ax.set_ylim(0, top)
        ax.set_aspect("equal")
        ax.set_xlabel(f"Design report [{unit}]")
        ax.set_ylabel(f"Full model [{unit}]")
        ax.set_title(title, fontsize="medium")
        ax.grid(True, alpha=0.3)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside upper center", ncol=4, frameon=False,
               fontsize="small")
    VERIFICATION.mkdir(parents=True, exist_ok=True)
    path = VERIFICATION / f"ReportMatch{suffix}.png"
    fig.savefig(path, metadata={"Software": None})
    plt.close(fig)
    return path


def plot_orbits(cases: list[dict], extents: dict, workers: int = 1) -> Path:
    """Planar isolator travel at the report's four monitored points, DD-1 lower bound."""
    IMAGES.mkdir(parents=True, exist_ok=True)
    readers = [result_reader(f)[1] for f in run_all(cases, workers)]
    circle = np.linspace(0, 2 * np.pi, 361)
    colours = plt.cm.tab20(np.arange(len(PAIRS)))
    fig, axes = plt.subplots(2, 2, figsize=(6.5, 6.4), sharex=True, sharey=True,
                             layout="constrained")
    for point, (ax, (x, y), report) in enumerate(
            zip(axes.flat, MONITORED_POINTS, REPORT_POINT_TRAVEL), 1):
        peaks_x, peaks_y = [], []
        for j, get in enumerate(readers):
            ux, uy = corner_travel(get, x, y)
            pk = np.hypot(ux, uy).max()
            if j % 2 == 0:
                peaks_x.append(pk)
            else:
                peaks_y.append(pk)
            ax.plot(1e3 * ux, 1e3 * uy, color=colours[j // 2], linewidth=0.45,
                    alpha=0.75, label=f"Pair {j // 2 + 1}" if j % 2 == 0 else None)
        mean = max(float(np.mean(peaks_x)), float(np.mean(peaks_y)))
        for radius, style, label in (
                (DISPLACEMENT_CAPACITY, {"color": "k", "linewidth": 1.3},
                 f"Capacity, {1e3 * DISPLACEMENT_CAPACITY:.0f} mm"),
                (report, {"color": REFERENCE, "linewidth": 1.2, "linestyle": "--"},
                 f"Report mean, {1e3 * report:.0f} mm"),
                (mean, {"color": ACCENT, "linewidth": 1.3},
                 f"Model mean, {1e3 * mean:.0f} mm")):
            ax.plot(1e3 * radius * np.cos(circle), 1e3 * radius * np.sin(circle),
                    **style, label=label)
        ax.set_aspect("equal")
        ax.set_xlim(-1250, 1250)
        ax.set_ylim(-1250, 1250)
        if point in (3, 4):
            ax.set_xlabel("x displacement [mm]")
        if point in (1, 3):
            ax.set_ylabel("y displacement [mm]")
        ax.set_title(f"Point {point} ({x:.1f} m, {y:.1f} m)", fontsize="small")
        ax.grid(True, alpha=0.3)
        ax.legend(*(x[len(PAIRS):] for x in ax.get_legend_handles_labels()),
                  loc="lower right", frameon=True, facecolor="white", framealpha=0.85,
                  fontsize=6.5)
    handles = [matplotlib.lines.Line2D([], [], color=colours[k], linewidth=1.5)
               for k in range(len(PAIRS))]
    labels = [f"RSN {rsn}" for rsn in PAIR_RECORDS]
    fig.legend(handles, labels, loc="outside upper center",
               ncol=(len(PAIRS) + 2) // 3, frameon=False, fontsize="x-small")
    path = IMAGES / "ReportTravel.png"
    fig.savefig(path, metadata={"Software": None})
    plt.close(fig)
    return path


def plot_travel_history(cases: list[dict], workers: int = 1) -> Path:
    """Animated FPS slider orbit (left) and ground motion (right) of the DD-1 lower-bound run
    with the largest travel inside the capacity at any of the four monitored points."""
    IMAGES.mkdir(parents=True, exist_ok=True)
    runs = []
    for case, path in zip(cases, run_all(cases, workers)):
        get = result_reader(path)[1]
        points = [(np.hypot(*corner_travel(get, x, y)).max(), point)
                  for point, (x, y) in enumerate(MONITORED_POINTS, 1)]
        runs.append((*max(points), case, get))
    # Past the capacity no model has the restrainer, so take the largest run inside it
    peak, point, case, get = max(
        (r for r in runs if r[0] <= DISPLACEMENT_CAPACITY), key=lambda r: r[0])
    ux, uy = corner_travel(get, *MONITORED_POINTS[point - 1])
    pair = case["extra"]["pairIndex"]
    rotated = case["extra"]["rotated"] == "true"
    rsn = PAIR_RECORDS[pair - DD1 - 1]
    table = np.loadtxt(ensure_record_table(), skiprows=2)
    ground = table[:, 1 + 3 * (pair - 1):3 + 3 * (pair - 1)] / GRAVITY
    if rotated:
        ground = ground[:, ::-1]
    time = get("time")
    stop = time[-1]
    x, y = MONITORED_POINTS[point - 1]
    models = [("Modelica 27-DOF", ACCENT, time, ux, uy)]
    full_file = DATA / f"full_model_travel_dd1low_p{pair - DD1}_r{int(rotated)}.npz"
    if full_file.exists():
        full = np.load(full_file)
        models.append(("Full ETABS model", GOLD, full["time"],
                       *corner_travel(lambda n: full[n], x, y)))
    frames = np.arange(0.0, stop + FRAME_STEP, FRAME_STEP)
    fig = plt.figure(figsize=(9.0, 4.0), layout="constrained")
    axes = fig.subplot_mosaic([["orbit", "x"], ["orbit", "y"]],
                              width_ratios=(1.0, 1.35))
    orbit = axes["orbit"]
    circle = np.linspace(0, 2 * np.pi, 361)
    cap = 1e3 * DISPLACEMENT_CAPACITY
    orbit.plot(cap * np.cos(circle), cap * np.sin(circle), color=REFERENCE,
               linestyle="--", linewidth=1.2, label=f"Capacity, {cap:.0f} mm")
    trails, sliders = [], []
    for label, colour, *_ in models:
        trails.append(orbit.plot([], [], color=colour, linewidth=1.0, alpha=0.85,
                                 label=label)[0])
        sliders.append(orbit.plot([], [], "o", color=colour, markeredgecolor="k",
                                  markersize=7)[0])
    readout = orbit.text(0.03, 0.97, "", transform=orbit.transAxes, va="top",
                         fontsize="x-small", family="monospace")
    lim = 1.1 * max(cap, *(1e3 * np.hypot(m[3], m[4]).max() for m in models))
    orbit.set_xlim(-lim, lim)
    orbit.set_ylim(-lim, lim)
    orbit.set_aspect("equal")
    orbit.set_xlabel("x displacement [mm]")
    orbit.set_ylabel("y displacement [mm]")
    orbit.set_title(f"FPS isolator at Point {point}", fontsize="small")
    orbit.legend(loc="lower right", fontsize="x-small", frameon=True, framealpha=0.85)
    orbit.grid(True, alpha=0.3)
    axes["x"].set_title(f"RSN {rsn}, MCE_{rsn}_{'Y' if rotated else 'X'} (scaled)",
                        fontsize="small")
    glim = 1.1 * np.abs(ground).max()
    traces, cursors = [], []
    for k in range(2):
        ax = axes["xy"[k]]
        ax.plot(table[:, 0], ground[:, k], color="0.85", linewidth=0.5)
        traces.append(ax.plot([], [], color="0.25", linewidth=0.5)[0])
        cursors.append(ax.axvline(0.0, color=REFERENCE, linewidth=0.8))
        ax.set_xlim(0, stop)
        ax.set_ylim(-glim, glim)
        ax.set_ylabel(f"$a_{'xy'[k]}$ [g]")
        ax.grid(True, alpha=0.3)
    axes["x"].tick_params(labelbottom=False)
    axes["y"].set_xlabel("Time [s]")
    tags = ("27-DOF", "full")

    def draw(now: float) -> None:
        lines = [f"t = {now:5.1f} s"]
        for k, (_, _, t_m, x_m, y_m) in enumerate(models):
            n = np.searchsorted(t_m, now, side="right")
            trails[k].set_data(1e3 * x_m[:n], 1e3 * y_m[:n])
            sliders[k].set_data(1e3 * x_m[max(n - 1, 0):n], 1e3 * y_m[max(n - 1, 0):n])
            so_far = 1e3 * np.hypot(x_m[:n], y_m[:n]).max(initial=0.0)
            ended = now > t_m[-1] + FRAME_STEP
            sliders[k].set_marker("X" if ended else "o")
            lines.append(f"peak {tags[k]:<6} = {so_far:5.0f} mm"
                         + (f", stops {t_m[-1]:.1f} s" if ended else ""))
        readout.set_text("\n".join(lines))
        m = np.searchsorted(table[:, 0], now, side="right")
        for k in range(2):
            traces[k].set_data(table[:m, 0], ground[:m, k])
            cursors[k].set_xdata([now, now])

    from matplotlib.animation import FuncAnimation, PillowWriter
    anim = FuncAnimation(fig, draw, frames=frames)
    path = IMAGES / "TravelHistory.gif"
    anim.save(path, writer=PillowWriter(fps=FRAME_RATE), dpi=80)
    plt.close(fig)
    return path


def load_isolator_geometry() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Read all 184 bearings, 16 group positions, and 64 dampers from data/."""
    with (DATA / "isolators.csv").open(encoding="utf-8") as f:
        bearings = np.array([[float(r["x"]), float(r["y"]), int(r["group"])]
                             for r in csv.DictReader(f)])
    with (DATA / "isolator_groups.csv").open(encoding="utf-8") as f:
        groups = np.array([[float(r["x"]), float(r["y"]), int(r["count"])]
                           for r in csv.DictReader(f)])
    with (DATA / "dampers.csv").open(encoding="utf-8") as f:
        dampers = np.array([[float(r["x"]), float(r["y"]), float(r["nx"]), float(r["ny"])]
                            for r in csv.DictReader(f)])
    return bearings, groups, dampers


def group_displacements(
    data: dict[str, np.ndarray], groups: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (ux, uy) arrays of shape (16, n_steps) in metres for all 16 groups."""
    if "bearingDisplacementX[1]" in data:
        ux = np.vstack([data[f"bearingDisplacementX[{i}]"] for i in range(1, 17)])
        uy = np.vstack([data[f"bearingDisplacementY[{i}]"] for i in range(1, 17)])
        return ux, uy
    ux0 = data["isolationDisplacementX"]
    uy0 = data["isolationDisplacementY"]
    twist = data["isolationTwist"]
    dx = groups[:, 0:1] - ISOLATION_CENTRE[0]
    dy = groups[:, 1:2] - ISOLATION_CENTRE[1]
    return ux0 - twist * dy, uy0 + twist * dx


def plot_plan_displacements(
    model: str, filename: str, orbit_scale: float = 25.0,
) -> Path:
    """Simulate DD-2 Pair 1 (RSN 173, 37.1 s) and plot the 16 isolator groups' plan orbits."""
    from fmpy import simulate_fmu

    table = ensure_record_table()
    outputs = [
        "isolationDisplacementX",
        "isolationDisplacementY",
        "isolationTwist",
        *[f"bearingDisplacementX[{i}]" for i in range(1, 17)],
        *[f"bearingDisplacementY[{i}]" for i in range(1, 17)],
    ]
    res = simulate_fmu(
        unpacked(model),
        fmi_type="ModelExchange",
        stop_time=stop_of(1),
        output_interval=0.02,
        relative_tolerance=1e-6,
        start_values={"pairFile": table.as_posix(), "pairIndex": 1},
        output=outputs,
    )
    data = {k: np.asarray(res[k], dtype=float) for k in res.dtype.names}
    bearings, groups, dampers = load_isolator_geometry()
    ux, uy = group_displacements(data, groups)
    ux_c = data["isolationDisplacementX"]
    uy_c = data["isolationDisplacementY"]
    peaks_mm = 1e3 * np.hypot(ux, uy).max(axis=1)
    peak_x_mm = 1e3 * np.abs(ux).max(axis=1)
    peak_y_mm = 1e3 * np.abs(uy).max(axis=1)

    fig = plt.figure(figsize=(6.5, 6.2), dpi=100, layout="constrained")
    gs = fig.add_gridspec(2, 2, height_ratios=[1.35, 1.0])
    ax_plan = fig.add_subplot(gs[0, :])
    ax_orbit = fig.add_subplot(gs[1, 0])
    ax_prof = fig.add_subplot(gs[1, 1])

    ax_plan.scatter(bearings[:, 0], bearings[:, 1], s=8, color="0.72", alpha=0.6,
                    label="184 bearings (ETABS)")
    ax_plan.scatter(dampers[:, 0], dampers[:, 1], s=14, marker="d", color=GOLD, alpha=0.65,
                    label="64 viscous dampers")
    for g in range(16):
        gx, gy = groups[g, 0], groups[g, 1]
        ax_plan.plot(gx + orbit_scale * ux[g], gy + orbit_scale * uy[g],
                     color=ACCENT, linewidth=0.75, alpha=0.85,
                     label=f"Group orbit (×{orbit_scale:g})" if g == 0 else None)
        idx_max = int(np.argmax(np.hypot(ux[g], uy[g])))
        ax_plan.annotate(
            "", xy=(gx + orbit_scale * ux[g, idx_max], gy + orbit_scale * uy[g, idx_max]),
            xytext=(gx, gy),
            arrowprops={"arrowstyle": "->", "color": REFERENCE, "lw": 1.0,
                        "shrinkA": 0, "shrinkB": 0},
        )
        ax_plan.plot(gx, gy, "o", color="k", ms=3.5, zorder=4,
                     label="16 group centroids" if g == 0 else None)
        ax_plan.text(gx, gy + 4.8, f"G{g + 1}",
                     fontsize=6.5, ha="center", va="bottom", color="0.2")
    ax_plan.plot([], [], color=REFERENCE, lw=1.2, label=f"Peak vector (×{orbit_scale:g})")
    ax_plan.plot(*ISOLATION_CENTRE, "+", color=REFERENCE, ms=8, mew=1.8, label="Isolation centre")
    ax_plan.set_aspect("equal")
    ax_plan.set_xlim(-50, 88)
    ax_plan.set_ylim(-88, 52)
    ax_plan.set_xlabel("Plan x from isolator centroid [m]")
    ax_plan.set_ylabel("Plan y [m]")
    ax_plan.grid(True, alpha=0.3)
    ax_plan.legend(loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=3,
                   frameon=False, fontsize="x-small", borderaxespad=0.0)

    for ux_i, uy_i, color, style, label in (
        (ux[0], uy[0], ACCENT, "-", f"West G1 ({peaks_mm[0]:.0f} mm)"),
        (ux_c, uy_c, "0.25", "--", f"Centre ({1e3 * np.hypot(ux_c, uy_c).max():.0f} mm)"),
        (ux[15], uy[15], GOLD, "-", f"East G16 ({peaks_mm[15]:.0f} mm)"),
    ):
        ax_orbit.plot(1e3 * ux_i, 1e3 * uy_i, color=color, linestyle=style,
                      linewidth=0.9, label=label)
    lim = max(300.0, 1.15 * float(peaks_mm.max()))
    ax_orbit.set_aspect("equal")
    ax_orbit.set_xlim(-lim, lim)
    ax_orbit.set_ylim(-lim, lim)
    ax_orbit.set_xlabel("Travel along x [mm]")
    ax_orbit.set_ylabel("Travel along y [mm]")
    ax_orbit.grid(True, alpha=0.3)
    ax_orbit.legend(loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=1,
                    frameon=False, fontsize="x-small", borderaxespad=0.0)

    order = np.argsort(groups[:, 0])
    ax_prof.plot(groups[order, 0], peaks_mm[order], "o-", color=ACCENT, ms=4,
                 linewidth=1.2, label="Resultant")
    ax_prof.plot(groups[order, 0], peak_x_mm[order], "s--", color=GOLD, ms=3.5,
                 linewidth=0.9, label="|ux| peak")
    ax_prof.plot(groups[order, 0], peak_y_mm[order], "^:", color=REFERENCE, ms=3.5,
                 linewidth=0.9, label="|uy| peak")
    ax_prof.set_xlabel("Group x position [m]")
    ax_prof.set_ylabel("Peak travel [mm]")
    ax_prof.set_ylim(0, 1.15 * float(peaks_mm.max()))
    ax_prof.grid(True, alpha=0.3)
    ax_prof.legend(loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=3,
                   frameon=False, fontsize="x-small", borderaxespad=0.0)

    IMAGES.mkdir(parents=True, exist_ok=True)
    path = IMAGES / filename
    fig.savefig(path, metadata={"Software": None})
    model_imgs = HERE.parent / "BoluHospital/Resources/Images/Models"
    if model_imgs.exists():
        fig.savefig(model_imgs / filename, metadata={"Software": None})
    plt.close(fig)
    return path


def plot_model_docs() -> list[Path]:
    """Render BoluHospital/Resources/Images/Models/{FixedBase,Isolated*}.png for Pair 1."""
    from fmpy import simulate_fmu

    model_imgs = HERE.parent / "BoluHospital/Resources/Images/Models"
    model_imgs.mkdir(parents=True, exist_ok=True)
    table = ensure_record_table()
    stop = stop_of(1)
    written = []
    specs = [
        (FIXED, "FixedBase.png", 4.33, [
            ("Acceleration along x [m/s²]", [
                ("groundAcceleration", 1.0, ACCENT, "Ground"),
                ("building.floorAcceleration[8,1]", 1.0, GOLD, "Roof"),
            ]),
            ("Elastic base shear along x [MN]", [
                ("elasticBaseShearX", 1e-6, ACCENT, "Fixed base"),
            ]),
        ]),
        (ISOLATED, "IsolatedFrictionPendulum.png", 6.5, [
            ("Acceleration along x [m/s²]", [
                ("base.a_0[1]", 1.0, ACCENT, "Ground"),
                ("building.floorAcceleration[8,1]", 1.0, GOLD, "Roof"),
            ]),
            ("Isolation travel [m]", [
                ("isolationDisplacementX", 1.0, ACCENT, "Along x"),
                ("isolationDisplacementY", 1.0, GOLD, "Along y"),
            ]),
            ("Isolation shear along x [MN]", [
                ("isolationForceX", 1e-6, ACCENT, "Bearings, dashpot and dampers"),
            ]),
        ]),
        (LEAD_RUBBER, "IsolatedLeadRubber.png", 6.5, [
            ("Acceleration along x [m/s²]", [
                ("base.a_0[1]", 1.0, ACCENT, "Ground"),
                ("building.floorAcceleration[8,1]", 1.0, GOLD, "Roof"),
            ]),
            ("Isolation travel [m]", [
                ("isolationDisplacementX", 1.0, ACCENT, "Along x"),
                ("isolationDisplacementY", 1.0, GOLD, "Along y"),
            ]),
            ("Isolation shear along x [MN]", [
                ("isolationForceX", 1e-6, ACCENT, "Lead rubber and dampers"),
            ]),
        ]),
    ]
    fix_res = simulate_fmu(
        unpacked(FIXED), fmi_type="ModelExchange", stop_time=stop, output_interval=0.02,
        relative_tolerance=1e-6, start_values={"pairFile": table.as_posix(), "pairIndex": 1},
        output=["groundAcceleration", "building.floorAcceleration[8,1]", "elasticBaseShearX"],
    )
    ag_x = np.asarray(fix_res["groundAcceleration"], dtype=float)
    for model, filename, height, panels in specs:
        if model == FIXED:
            res = fix_res
        else:
            out_vars = [c[0] for _, curves in panels for c in curves if c[0] != "base.a_0[1]"]
            res = simulate_fmu(
                unpacked(model), fmi_type="ModelExchange", stop_time=stop, output_interval=0.02,
                relative_tolerance=1e-6,
                start_values={"pairFile": table.as_posix(), "pairIndex": 1},
                output=out_vars,
            )
        t_arr = np.asarray(res["time"], dtype=float)
        fig, axes = plt.subplots(len(panels), 1, figsize=(6.5, height), dpi=100,
                                 sharex=True, squeeze=False, layout="constrained")
        for idx, (ax, (ylabel, curves)) in enumerate(zip(axes[:, 0], panels)):
            for col, scale, color, label in curves:
                y = ag_x if col == "base.a_0[1]" else np.asarray(res[col], dtype=float) * scale
                ax.plot(t_arr, y, color=color, linewidth=1.2, label=label)
            if idx == len(panels) - 1:
                ax.set_xlabel("Time [s]")
            ax.set_ylabel(ylabel)
            ax.set_xlim(float(t_arr.min()), float(t_arr.max()))
            ax.grid(True, alpha=0.3)
            ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.01),
                      ncol=len(curves), frameon=False, borderaxespad=0.0)
        path = model_imgs / filename
        fig.savefig(path, metadata={"Software": None})
        plt.close(fig)
        written.append(path)
    return written


def report_match(out: dict) -> None:
    """Print the comparison of the adopted model with the report."""
    upper, lower, fixed = (out[k] for k in ("upper", "lower", "fixed"))
    mm, kk = matrices()
    t1 = 2 * np.pi / np.sqrt(eigh(kk, mm, eigvals_only=True)[0])
    full = full_model()
    names = ("Basement", "Ground", *(f"Floor {i}" for i in range(1, STOREYS)))

    def print_profiles(prefix: str, prof: dict, fmu: dict, rep: dict, ref: dict,
                       acc_slice: slice) -> None:
        for key, short, unit, scale in (("drift", "Drift", "%", 100), ("acceleration", "Acc", "g", 1)):
            joint, mean = prof[f"{key}Joint"], prof[f"{key}Mean"]
            centre = np.column_stack([fmu[f"centre{short}{a}Abs"] for a in "XY"])
            corner = np.column_stack([fmu[f"{short.lower()}{a}Abs"] for a in "XY"])[:len(joint)]
            columns = [joint, mean, centre, corner]
            head = "full-model joint maximum | full-model floor mean | 24-DOF mass centre | 24-DOF corners"
            if rep[key] is not None:
                columns.insert(0, rep[key])
                head = f"{ref[key]} | {head}"
            print(f"{prefix}{key} [{unit}] X, Y: {head}")
            for i, row in enumerate(zip(*columns)):
                print(f" {names[i + len(names) - len(joint)]:8s}"
                      + " |".join("".join(f"{scale * x:6.2f}" for x in pair) for pair in row))
            ratios = [("24-DOF mass centre / full-model floor mean", centre / mean)]
            if rep[key] is not None:
                sl = acc_slice if key == "acceleration" else slice(None)
                label = f"full-model joint maximum / {ref[key]}"
                if sl != slice(None):
                    label += " (Floor 1 to Floor 7)"
                ratios.insert(0, (label, (joint / rep[key])[sl]))
            for label, ratio in ratios:
                print(f" {label}: {ratio.min():.2f} to {ratio.max():.2f}, mean {ratio.mean():.2f}")

    et_fps = etabs_fps_drifts()
    print("ETABS Superstructure vs Design Report Table 19 (FPS drift [%], X, Y):")
    for i, st in enumerate(names[1:]):
        r_d = et_fps["dbe"]["x"][i] / REPORT_DRIFT_XY[i]
        r_m = et_fps["mce"]["x"][i] / REPORT_DRIFT_XY[i]
        print(
            f" {st:8s} Rep {100*REPORT_DRIFT_XY[i,0]:5.2f} {100*REPORT_DRIFT_XY[i,1]:5.2f} | "
            f"ETABS DD-2 {100*et_fps['dbe']['x'][i,0]:5.2f} {100*et_fps['dbe']['x'][i,1]:5.2f} ({r_d[0]:.2f},{r_d[1]:.2f}) | "
            f"DD-1 {100*et_fps['mce']['x'][i,0]:5.2f} {100*et_fps['mce']['x'][i,1]:5.2f} ({r_m[0]:.2f},{r_m[1]:.2f})"
        )
    print_profiles("FPS ", full, upper, {"drift": et_fps["dbe"]["x"], "acceleration": None},
                   {"drift": "ETABS Superstructure"}, slice(None))
    print(f"full model V/W x, y {full['baseShear'][0]:.3f}, {full['baseShear'][1]:.3f}, "
          f"DD-2 slab travel {full['travel']:.3f} m")
    print(f"FPS upper V/W x (_X) {upper.get('shearX_X', upper['shearX']):.4f} "
          f"(report {REPORT_BASE_SHEAR_X:.3f}), y (_X) {upper.get('shearY_X', upper['shearY']):.4f} "
          f"(report {REPORT_BASE_SHEAR_Y:.3f})")
    if "storeyShearX_X" in upper:
        for axis, spec in (("X", SPEC_STOREY_SHEAR_X), ("Y", SPEC_STOREY_SHEAR_Y)):
            ratio = upper[f"storeyShear{axis}_X"] / (spec / SPEC_SHEAR_SCALE)
            print(f"FPS upper storey shear {axis} (_X) / spec Table 7 / {SPEC_SHEAR_SCALE:.3f}, "
                  "Ground to Floor 7: " + " ".join(f"{r:.2f}" for r in ratio))
    if "lrb" in full and "lrb_upper" in out:
        lrb_full, lrb_up = full["lrb"], out["lrb_upper"]
        print_profiles("LRB ", lrb_full, lrb_up,
                       {"drift": REPORT_LRB_DRIFT_XY, "acceleration": REPORT_LRB_ACCELERATION_XY},
                       {"drift": "report", "acceleration": "report"}, slice(2, None))
        print(f"full model LRB V/W x, y {lrb_full['baseShear'][0]:.3f}, "
              f"{lrb_full['baseShear'][1]:.3f}, DD-2 slab travel {lrb_full['travel']:.3f} m")
        print(f"LRB upper V/W x (_X) {lrb_up.get('shearX_X', lrb_up['shearX']):.4f} "
              f"(report {REPORT_LRB_BASE_SHEAR_X:.3f}), y (_X) "
              f"{lrb_up.get('shearY_X', lrb_up['shearY']):.4f} "
              f"(report {REPORT_LRB_BASE_SHEAR_Y:.3f})")
    if "pointsX" in lower:
        px, py = 1e3 * np.asarray(lower["pointsX"]), 1e3 * np.asarray(lower["pointsY"])
        print("DD-1 FPS lower travel X [mm]: "
              + ", ".join(f"P{i+1}={px[i]:.0f} (rep {1e3*REPORT_POINT_TRAVEL_X[i]:.0f})" for i in range(4)))
        print("DD-1 FPS lower travel Y [mm]: "
              + ", ".join(f"P{i+1}={py[i]:.0f} (rep {1e3*REPORT_POINT_TRAVEL_Y[i]:.0f})" for i in range(4)))
    print(f"DD-1 lower peak travel {lower['travel']:.4f} m (report {REPORT_DISPLACEMENT:.3f} m)")
    print(f"fixed base T1 {t1:.3f} s, V/W {fixed['shear']:.4f}, drift x/y "
          f"{100 * fixed['driftXAbs'].max():.2f}/{100 * fixed['driftYAbs'].max():.2f} %")


def save_cached_match(out: dict) -> None:
    """Write the 11-pair report comparison to data/report_match.json."""
    serializable = {}
    for key, val in out.items():
        if isinstance(val, dict):
            serializable[key] = {
                k: (v.tolist() if isinstance(v, np.ndarray) else float(v))
                for k, v in val.items()
            }
        else:
            serializable[key] = val
    (DATA / "report_match.json").write_text(
        json.dumps(serializable, indent=1), encoding="utf-8"
    )


def load_cached_match() -> dict:
    """Load the pre-computed 11-pair report comparison from data/report_match.json."""
    raw = json.loads((DATA / "report_match.json").read_text(encoding="utf-8"))
    out = {"slip": SLIP}
    for key, val in raw.items():
        if isinstance(val, dict):
            out[key] = {k: np.array(v) if isinstance(v, list) else v for k, v in val.items()}
        else:
            out[key] = val
    return out


def occupied_peak(result: dict, kind: str, floors: slice) -> float:
    """Largest absolute peak over x, y and floors."""
    return float(max(result[f"{kind}{a}Abs"][floors].max() for a in "XY"))


def main_pairs(workers: int, live: bool = False) -> None:
    """Evaluate the report design against the report (cached or live FMU simulation)."""
    extents = storey_extents()
    if live:
        try:
            import fmpy  # noqa: F401
        except ImportError:
            print("Note: fmpy is not installed (run: pip install fmpy); "
                  "using pre-computed results from data/report_match.json.")
            live = False
    if live or not (DATA / "report_match.json").exists():
        bounds = fps_bounds(PENDULUM_RADIUS, FRICTION_NOMINAL, SLIP)
        nominal, upper, lower = (pair_mean(b, extents, workers) for b in bounds)
        lrb_up_cases, lrb_low_cases = lrb_bounds()
        lrb_upper = pair_mean(lrb_up_cases, extents, workers)
        lrb_lower = pair_mean(lrb_low_cases, extents, workers)
        out = {
            "slip": SLIP,
            "nominal": nominal,
            "upper": upper,
            "lower": lower,
            "lrb_upper": lrb_upper,
            "lrb_lower": lrb_lower,
            "fixed": pair_mean(fixed_cases(), extents, workers),
        }
        save_cached_match(out)
    else:
        out = load_cached_match()
    report_match(out)
    if not FIGURES_ON:
        return
    full = full_model()
    et_fps_dbe = etabs_fps_drifts()["dbe"]["x"]
    paths = []
    for with_full in (False, True):
        paths.extend(plot_match_pairs(
            out["upper"], full, tab_drift=et_fps_dbe,
            # ETABS Story Accelerations of Superstructure are not joint maxima (several storeys
            # read the ground motion), so FPS acceleration is compared in verification/ only
            drift_limit=DRIFT_LIMIT, full=with_full,
            modal=modal_results("upper") if with_full else None,
        ))
        if "lrb" in full and "lrb_upper" in out:
            paths.extend(plot_match_pairs(
                out["lrb_upper"], full["lrb"], REPORT_LRB_DRIFT_XY,
                REPORT_LRB_ACCELERATION_XY, DRIFT_LIMIT, "LRB", full=with_full,
            ))
    mce = modal_results("mce")
    if mce is not None and "dd1" in full:
        # DD-1 with upper-bound properties, the basis of the ETABS MCE drifts
        paths.extend(plot_match_pairs(
            mce["guyan"], full["dd1"], tab_drift=etabs_fps_drifts()["mce"]["x"],
            drift_limit=DRIFT_LIMIT, suffix="MCE", full=True, modal=mce["modal"],
            acceleration=False,
        ))
    if "lrb" in full and "lrb_upper" in out:
        paths.extend([
            plot_parity(
                extents, full["lrb"], REPORT_LRB_DRIFT_XY,
                REPORT_LRB_ACCELERATION_XY, "LRB",
            ),
        ])
    if "dd1" in full:
        paths.extend(plot_levels(full))
    low = fps_bounds(PENDULUM_RADIUS, FRICTION_NOMINAL, SLIP)[2]
    # The GIF takes about a minute to render, so redraw it only for new or missing runs
    if live or (not (IMAGES / "TravelHistory.gif").exists()
                and all((RUNS / f"{c['name']}.npz").exists() for c in low)):
        paths.append(plot_travel_history(low, workers))
    if live:
        paths.extend([
            plot_orbits(bounds[2], extents, workers),
            plot_plan_displacements(ISOLATED, "IsolatorPlanFrictionPendulum.png"),
            plot_plan_displacements(LEAD_RUBBER, "IsolatorPlanLeadRubber.png"),
            *plot_model_docs(),
        ])
    for path in paths:
        print(f"Wrote {path}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--live", action="store_true",
                        help="re-simulate all 11 pairs on the FMUs via FMPy")
    args = parser.parse_args()
    main_pairs(args.workers, live=args.live)


if __name__ == "__main__":
    main()
