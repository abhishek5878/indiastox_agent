// Tiny fetch wrapper around the FastAPI backend.
const BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!r.ok) throw new Error(`${r.status} ${path}: ${await r.text()}`);
  return r.json();
}

// --- Sim ---
export const sim = {
  state: () => j<{ sim_now: string; tick_count: number; accel: number }>("/api/sim/state"),
  tick: (minutes: number) =>
    j<{ counters: Record<string, number>; sim_now: string; tick_count: number; watchers: any }>(
      "/api/sim/tick",
      { method: "POST", body: JSON.stringify({ minutes, run_watchers: true }) },
    ),
  reset: () => j("/api/sim/reset", { method: "POST" }),
  events: (lens?: string, limit = 30) =>
    j<SimEvent[]>(
      `/api/sim/events?limit=${limit}${lens && lens !== "all" ? `&lens=${lens}` : ""}`,
    ),
  kpis: () => j<Kpis>("/api/sim/kpis"),
  reasons: () => j<{ reason: string; n: number }[]>("/api/sim/reasons"),
};

// --- Metrics ---
export const metrics = {
  list: () => j<ToolMeta[]>("/api/metrics"),
  invoke: (name: string, args: Record<string, any>) =>
    j<MetricResult>(`/api/metrics/${name}`, {
      method: "POST",
      body: JSON.stringify({ args }),
    }),
};

// --- Proposals ---
export const proposals = {
  list: (status?: string) =>
    j<Proposal[]>(`/api/proposals${status ? `?status=${status}` : ""}`),
  act: (id: string, action: "approve" | "reject" | "execute") =>
    j(`/api/proposals/${id}/${action}`, { method: "POST" }),
  auto: (weekOf = "2024-W01") =>
    j<AutoProposalResult>("/api/proposals/auto", {
      method: "POST",
      body: JSON.stringify({ week_of: weekOf }),
    }),
};

export interface AutoProposalResult {
  filed: boolean;
  reason: string;
  proposal_id: string | null;
  yaml_path?: string;
  insight: {
    kind: string;
    subject: string;
    surprise_score: number;
    summary: string;
    suggested_experiment: string;
  } | null;
}

// --- Interventions ---
export const interventions = {
  list: (status = "pending") => j<Intervention[]>(`/api/interventions?status=${status}`),
  act: (userId: string, action: "approve" | "reject") =>
    j<{ user_id: string; new_status: string; sim_reengaged?: boolean }>(
      `/api/interventions/${userId}/${action}`,
      { method: "POST" },
    ),
};

// --- Eval ---
export const evalApi = {
  latest: () => j<EvalRun>("/api/eval/latest"),
};

// --- Identity ---
export const identity = {
  search: (q: string) => j<IdentityUser[]>(`/api/identity/search?q=${encodeURIComponent(q)}`),
  edges: (userId: string) => j<IdentityEdge[]>(`/api/identity/${userId}/edges`),
  blocked: () => j<any[]>("/api/identity/blocked-pairs"),
};

// --- Audit ---
export const audit = {
  summary: (days = 7) => j<AuditSummary>(`/api/audit?days=${days}`),
};

// --- LLM ---
export const llm = {
  status: () => j<{ has_key: boolean; model: string }>("/api/llm/status"),
  asset: (name: string) => `${BASE}/api/assets/${name}`,
};

// --- WebSocket helper for sim events ---
export function openSimEventsWS(onEvent: (e: SimEvent) => void): WebSocket {
  const wsUrl = BASE.replace(/^http/, "ws") + "/api/sim/ws";
  const ws = new WebSocket(wsUrl);
  ws.onmessage = (m) => {
    try {
      onEvent(JSON.parse(m.data));
    } catch {}
  };
  return ws;
}

// ---- Types ----
export interface SimEvent {
  event_id: string;
  sim_ts: string;
  wall_ts: string;
  kind: string;
  actor: string;
  payload: Record<string, any>;
  lens: string;
}

export interface Kpis {
  ghost_rate_unstop: { value: number; confidence: number; interpretation: string; sample_n: number };
  dark_fraction: { value: number; confidence: number; interpretation: string };
  sim_personas_new: number;
  sim_preds_24h: number;
  at_risk_3d: number;
  outcomes_resolved_24h: number;
  sim_now: string;
  tick_count: number;
}

export interface MetricResult {
  metric_name: string;
  value: number;
  confidence: number;
  sample_n: number;
  provenance: string[];
  window_open: boolean;
  interpretation: string;
  trace: string[];
  definition_version: string;
  definition_hash: string;
  confidence_interval: [number, number] | null;
  breakdowns: any;
  as_of: string;
  session_id: string;
}

export interface ToolMeta {
  name: string;
  description: string;
  params: { name: string; type: string; default: any; required: boolean }[];
}

export interface Proposal {
  proposal_id: string;
  status: string;
  hypothesis: string;
  affected_metric: string;
  expected_lift_pct: number;
  required_sample_n: number;
  estimated_days: number;
  created_ts: string;
  critique: any;
  proposed_experiment: string;
}

export interface Intervention {
  user_id: string;
  tone: string;
  risk_score: number;
  channel: string;
  primary_ticker: string;
  intervention_text: string;
  grounding_facts: string[];
  n_predictions: number;
  n_correct: number;
  estimated_reactivation_lift: number;
}

export interface EvalRun {
  ts: string;
  session_id: string;
  total_score: number;
  max_total: number;
  results: Array<{
    id: string;
    text: string;
    ground_truth: any;
    ground_truth_kind: string;
    agent_value: any;
    agent_calibration: string;
    agent_action: string;
    scores: { accuracy: number; calibration: number; action: number; total: number; max: number };
  }>;
}

export interface IdentityUser {
  user_id: string;
  full_name: string;
  personal_email: string;
  college_email: string | null;
  acquisition_source: string;
  identity_confidence: number;
  identity_flags: string[];
}

export interface IdentityEdge {
  source_system: string;
  source_key: string;
  key_type: string;
  confidence: number;
  resolution_method: string;
  provenance: string;
  model_version: string;
}

export interface AuditSummary {
  days: number;
  total_calls: number;
  tools: { name: string; n: number; mean_conf: number }[];
  proposal_status: { status: string; n: number }[];
  critique_severity: Record<string, number>;
  top_sessions: any[];
  downstream: any[];
}
