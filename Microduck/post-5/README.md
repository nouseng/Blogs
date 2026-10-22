# Which Servo Failure Can a Walking Robot Survive?

A worn gear, a weak motor and an unpowered motor on the left knee, and the
copper loss of every servo.

[Read the post](https://nouseng.co/posts/microduck-servo-faults/)

## Files

- `servo-faults.ipynb` — notebook: runs this post's scenarios live through
  `../fmu/` and `../mujoco/`, with the policy in Python.
- `servo-faults.md` — the post.
- `figures.py` — Figures 1 and 2 and the fault table.
- `models/` — `WalkNominal`, `WalkWornKnee` (6° play), `WalkWeakKnee` (3.7 V),
  `WalkLimpKnee` (gain 0), with motor currents, `run.mos`.
- `data/walk_*.csv` — distance, trunk height and pitch, motor current of all
  14 servos, knee angles and targets.
- `images/` — figures used in the post.

## Assumptions

- Each fault is present from t = 0 on one joint, 0.3 m/s command, flat ground.
- Only the soles collide, so a fallen robot sinks through the floor.
- Copper loss is R i² with the identified 2.50 Ω, no thermal model.

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
