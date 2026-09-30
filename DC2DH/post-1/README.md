# The model behind "Why Stockholm, Not Arizona"

This is the companion code for our blog post,
[**Why Stockholm, Not Arizona: Where AI Waste Heat Has a Buyer**](post-1-plant.md).
Every modelled plant-performance number in that post comes from one notebook
study. This is that study, made runnable: a single notebook that steps a 10 MW
data-centre heat-recovery pod through a full Stockholm weather year and
redraws the figures.

[Read the post](https://nouseng.co/posts/dc2dh-plant/)

You do not need OpenModelica. The committed `StockholmPod.fmu` carries its
own solver, so `fmpy` runs it straight from Python.

## What's in here

```text
stockholm_pod_annual.ipynb   the notebook to run
StockholmPod.fmu             the pod, an FMI 2.0 co-simulation FMU (CVODE solver)
network_inputs.csv           hourly ambient, plus the network curves it drives
post-1-plant.md              the blog post
images/                      the post's figures (charts rewritten on each run)
```

## Running it

```bash
pip install -r requirements.txt
jupyter notebook stockholm_pod_annual.ipynb
```

Run the notebook top to bottom. It steps the FMU over the 8,760-hour
Stockholm Arlanda TMYx year, once for each Open District Heating product
(Retur, Inblandning, Prima), prints the annual table, and writes the data
charts into `images/`.

The FMU ships prebuilt binaries for Windows and Linux (`win64`, `linux64`)
alongside its bundled CVODE solver, so `fmpy` runs it with no compiler. It
also carries its full C source, so on any other platform `fmpy` compiles it in
place the first time it loads, which needs a C compiler (`gcc`, `clang` or
MSVC) on your `PATH`.

## What the year says

The pod recovers 61.5% of its IT heat for Retur, 55.7% for Inblandning and
54.6% for Prima, and evaporates nothing on site. Delivered heat runs higher:
64.5%, 65.9% and 65.9% of IT energy respectively, because it includes the
compressor work added on top of recovered loop heat.

A fully evaporative counterfactual for the same 10 MW IT load consumes roughly
130 million litres a year at the latent-heat floor. In the Inblandning run,
48,782 MWh of recovered IT heat accounts for about 73 million litres-equivalent
of that burden; the remaining roughly 58 million litres-equivalent is avoided
because the residual heat is rejected through the dry cooler. Recovery and dry
rejection are separate contributions.

## Image credit

The Lake Mead photo (`images/post1-lake-mead.jpg`) is a USGS public-domain
image.
