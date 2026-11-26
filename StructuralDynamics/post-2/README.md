# Bolu FTR Hospital: Standalone FMU Verification and Bearing Sweep

This self-contained folder reproduces the figures, record-by-record verification,
and bearing parameter sweep in the [blog post][post] and
[`technical_notes.md`](technical_notes.md) using **portable Model-Exchange FMUs**
(`fmu/`). The FMUs are the only models in this folder. **Neither OpenModelica nor
the source ETABS `.$et` models are required.**

The ETABS models, design report and isolator specification come from the
Ministry of Health (Sağlık Bakanlığı) tender archive. Search İKN `2025/860174`
in [EKAP](https://ekapv2.kik.gov.tr/ekap/search) and download the tender
document (İhale Dokümanı).

## Setup

```bash
pip install fmpy numpy scipy matplotlib pandas jupyter
```

## Contents

- [Blog post][post]: article comparing the 27-DOF reduced model against
  ETABS and the design report, plus a 107-design catalogue isolator sweep.
- [`technical_notes.md`](technical_notes.md): peer-review notes on matrix
  condensation, bearing/damper modelling, record provenance, report verification,
  and the TBDY 2018 Chapter 14 sweep.
- [`hospital_design.ipynb`](hospital_design.ipynb): interactive Jupyter notebook
  reproducing all figures and tables in the blog post and `technical_notes.md`.
- `fmu/`: portable 64-bit Model-Exchange FMUs (`BoluFrictionPendulum.fmu`,
  `BoluLeadRubber.fmu`, `BoluFixedBase.fmu`).
- `data/`: 52 earthquake records (`records/`), 253 ETABS load cases
  (`load_cases.csv`), target spectra (`spectrum.csv`), condensed superstructure
  and isolation tables (`storeys.csv`, `extents.json`, `isolators.csv`,
  `isolator_groups.csv`, `dampers.csv`, `monitored_points.csv`), full-model
  reference outputs (`full_model_profiles.json`, `etabs_check_rsn1158.csv`),
  digitized report profile curves (`report_curves.json`), and cached FMU
  verification and sweep results (`report_match.json`, `bearing_sweep.json`).
- `images/`: figures referenced by the blog post and `hospital_design.ipynb`.

## Scripts

Run from this folder. Without options, each script uses the cached results in
`data/` and finishes in seconds.

| Script | What it does | Reads | Writes |
| --- | --- | --- | --- |
| [`bolu_record_pairs.py`](bolu_record_pairs.py) | Builds the 22 scaled record pairs (11 DD-2, 11 DD-1). The other scripts call it when needed. | `data/records/`, `data/load_cases.csv` | `runs/record_pairs.txt`, `runs/stops_report.json` |
| [`bolu_time_history.py`](bolu_time_history.py) | Compares the report design with the design report and the full-model run. | `data/report_match.json`, `data/full_model_profiles.json`, `data/report_curves.json` | `images/Report*.png` |
| [`bolu_bearing_sweep.py`](bolu_bearing_sweep.py) | Checks 35 friction pendulum and 72 lead-rubber catalogue designs against TBDY 2018 Chapter 14 and prints the table. | `data/bearing_sweep.json` | `images/BearingSweep.png` (with `--plot`) |

Options:

- `python bolu_time_history.py --live` runs all record pairs again on the FMUs
  (needs `fmpy`) and rewrites `data/report_match.json` and the model figures.
- `python bolu_bearing_sweep.py --fps-radius ... --fps-friction ...
  --lrb-diameter ... --lrb-lead-ratio ... --lrb-thickness ... --lrb-modulus ...`
  simulates the designs that are not yet in
  `data/bearing_sweep.json` and adds them to it.
- `--workers N` sets the number of parallel FMU processes (default 8).

FMU results are cached in `runs/` (not in git).

## Bearing Sweep: Runs and Bounds

Each design gets `66` FMU runs: 11 record pairs × 2 orientations × 3 property
bounds. The bounds bracket manufacturing, ageing and test scatter of the
isolators and the 64 viscous dampers. Each check reads the bound that TBDY 2018
assigns to it:

| Bound | Level | Checks | TBDY 2018 |
| --- | --- | --- | --- |
| Upper | DD-2 | Base shear ≤ `0.20 W`, drift ≤ `0.50 %` | §14.3.6 |
| Nominal | DD-2 | Floor acceleration ≤ `0.30 g` | §14.3.10 |
| Lower | DD-1 | $D_{TM}$ ≤ capacity, LRB strain ≤ `250 %` | §14.3.6 |

The capacity is `1.04 m` for FPS and `0.75 m` for LRB. The bound factors are:

| Bound | FPS | LRB $(Q_d, K_2)$ | Damper $C$ |
| --- | --- | --- | --- |
| Upper | $1.5\mu$ | `(1.6445, 1.9435)` | `2.825` |
| Nominal | $\mu$ | `(1.0, 1.0)` | `2.35` |
| Lower | $0.8\mu$ | `(0.595, 0.765)` | `2.00` |

Damper $C$ is in MN·(s/m)^0.5.

- **Why these bounds:** §14.3.6 sets the lower bound for the maximum isolator
  displacement and the upper bound for the maximum force on the
  superstructure, so drift follows the upper bound. §14.3.10 permits nominal
  values for floor accelerations.
- **Factors:** for the report FPS design, `1.5` and `0.8` give the ETABS links
  `FP-DBE-UB` ($\mu$ `0.0825`) and `FP_MCE-LB` ($\mu$ `0.044`). The LRB and
  damper factors come from Report Table 10 and the `VD_UB` and `VD_LB` links.
  The TBDY Table 14.3 defaults (`1.72`, `0.595`) apply only without test data.
- **Combinations:** isolators and dampers take the same bound. §14.0.2 counts
  the dampers as part of the isolation system, so §14.3.6 applies to both.
  Every ETABS model pairs `FP-*-UB` with `VD_UB` and `FP_MCE-LB` with `VD_LB`.
  Mixed bounds (UB friction with LB dampers) are not run. TBDY does not
  require them, but they are worth a run, because the damper specification
  sets its own factors (`1.20`, `0.85`).
- **Other bound:** each row also stores `drift_nominal` and
  `acceleration_upper` for comparison. These values are not used in the
  checks.

The ETABS archive holds one bound for each model file, and the Python full
model runs the same bounds for the report design only. Each ETABS file pairs
the FPS link with the damper link of the same bound. The `dd1low` prefix runs
one pair per call:

| Bound | ETABS file (FPS link) | Python full model prefix |
| --- | --- | --- |
| DD-2 upper | `Superstructure` (`FP-DBE-UB`) | `run`, `lrb` |
| DD-1 upper | `Foundation`, `Foundation_Vert` (`FP-MCE-UB`) | `dd1` |
| DD-1 lower | `Foundation_MCE_LB` (`FP_MCE-LB`) | `dd1low` |
| DD-2 nominal | none | none |

The tender files have Turkish names: `Superstructure` (`Üst Yapı`),
`Foundation` (`Temel`), `Foundation_Vert` (`Temel_Vert`) and
`Foundation_MCE_LB` (`Temel_MCE_LB_DeplasmanKontrol`, displacement check).

[post]: https://nouseng.co/posts/bolu-hospital-isolator-sweep/
