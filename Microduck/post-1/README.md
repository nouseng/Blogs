# Why We Built a Walking Robot Duck Twice

Why rebuild the Microduck, a 14-servo biped whose policy was trained in
MuJoCo, as a Modelica plant model, and how it was verified against MuJoCo
before anything was added.

[Read the post](https://nouseng.co/posts/microduck-why-modelica/)

## Files

- `why-modelica.ipynb` — notebook: runs this post's scenarios live through
  `../fmu/` and `../mujoco/`, with the policy in Python.
- `why-modelica.md` — the post.
- `figures.py` — renders `images/walk.gif` and `images/walk-frame.png` from the
  MuJoCo walk at a 0.3 m/s command, draws `images/walking.png` and prints the
  numbers quoted in the post.
- `data/walk_duck.csv` — the OpenModelica walk (Part 5 healthy run).
- `data/walk_mujoco.csv` — the MuJoCo walk, written by `figures.py`.

The numbers in the voltage table come from [Part 3](../post-3).
