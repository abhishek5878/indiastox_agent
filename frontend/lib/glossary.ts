// Glossary of jargon a first-time visitor will see.
// Used by Tooltip + HintIcon to make every technical term hoverable.

export interface GlossaryEntry {
  label: string;     // human-readable label, used in place of the raw key
  short: string;     // 1-line description shown inline
  long?: string;     // optional longer explanation in the tooltip
}

export const CONFOUNDERS: Record<string, GlossaryEntry> = {
  klaviyo_deliverability_drop: {
    label: "Klaviyo delivery integrity",
    short: "Are open events arriving before send events?",
    long: "Scans email-pairs in raw.klaviyo_events for opened_at < sent_at. If >1% of pairs are inverted, downstream lift attributed to email may be measuring clock drift, not engagement.",
  },
  prediction_market_noise_floor: {
    label: "Noise-floor proximity",
    short: "Are user calls only marginally better than random?",
    long: "Compares brier_score against the random-guess baseline of 0.25. If the substrate is near the floor, any channel intervention is fitting noise. BULL/BEAR resolutions can't tell the variants apart.",
  },
  identity_resolution_drift: {
    label: "Identity-graph drift",
    short: "Did the join logic change since this proposal was scored?",
    long: "Checks metric_gameability_index. The hash of every metric definition + source table version. If a definition changed mid-experiment, the headline number is comparing apples to a different apple.",
  },
  dark_channel_dominance: {
    label: "Dark-channel floor",
    short: "How much CAC is unknowable by construction?",
    long: "dark_channel_fraction counts users whose first touchpoint is WhatsApp forwards / IRL screenshots. No UTM, no attribution. Any attribution-side proposal is bounded by this floor.",
  },
  exam_season_seasonality: {
    label: "Exam-season effect",
    short: "Is this lift just a calendar artifact?",
    long: "Cross-checks the proposed effect against historical exam-season cohorts. If signups always dip in Jan, attributing a Jan dip to a channel change is confounded.",
  },
};

export const METRICS: Record<string, GlossaryEntry> = {
  ghost_rate: {
    label: "Ghost rate",
    short: "Fraction of users who sign up and never Make a Call.",
    long: "Computed weekly per acquisition_source. The cohort is closed at sign-up; the metric carries a typed confidence score that reflects sample size + completeness of the join.",
  },
  ghost_rate_unstop: {
    label: "Ghost rate · Unstop",
    short: "Unstop-cohort fraction that signs up and never makes a BULL/BEAR call.",
  },
  brier_score: {
    label: "Brier score",
    short: "Call calibration. Lower is better. Random = 0.25.",
    long: "Mean squared error between a user's confidence-stars (rescaled to probability) and their actual BULL/BEAR outcomes. The agent's eval also asks for the calibration *string* alongside the number. See /eval.",
  },
  dark_channel_fraction: {
    label: "Dark-channel fraction",
    short: "Share of users arriving through unmeasurable surfaces.",
    long: "17.6% of W01 users come in through WhatsApp forwards, Telegram @indiastox shares, IRL screenshots. Surfaces that carry no UTM and no consent-bound identifier. The CAC bound is wide because the substrate types the uncertainty (channel_cac_bounds returns a lower + upper interval) rather than collapsing it to a point estimate. Any attribution-side proposal is bounded by this floor.",
  },
  metric_gameability_index: {
    label: "Gameability index",
    short: "Three-axis watchdog over the metric layer itself.",
    long: "Tracks definition_hash_drift (did the SQL change?), source_table_drift (did dim_user gain rows?), value_outlier_drift (is the number anomalously far from its 30-day baseline?). Treat any nonzero value as load-bearing.",
  },
  time_to_first_action: {
    label: "Time to first call",
    short: "Median minutes from signup to first BULL/BEAR call.",
  },
  weekly_active_posters: {
    label: "Weekly active callers",
    short: "Users who made at least one BULL/BEAR call in the 7-day window.",
  },
  unstop_to_participation_rate: {
    label: "Unstop → participation",
    short: "Fraction of Unstop signups that participate in any challenge.",
  },
  channel_cac_bounds: {
    label: "Channel CAC bounds",
    short: "CAC interval per channel, widened by dark-channel fraction.",
    long: "Returns lower + upper estimate. Lower bound assumes the dark fraction was acquired via the cheapest channel; upper assumes the most expensive. The interval is the headline.",
  },
  call_consensus_divergence: {
    label: "Call consensus divergence",
    short: "Mean gap between retail BULL-share and actual BULL-win-rate per ticker.",
    long: "For every ticker with 20+ resolved calls, compares the share of calls that were BULL against the share of BULL calls that won. The mean absolute gap across tickers tells you whether retail consensus is systematically wrong. Treat as a feed-weighting signal, not a tradeable one.",
  },
  ai_content_flagged_share: {
    label: "AI-content flagged share",
    short: "Share of analysis posts flagged by the AI-author heuristic.",
    long: "Detector runs over user-submitted thesis posts (separate from BULL/BEAR calls) on three signals: avg word length, no-first-person + long text, and a 47-string LLM-tell phrase list. Shadow-mode until false-positive rate drops below 2.0%. The Critic uses this as a calibration input for content-policy proposals.",
  },
  pre_ipo_call_interest: {
    label: "Pre-IPO call interest",
    short: "Share of W01 calls placed on Pre-IPO tray tickers.",
    long: "The Pre-IPO tray is a separate surface where outcomes resolve at the IPO event, not at T+5d. This metric tracks engagement with the tray (a leading indicator on which Pre-IPO names the cohort wants to bet on) and is a proxy for tray-positioning decisions.",
  },
  behavioral_concentration_index: {
    label: "Behavioral concentration",
    short: "Mean per-user Herfindahl on ticker distribution.",
    long: "For each user with 3+ calls, sum((calls_on_ticker / total_calls)^2). HHI=1.0 means single-ticker concentration; ~0.1 means perfectly diversified across 10 names. Typical retail lands 0.35-0.55. The cohort distribution (concentrated / focused / diversified / exploratory) tells you whether feed-weighting should reward exploration or rein in concentration.",
  },
  cascade_followon_lift: {
    label: "Cascade follow-on lift",
    short: "Post-cascade call rate vs baseline on the same ticker.",
    long: "For every `news_cascade` event in the last 7 sim-days, measures the 2-hour post-window call count on the cascade ticker vs that ticker's rolling baseline rate. Lift > 1.0 means organic FOMO follow-on. A real signal that cascades create herd behavior beyond just the directly-affected users.",
  },
};

export const TERMS: Record<string, GlossaryEntry> = {
  confidence: {
    label: "Identity confidence",
    short: "A number from 0–1, never a yes/no.",
    long: "Every user-touchpoint match in the substrate carries a typed score + provenance. Downstream metrics that join on identity inherit the floor confidence.",
  },
  tool_call: {
    label: "Tool call",
    short: "Every metric is exposed as a function the agent can invoke.",
    long: "All numbers. Dashboard tiles, agent answers, CS interventions. Flow through the same audit-logged ToolSession. There is no separate \"query for the dashboard.\"",
  },
  critic: {
    label: "Critic Agent v2.0.0",
    short: "Runs the 5 confounder checks against live data before any proposal is approved.",
    long: "Each confounder is a tool call that returns a real number. If the number crosses a threshold (e.g., dark_channel_fraction > 15%), the confounder fires and gets attached to the proposal's critique payload.",
  },
  audit_log: {
    label: "Audit log",
    short: "Every tool call lands in agent_actions. Append-only.",
    long: "Same stream whether the caller is the Living World sim, the LLM growth agent, the CS agent, or the human dashboard. The /audit page is a degraded read of this stream.",
  },
};

export function humanizeConfounder(name: string): string {
  return CONFOUNDERS[name]?.label || name.replace(/_/g, " ");
}

export function humanizeMetric(name: string): string {
  return METRICS[name]?.label || name.replace(/_/g, " ");
}
