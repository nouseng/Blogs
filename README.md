# Blogs

Code, data, and figures for the posts on [nouseng.co](https://nouseng.co).

## FOWT

- [`FOWT/mooring-models-benchmark`](FOWT/mooring-models-benchmark) — *One Line. Four Models.
  Which One, and When?* Analytical catenary, FEM, Guyan reduction, and an ONNX surrogate for an
  OC4 DeepCwind mooring line.
  [Read the post](https://nouseng.co/posts/fowt-mooring-models-benchmark/)
- [`FOWT/dynamic-mooring-6dof`](FOWT/dynamic-mooring-6dof) — *It Moves Now: Dynamic Mooring with a
  6DOF FOWT.* A full 6DOF Modelica MultiBody floating turbine, exported as an FMI 2.0 co-simulation
  FMU and driven from Python under wind and wave loading, comparing the analytical catenary against
  Part 1's ONNX surrogate.
  [Read the post](https://nouseng.co/posts/fowt-dynamic-mooring-6dof/)
- [`FOWT/agentic-simulation`](FOWT/agentic-simulation) — *Who Runs Your Simulation When You're Not
  a Simulation Engineer?* A thin LLM tool-calling layer over the Part 2 FMU co-simulation: agent
  loop, tool schemas, Streamlit app, and notebook, running locally against Ollama.
  [Read the post](https://nouseng.co/posts/fowt-agentic-simulation/)

## R2RDynamics

- [`R2RDynamics/misaligned-idler`](R2RDynamics/misaligned-idler) — *More Grip, Better Tracking?
  Modeling the Tradeoffs.* A misaligned idler under nip load in a Modelica film-winding line, run
  as an FMI 2.0 FMU from Python: nip load, friction, yaw, tram and runout sweeps.
  [Read the post](https://nouseng.co/posts/nip-force-web-tracking/)
