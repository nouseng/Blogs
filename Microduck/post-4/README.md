# Same Policy, 50% Faster: The Contact Law Was the Model

Why the first Modelica walk ran 50% faster than MuJoCo, the MuJoCo soft
contact law rebuilt point by point, and a friction sweep showing where the
match holds.

[Read the post](https://nouseng.co/posts/microduck-contact-law/)

## Files

- `contact-law.ipynb` — notebook: runs this post's scenarios live through
  `../fmu/` and `../mujoco/`, with the policy in Python.
- `contact-law.md` — the post.
- `figures.py` — Figure 3 and the friction table, from `data/` and the
  MuJoCo speeds of the notebook.
- `models/` — `WalkMu03` to `WalkMu20`, `run.mos`.
- `data/walk_mu*.csv` — distance and trunk height.
- `images/drop.png`, `images/slide.png` — from the DuckTest library
  documentation (`DropTest`, `SlideTest`).

The penalty-contact numbers in the first half of the post (0.25 against
0.17 m/s, 43 against 6.5 mm/s slip, the 30 mm drop) come from earlier model
versions and are not reproduced here.

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
