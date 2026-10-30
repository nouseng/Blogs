# Why Rebuild a Walking Robot Duck in Modelica?

Why rebuild the MicroDuck, a 14-servo biped whose policy was trained in
MuJoCo, as a Modelica plant model, and how it was verified against MuJoCo
before anything was added.

- **Article:**
  [Why Rebuild a Walking Robot Duck in Modelica?](https://nouseng.co/libraries/atelier/microduck/why-modelica/)
- **Modelica library (`MicroDuck` & `MicroDuckTest`):**
  [`nouseng/libraries/RoboticsAtelier/MicroDuck`](https://github.com/nouseng/libraries/tree/main/RoboticsAtelier/MicroDuck)

## Setup

```bash
pip install -r requirements.txt
```

Everything needed to run `why-modelica.ipynb` and `figures.py` is inside this
folder (`fmu/`, `mujoco/`, `common.py`, and `data/`). No OpenModelica
installation is required to run the notebook.

## Files

- `why-modelica.ipynb` — notebook: runs this post's standing and walking
  scenarios live through `fmu/` and `mujoco/`, with the policy in Python.
- `why-modelica.md` — the post.
- `figures.py` — renders `images/walk.gif` and `images/walk-frame.png` from the
  MuJoCo walk at a 0.3 m/s command, draws `images/standing.png` and
  `images/walking.png`, and prints the numbers quoted in the post.
- `common.py` — shared FMU (`stand_fmu`, `walk_fmu`) and MuJoCo
  (`stand_mujoco`, `walk_mujoco`) runners and plot style.
- `requirements.txt` — Python dependencies.
- `fmu/` — `DuckPlant.fmu` and `DuckStand.fmu` (Model Exchange 2.0, Win64 +
  Linux64).
- `mujoco/` — `velstand.onnx` (trained 50 Hz policy), `walk.ipynb`,
  `build_duck.ipynb`, and `model/` (`scene_backlash.xml`,
  `robot_groundcontact_backlash.xml`, and `assets/*.stl`).
- `images/WalkingTest.svg` — diagram view of `MicroDuck.Examples.WalkingTest`.
- `images/standing.png` — sole normal forces and trunk height during the 2.8 mm
  standing drop test (`positionGain = 800`), compared with MuJoCo.
- `images/walk_modelica.gif` — animation of the OpenModelica walk.
- `images/walking.png` — forward position and trunk height over a 6 s walk,
  compared with MuJoCo.
- `data/walk_duck.csv` — the OpenModelica walk (`0.797 m` after `6 s`; running
  `DuckPlant.fmu` in Python with 1 ms Runge-Kutta gives `0.798 m`).
- `data/walk_mujoco.csv` — the MuJoCo walk, written by `figures.py`.

## References and licences

- **MuJoCo robot model and meshes (`mujoco/model/`):**
  [`pollen-robotics/microduck_rl`](https://github.com/pollen-robotics/microduck_rl)
  (`src/mjlab_microduck/robot/microduck/`, commit `273afe0b`, Apache-2.0).
- **Trained walking policy (`mujoco/velstand.onnx`):**
  [`pollen-robotics/microduck-policies`](https://huggingface.co/pollen-robotics/microduck-policies)
  (`velstand.onnx`, Apache-2.0).
- **Identified Dynamixel XL330 servo parameters:**
  [`Rhoban/bam`](https://github.com/Rhoban/bam)
  (`bam/params/xl330/m6.json`, Apache-2.0).
- **Modelica plant library (`MicroDuck` & `MicroDuckTest`):**
  [`nouseng/libraries/RoboticsAtelier/MicroDuck`](https://github.com/nouseng/libraries/tree/main/RoboticsAtelier/MicroDuck)
  (BSD 3-Clause).
