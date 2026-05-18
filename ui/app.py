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

# Load .env BEFORE anything reads os.environ. Streamlit launched via
# nohup / detached shells doesn't inherit interactive env; without this
# the LLM-chat tab false-negatives on ANTHROPIC_API_KEY.
try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env")
except ImportError:
    pass

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
def _connect():
    """Single RW connection cached for the Streamlit session.

    DuckDB rejects opening a second connection to the same file with a
    different read_only flag in the same process. Tool calls flowing
    through `ToolSession._log_action` open RW connections to write
    audit rows; we match that mode here so the two paths coexist.
    """
    return duckdb.connect(str(WAREHOUSE), read_only=False)


def _connect_rw():
    return _connect()


@st.cache_data(ttl=60)
def df_query(sql: str, params: tuple = ()) -> pd.DataFrame:
    con = _connect()
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
    "Living World",
    "Overview",
    "Metric explorer",
    "Identity explorer",
    "Eval scorecard",
    "Proposals + critiques",
    "CS interventions",
    "LLM agent chat",
    "Audit trail",
]
tabs = st.tabs(tab_names)
# Existing tabs were indexed 0..7; the new Living-World tab is now tabs[0]
# and everything else shifts +1. References below have been remapped.


# ---------------------------------------------------------------------------
# Tab 0 — Living World (sim demo)
# ---------------------------------------------------------------------------

import time

from sim.world import WorldState, fresh_world, tick as sim_tick, SIM_T0
from sim.baseline import restore as sim_restore
from sim.watchers import growth_watcher_tick, cs_watcher_tick

# Initialise session state for the simulator.
if "world" not in st.session_state:
    st.session_state.world = fresh_world()
if "bg_on" not in st.session_state:
    st.session_state.bg_on = False
if "lens" not in st.session_state:
    st.session_state.lens = "growth"

with tabs[0]:
    st.header("Living World")
    st.caption("The W01 baseline as a starting point. Click 'Advance 1 hour' to "
               "tick the simulator; turn on Background to let it run. Personas "
               "join, predict, ghost, resolve. Watchers fire when signals move. "
               "Two lenses: Growth and CS.")

    world: WorldState = st.session_state.world
    bg_on: bool = st.session_state.bg_on

    # ---------- World clock + controls ----------
    clock_col, lens_col = st.columns([2, 1])
    with clock_col:
        st.markdown(
            f"### Sim time: `{world.sim_now.strftime('%a %Y-%m-%d %H:%M')}`  "
            f"·  tick #{world.tick_count}"
        )
    with lens_col:
        new_lens = st.radio("Lens", ["growth", "cs"], horizontal=True,
                             index=0 if st.session_state.lens == "growth" else 1,
                             key="lens_picker")
        if new_lens != st.session_state.lens:
            st.session_state.lens = new_lens
            st.rerun()

    btn_col1, btn_col2, btn_col3, btn_col4, btn_col5 = st.columns([1.2, 1.2, 1.2, 1.2, 2])
    if btn_col1.button("Advance 1 hour", key="adv_1h"):
        counters = sim_tick(world, advance_minutes=60)
        growth_watcher_tick(world.sim_now)
        cs_watcher_tick(world.sim_now)
        st.toast(f"tick: joined={counters['joined']} "
                 f"pred={counters['predictions']} resolved={counters['resolved']}")
        st.rerun()
    if btn_col2.button("Advance 1 day", key="adv_1d"):
        with st.spinner("ticking 24 hours..."):
            agg = dict(joined=0, predictions=0, resolved=0)
            for _ in range(24):
                c = sim_tick(world, advance_minutes=60)
                for k in agg:
                    agg[k] += c.get(k, 0)
            growth_watcher_tick(world.sim_now)
            cs_watcher_tick(world.sim_now)
        st.toast(f"day: joined={agg['joined']} pred={agg['predictions']} resolved={agg['resolved']}")
        st.rerun()
    if btn_col3.button("Background: " + ("ON" if bg_on else "OFF"), key="bg_toggle"):
        st.session_state.bg_on = not bg_on
        st.rerun()
    if btn_col4.button("Reset to W01", key="reset_w01"):
        sim_restore()
        st.session_state.world = fresh_world()
        # Wipe the cached cohort queries.
        st.cache_data.clear()
        st.toast("Restored W01 baseline.")
        st.rerun()
    btn_col5.markdown(
        f"Background tick auto-advances 1 hour every 2 seconds when ON. "
        f"Currently: **{'ON' if bg_on else 'OFF'}**."
    )

    st.divider()

    # ---------- KPI tiles (lens-sensitive) ----------
    session = ToolSession()
    try:
        ghost = session.call("ghost_rate", week_of="2024-W01", acquisition_source="unstop")
        dark = session.call("dark_channel_fraction", week_of="2024-W01")
    except Exception as e:
        st.error(f"Metric layer error: {e}")
        ghost = dark = None

    lens = st.session_state.lens
    if lens == "growth":
        k1, k2, k3, k4 = st.columns(4)
        new_personas = df_query(
            "SELECT COUNT(*) AS n FROM dim_user WHERE _source_system = 'sim.world'"
        ).iloc[0]["n"]
        new_preds_24h = df_query(
            """SELECT COUNT(*) AS n FROM fact_prediction
               WHERE _source_system = 'sim.world' AND made_at >= ?""",
            params=(world.sim_now - timedelta(hours=24),),
        ).iloc[0]["n"]
        k1.metric("Ghost rate (Unstop)", f"{ghost.value:.1%}" if ghost else "—",
                  delta=f"conf {ghost.confidence:.2f}" if ghost else None)
        k2.metric("Dark fraction", f"{dark.value:.1%}" if dark else "—")
        k3.metric("New personas (sim)", f"{int(new_personas):,}")
        k4.metric("Preds last 24h (sim)", f"{int(new_preds_24h):,}")
    else:  # cs lens
        k1, k2, k3, k4 = st.columns(4)
        at_risk = df_query(
            """SELECT COUNT(*) AS n FROM dim_user du
               WHERE du.signup_time IS NOT NULL
                 AND du.signup_time < ?
                 AND NOT EXISTS (
                   SELECT 1 FROM fact_prediction p
                   WHERE p.user_id = du.user_id AND p.made_at >= ?
                 )""",
            params=(world.sim_now, world.sim_now - timedelta(days=3)),
        ).iloc[0]["n"]
        recently_active = df_query(
            """SELECT COUNT(DISTINCT user_id) AS n FROM fact_prediction
               WHERE made_at >= ?""",
            params=(world.sim_now - timedelta(hours=24),),
        ).iloc[0]["n"]
        resolved_24h = df_query(
            """SELECT COUNT(*) AS n FROM fact_prediction
               WHERE is_outcome_resolved AND resolved_at >= ?""",
            params=(world.sim_now - timedelta(hours=24),),
        ).iloc[0]["n"]
        k1.metric("At-risk users (no preds 3d)", f"{int(at_risk):,}")
        k2.metric("Recently active (24h)", f"{int(recently_active):,}")
        k3.metric("Outcomes resolved (24h)", f"{int(resolved_24h):,}")
        k4.metric("Ghost rate", f"{ghost.value:.1%}" if ghost else "—")

    st.divider()

    # ---------- Event stream ----------
    st.subheader("Event stream (latest 30)")
    lens_filter = "AND (lens = ? OR lens = 'all')"
    try:
        events = df_query(
            f"""SELECT sim_ts, wall_ts, kind, actor, payload, lens
                FROM sim_events
                WHERE 1=1 {lens_filter}
                ORDER BY sim_ts DESC, wall_ts DESC LIMIT 30""",
            params=(lens,),
        )
    except Exception:
        events = pd.DataFrame(columns=["sim_ts", "wall_ts", "kind", "actor", "payload", "lens"])

    if events.empty:
        st.info("No events yet. Click 'Advance 1 hour' to start the world.")
    else:
        # Render as a compact log.
        events_display = events.copy()
        events_display["actor_short"] = events_display["actor"].apply(
            lambda s: (s[:12] + "...") if isinstance(s, str) and len(s) > 12 else (s or "")
        )
        for _, row in events_display.iterrows():
            try:
                p = json.loads(row["payload"]) if row["payload"] else {}
            except Exception:
                p = {}
            summary = ", ".join(f"{k}={v}" for k, v in list(p.items())[:3])
            ts = row["sim_ts"].strftime("%m-%d %H:%M") if hasattr(row["sim_ts"], "strftime") else str(row["sim_ts"])[:16]
            st.text(f"{ts}  [{row['lens']:6s}]  {row['kind']:24s}  {row['actor_short']:14s}  {summary}")

    st.divider()

    # ---------- Watcher state ----------
    st.subheader("Watcher state (last check)")
    try:
        kv = df_query(
            "SELECT key, value, updated_at FROM sim_kv ORDER BY key"
        )
        if kv.empty:
            st.write("(no watcher state yet — tick once)")
        else:
            st.dataframe(kv, use_container_width=True, hide_index=True)
    except Exception:
        st.write("(sim_kv not yet created)")

    # ---------- Background loop ----------
    # Streamlit reruns the script top-to-bottom on each interaction. If
    # background is on, sleep briefly then trigger a rerun so the world
    # advances on its own. Cheap because we only re-render the visible tab.
    if bg_on:
        time.sleep(2.0)
        sim_tick(world, advance_minutes=60)
        growth_watcher_tick(world.sim_now)
        cs_watcher_tick(world.sim_now)
        st.rerun()


# ---------------------------------------------------------------------------
# Tab 1 — Overview
# ---------------------------------------------------------------------------

with tabs[1]:
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

with tabs[2]:
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

with tabs[3]:
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

with tabs[4]:
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

with tabs[5]:
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
        sev_label = {"high": "[HIGH]", "medium": "[MED] ", "low": "[LOW] "}.get(sev, "[?]   ")
        with st.expander(f"{sev_label} {path.stem}  ·  status={status}  ·  severity={sev}", expanded=False):
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
                        icon = "FIRED" if c["fired"] else "    -"
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

with tabs[6]:
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

with tabs[7]:
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
                with st.expander(f"-> {t['tool']}({t['args']})  {'ERROR' if t['is_error'] else 'OK'}"):
                    st.json(t["result"])
            st.subheader("Agent answer")
            st.markdown(ans.final_text)
            st.caption(f"turns={ans.n_turns}  ·  tool_calls={len(ans.tool_trace)}")


# ---------------------------------------------------------------------------
# Tab 8 — Audit trail
# ---------------------------------------------------------------------------

with tabs[8]:
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
