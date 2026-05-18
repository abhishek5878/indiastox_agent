"""Workbook schema — Pydantic models are the single source of truth.

DuckDB DDL is *generated* from the Pydantic models via `generate_ddl()`. Do
not write DDL by hand; do not let the dashboard re-define columns. The
six tabs plus the metric-results materialization are all defined here.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, ClassVar, Optional, Union, get_args, get_origin

try:  # Python 3.10+ has `X | Y` as types.UnionType; 3.9 only has typing.Union
    from types import UnionType as _PEP604UnionType  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - Python 3.9 branch
    _PEP604UnionType = None  # type: ignore[assignment]

from pydantic import BaseModel, ConfigDict, Field


def _is_union_origin(origin: Any) -> bool:
    if origin is Union:
        return True
    if _PEP604UnionType is not None and origin is _PEP604UnionType:
        return True
    return False

SCHEMA_VERSION = "1.0.0"

SCHEMA_CHANGELOG: dict[str, str] = {
    "1.0.0": (
        "Initial six-tab schema: dim_user, dim_challenge, fact_acquisition, "
        "fact_engagement, fact_prediction, audit_log. Plus metric_results "
        "materialization read by Metabase."
    ),
}


# Map Python types to DuckDB column types.
_TYPE_MAP: dict[Any, str] = {
    str: "TEXT",
    int: "INTEGER",
    float: "DOUBLE",
    bool: "BOOLEAN",
    datetime: "TIMESTAMP",
    date: "DATE",
    bytes: "BLOB",
}


def _ddl_type(annotation: Any) -> tuple[str, bool]:
    """Return (duckdb_type, is_nullable) for a Python annotation."""
    origin = get_origin(annotation)
    args = get_args(annotation)

    # Handle Optional[X] / X | None / Union[X, None]
    if _is_union_origin(origin):
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            inner_type, _ = _ddl_type(non_none[0])
            return inner_type, True
        raise ValueError(f"unsupported Union: {annotation}")

    # Handle list[X] / List[X]
    if origin is list:
        inner_type, _ = _ddl_type(args[0]) if args else ("TEXT", False)
        return f"{inner_type}[]", False

    # Handle dict / Dict → JSON
    if origin is dict or annotation is dict:
        return "JSON", False

    # Plain scalar
    if annotation in _TYPE_MAP:
        return _TYPE_MAP[annotation], False

    raise ValueError(f"no DDL mapping for annotation: {annotation!r}")


class WorkbookBase(BaseModel):
    """Common audit columns inherited by every workbook table."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    table_name: ClassVar[str] = ""
    primary_key: ClassVar[list[str]] = []

    schema_version: str = Field(default=SCHEMA_VERSION)
    loaded_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), alias="_loaded_at"
    )
    source_system: str = Field(default="", alias="_source_system")


class DimUser(WorkbookBase):
    """Canonical user record after identity resolution. One row per resolved entity."""

    table_name: ClassVar[str] = "dim_user"
    primary_key: ClassVar[list[str]] = ["user_id"]

    user_id: str
    full_name: str
    personal_email: Optional[str] = None
    college_email: Optional[str] = None
    phone_hash: Optional[str] = None
    device_fingerprint: str
    city: str
    city_tier: str  # "Tier-1" | "Tier-2"
    device_type: str  # "mobile" | "desktop"
    occupation: Optional[str] = None
    age: Optional[int] = None
    college: Optional[str] = None
    identity_confidence: float
    identity_flags: list[str]
    model_version: str
    acquisition_source: Optional[str] = None  # earliest known acquisition source
    signup_time: Optional[datetime] = None
    true_skill: Optional[float] = None  # latent ground-truth (Layer N1); for Glicko-2 mu validation


class DimChallenge(WorkbookBase):
    """Weekly-challenge dimension."""

    table_name: ClassVar[str] = "dim_challenge"
    primary_key: ClassVar[list[str]] = ["weekly_challenge_id"]

    weekly_challenge_id: str
    week_of: str  # ISO week, e.g. "2024-W01"
    challenge_name: str
    start_date: date
    end_date: date


class FactAcquisition(WorkbookBase):
    """One row per user per acquisition touchpoint."""

    table_name: ClassVar[str] = "fact_acquisition"
    primary_key: ClassVar[list[str]] = ["acquisition_id"]

    acquisition_id: str
    user_id: str
    weekly_challenge_id: Optional[str] = None
    touchpoint_source: str  # which raw system: unstop|backend|posthog|klaviyo|ga4
    utm_source: Optional[str] = None
    utm_campaign: Optional[str] = None
    touchpoint_at: datetime


class FactEngagement(WorkbookBase):
    """One row per meaningful user action (challenge_signup / participation / etc.)."""

    table_name: ClassVar[str] = "fact_engagement"
    primary_key: ClassVar[list[str]] = ["engagement_id"]

    engagement_id: str
    user_id: str
    weekly_challenge_id: Optional[str] = None
    event_type: str  # "challenge_signup" | "challenge_participation" | "prediction" | ...
    event_at: datetime
    properties: Optional[dict] = None


class FactPrediction(WorkbookBase):
    """One row per prediction. Outcome columns are nullable and resolved later (deferred join)."""

    table_name: ClassVar[str] = "fact_prediction"
    primary_key: ClassVar[list[str]] = ["prediction_id"]

    prediction_id: str
    user_id: str
    stock_symbol: str
    direction: str  # "BULL" | "BEAR"
    confidence_stars: int  # 1..5
    made_at: datetime
    # deferred-join columns:
    outcome: Optional[str] = None  # "WIN" | "LOSS" | "DRAW"
    pnl_points: Optional[float] = None
    accuracy_delta: Optional[float] = None
    resolved_at: Optional[datetime] = None
    is_outcome_resolved: bool = False


class AuditLog(WorkbookBase):
    """One row per pipeline-stage run. Drives the data-quality story."""

    table_name: ClassVar[str] = "audit_log"
    primary_key: ClassVar[list[str]] = ["run_id"]

    run_id: str
    run_at: datetime
    pipeline_stage: str  # "generate" | "resolve" | "load" | "metric"
    input_row_count: Optional[int] = None
    output_row_count: Optional[int] = None
    identity_stats: Optional[dict] = None
    notes: Optional[str] = None


# Side table read by Metabase. Not one of the six tabs but materialized
# from the metric layer so dashboards never re-implement the metric SQL.
class MetricResults(WorkbookBase):
    table_name: ClassVar[str] = "metric_results"
    primary_key: ClassVar[list[str]] = ["metric_name", "as_of", "definition_version", "breakdown_key"]

    metric_name: str
    as_of: datetime
    value: float
    confidence: float
    sample_n: int
    provenance_json: str   # JSON-encoded list[str]
    window_open: bool
    interpretation: str
    definition_version: str
    confidence_interval_low: Optional[float] = None
    confidence_interval_high: Optional[float] = None
    computation_sql: str
    breakdown_key: str = "all"
    breakdown_value: Optional[float] = None


class AgentActions(WorkbookBase):
    """Every tool call the agent makes is itself an event. This is the audit
    trail that makes agent behavior reproducible and reviewable.
    """

    table_name: ClassVar[str] = "agent_actions"
    primary_key: ClassVar[list[str]] = ["action_id"]

    action_id: str
    ts: datetime
    session_id: str
    tool_name: str
    args_json: str
    result_hash: str  # sha256 of MetricResult agent-visible fields
    result_confidence: float
    downstream_proposal_id: Optional[str] = None


class Proposals(WorkbookBase):
    """Experiment proposals — written by the agent, approved by a human.

    Status lifecycle: pending -> approved -> executed (-> rejected at any stage).
    """

    table_name: ClassVar[str] = "proposals"
    primary_key: ClassVar[list[str]] = ["proposal_id"]

    proposal_id: str
    created_ts: datetime
    triggered_by_action_id: Optional[str] = None
    hypothesis: str
    affected_metric: str
    expected_lift_pct: float
    confidence: float
    required_sample_n: int
    estimated_days: int
    status: str  # 'pending' | 'approved' | 'executed' | 'rejected'


class MetricVersions(WorkbookBase):
    """Ledger of every metric definition version ever deployed.

    Populated on startup by `core.version_registry.register_all()` — a row
    is inserted the FIRST time a (metric_name, definition_hash) pair is
    seen. Previous active versions are marked deprecated_at = now() so the
    timeline is queryable.

    Reproducibility hinges on this: a MetricResult cites its
    `metric_version` + `definition_hash`; `make reproduce` looks the
    hash up here to detect whether the definition has shifted since.
    """

    table_name: ClassVar[str] = "metric_versions"
    primary_key: ClassVar[list[str]] = ["metric_name", "version", "definition_hash"]

    metric_name: str
    version: str
    definition_hash: str
    deployed_at: datetime
    deprecated_at: Optional[datetime] = None
    breaking_change: bool
    change_note: Optional[str] = None


class SourceTableVersions(WorkbookBase):
    """DDL-hash snapshot per upstream source table — N8 anti-Goodhart axis 2.

    Every pipeline run hashes the schema (column names + types) of each
    source table that metrics read from. If the hash drifts without a
    deliberate migration, `metric_gameability_index` fires the
    `source_table_drift` axis — meaning a metric's definition stayed
    constant but its source got reshaped, and any number cited under
    the prior DDL is no longer directly comparable.
    """

    table_name: ClassVar[str] = "source_table_versions"
    primary_key: ClassVar[list[str]] = ["source_table_name", "ddl_hash"]

    source_table_name: str  # renamed from `table_name` to avoid shadowing the ClassVar
    ddl_hash: str  # sha256 of column-name + type list
    deployed_at: datetime
    deprecated_at: Optional[datetime] = None
    column_count: int
    notes: Optional[str] = None


ALL_TABLES: list[type[WorkbookBase]] = [
    DimUser,
    DimChallenge,
    FactAcquisition,
    FactEngagement,
    FactPrediction,
    AuditLog,
    MetricResults,
    AgentActions,
    Proposals,
    MetricVersions,
    SourceTableVersions,
]


def generate_ddl(model: type[WorkbookBase]) -> str:
    """Emit a DuckDB `CREATE TABLE IF NOT EXISTS` statement from a Pydantic model.

    Field name in DDL = `Field(alias=...)` if set, else the Python attribute
    name. Nullability is derived from `Optional[...]` / `X | None`. Audit
    columns inherit from `WorkbookBase` and ride along.
    """
    cols: list[str] = []
    for name, field_info in model.model_fields.items():
        ddl_name = field_info.alias or name
        annotation = field_info.annotation
        ddl_type, is_nullable = _ddl_type(annotation)

        parts = [f"  {ddl_name} {ddl_type}"]
        if not is_nullable and field_info.is_required():
            parts.append("NOT NULL")

        # Defaults for the three audit columns.
        if ddl_name == "schema_version":
            parts.append(f"DEFAULT '{SCHEMA_VERSION}'")
        elif ddl_name == "_loaded_at":
            parts.append("DEFAULT now()")

        cols.append(" ".join(parts))

    pk = model.primary_key
    if pk:
        cols.append(f"  PRIMARY KEY ({', '.join(pk)})")

    return f"CREATE TABLE IF NOT EXISTS {model.table_name} (\n" + ",\n".join(cols) + "\n);"


def generate_all_ddl() -> str:
    """All tables, concatenated, in dependency order."""
    return "\n\n".join(generate_ddl(t) for t in ALL_TABLES)


def apply_ddl(connection) -> None:
    """Apply all CREATE TABLE statements to a DuckDB connection."""
    connection.execute(generate_all_ddl())


if __name__ == "__main__":
    print(f"-- Schema version {SCHEMA_VERSION}")
    print(f"-- Tables: {[t.table_name for t in ALL_TABLES]}")
    print()
    print(generate_all_ddl())
