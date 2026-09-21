# More Grip, Better Tracking? Modeling the Tradeoffs

Nine 40 s cases of a misaligned idler under nip load in a Modelica
film-winding line, run from one FMI 2.0 Model Exchange FMU built with
**Roll2RollDynamics** (internal library). More nip force cuts accumulated
slip by 66% and moves lateral offset by less than 1%.

[Read the post](https://nouseng.co/posts/nip-force-web-tracking/)

## Start here

- **The write-up** → [`misaligned-idler.md`](misaligned-idler.md).
- **The cases, end to end** →
  [`misaligned-idler-fmu.ipynb`](misaligned-idler-fmu.ipynb). Load the
  FMU, run the nine cases, draw the startup, yaw, tram, runout and
  friction-curve figures.
- **Two more figures** → `python notebook_utils.py load-sweep` and
  `python notebook_utils.py friction-sweep` produce the nip-load and
  nip-friction sweeps. Remaining images (gap schematics, line overview,
  animations, diagram) come from the library, not this folder.

## Files

- `misaligned-idler-fmu.ipynb` — notebook walkthrough.
- `notebook_utils.py` — FMPy runner, checks, plotting, CLI sweeps.
- `FMUs/UnparallelIdler.fmu` — FMI 2.0 Model Exchange, Windows 64-bit only.
- `images/MisalignedIdler/` — figures and animations used in the post.
- `requirements.txt` — FMPy 0.3.29, NumPy, Matplotlib.

## Run

```
pip install -r requirements.txt
jupyter notebook misaligned-idler-fmu.ipynb
```

Solver: CVode, relative tolerance 1e-8, output spacing 0.2 ms.
