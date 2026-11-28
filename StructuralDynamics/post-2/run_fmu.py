"""Run one Bolu isolation FMU and print travel, drift and floor acceleration.

    pip install fmpy numpy
    python run_fmu.py                              # synthetic demonstration pulse
    python run_fmu.py BoluLeadRubber table.txt 1   # your own record table, pair 1
"""
import json
import sys
from pathlib import Path

import numpy as np
from fmpy import simulate_fmu

HERE = Path(__file__).resolve().parent
GRAVITY = 9.80665
STOREYS = 8


def demo_table(path: Path) -> Path:
    """One 1 Hz Ricker pulse (0.3 g in x, 0.2 g in y): not an earthquake record."""
    time = np.arange(0, 20.0001, 0.005)
    arg = (np.pi * (time - 3.0)) ** 2
    pulse = (1 - 2 * arg) * np.exp(-arg) * GRAVITY
    data = np.column_stack([time, 0.3 * pulse, 0.2 * pulse, 0 * pulse])
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"#1\ndouble acc({len(time)},4)\n")
        np.savetxt(fh, data, fmt="%.6g")
    return path


def building_values(fmu: str) -> dict:
    """Condensed ETABS matrices of the model behind the FMU (keys *Fps for pendulums)."""
    ext = json.loads((HERE / "data" / "extents.json").read_text(encoding="utf-8"))
    fps = fmu == "BoluFrictionPendulum"
    tag = "Fps" if fps else ""
    values = {f"building.stiffnessMatrix[{i + 1},{j + 1}]": v
              for i, row in enumerate(ext["stiffnessMatrix" + tag]) for j, v in enumerate(row)}
    if fps:
        values |= {"baseMass": ext["isolationMassFps"], "baseInertia": ext["isolationInertiaFps"],
                   "weight": (ext["isolationMassFps"] + sum(ext["massFps"])) * GRAVITY}
        for i, (m, inertia, (x, y)) in enumerate(zip(
                ext["massFps"], ext["inertiaFps"], ext["massCentreFps"]), start=1):
            values |= {f"building.floorMass[{i}]": m, f"building.floorInertia[{i}]": inertia,
                       f"building.massCentreX[{i}]": x, f"building.massCentreY[{i}]": y}
    return values


def main(fmu: str = "BoluFrictionPendulum", table: str = "", pair: str = "1") -> None:
    if table:
        path = Path(table).resolve()
    else:
        path = demo_table(HERE / "demo_pulse.txt")
        print("Synthetic pulse: demonstration only, not a blog result")
    stop = float(np.loadtxt(path, skiprows=2, usecols=0)[-1])
    isolated = fmu != "BoluFixedBase"
    outputs = [f"building.interstorey{a}[{i}]" for a in "XY" for i in range(1, STOREYS + 1)]
    outputs += [f"building.floorAcceleration[{i},{a}]"
                for i in range(1, STOREYS + 1) for a in (1, 2)]
    if isolated:
        outputs += ["isolationDisplacementX", "isolationDisplacementY"]
    res = simulate_fmu(
        str(HERE / "fmu" / f"{fmu}.fmu"), fmi_type="ModelExchange", stop_time=stop,
        output_interval=0.005, relative_tolerance=1e-6, output=outputs,
        start_values={"pairFile": path.as_posix(), "pairIndex": int(pair),
                      **building_values(fmu)})

    def peak(prefix: str) -> float:
        return max(np.abs(res[n]).max() for n in outputs if n.startswith(prefix))

    if isolated:
        travel = np.hypot(res["isolationDisplacementX"], res["isolationDisplacementY"]).max()
        print(f"Isolation travel (slab centre): {1000 * travel:.0f} mm")
    print(f"Peak storey drift (floor centre): {1000 * peak('building.interstorey'):.2f} mm")
    print(f"Peak floor acceleration (floor centre): "
          f"{peak('building.floorAcceleration') / GRAVITY:.3f} g")


if __name__ == "__main__":
    main(*sys.argv[1:])
