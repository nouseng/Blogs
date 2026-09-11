# It Moves Now: Dynamic Mooring with a 6DOF FOWT

A full 6DOF Modelica MultiBody floating turbine, exported as an FMI 2.0 co-simulation FMU and
driven from Python under combined wind and wave loading. Each mooring line's force is computed at
every step by either the analytical catenary or Part 1's ONNX surrogate, so the two can be
compared on a platform that is actually moving. The companion article walks through the model, the
co-simulation loop, and where the surrogate's error shows up.

## Contents

- [`part2-dynamic-mooring.md`](part2-dynamic-mooring.md): the full article.
- [`part2_dynamic_mooring_notebook.ipynb`](part2_dynamic_mooring_notebook.ipynb): reproducible
  notebook (figures and results).
- [`notebook_helpers.py`](notebook_helpers.py): the co-simulation and plotting helpers used by the
  notebook.
- [`FOWT.fmu`](FOWT.fmu): the exported FMI 2.0 co-simulation FMU (OpenModelica 1.27.0, Windows).
- `mooring_surrogate_fx.onnx`, `mooring_surrogate_fz.onnx`, `mooring_surrogate_t.onnx`, and
  `surrogate_metadata.json`: Part 1's ONNX surrogates for the line force components (`F_x`,
  `F_z`) and tension (`T`).
- `figures/`: the article's figures and animation.

## Quickstart

```bash
pip install -r requirements.txt

jupyter notebook part2_dynamic_mooring_notebook.ipynb
```

The notebook drives `FOWT.fmu` through [FMPy](https://github.com/CATIA-Systems/FMPy), so it runs
from this folder with no extra setup.

## References

- OC4 geometry: Robertson et al. (2014), NREL/TP-5000-60601. <https://doi.org/10.2172/1155123>
