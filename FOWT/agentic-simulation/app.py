"""Thin Streamlit UI for the public FOWT simulation agent."""
import base64
import contextlib
import logging
import os

import streamlit as st

with contextlib.suppress(Exception):
    for key in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        if key in st.secrets:
            os.environ.setdefault(key, str(st.secrets[key]))

from agent import RunStore, backend_label, run_agent

log = logging.getLogger(__name__)
HERE = os.path.dirname(__file__)
ICON = os.path.join(HERE, "figures", "wind_turbine.svg")


def _data_uri(path: str, mime: str) -> str:
    with open(path, "rb") as file:
        encoded = base64.b64encode(file.read()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


st.set_page_config(
    page_title="FOWT Simulation Agent",
    page_icon=ICON if os.path.isfile(ICON) else "⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
:root {
  --ui-line: color-mix(in srgb, currentColor 14%, transparent);
  --ui-panel: color-mix(in srgb, currentColor 4%, transparent);
  --ui-panel-hover: color-mix(in srgb, currentColor 7%, transparent);
  --ui-muted: color-mix(in srgb, currentColor 62%, transparent);
}

/* Let Streamlit own the actual light/dark theme. Custom UI inherits it. */
[data-testid="stAppViewContainer"],
[data-testid="stSidebar"] {
  color: inherit;
}
[data-testid="stSidebar"] {
  border-right: 1px solid var(--ui-line);
}
[data-testid="stSidebar"] > div:first-child {padding-top:1rem;}
header[data-testid="stHeader"] {background:transparent;}
[data-testid="stToolbar"] {background:transparent;}
.block-container {padding-top:1.15rem;max-width:1450px;}

.app-title-row {
  display:flex;align-items:center;justify-content:space-between;
  gap:1rem;margin-bottom:.15rem;
}
.app-title-row h1 {
  font-size:2.65rem;line-height:1.05;margin:0;font-weight:750;
  letter-spacing:-.035em;color:inherit;
}
.step-badge {
  display:inline-flex;align-items:center;gap:.4rem;padding:.38rem .72rem;
  border-radius:999px;background:rgba(47,128,237,.12);color:#2f80ed;
  border:1px solid rgba(47,128,237,.22);font-size:.82rem;font-weight:650;
  white-space:nowrap;
}
.app-subtitle {color:var(--ui-muted);font-size:1.02rem;margin-bottom:1rem;}

.sidebar-brand {display:flex;align-items:center;gap:.72rem;padding:.2rem 0 .8rem;}
.sidebar-brand img {width:31px;height:31px;display:block;}
.sidebar-brand strong {font-size:1.05rem;color:inherit;}
.sidebar-section-title {
  margin:.85rem 0 .4rem;
  font-size:.88rem;
  font-weight:650;
  letter-spacing:.01em;
  color:inherit;
}
.sidebar-section-title::before {
  content:"";
  display:inline-block;
  width:3px;
  height:.82rem;
  margin-right:.5rem;
  border-radius:2px;
  background:rgba(47,128,237,.7);
  vertical-align:-.08rem;
}
.info-card {
  background:var(--ui-panel);border:1px solid var(--ui-line);border-radius:12px;
  padding:.7rem .8rem;margin:.35rem 0 1rem;
}
.info-row {display:flex;justify-content:space-between;gap:1rem;padding:.22rem 0;font-size:.86rem;}
.info-row span:first-child {font-weight:600;color:inherit;}
.info-row span:last-child {color:var(--ui-muted);text-align:right;}
.stButton>button {
  border-radius:10px;border:1px solid var(--ui-line);background:var(--ui-panel);
  color:inherit;text-align:left;justify-content:flex-start;min-height:3.1rem;
}
.stButton>button p {color:inherit;}
.stButton>button:hover {
  border-color:rgba(47,128,237,.55);color:#2f80ed;background:var(--ui-panel-hover);
}
.run-card {
  border:1px solid var(--ui-line);border-radius:10px;padding:.55rem .65rem;
  margin-bottom:.45rem;background:var(--ui-panel);font-size:.86rem;color:inherit;
}
.run-card b {color:inherit;}
.small-muted {font-size:.78rem;color:var(--ui-muted);}

.hero-card {
  border:1px solid #202631;border-radius:12px;background:#101722;
  padding:.5rem .55rem .55rem;margin-bottom:1rem;overflow:hidden;
}
.hero-label {color:#e5e7eb;font-size:.88rem;padding:.15rem .25rem .5rem;}
.hero-viewport {
  width:100%;aspect-ratio:16 / 9;border-radius:9px;overflow:hidden;
  background:#0d1117;display:flex;align-items:center;justify-content:center;
}
.hero-viewport img {
  width:100%;height:100%;display:block;object-fit:contain;object-position:center;
}
.empty-chat {
  border:1px solid var(--ui-line);border-radius:12px;padding:2.2rem 1rem;
  text-align:center;color:var(--ui-muted);margin:.35rem 0 1rem;background:var(--ui-panel);
}
.empty-chat strong {display:block;color:inherit;margin-bottom:.25rem;}
[data-testid="stChatMessage"] {
  border:1px solid var(--ui-line);border-radius:12px;padding:.35rem .25rem;
  background:var(--ui-panel);color:inherit;
}
[data-testid="stChatMessage"] p {color:inherit;}

/* The chat input stays native to Streamlit, so it automatically follows theme. */
[data-testid="stChatInput"] {border-color:var(--ui-line);}

@media (max-width:1100px) {
  .app-title-row h1 {font-size:2.2rem;}
}
</style>
""",
    unsafe_allow_html=True,
)

if "store" not in st.session_state:
    st.session_state.store = RunStore()
if "chat" not in st.session_state:
    st.session_state.chat = []
if "pending_prompt" not in st.session_state:
    st.session_state.pending_prompt = None

EXAMPLE_PROMPTS = [
    "Run a 6 m storm for 30 s and plot surge and tension1 separately",
    "Run a calm sea (Hs 1.5 m, Tp 7 s, 8 m/s wind) for 30 s and plot pitch",
    "Compare max tension between my last two runs",
]


def current_step() -> str:
    if st.session_state.pending_prompt:
        return "Step 2: Dispatch"
    runs = st.session_state.store.runs
    if len(runs) >= 2:
        return "Step 4: Compare"
    if len(runs) == 1:
        return "Step 3: Analyze"
    return "Step 1: Ask"


with st.sidebar:
    if os.path.isfile(ICON):
        st.markdown(
            f'<div class="sidebar-brand"><img src="{_data_uri(ICON, "image/svg+xml")}" alt="Wind turbine"><strong>FOWT Simulation Agent</strong></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown("### FOWT Simulation Agent")

    st.markdown('<div class="sidebar-section-title">Backend</div>', unsafe_allow_html=True)
    info = [
        ("Framework", "Streamlit"),
        ("Agent loop", "Active"),
        ("LLM", backend_label()),
        ("Solver", "FOWT FMU"),
        ("Platform", "Windows / Linux"),
    ]
    rows = "".join(
        f'<div class="info-row"><span>{name}</span><span>{value}</span></div>'
        for name, value in info
    )
    st.markdown(f'<div class="info-card">{rows}</div>', unsafe_allow_html=True)

    st.markdown('<div class="sidebar-section-title">Examples</div>', unsafe_allow_html=True)
    for i, example in enumerate(EXAMPLE_PROMPTS):
        if st.button(example, key=f"example_{i}", use_container_width=True):
            st.session_state.pending_prompt = example
            st.rerun()

    st.markdown('<div class="sidebar-section-title">Run history</div>', unsafe_allow_html=True)
    if not st.session_state.store.runs:
        st.markdown(
            '<div class="info-card" style="text-align:center;padding:1rem"><b>No runs yet</b><div class="small-muted">Your simulations will appear here.</div></div>',
            unsafe_allow_html=True,
        )
    for run_id, rec in st.session_state.store.runs.items():
        summary = rec["summary"]
        params = rec["params"]
        st.markdown(
            f'<div class="run-card"><b>● {run_id}</b><br>'
            f'Hs {params["Hs"]} m · {params["duration"]} s<br>'
            f'<span class="small-muted">Max tension {summary["max_tension_mn"]:.2f} MN</span></div>',
            unsafe_allow_html=True,
        )

st.markdown(
    f'<div class="app-title-row"><h1>FOWT Simulation Agent</h1><span class="step-badge">✦ {current_step()}</span></div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="app-subtitle">Natural language in, tool calls out. Deterministic FOWT simulation for floating offshore wind turbines.</div>',
    unsafe_allow_html=True,
)

image = os.path.join(HERE, "figures", "anim_0_platform_dark.gif")
if not os.path.isfile(image):
    image = os.path.join(HERE, "figures", "anim_0_platform.gif")
if os.path.isfile(image):
    st.markdown(
        f'<div class="hero-card"><div class="hero-label">OC4 DeepCwind · NREL 5MW · 3-line mooring system</div><div class="hero-viewport"><img src="{_data_uri(image, "image/gif")}" alt="FOWT platform animation"></div></div>',
        unsafe_allow_html=True,
    )

if not st.session_state.chat:
    st.markdown(
        '<div class="empty-chat"><strong>Ask a question or request a simulation.</strong>The agent will choose from the exposed tools, run the deterministic model, and return plots or comparisons.</div>',
        unsafe_allow_html=True,
    )

for item in st.session_state.chat:
    with st.chat_message(item["role"]):
        st.write(item["text"])
        if item.get("trace"):
            with st.expander("Tool calls", expanded=False):
                for call in item["trace"]:
                    st.code(call, language=None)
        for fig in item.get("figures", []):
            st.plotly_chart(fig, use_container_width=True)

typed = st.chat_input("Ask something about sea state, wind, stored runs, or results...")
prompt = typed or st.session_state.pending_prompt
st.session_state.pending_prompt = None

if prompt:
    st.session_state.chat.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Agent is operating the simulation..."):
            try:
                text, figures, trace = run_agent(prompt, st.session_state.store)
            except Exception:
                log.exception("LLM backend error")
                text = (
                    "LLM backend error. Check LLM_BASE_URL, LLM_API_KEY and "
                    "LLM_MODEL."
                )
                figures, trace = [], []

        st.write(text)
        if trace:
            with st.expander("Tool calls", expanded=True):
                for call in trace:
                    st.code(call, language=None)
        for fig in figures:
            st.plotly_chart(fig, use_container_width=True)

    st.session_state.chat.append(
        {
            "role": "assistant",
            "text": text,
            "figures": figures,
            "trace": trace,
        }
    )
    st.rerun()
