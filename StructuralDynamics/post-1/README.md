# What Can Electrical Circuits Teach Us About Earthquake Engineering?

Why the same ten-storey steel frame sways 3.8 times more under Northridge 1994
than under Kobe 1995 despite a lower PGA, and how a series RLC circuit explains
resonance and base isolation. Two FMI 2.0 Model Exchange FMUs, built with
**StructuralDynamics** (internal Modelica library), run from Python.

[Read the post](https://nouseng.co/posts/structural-circuits-earthquake/)

## Start here

- **The write-up** → [`isolation-spectrum.md`](isolation-spectrum.md).
- **The numbers, end to end** →
  [`isolation_spectrum.ipynb`](isolation_spectrum.ipynb). Change period and
  damping, cross-check the SciPy spectra against the FMU, inspect the FEMA
  P-695 ensemble and the frame results.
- **Figures and checks** → `python notebook_utils.py figures` redraws
  Figures 1-8 into `images/`; `python notebook_utils.py verify` checks the
  numbers quoted in the article.

## Files

- `isolation_spectrum.ipynb` — notebook walkthrough.
- `notebook_utils.py` — spectra, bearing analysis, plotting, CLI commands.
- `fmu/SdofSpectrum.fmu` — single-mass spectrum model, Windows 64-bit only.
- `fmu/TenStoreyShear.fmu` — ten-storey shear-chain cross-check, Windows
  64-bit only.
- `fmu/frame_*_reference.csv` — saved multibody frame histories.
- `data/records/` — Northridge 1994 (MUL009) and Kobe 1995 (NIS000)
  accelerations in m/s², 0.01 s sampling.
- `data/` — FEMA P-695 ensemble spectra, frame summaries, figure values.
- `images/` — figures and animations used in the post.
- `requirements.txt` — FMPy, NumPy, SciPy, Matplotlib, pandas, Pillow.

## Run

```
pip install -r requirements.txt
jupyter notebook isolation_spectrum.ipynb
```

## Assumptions

- Figures 2 and 7 use 2% damping and a five-second high-pass correction.
  Figure 8 uses 5% damping and PGA-normalized spectra, so values are not
  comparable across figures.
- Unscaled Northridge MUL009 and Kobe NIS000 components, PGA 0.42 g and 0.51 g.
- Ten-storey elastic plane frame (3 m storeys, one 6 m bay, HEB500, 20 t per
  floor), first sway period 1.05 s, nonlinear bearing, prescribed ground motion,
  no soil interaction. Teaching examples; not a safety assessment.

## Data

Both records are PEER NGA processed accelerations from the unscaled FEMA P-695
far-field set, converted with 1 g = 9.80665 m/s² and no further filtering or
scaling. Ensemble metadata, spectra and checksums are in [`data/`](data/).
Source and reuse terms: [FEMA P-695 ground-motion sets](https://sp3risk.com/ground-motion-sets/).
