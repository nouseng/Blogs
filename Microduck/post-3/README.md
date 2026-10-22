# What Does an Empty Battery Do to a Walking Robot?

The walk at 8.2, 7.4 and 6.5 V servo supply: stiffness, speed, current and
power, and whether pack sag matters.

[Read the post](https://nouseng.co/posts/microduck-battery-voltage/)

## Files

- `battery-voltage.ipynb` — notebook: runs this post's scenarios live through
  `../fmu/` and `../mujoco/`, with the policy in Python.
- `battery-voltage.md` — the post.
- `figures.py` — Figure 1 and the table values.
- `models/` — `Walk82V`, `Walk74V`, `Walk65V` with motor and supply current,
  `run.mos`.
- `data/walk_*V.csv` — distance, trunk height and supply current.
- `images/` — figure used in the post.

## Assumptions

- Ideal voltage source per run. The supply current is the sum of drive
  fraction times motor current over the 14 servos (ideal H-bridge).
- The 0.1 Ω pack resistance in the post is an assumption, not a measurement.

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
