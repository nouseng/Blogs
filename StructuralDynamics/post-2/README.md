# Bolu FTR Hospital: Isolation FMUs and Notes

Companion files for the [blog post][post]: portable Model-Exchange FMUs, technical
notes and verification figures.

The ETABS models, design report and isolator specification come from the
Ministry of Health (Sağlık Bakanlığı) tender archive. Search İKN `2025/860174`
in [EKAP](https://ekapv2.kik.gov.tr/ekap/search) and download the tender
document (İhale Dokümanı).

## Contents

- [`technical_notes.md`](technical_notes.md): matrix condensation, bearing and
  damper models, record provenance, verification and the TBDY 2018 Chapter 14
  sweep.
- `fmu/`: 64-bit Model-Exchange FMUs (`BoluFrictionPendulum.fmu`,
  `BoluFrictionPendulumModal.fmu`, `BoluLeadRubber.fmu`, `BoluFixedBase.fmu`).
- `images/`: figures of the blog post and the notes.
- `verification/`: comparison plots of drift, acceleration and travel.
- `data/`: model matrices, geometry, scale factors and result files. It holds no
  ground motion records.
- `run_fmu.py`: runs one FMU and prints travel, drift and floor acceleration.

## Run an FMU

```bash
pip install fmpy numpy
python run_fmu.py                              # synthetic demonstration pulse
python run_fmu.py BoluLeadRubber table.txt 1   # your own record table, pair 1
```

The FMU names are `BoluFrictionPendulum`, `BoluLeadRubber` and `BoluFixedBase`.
The demonstration pulse does not reproduce the blog results.

## Ground Motion Input

This folder contains no records. Download them from PEER NGA-West2 (RSN numbers
and scale factors are in `data/load_cases.csv`). The FMUs read a Modelica text
table named `acc` through the `pairFile` parameter. Column 1 is time [s]. Each record pair then adds three
acceleration columns (x, y, z) in m/s². `pairIndex` selects the pair, and
`rotated = true` swaps x and y.

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

The ETABS archive holds one bound for each model file. Each file pairs the FPS
link with the damper link of the same bound:

| Bound | ETABS file (FPS link) |
| --- | --- |
| DD-2 upper | `Superstructure` (`FP-DBE-UB`) |
| DD-1 upper | `Foundation`, `Foundation_Vert` (`FP-MCE-UB`) |
| DD-1 lower | `Foundation_MCE_LB` (`FP_MCE-LB`) |
| DD-2 nominal | none |

The tender files have Turkish names: `Superstructure` (`Üst Yapı`),
`Foundation` (`Temel`), `Foundation_Vert` (`Temel_Vert`) and
`Foundation_MCE_LB` (`Temel_MCE_LB_DeplasmanKontrol`, displacement check).

[post]: https://nouseng.co/posts/bolu-hospital-isolator-sweep/
