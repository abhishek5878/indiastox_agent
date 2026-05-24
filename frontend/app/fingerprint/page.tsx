"use client";

import { Badge, Card, CardContent, CardHeader, CardTitle, HintIcon } from "@/components/ui";
import { metrics, MetricResult } from "@/lib/api";
import { useEffect, useState } from "react";

interface AxisScore {
  score: number;
  n?: number;
  confidence_low?: boolean;
  status?: string;
}

interface FingerprintBreakdowns {
  gyaani: {
    tier: string;
    mu: number | null;
    phi: number | null;
    n_resolved: number;
    gaps_to_locked: {
      mu_short_by: number | null;
      phi_excess: number | null;
      calls_short_by: number | null;
    };
    rule_version: string;
  };
  reward_axes: {
    axes: Record<string, AxisScore>;
    top_axis: string | null;
    top_score: number;
    rule_version: string;
  };
  behavior_segment: {
    primary_segment: string | null;
    primary_score: number;
    segments: Record<string, AxisScore>;
    rule_version: string;
  };
  identity: {
    full_name: string | null;
    archetype_slug: string | null;
    acquisition_source: string | null;
  };
  tier_rank: number;
}

const TIER_TONE: Record<string, string> = {
  none: "bg-slate-500/30 text-slate-200 border-slate-500/40",
  aspirant: "bg-emerald-500/30 text-emerald-200 border-emerald-500/40",
  locked: "bg-fuchsia-500/30 text-fuchsia-200 border-fuchsia-500/40",
};

const AXIS_LABEL: Record<string, string> = {
  accuracy: "Accuracy",
  calibration: "Calibration",
  coverage: "Coverage",
  consistency: "Consistency",
  recovery: "Recovery",
  presence: "Presence",
  influence: "Influence",
  discovery: "Discovery",
};

const SEGMENT_LABEL: Record<string, string> = {
  ghosted: "Ghosted",
  cooled_off: "Cooled off",
  tilted: "Tilted",
  alphas: "Alpha",
  anchored: "Anchored",
  concentrators: "Concentrator",
  diversifiers: "Diversifier",
  shadows: "Shadow (stub)",
};

export default function FingerprintPage() {
  const [userId, setUserId] = useState<string>("");
  const [submittedId, setSubmittedId] = useState<string>("");
  const [result, setResult] = useState<MetricResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [sampleIds, setSampleIds] = useState<string[]>([]);

  // Seed the input with a few real near-miss aspirants so the page
  // demonstrates immediately. Pulls from nudge_targets.
  useEffect(() => {
    metrics.invoke("nudge_targets", { week_of: "2024-W01", top_n: 6 })
      .then((r) => {
        const ids: string[] = (r.breakdowns?.targets || []).map((t: any) => t.user_id);
        setSampleIds(ids);
        if (ids.length > 0 && !submittedId) {
          setUserId(ids[0]);
          setSubmittedId(ids[0]);
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!submittedId) return;
    setLoading(true);
    setErr(null);
    metrics.invoke("user_fingerprint", { user_id: submittedId, week_of: "2024-W01" })
      .then((r) => { setResult(r); setLoading(false); })
      .catch((e) => { setErr(String(e)); setLoading(false); });
  }, [submittedId]);

  return (
    <div className="px-8 py-7 max-w-[1200px] mx-auto">
      <header className="mb-6">
        <div className="text-xs font-medium tracking-widest text-[var(--muted-foreground)] uppercase">User fingerprint</div>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Gyaani · Reward axes · Behavior segment</h1>
        <p className="mt-1 text-sm text-[var(--muted-foreground)] max-w-2xl">
          The unified per-user view: tier + 8-axis fingerprint + dominant
          behavioral segment, all from a single tool call
          (<span className="mono">user_fingerprint</span>). The mechanic
          the product would expose to the user themselves.
        </p>
      </header>

      <Card className="mb-5">
        <CardContent>
          <form
            className="flex flex-wrap gap-2 items-center"
            onSubmit={(e) => { e.preventDefault(); setSubmittedId(userId.trim()); }}
          >
            <input
              type="text"
              className="flex-1 min-w-[300px] px-3 py-1.5 rounded-md bg-[var(--muted)] border border-[var(--border)] text-sm mono"
              placeholder="user_id (uuid)"
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
            />
            <button
              type="submit"
              className="px-3 py-1.5 rounded-md bg-[var(--primary)] text-white text-xs font-medium"
            >
              Look up
            </button>
          </form>
          {sampleIds.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5 text-[11px]">
              <span className="text-[var(--muted-foreground)]">Near-miss samples:</span>
              {sampleIds.slice(0, 6).map((id) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => { setUserId(id); setSubmittedId(id); }}
                  className="mono px-2 py-0.5 rounded border border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--accent)]/50"
                >
                  {id.slice(0, 8)}…
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {err && (
        <Card>
          <CardHeader><CardTitle>Lookup failed</CardTitle></CardHeader>
          <CardContent>
            <pre className="text-xs text-red-400 mono whitespace-pre-wrap">{err}</pre>
          </CardContent>
        </Card>
      )}

      {loading && (
        <div className="text-sm text-[var(--muted-foreground)]">Loading fingerprint…</div>
      )}

      {result && !loading && !err && (
        <FingerprintCards b={result.breakdowns as FingerprintBreakdowns} userId={submittedId} />
      )}
    </div>
  );
}

function FingerprintCards({ b, userId }: { b: FingerprintBreakdowns; userId: string }) {
  const g = b.gyaani;
  const a = b.reward_axes;
  const seg = b.behavior_segment;
  const id = b.identity;
  const axes = Object.entries(a.axes || {});

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader>
          <CardTitle>
            {id.full_name || `User ${userId.slice(0, 8)}…`}
            <span className="ml-2 text-xs text-[var(--muted-foreground)] mono">{userId.slice(0, 12)}…</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-4 text-sm">
            <FactPill label="Archetype" value={id.archetype_slug || "unknown"} />
            <FactPill label="Acquisition" value={id.acquisition_source || "—"} />
            <FactPill
              label="Gyaani tier"
              value={g.tier}
              tone={TIER_TONE[g.tier]}
            />
            <FactPill label="μ" value={g.mu === null ? "—" : g.mu.toFixed(0)} />
            <FactPill label="φ" value={g.phi === null ? "—" : g.phi.toFixed(0)} />
            <FactPill label="resolved calls" value={String(g.n_resolved)} />
          </div>
          {g.tier !== "locked" && g.gaps_to_locked.mu_short_by !== null && (
            <div className="mt-4 p-3 rounded-md bg-[var(--accent)]/40 border border-[var(--border)]">
              <div className="text-xs font-medium text-[var(--foreground)] mb-2">
                Gap to Gyaani-locked
                <HintIcon content={"The remaining distance on each axis. The product surface this as a personalised CTA: 'X more calls until you lock the badge'."} />
              </div>
              <div className="flex flex-wrap gap-4 text-xs mono">
                <span className="text-[var(--muted-foreground)]">
                  calls short: <span className="text-[var(--foreground)]">{g.gaps_to_locked.calls_short_by}</span>
                </span>
                <span className="text-[var(--muted-foreground)]">
                  μ short by: <span className="text-[var(--foreground)]">{Number(g.gaps_to_locked.mu_short_by || 0).toFixed(1)}</span>
                </span>
                <span className="text-[var(--muted-foreground)]">
                  φ excess: <span className="text-[var(--foreground)]">{Number(g.gaps_to_locked.phi_excess || 0).toFixed(1)}</span>
                </span>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-3 gap-5">
        <Card className="col-span-2">
          <CardHeader>
            <CardTitle>
              Reward axes
              <HintIcon content={"Eight orthogonal axes (P2). Even users far from Gyaani score on presence + recovery so 'everyone is needed'. Stubbed axes flagged status='stub'."} />
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2.5">
              {axes.map(([name, v]) => {
                const score = Number(v.score || 0);
                const isStub = v.status?.startsWith("stub");
                return (
                  <div key={name}>
                    <div className="flex justify-between mb-1 text-xs">
                      <span>
                        {AXIS_LABEL[name] || name}
                        {isStub && <Badge variant="outline" className="ml-1 text-[9px]">stub</Badge>}
                        {a.top_axis === name && (
                          <Badge variant="info" className="ml-1 text-[9px]">top</Badge>
                        )}
                      </span>
                      <span className="text-[var(--muted-foreground)] mono">{(score * 100).toFixed(0)}</span>
                    </div>
                    <div className="h-1.5 bg-[var(--muted)] rounded overflow-hidden">
                      <div
                        className={isStub ? "h-full bg-[var(--muted-foreground)]/30" : "h-full bg-[var(--primary)]"}
                        style={{ width: `${Math.max(2, score * 100)}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>
              Behavior segment
              <HintIcon content={"P3 classifier. A user has scores on every segment; the dominant one labels them."} />
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold tracking-tight">
              {SEGMENT_LABEL[seg.primary_segment || ""] || seg.primary_segment || "—"}
            </div>
            <div className="text-[11px] text-[var(--muted-foreground)] mono mt-1">
              primary_score={seg.primary_score?.toFixed(2)}
            </div>
            <div className="mt-4 space-y-1.5">
              {Object.entries(seg.segments || {})
                .filter(([, v]) => Number(v.score || 0) > 0)
                .sort((a, b) => Number(b[1].score) - Number(a[1].score))
                .map(([name, v]) => (
                  <div key={name} className="flex justify-between text-[11px]">
                    <span className="text-[var(--muted-foreground)]">{SEGMENT_LABEL[name] || name}</span>
                    <span className="mono">{Number(v.score).toFixed(2)}</span>
                  </div>
                ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function FactPill({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className={`px-2.5 py-1.5 rounded-md border ${tone || "border-[var(--border)] bg-[var(--muted)]"}`}>
      <div className="text-[10px] uppercase tracking-wider opacity-70">{label}</div>
      <div className="text-sm font-medium mono">{value}</div>
    </div>
  );
}
