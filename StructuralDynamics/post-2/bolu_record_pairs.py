"""Three-component record table for the Bolu time-history study (public bundle).

The design records are taken as used in the Bolu ETABS models: each history in
data/records/ (g) times the load-case factor in data/load_cases.csv. Pair k of each
level is the ETABS "_X" case, fault-parallel (FP) along x and fault-normal (FN) along
y, with the record's vertical component along z when the models define one (DD-1).
The "_Y" case is the same pair with the horizontal components swapped, which the
Modelica models apply with rotated = true. Writes runs/record_pairs.txt (time, then
x, y, z for the 11 DD-2 pairs and the 11 DD-1 pairs) and runs/stops_report.json
(analysis duration per pair).
"""

import csv
import json
import time as clock
from functools import cache
from pathlib import Path

import numpy as np
from scipy.signal import cont2discrete, lfilter

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RUNS = HERE / "runs"
GRAVITY = 9.80665
DT = 0.005
REFINE = 4
ANGLES = np.deg2rad(np.arange(0, 180, 5))
CHECK_PERIODS = np.geomspace(0.02, 8.0, 120)
LEVELS = ("DD-2", "DD-1")


def load_cases() -> list[dict]:
    """Rows of data/load_cases.csv with numeric fields converted."""
    with (DATA / "load_cases.csv").open(encoding="utf-8") as fh:
        return [{**r, "rsn": int(r["rsn"]), "factor": float(r["factor"]),
                 "duration": float(r["duration"])} for r in csv.DictReader(fh)]


def records() -> dict[str, tuple[int, ...]]:
    """Record numbers of each level in ascending order."""
    rows = load_cases()
    return {level: tuple(sorted({r["rsn"] for r in rows if r["level"] == level}))
            for level in LEVELS}


RECORDS = records()


@cache
def history(name: str) -> tuple[np.ndarray, np.ndarray]:
    """Time [s] and acceleration [g] of one ETABS history function."""
    data = np.loadtxt(DATA / "records" / f"{name}.txt")
    return data[:, 0], data[:, 1]


def component(row: dict | None, length: int) -> np.ndarray:
    """Scaled acceleration [m/s2] of one load on the DT grid, zero after the record."""
    if row is None:
        return np.zeros(length)
    t, a = history(row["function"])
    return row["factor"] * GRAVITY * np.interp(np.arange(length) * DT, t, a, right=0.0)


def triplet(level: str, rsn: int, length: int) -> tuple[np.ndarray, ...]:
    """x (FP), y (FN) and z accelerations of one pair as applied in the "_X" case."""
    rows = [r for r in load_cases() if r["level"] == level and r["rsn"] == rsn]
    tag = "MCE" if level == "DD-1" else "DBE"

    def pick(case: str, dof: str) -> dict | None:
        return next((r for r in rows if r["case"] == case and r["dof"] == dof), None)

    return (component(pick(f"{tag}_{rsn}_X", "U1"), length),
            component(pick(f"{tag}_{rsn}_X", "U2"), length),
            component(pick(f"{tag}_{rsn}-V", "U3"), length))


@cache
def oscillator(period: float) -> tuple[np.ndarray, np.ndarray]:
    """Exact discrete 5 % oscillator for piecewise-linear input at DT / REFINE."""
    w = 2 * np.pi / period
    num, den, _ = cont2discrete(([-1.0], [1.0, 0.1 * w, w**2]), DT / REFINE, method="foh")
    return num.ravel(), den


def response_history(acc: np.ndarray, periods: np.ndarray) -> np.ndarray:
    """Displacement history of 5 % oscillators under the piecewise-linear record."""
    fine = np.interp(np.arange((len(acc) - 1) * REFINE + 1) / REFINE, np.arange(len(acc)), acc)
    return np.column_stack([lfilter(*oscillator(float(t)), fine) for t in periods])


def rotd100(x: np.ndarray, y: np.ndarray, periods: np.ndarray) -> np.ndarray:
    """Maximum-direction pseudo-acceleration spectrum of a pair [m/s2]."""
    ux = response_history(x, periods)
    uy = response_history(y, periods)
    peak = np.max([np.abs(np.cos(t) * ux + np.sin(t) * uy).max(axis=0) for t in ANGLES], axis=0)
    return (2 * np.pi / periods) ** 2 * peak


def main(name: str = "record_pairs.txt") -> None:
    """Write the 22 three-component pairs and their analysis durations."""
    RUNS.mkdir(parents=True, exist_ok=True)
    start = clock.time()
    stops = {}
    for level in LEVELS:
        for rsn in RECORDS[level]:
            stops[len(stops) + 1] = max(r["duration"] for r in load_cases()
                                        if r["level"] == level and r["rsn"] == rsn)
    rows = round(max(stops.values()) / DT) + 1
    columns = []
    for level in LEVELS:
        for i, rsn in enumerate(RECORDS[level]):
            x, y, z = triplet(level, rsn, rows)
            columns += [x, y, z]
            print(f"{level} pair {i + 1} (RSN {rsn}): PGA x {abs(x).max() / GRAVITY:.3f} g, "
                  f"y {abs(y).max() / GRAVITY:.3f} g, z {abs(z).max() / GRAVITY:.3f} g")
    data = np.column_stack([np.arange(rows) * DT, *columns])
    path = RUNS / name
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"#1\ndouble acc({rows},{data.shape[1]})\n")
        np.savetxt(fh, data, fmt="%.6g")
    (RUNS / "stops_report.json").write_text(json.dumps(stops, indent=1), encoding="utf-8")
    print(f"Wrote {path}, run time {clock.time() - start:.0f} s")


if __name__ == "__main__":
    main()
