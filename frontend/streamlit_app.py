"""BugHound — Streamlit client.

A second, self-contained way in. It talks to the FastAPI service over HTTP when
``BUGHOUND_API_URL`` is reachable, and falls back to running the graph in-process
so the UI still works as a single-command local demo.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

API_URL = os.getenv("BUGHOUND_API_URL", "http://localhost:8000").rstrip("/")

st.set_page_config(
    page_title="BugHound — AI Bug Investigation Agent",
    page_icon="🐾",
    layout="wide",
)

STYLE = """
<style>
:root { --bh-blue: #1668e3; --bh-navy: #0b3c7e; }
.stApp { background: linear-gradient(168deg, #eaf1fa 0%, #f5f9fd 60%, #eaf1fa 100%); }
h1, h2, h3 { color: #14263d; letter-spacing: -.01em; }
.bh-head { display:flex; align-items:center; gap:14px; margin-bottom:6px; }
.bh-mark { width:40px;height:40px;border-radius:12px;
  background:linear-gradient(150deg,#2e86f0,#0b3c7e);color:#fff;
  display:grid;place-items:center;font-weight:700;font-size:15px; }
.bh-sub { color:#7386a0; font-size:13px; margin:0 0 18px; }
.bh-card { background:#fff;border:1px solid #e3eaf5;border-radius:14px;padding:16px 18px;
  box-shadow:0 8px 24px rgba(16,40,80,.06); margin-bottom:12px; }
.bh-tag { display:inline-block;padding:4px 10px;border-radius:999px;font-size:12px;
  background:#e3eefc;color:#1250b0;border:1px solid #b9d6fa; }
.bh-good { background:rgba(23,178,106,.12); color:#0f8a51; border-color:rgba(23,178,106,.25); }
.bh-bad { background:rgba(229,72,77,.12); color:#c93438; border-color:rgba(229,72,77,.25); }
</style>
"""
st.markdown(STYLE, unsafe_allow_html=True)

st.markdown(
    '<div class="bh-head"><div class="bh-mark">BH</div>'
    "<div><h1 style='margin:0;font-size:26px'>BugHound</h1>"
    "<p class='bh-sub'>AI Bug Investigation Agent — debug, research, root cause, fix, "
    "independent review, static validation.</p></div></div>",
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# transport
# --------------------------------------------------------------------------- #
def fetch_samples() -> list[dict]:
    try:
        import httpx

        response = httpx.get(f"{API_URL}/api/samples", timeout=5)
        response.raise_for_status()
        return response.json()["samples"]
    except Exception:
        from app.services.samples import SAMPLES

        return SAMPLES


def investigate(payload: dict) -> dict:
    """Try the API first, then fall back to the in-process graph."""
    try:
        import httpx

        response = httpx.post(f"{API_URL}/api/investigate", json=payload, timeout=300)
        response.raise_for_status()
        return response.json()
    except Exception as exc:  # noqa: BLE001
        st.info(f"API unavailable ({exc}). Running the graph in this process instead.")
        from app.api.routes import to_response
        from app.graph.graph import run_investigation
        from app.models.schemas import InvestigationRequest

        state = run_investigation(InvestigationRequest(**payload))
        return to_response(state).model_dump(mode="json")


# --------------------------------------------------------------------------- #
# sidebar
# --------------------------------------------------------------------------- #
samples = fetch_samples()
sample_labels = ["(start from scratch)"] + [s["label"] for s in samples]

with st.sidebar:
    st.subheader("Sample bugs")
    choice = st.selectbox("Load a known failure", sample_labels, key="sample_choice")
    st.caption(
        "BugHound never executes your code. Validation is static: syntax, imports, "
        "dependency pins and a security scan."
    )
    st.divider()
    st.caption(f"API: `{API_URL}`")

selected = next((s for s in samples if s["label"] == choice), None)


def prefill(field: str, default: str = "") -> str:
    return (selected or {}).get(field, default) or default


# --------------------------------------------------------------------------- #
# input form
# --------------------------------------------------------------------------- #
left, right = st.columns([1.15, 1])

with left:
    error_message = st.text_area(
        "Error message *", value=prefill("error_message"), height=90
    )
    col_a, col_b = st.columns(2)
    language = col_a.text_input("Language", value=prefill("language"))
    framework = col_b.text_input("Framework", value=prefill("framework"))
    stack_trace = st.text_area("Stack trace", value=prefill("stack_trace"), height=140)

with right:
    source_code = st.text_area("Source code", value=prefill("source_code"), height=170)
    logs = st.text_area("Logs", value=prefill("logs"), height=90)
    col_c, col_d = st.columns(2)
    dependencies = col_c.text_input(
        "Dependencies", value=", ".join(prefill("dependencies", []) or [])
    )
    repository_url = col_d.text_input("Repository URL", value=prefill("repository_url"))

run = st.button("🐾 Investigate bug", type="primary", use_container_width=True)

# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #
if run:
    if not error_message.strip():
        st.error("Add an error message first.")
        st.stop()

    payload = {
        "error_message": error_message.strip(),
        "stack_trace": stack_trace or None,
        "logs": logs or None,
        "source_code": source_code or None,
        "language": language or None,
        "framework": framework or None,
        "repository_url": repository_url or None,
        "dependencies": [d.strip() for d in dependencies.split(",") if d.strip()],
    }

    with st.status("Running the agent pipeline…", expanded=True) as status:
        st.write("🔍 Debug analysis → 🌐 Research → 🎯 Root cause → 🔧 Fix → 🧑‍💻 Review → 🧪 Validation")
        result = investigate(payload)
        status.update(label="Investigation complete", state="complete")

    st.session_state["result"] = result

result = st.session_state.get("result")

if result:
    review = result.get("review") or {}
    validation = result.get("validation") or {}
    approved = review.get("decision") == "APPROVED"

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Error type", result.get("error_type", "Unknown"))
    m2.metric("Confidence", f"{result.get('confidence', 0) * 100:.0f}%")
    m3.metric("Review", review.get("decision", "N/A"))
    m4.metric("Validation", validation.get("status", "SKIPPED"))

    st.progress(min(1.0, float(result.get("confidence", 0))))

    tab_report, tab_stages, tab_sources, tab_raw = st.tabs(
        ["📋 Report", "🧭 Stages", "🔗 Sources", "🧾 Raw JSON"]
    )

    with tab_report:
        st.markdown(result.get("final_response", "_No report produced._"))

    with tab_stages:
        for entry in result.get("trace", []):
            st.markdown(
                f'<div class="bh-card"><span class="bh-tag">{entry["label"]}</span>'
                f'<span style="float:right;color:#7386a0;font-size:12px">{entry["duration_ms"]} ms</span>'
                f'<p style="margin:8px 0 0;color:#3d5473;font-size:13px">{entry["detail"]}</p></div>',
                unsafe_allow_html=True,
            )
        for warning in result.get("warnings", []):
            st.warning(warning)

    with tab_sources:
        citations = result.get("citations", [])
        if not citations:
            st.info("No external sources were reachable for this investigation.")
        for c in citations:
            st.markdown(f"**{c['index']}.** [{c['title']}]({c['url']}) — `{c['source_type']}`")

    with tab_raw:
        st.json(result)

    badge = "bh-good" if approved else "bh-bad"
    st.markdown(
        f'<span class="bh-tag {badge}">Review {review.get("decision", "N/A")} · '
        f'score {review.get("score", 0)}/100 · risk {result.get("risk", "MEDIUM")}</span>',
        unsafe_allow_html=True,
    )
