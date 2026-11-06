# Can a Lame Duck Still Walk?

A worn gear, a weak motor and an unpowered motor on the left knee, and a sweep
of the left knee's supply voltage down to the point where the robot falls.

- **Article:**
  [Can a Lame Duck Still Walk?](https://nouseng.co/libraries/atelier/microduck/servo-faults/)
- **Modelica library (`MicroDuck` & `MicroDuckTest`):**
  [`nouseng/libraries/RoboticsAtelier/MicroDuck`](https://github.com/nouseng/libraries/tree/main/RoboticsAtelier/MicroDuck)

## Run

```bash
pip install -r requirements.txt
jupyter lab servo-faults.ipynb
```

The notebook runs every walk of the post through `fmu/DuckPlant.fmu`, the
Modelica plant exported from the MicroDuck library, with the trained policy in
Python at 50 Hz. It prints every number quoted in the post and writes
`images/faults.png`, `images/knee_sweep.png`, `images/lame_walk.gif` and
`images/hero.gif`. The 13 walks and the animations take about three minutes.
No OpenModelica installation is needed.

## Files

- `servo-faults.md` — the post.
- `servo-faults.ipynb` — the notebook.
- `common.py` — plot style, the FMU walk (`walk_fmu`) and the paths of the
  plant, the policy and the MuJoCo scene.
- `fmu/DuckPlant.fmu` — Model Exchange 2.0, Win64.
- `mujoco/velstand.onnx` — the trained 50 Hz walking policy.
- `mujoco/model/` — `scene_backlash.xml`, `robot_groundcontact_backlash.xml`
  and the 38 `assets/*.stl` meshes they use, only to draw the animation.
- `images/` — the figures and the animation of the post.
- `requirements.txt` — Python dependencies.

## Assumptions

- Each fault is present from t = 0 on one joint, 0.3 m/s command, flat ground.
- Only the soles collide, so a fallen robot sinks through the floor.
- Fixed 7.4 V supply for the other 13 servos, thermal network off.

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

The robot model, meshes and policy are redistributed under their Apache-2.0
licences.
