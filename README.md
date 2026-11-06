# Blogs

Code, data, and figures for the posts on [nouseng.co](https://nouseng.co).

## FOWT

- [`FOWT/mooring-models-benchmark`](FOWT/mooring-models-benchmark) — *One Line.
  Four Models. Which One, and When?* Analytical catenary, FEM, Guyan reduction,
  and an ONNX surrogate for an OC4 DeepCwind mooring line.
  [Read the post](https://nouseng.co/posts/fowt-mooring-models-benchmark/)
- [`FOWT/dynamic-mooring-6dof`](FOWT/dynamic-mooring-6dof) — *It Moves Now:
  Dynamic Mooring with a 6DOF FOWT.* A full 6DOF Modelica MultiBody floating
  turbine, exported as an FMI 2.0 co-simulation FMU and driven from Python under
  wind and wave loading, comparing the analytical catenary against Part 1's ONNX
  surrogate.
  [Read the post](https://nouseng.co/posts/fowt-dynamic-mooring-6dof/)
- [`FOWT/agentic-simulation`](FOWT/agentic-simulation) — *Who Runs Your
  Simulation When You're Not a Simulation Engineer?* A thin LLM tool-calling
  layer over the Part 2 FMU co-simulation: agent loop, tool schemas, Streamlit
  app, and notebook, running locally against Ollama.
  [Read the post](https://nouseng.co/posts/fowt-agentic-simulation/)
- [`FOWT/active-control`](FOWT/active-control) — *Pitch Damping and Mooring
  Repositioning: The Same Kind of Control?* ROSCO-style platform-rate feedback
  on collective blade pitch, run in the Python loop around an FMI 2.0 FMU with a
  blade-pitch actuator, and a static mooring-reposition solver for line lengths.
  [Read the post](https://nouseng.co/posts/fowt-active-control/)

## DC2DH

- [`DC2DH/post-1`](DC2DH/post-1) — *Why Stockholm, Not Arizona: Where AI Waste
  Heat Has a Buyer.* A 10 MW data-centre heat-recovery pod in Modelica, exported
  as an FMI 2.0 co-simulation FMU and stepped from Python over a Stockholm
  weather year for each Open District Heating product.
  [Read the post](https://nouseng.co/posts/dc2dh-plant/)
- [DC2DH/post-2](DC2DH/post-2) — *Building a Digital Twin's Skeleton, End to
  End.* The same StockholmPod.fmu wired into a Modbus TCP operating loop with a
  NiceGUI web console, register bounds checking, and 30-second co-simulation
  ticks.
  [Read the post](https://nouseng.co/posts/dc2dh-skeleton/)

## R2RDynamics

- [`R2RDynamics/misaligned-idler`](R2RDynamics/misaligned-idler) — *More Grip,
  Better Tracking? Modeling the Tradeoffs.* A misaligned idler under nip load in
  a Modelica film-winding line, run as an FMI 2.0 FMU from Python: nip load,
  friction, yaw, tram and runout sweeps.
  [Read the post](https://nouseng.co/posts/nip-force-web-tracking/)

## StructuralDynamics

- [`StructuralDynamics/post-1`](StructuralDynamics/post-1) — *What Can
  Electrical Circuits Teach Us About Earthquake Engineering?* A ten-storey steel
  frame under Northridge 1994 and Kobe 1995, base isolation explained through a
  series RLC circuit, with spectra run from FMI 2.0 FMUs in Python and checked
  against the FEMA P-695 far-field set.
  [Read the post](https://nouseng.co/posts/structural-circuits-earthquake/)

## MicroDuck

- [`Microduck/post-1`](Microduck/post-1) — *Why Rebuild a Walking Robot Duck in
  Modelica?* The Pollen Robotics MicroDuck biped rebuilt as a Modelica plant
  model, exported as an FMI 2.0 Model Exchange FMU and verified against MuJoCo.
  [Read the post](https://nouseng.co/libraries/atelier/microduck/why-modelica/)
- [`Microduck/post-2`](Microduck/post-2) — *Can a Lame Duck Still Walk?* A
  worn gear, a weak motor and an unpowered motor injected into one knee of the
  MicroDuck plant, then a sweep of that knee's supply voltage to find where the
  trained walking policy stops walking.
  [Read the post](https://nouseng.co/libraries/atelier/microduck/servo-faults/)
