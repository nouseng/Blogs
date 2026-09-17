"""Reusable agent layer for the public FOWT simulation demo.

The boundary is deliberate:
- agent.py interprets language, exposes tools, stores run state and dispatches calls.
- simulation.py owns environment generation, mooring physics and FMU execution.

The LLM never accesses the FMU directly.
"""
from __future__ import annotations

import json
import os

import numpy as np
import plotly.graph_objects as go
from openai import OpenAI
from simulation import run_cosim

SYSTEM_PROMPT = """You operate a floating offshore wind turbine simulation.
Use tools instead of inventing numerical results.

You have exactly three capabilities:
1. run_simulation: run and store a new FMU simulation
2. plot_results: plot signals from a stored run
3. compare_runs: compare stored summary metrics

Reuse a stored run when it already answers the request. Report mooring tension in
MN, translational motion in m and angles in degrees. State constraint_ok when a
simulation is run. Never claim validity outside the tool input ranges.
"""


class RunStore:
    """In-memory simulation state shared across agent turns."""

    def __init__(self):
        self.runs: dict[str, dict] = {}
        self.counter = 0
        self.figures = []

    def add(self, params: dict, result: dict, summary: dict) -> str:
        self.counter += 1
        run_id = f"run{self.counter}"
        self.runs[run_id] = {
            "params": params,
            "result": result,
            "summary": summary,
        }
        return run_id

    def context(self) -> str:
        """Compact state visible to the LLM; raw time series stay out of context."""
        if not self.runs:
            return "No stored runs."
        compact = {
            run_id: {"params": rec["params"], "summary": rec["summary"]}
            for run_id, rec in self.runs.items()
        }
        return "Stored runs:\n" + json.dumps(compact)

    def drain_figures(self) -> list:
        figures, self.figures = self.figures, []
        return figures


def get_client() -> OpenAI:
    """Create an OpenAI-compatible client from environment variables."""
    return OpenAI(
        base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
        api_key=os.getenv("LLM_API_KEY", "ollama"),
    )


def get_model() -> str:
    return os.getenv("LLM_MODEL", "qwen2.5")


def backend_label() -> str:
    base_url = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
    model = get_model()
    if "groq.com" in base_url:
        return f"Groq · {model}"
    if "localhost" in base_url or "127.0.0.1" in base_url:
        return f"Ollama · {model}"
    return f"{base_url} · {model}"


def _validate(Hs: float, Tp: float, U_hub: float, TI: float, duration: float):
    limits = (
        ("Hs", Hs, 1.0, 10.0),
        ("Tp", Tp, 6.0, 16.0),
        ("U_hub", U_hub, 4.0, 25.0),
        ("TI", TI, 0.06, 0.20),
        ("duration", duration, 1.0, 60.0),
    )
    for name, value, low, high in limits:
        if not low <= value <= high:
            raise ValueError(f"{name} must be between {low} and {high}; got {value}")


def _summary(result: dict) -> dict:
    max_tension = max(
        float(np.max(result["tension1"])),
        float(np.max(result["tension2"])),
        float(np.max(result["tension3"])),
    )
    max_offset = float(np.max(np.abs(result["surge"])))
    return {
        "surge_rms_m": float(np.sqrt(np.mean(result["surge"] ** 2))),
        "pitch_rms_deg": float(
            np.degrees(np.sqrt(np.mean(result["pitch"] ** 2)))
        ),
        "max_tension_mn": max_tension / 1e6,
        "constraint_ok": bool(max_tension < 1.8e6 and max_offset < 50.0),
    }


def run_simulation(
    store: RunStore,
    Hs: float,
    Tp: float,
    U_hub: float,
    TI: float,
    duration: float = 30.0,
) -> dict:
    """Validate, run and store one deterministic simulation realization."""
    _validate(Hs, Tp, U_hub, TI, duration)
    params = {
        "Hs": Hs,
        "Tp": Tp,
        "U_hub": U_hub,
        "TI": TI,
        "duration": duration,
    }

    # Reuse an exact deterministic realization instead of re-running it.
    for run_id, rec in store.runs.items():
        if rec["params"] == params:
            return {"run_id": run_id, "reused": True, **rec["summary"]}

    result = run_cosim(**params)
    summary = _summary(result)
    run_id = store.add(params, result, summary)
    return {"run_id": run_id, "reused": False, **summary}


SIGNAL_UNITS = {
    "surge": "m",
    "sway": "m",
    "heave": "m",
    "roll": "rad",
    "pitch": "rad",
    "yaw": "rad",
    "tension1": "N",
    "tension2": "N",
    "tension3": "N",
}


def plot_results(store: RunStore, run_id: str, signals: list[str]) -> dict:
    """Create Plotly figures from a previously stored simulation."""
    rec = store.runs.get(run_id)
    if rec is None:
        return {"error": f"Unknown run {run_id!r}."}

    valid = [signal for signal in signals if signal in SIGNAL_UNITS]
    if not valid:
        return {"error": f"No valid signals in {signals}."}

    groups: dict[str, list[str]] = {}
    for signal in valid:
        groups.setdefault(SIGNAL_UNITS[signal], []).append(signal)

    t = rec["result"]["time"]
    for unit, names in groups.items():
        fig = go.Figure()
        for name in names:
            fig.add_trace(
                go.Scatter(
                    x=t,
                    y=rec["result"][name],
                    mode="lines",
                    name=name,
                )
            )
        fig.update_layout(
            title=f"{run_id}: {', '.join(names)}",
            xaxis_title="time [s]",
            yaxis_title=unit,
            margin={"l": 40, "r": 20, "t": 55, "b": 40},
        )
        store.figures.append(fig)

    return {"ok": True, "run_id": run_id, "plotted": valid}


def compare_runs(store: RunStore, run_ids: list[str], metric: str) -> dict:
    """Return one stored summary metric across several runs."""
    values = {}
    for run_id in run_ids:
        rec = store.runs.get(run_id)
        if rec is not None and metric in rec["summary"]:
            values[run_id] = rec["summary"][metric]
    if not values:
        return {"error": f"No requested runs contain {metric!r}."}
    return {"metric": metric, "values": values}


TOOLS = {
    "run_simulation": run_simulation,
    "plot_results": plot_results,
    "compare_runs": compare_runs,
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "run_simulation",
            "description": "Run and store the FOWT FMU for one wind/wave condition.",
            "parameters": {
                "type": "object",
                "properties": {
                    "Hs": {
                        "type": "number",
                        "minimum": 1.0,
                        "maximum": 10.0,
                        "description": "Significant wave height [m].",
                    },
                    "Tp": {
                        "type": "number",
                        "minimum": 6.0,
                        "maximum": 16.0,
                        "description": "Peak wave period [s].",
                    },
                    "U_hub": {
                        "type": "number",
                        "minimum": 4.0,
                        "maximum": 25.0,
                        "description": "Mean hub-height wind speed [m/s].",
                    },
                    "TI": {
                        "type": "number",
                        "minimum": 0.06,
                        "maximum": 0.20,
                        "description": "Turbulence intensity [-].",
                    },
                    "duration": {
                        "type": "number",
                        "minimum": 1.0,
                        "maximum": 60.0,
                        "default": 30.0,
                        "description": "Simulation duration [s].",
                    },
                },
                "required": ["Hs", "Tp", "U_hub", "TI"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plot_results",
            "description": (
                "Plot stored signals: surge, sway, heave, roll, pitch, yaw, "
                "tension1, tension2, tension3."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "string"},
                    "signals": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": list(SIGNAL_UNITS),
                        },
                    },
                },
                "required": ["run_id", "signals"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_runs",
            "description": "Compare one summary metric across stored runs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "run_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "metric": {
                        "type": "string",
                        "enum": [
                            "surge_rms_m",
                            "pitch_rms_deg",
                            "max_tension_mn",
                        ],
                    },
                },
                "required": ["run_ids", "metric"],
            },
        },
    },
]


def dispatch(name: str, args: dict, store: RunStore) -> dict:
    """Execute one registered tool; tool errors are returned to the model."""
    function = TOOLS.get(name)
    if function is None:
        return {"error": f"Unknown tool {name!r}."}
    try:
        return function(store, **args)
    except Exception as exc:  # noqa: BLE001 - surface any tool failure to the model
        return {"error": f"{type(exc).__name__}: {exc}"}


def run_agent(
    user_text: str,
    store: RunStore,
    max_steps: int = 6,
    client: OpenAI | None = None,
    model: str | None = None,
):
    """Let the LLM choose and sequence tools until it returns plain text.

    Returns ``(text, figures, trace)``. ``trace`` contains only observable tool
    calls, not private model reasoning.
    """
    client = client or get_client()
    model = model or get_model()
    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT + "\n\n" + store.context(),
        },
        {"role": "user", "content": user_text},
    ]
    trace = []

    for _ in range(max_steps):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOL_SCHEMAS,
        )
        message = response.choices[0].message

        if not message.tool_calls:
            return message.content or "", store.drain_figures(), trace

        messages.append(message)
        for call in message.tool_calls:
            args = json.loads(call.function.arguments)
            trace.append(f"{call.function.name}({json.dumps(args)})")
            result = dispatch(call.function.name, args, store)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result),
                }
            )

    return "Stopped after the maximum number of tool steps.", store.drain_figures(), trace
