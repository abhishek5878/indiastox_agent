"""IndiaStox substrate dashboard — Streamlit, 8 tabs.

Run:
    make ui                               # streamlit run ui/app.py
    open http://localhost:8501

Reads from warehouse/indiastox.duckdb (read-only for most tabs).
Tabs that mutate state — Proposals approve/reject, CS approve — open
a write connection on click.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from mcp.tools import TOOLS, ToolSession  # tool registry + audit-logged caller

WAREHOUSE = _REPO / "warehouse" / "indiastox.duckdb"
ASSETS = _REPO / "assets"
PROPOSALS_DIR = _REPO / "proposals"
INTERVENTIONS_DIR = _REPO / "interventions"

st.set_page_config(
    page_title="IndiaStox — substrate dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Cached data access
# ---------------------------------------------------------------------------

@st.cache_resource
def _connect_ro():
    return duckdb.connect(str(WAREHOUSE), read_only=True)


def _connect_rw():
    return duckdb.connect(str(WAREHOUSE), read_only=False)


@st.cache_data(ttl=60)
def df_query(sql: str, params: tuple = ()) -> pd.DataFrame:
    con = _connect_ro()
    return con.execute(sql, list(params)).df()


@st.cache_data(ttl=60)
def latest_eval_run() -> dict | None:
    runs = sorted((_REPO / "eval" / "results").glob("run_*.json"))
    if not runs:
        return None
    return json.loads(runs[-1].read_text())


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("IndiaStox")
    st.caption("Agent-native analytics substrate")
    st.markdown(
        f"**Warehouse:** `{WAREHOUSE.name}`\n\n"
        f"**Tools registered:** {len(TOOLS)}\n\n"
        f"**Active session:** `(per-tab)`"
    )
    if not WAREHOUSE.exists():
        st.error("Warehouse missing. Run `make all` first.")
        st.stop()


tab_names = [
    "🏠 Overview",
    "📊 Metric explorer",
    "🆔 Identity explorer",
    "📝 Eval scorecard",
    "📬 Proposals + critiques",
    "💬 CS interventions",
    "🤖 LLM agent chat",
    "🗂 Audit trail",
]
tabs = st.tabs(tab_names)


# ---------------------------------------------------------------------------
# Tab 1 — Overview
# ---------------------------------------------------------------------------

with tabs[0]:
    st.header("Overview")

    # KPI row.
    eval_run = latest_eval_run()
    identity_summary = df_query("""
        SELECT
          SUM(CASE WHEN identity_confidence >= 0.85 THEN 1 ELSE 0 END) AS high,
          SUM(CASE WHEN identity_confidence BETWEEN 0.60 AND 0.8499 THEN 1 ELSE 0 END) AS medium,
          COUNT(*) AS total
        FROM dim_user
    """)
    high_pct = (identity_summary.iloc[0]["high"] / identity_summary.iloc[0]["total"]) if len(identity_summary) else 0
    persona_count = df_query("SELECT COUNT(*) AS n FROM dim_user").iloc[0]["n"]

    session = ToolSession()
    ghost = session.call("ghost_rate", week_of="2024-W01", acquisition_source="unstop")
    dark = session.call("dark_channel_fraction", week_of="2024-W01")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Personas resolved", f"{int(persona_count):,}")
    col2.metric("Identity high-conf", f"{high_pct:.1%}")
    if eval_run:
        col3.metric("Latest eval", f"{eval_run['total_score']}/{eval_run['max_total']}")
    col4.metric("Ghost rate (Unstop)", f"{ghost.value:.1%}")

    st.divider()

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Prediction calibration")
        png = ASSETS / "calibration_curve.png"
        if png.exists():
            st.image(str(png), caption="`make calibration` regenerates")
        else:
            st.info("Run `make calibration` to generate.")
    with col_b:
        st.subheader("Agent eval scorecard")
        png = ASSETS / "eval_scorecard.png"
        if png.exists():
            st.image(str(png), caption="`make eval-scorecard` regenerates")
        else:
            st.info("Run `make eval-scorecard` to generate.")

    st.subheader("Dashboard mosaic — 4 panels live")
    png = ASSETS / "dashboard_mosaic.png"
    if png.exists():
        st.image(str(png))


# ---------------------------------------------------------------------------
# Tab 2 — Metric explorer
# ---------------------------------------------------------------------------

with tabs[1]:
    st.header("Metric explorer")
    st.caption("Every tool returns the same typed `MetricResult`. Slide the params; "
               "watch the trace + provenance update live.")

    tool_name = st.selectbox("Metric", sorted(TOOLS.keys()))
    fn = TOOLS[tool_name]

    # Build kwargs UI from function signature.
    underlying = fn
    while hasattr(underlying, "__wrapped__"):
        underlying = underlying.__wrapped__
    import inspect
    sig = inspect.signature(underlying)
    kwargs: dict = {}
    for pname, p in sig.parameters.items():
        if p.annotation is float:
            kwargs[pname] = st.number_input(
                pname, value=float(p.default) if p.default is not inspect.Parameter.empty else 0.0,
                key=f"k_{tool_name}_{pname}",
            )
        elif p.annotation is int:
            kwargs[pname] = st.number_input(
                pname, value=int(p.default) if p.default is not inspect.Parameter.empty else 0,
                step=1, key=f"k_{tool_name}_{pname}",
            )
        elif p.annotation is bool:
            kwargs[pname] = st.checkbox(
                pname, value=bool(p.default) if p.default is not inspect.Parameter.empty else False,
                key=f"k_{tool_name}_{pname}",
            )
        else:
            kwargs[pname] = st.text_input(
                pname, value=str(p.default) if p.default not in (inspect.Parameter.empty, None) else "",
                key=f"k_{tool_name}_{pname}",
            )
            if kwargs[pname] in ("", "None"):
                kwargs[pname] = None

    if st.button("Run", key=f"run_{tool_name}"):
        session = ToolSession()
        try:
            result = session.call(tool_name, **{k: v for k, v in kwargs.items() if v is not None})
        except Exception as e:
            st.error(f"Tool errored: {e}")
        else:
            st.subheader(f"{result.metric_name}  ({result.metric_version})")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("value", f"{result.value:.4f}" if isinstance(result.value, float) else result.value)
            c2.metric("confidence", f"{result.confidence:.2f}")
            c3.metric("sample_n", f"{int(result.sample_n):,}")
            c4.metric("window_open", str(result.window_open))
            st.info(result.interpretation)
            st.markdown("**Why this number? — 3-step trace:**")
            for i, step in enumerate(result.trace, 1):
                st.markdown(f"  **[{i}]** {step}")
            with st.expander("Provenance"):
                st.json(result.provenance)
            with st.expander("Audit"):
                st.code(f"definition_hash: {result.definition_hash}\n"
                        f"audit_session: {session.session_id}")


# ---------------------------------------------------------------------------
# Tab 3 — Identity explorer
# ---------------------------------------------------------------------------

with tabs[2]:
    st.header("Identity explorer")
    st.caption("Search by user_id or email; browse the typed-confidence edges.")

    q = st.text_input("user_id or email contains …", key="id_q").strip()
    if q:
        df = df_query("""
            SELECT user_id, full_name, personal_email, college_email,
                   acquisition_source, identity_confidence, identity_flags
            FROM dim_user
            WHERE user_id LIKE '%' || ? || '%'
               OR LOWER(personal_email) LIKE '%' || LOWER(?) || '%'
               OR LOWER(college_email)  LIKE '%' || LOWER(?) || '%'
            LIMIT 50
        """, params=(q, q, q))
        st.write(f"{len(df)} match(es)")
        st.dataframe(df, use_container_width=True)
        if len(df):
            chosen = st.selectbox("Select user_id for edge browse", df["user_id"].tolist())
            edges_db = _REPO / "identity" / "edges.duckdb"
            if edges_db.exists():
                econ = duckdb.connect(str(edges_db), read_only=True)
                try:
                    edges = econ.execute("""
                        SELECT source_system, source_key, key_type,
                               confidence, resolution_method, provenance
                        FROM identity_edge WHERE entity_id = ?
                    """, [chosen]).df()
                finally:
                    econ.close()
                st.dataframe(edges, use_container_width=True)

    st.divider()
    st.subheader("Blocked shared-device pairs (Pass 3 anti-merge)")
    blocked = df_query("""
        SELECT entity_id, source_key, confidence, provenance
        FROM (SELECT * FROM identity_edge) tmp
        WHERE FALSE -- placeholder, edges.duckdb is a separate file
    """) if False else None
    # Load from edges.duckdb directly.
    edges_db = _REPO / "identity" / "edges.duckdb"
    if edges_db.exists():
        econ = duckdb.connect(str(edges_db), read_only=True)
        try:
            blocked = econ.execute("""
                SELECT entity_id, source_key, confidence, provenance
                FROM identity_edge WHERE resolution_method = 'blocked_shared_device'
                LIMIT 50
            """).df()
        finally:
            econ.close()
        st.write(f"{len(blocked)} blocked rows (showing 50)")
        st.dataframe(blocked, use_container_width=True)


# ---------------------------------------------------------------------------
# Tab 4 — Eval scorecard (interactive)
# ---------------------------------------------------------------------------

with tabs[3]:
    st.header("Eval scorecard")
    run = latest_eval_run()
    if not run:
        st.warning("No eval runs yet. `make eval` first.")
    else:
        st.metric("Total", f"{run['total_score']}/{run['max_total']}")
        st.caption(f"Run: {run['ts']}  ·  session: {run['session_id']}")

        import plotly.graph_objects as go
        results = run["results"]
        dims = ["accuracy", "calibration", "action"]
        z = [[r["scores"][d] for r in results] for d in dims]
        x = [r["id"] for r in results]
        fig = go.Figure(data=go.Heatmap(
            z=z, x=x, y=dims,
            colorscale=[[0, "#d62728"], [1, "#2ca02c"]], zmin=0, zmax=1,
            text=[[str(int(v)) for v in row] for row in z],
            texttemplate="%{text}", textfont=dict(size=14, color="white"),
            hoverongaps=False,
        ))
        fig.update_layout(height=240, margin=dict(t=20, b=20))
        st.plotly_chart(fig, use_container_width=True)

        # Drill-down.
        qid = st.selectbox("Drill down", [r["id"] for r in results])
        chosen = next(r for r in results if r["id"] == qid)
        st.subheader(qid)
        st.write(f"**Question:** {chosen['text']}")
        col_l, col_r = st.columns(2)
        col_l.metric("Agent value", str(chosen["agent_value"]))
        col_r.metric("Ground truth", f"{chosen['ground_truth']}  ({chosen['ground_truth_kind']})")
        st.write(f"**Calibration string:**\n\n> {chosen['agent_calibration']}")
        st.write(f"**Proposed action:**\n\n> {chosen['agent_action']}")
        st.json(chosen["scores"])


# ---------------------------------------------------------------------------
# Tab 5 — Proposals + critiques inbox
# ---------------------------------------------------------------------------

with tabs[4]:
    st.header("Proposals inbox")
    st.caption("Pending / approved / executed / rejected. Every card carries its Critic-Agent v2.0.0 review inline.")

    import yaml as _yaml
    status_filter = st.radio("Filter", ["pending", "approved", "executed", "rejected", "all"],
                             horizontal=True, index=0)
    folders = ["pending", "approved", "executed", "rejected"] if status_filter == "all" else [status_filter]
    files = []
    for f in folders:
        for p in (PROPOSALS_DIR / f).glob("*.yaml"):
            files.append((f, p))
    st.write(f"{len(files)} proposal(s)")

    for status, path in files:
        doc = _yaml.safe_load(path.read_text())
        crit = doc.get("critique", {})
        sev = crit.get("severity", "?")
        color = {"high": "🔴", "medium": "🟠", "low": "🟢"}.get(sev, "⚪")
        with st.expander(f"{color} {path.stem}  ·  status={status}  ·  severity={sev}", expanded=False):
            st.write(f"**Hypothesis:** {doc.get('hypothesis', '(missing)')}")
            st.write(f"**Affected metric:** `{doc.get('affected_metric', '?')}`  "
                     f"·  expected lift: {doc.get('expected_lift_pct', 0):+.1f}pp  "
                     f"·  required n: {doc.get('required_sample_n', '?')}")
            if crit:
                st.markdown("**Critic v2.0.0 — counter-argument:**")
                st.text(crit.get("counter_argument", "(missing)"))
                checks = crit.get("confounder_checks", [])
                if checks:
                    fired = sum(1 for c in checks if c["fired"])
                    st.markdown(f"**Confounder checks** — {fired}/{len(checks)} fired:")
                    for c in checks:
                        icon = "🔥" if c["fired"] else "·"
                        st.text(f"  {icon}  {c['name']}: {c['evidence']}")
                st.markdown("**Alternative proposal:**")
                st.info(crit.get("alternative_proposal", "(none)"))
            if status == "pending":
                c1, c2 = st.columns(2)
                if c1.button("Approve", key=f"appr_{path.stem}"):
                    new = PROPOSALS_DIR / "approved" / path.name
                    new.parent.mkdir(parents=True, exist_ok=True)
                    path.replace(new)
                    con = _connect_rw()
                    con.execute("UPDATE proposals SET status='approved' WHERE proposal_id=?",
                                [path.stem])
                    con.close()
                    st.success(f"Approved {path.stem}.")
                    st.rerun()
                if c2.button("Reject", key=f"rej_{path.stem}"):
                    new = PROPOSALS_DIR / "rejected" / path.name
                    new.parent.mkdir(parents=True, exist_ok=True)
                    path.replace(new)
                    con = _connect_rw()
                    con.execute("UPDATE proposals SET status='rejected' WHERE proposal_id=?",
                                [path.stem])
                    con.close()
                    st.warning(f"Rejected {path.stem}.")
                    st.rerun()


# ---------------------------------------------------------------------------
# Tab 6 — CS interventions feed
# ---------------------------------------------------------------------------

with tabs[5]:
    st.header("CS interventions")
    st.caption("Personalized at-risk-user nudges from `agent/cs_agent.py`. Each card is grounded in the user's actual ticker history.")
    import yaml as _yaml
    pending = sorted((INTERVENTIONS_DIR / "pending").glob("*.yaml"))
    st.write(f"{len(pending)} pending intervention(s)")
    for p in pending:
        doc = _yaml.safe_load(p.read_text())
        with st.expander(f"{doc.get('tone', '?').upper()}  ·  user {p.stem[:8]}  ·  primary_ticker {doc.get('primary_ticker', '?')}"):
            st.write(doc.get("intervention_text", "(missing)"))
            st.markdown("**Grounding facts:**")
            for g in doc.get("grounding_facts", []):
                st.text(f"  · {g}")
            c1, c2, c3 = st.columns(3)
            c1.metric("Risk score", f"{doc.get('risk_score', 0):.2f}")
            c2.metric("Est. reactivation lift", f"{doc.get('estimated_reactivation_lift', 0):.1%}")
            c3.metric("Channel", doc.get("channel", "?"))


# ---------------------------------------------------------------------------
# Tab 7 — LLM agent chat
# ---------------------------------------------------------------------------

with tabs[6]:
    st.header("LLM agent chat")
    st.caption("Live `claude-sonnet-4-6` Growth Agent — reads the same `mcp.tools` substrate.")

    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if not has_key:
        st.error("ANTHROPIC_API_KEY not set. Add to .env or export in shell.")
    else:
        prompt = st.text_input("Ask the Growth Agent:", value="What is the week-1 ghost rate for Unstop cohort?", key="llm_q")
        if st.button("Ask", key="llm_ask"):
            from agent.llm_growth_agent import LLMGrowthAgent
            with st.spinner("Calling Claude — model + tools …"):
                ans = LLMGrowthAgent().answer("user", prompt)
            st.subheader("Tool trace")
            for t in ans.tool_trace:
                with st.expander(f"→ {t['tool']}({t['args']})  {'⚠ error' if t['is_error'] else 'OK'}"):
                    st.json(t["result"])
            st.subheader("Agent answer")
            st.markdown(ans.final_text)
            st.caption(f"turns={ans.n_turns}  ·  tool_calls={len(ans.tool_trace)}")


# ---------------------------------------------------------------------------
# Tab 8 — Audit trail
# ---------------------------------------------------------------------------

with tabs[7]:
    st.header("Audit trail")
    st.caption("Every tool call. Every proposal. Every human decision.")

    days = st.slider("Window (days)", 1, 30, 7, key="audit_days")
    from agent.audit_summary import render
    summary = render(days=days)

    if "error" in summary:
        st.error(summary["error"])
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Total tool calls", summary["total_calls"])
        c2.metric("Tools used", len(summary["tools"]))
        c3.metric("Sessions seen", len(summary["top_sessions"]))

        if summary["tools"]:
            df = pd.DataFrame(summary["tools"])
            df = df.rename(columns={"name": "tool", "n": "calls", "mean_conf": "mean_confidence"})
            st.dataframe(df, use_container_width=True)

        col_l, col_r = st.columns(2)
        with col_l:
            st.subheader("Proposal status")
            if summary["proposal_status"]:
                st.dataframe(pd.DataFrame(summary["proposal_status"]), use_container_width=True)
            else:
                st.write("(no proposals)")
        with col_r:
            st.subheader("Critique severity")
            sev = summary["critique_severity"]
            st.dataframe(pd.DataFrame([{"severity": k, "n": v} for k, v in sev.items()]),
                         use_container_width=True)

        st.subheader("Top sessions")
        if summary["top_sessions"]:
            st.dataframe(pd.DataFrame(summary["top_sessions"]), use_container_width=True)

        st.subheader("Recent downstream-proposal events")
        if summary["downstream"]:
            st.dataframe(pd.DataFrame(summary["downstream"]), use_container_width=True)
