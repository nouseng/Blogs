# The Servo Is a Motor, Not a Gain

The Dynamixel XL330 from gain register to joint torque, why the robot cannot
stand at the walking gain, and how the policy uses the soft servo as a torque
command.

[Read the post](https://nouseng.co/posts/microduck-servo-motor/)

## Files

- `servo-motor.ipynb` — notebook: runs this post's scenarios live through
  `../fmu/` and `../mujoco/`, with the policy in Python.
- `servo-motor.md` — the post.
- `figures.py` — Figures 1 and 2.
- `models/` — `Stand200`, `Stand800` (Standing at two gains), `WalkNominal`
  (walk with servo torques), `run.mos`.
- `data/stand_gain200.csv`, `data/stand_gain800.csv` — trunk height and pitch.
- `data/mujoco_standing.csv` — MuJoCo trunk height at both gains, from
  `tools/data/standing_reference.json` in the Microduck repository.
- `data/walk_nominal.csv` — joint angles, targets and servo torques over a
  6 s walk.
- `images/` — figures used in the post.

## Redraw the figures

```bash
pip install -r ../requirements.txt
python figures.py
```

`figures.py` redraws the figures into `images/` and prints every number quoted
in the post.

## Rerun the simulations

The models extend examples of the Duck library from the Microduck repository.
Copy `models/` into `<Microduck repo>/build/<task>/` and run from there:

```bash
omc run.mos
```

Each run writes `<Model>_res.csv`. The files in `data/` hold the columns the
figures use, with OpenModelica's duplicate event rows removed.
A rerun agrees with them to about 2% (walking speed to 0.001 m/s) rather
than bit for bit: the walk is sensitive to floating-point order, which changes
with the generated code.
