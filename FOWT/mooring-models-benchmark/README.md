# Mooring line models: analytical, FEM, Guyan, and a neural surrogate

Four ways to compute the fairlead tension of a floating-wind mooring line, benchmarked on the
OC4 DeepCwind semi-submersible geometry: a closed-form analytical catenary, a nonlinear finite
element model (DOLFINx), a Guyan-reduced stiffness model, and an ONNX neural surrogate. The
companion article walks through each model, the accuracy-versus-cost trade-off, and when to reach
for which.

## Contents

- [`part1-mooring-models.md`](part1-mooring-models.md): the full article.
- [`blog_notebook.ipynb`](blog_notebook.ipynb): reproducible notebook (figures and results).
- [`mooring_utils.py`](mooring_utils.py): the analytical catenary solver, Guyan reduction, and
  the ONNX surrogate loader, self-contained.
- `data/`: the exported ONNX surrogates (`F_x`, `F_z`, `T`) and metadata.
- `figures/`: the article's animations and diagrams.

## Quickstart

```bash
pip install -r requirements.txt

jupyter notebook blog_notebook.ipynb
```

The analytical catenary and the ONNX surrogate run from this folder with no extra setup. The FEM
and Guyan models need [DOLFINx](https://fenicsproject.org/) (the `dolfinx/dolfinx:v0.9.0` Docker
image) and the solver module from the source repository.

## References

- OC4 geometry: Robertson et al. (2014), NREL/TP-5000-60601. <https://doi.org/10.2172/1155123>
- OC5 validation: Robertson et al. (2017), Energy Procedia 137.
  <https://doi.org/10.1016/j.egypro.2017.10.333>
