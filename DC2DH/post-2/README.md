# A Digital Twin's Skeleton

Companion code for our blog post,
[**Building a Digital Twin's Skeleton, End to End**](post-2-skeleton.md).

[Read the post](https://nouseng.co/posts/dc2dh-skeleton/)

The last post built a data-centre heat-recovery pod as a Modelica model and
ran it against a Stockholm weather year. This one wires that same model into a
loop you can operate. A web console writes setpoints, a gateway holds them in
Modbus registers, and an orchestrator steps the plant and writes the readings
back. The plant model is the committed `StockholmPod.fmu`, stepped through
`fmpy`. There is no simplified stand-in anywhere in the loop.

This is a digital twin prototype, not a synchronized operational twin. It has
no physical asset connection, live telemetry, state recovery, or controller.

## Run it

```bash
docker compose up --build
```

Open <http://localhost:8080>. Set District-Heating Product to **Retur** for
an answer in seconds: the mild-weather loop already clears Retur's requirement,
so Heat Export jumps to a real number at zero Heat-Pump Output. The heat-pump
slider is shown as 0–8.0 MW thermal, and Current Heat-Pump COP reports the
corresponding efficiency (or Off when inactive). A Network Water Flow tile
derives the litres per second sold to the network from Heat Export and the
delivery and return temperatures. The accumulator uses Discharge / Idle /
Charge buttons, and dry-cooler capacity uses Off / 50% / Full stages. The
dashboard also integrates session-only Electricity Bought and Heat Sold from
a visible UTC start time. These totals follow simulated time and reset when
the page reloads.

The FMU ships a prebuilt `linux64` CVODE binary, so the container loads the
plant directly without a compiler. Run `docker compose down` when done.

## What's in here

```text
console/       NiceGUI web page + Modbus client
gateway/       Modbus TCP server, write arbiter
orchestrator/  FMU plant (fmpy), tick loop, Modbus client
contracts/     PlantInputs/PlantOutputs, the register map
modelica/      the committed StockholmPod.fmu
compose.yml    three services off one image
```

## Run it without Docker

```bash
pip install -r requirements.txt
```

The FMU ships prebuilt `win64` and `linux64` binaries with CVODE, so Windows
and Linux load it directly. Its bundled C source remains available as a
fallback on other platforms, where `fmpy` needs a C compiler.
