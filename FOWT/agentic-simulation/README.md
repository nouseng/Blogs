# Part 3: Agentic FOWT Simulation

A minimal LLM tool-calling loop over a real floating offshore wind
turbine co-simulation. The agent pattern is the point; the wind turbine
is the payload.

## Start here

- **Learning the pattern** →
  [`agent_demo.ipynb`](agent_demo.ipynb). Step-by-step: schema, tool
  boundary, direct deterministic call, then the same call driven by the
  LLM.
- **Full write-up** →
  [`part3-agentic-fowt.md`](part3-agentic-fowt.md). Blog post with the
  whole loop shown and a `get_inventory()` transfer example.
- **The ~40-line agent loop** → [`agent.py`](agent.py). One file, one
  registry, one loop (plus schemas, plotting, and state around it).

## Files

- `agent.py` — agent loop, tool registry, schemas, `RunStore`.
- `simulation.py` — JONSWAP/Kaimal environment, catenary mooring, FMU stepping.
- `app.py` — thin Streamlit UI.
- `agent_demo.ipynb` — notebook walkthrough.
- `part3-agentic-fowt.md` — the blog post.
- `FOWT.fmu` / `FOWT_linux.fmu` — per-platform FMU binaries.

## Run the Streamlit app

```bash
pip install -r requirements.txt
streamlit run app.py
```

Defaults expect a local Ollama-compatible endpoint:

```bash
ollama serve
ollama pull qwen2.5
```

Point at another OpenAI-compatible backend with:

```bash
LLM_BASE_URL=...
LLM_API_KEY=...
LLM_MODEL=<a tool-capable model available from your provider>
```

On Windows the simulation loads `FOWT.fmu`. On Linux it automatically
loads `FOWT_linux.fmu`.

## Note

This is a supervisory research/demo framework, not a real-time
controller or safety system.
