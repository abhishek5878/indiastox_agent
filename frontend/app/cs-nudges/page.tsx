"use client";

import { Badge, Card, CardContent, CardHeader, CardTitle, HintIcon } from "@/components/ui";
import { metrics, MetricResult } from "@/lib/api";
import { useEffect, useState } from "react";

interface NudgeTarget {
  user_id: string;
  display_name: string;
  archetype: string;
  acquisition_source: string;
  tier: string;
  mu: number;
  phi: number;
  n_resolved: number;
  gap_score: number;
  biggest_gap_axis: string;
  gap_calls: number;
  gap_mu: number;
  gap_phi: number;
  nudge_hook: string;
}

interface NudgeBreakdowns {
  targets: NudgeTarget[];
  cohort_size: number;
  acquisition_source: string;
}

const AXIS_TONE: Record<string, string> = {
  calls: "bg-amber-500/30 text-amber-200 border-amber-500/40",
  mu: "bg-fuchsia-500/30 text-fuchsia-200 border-fuchsia-500/40",
  phi: "bg-cyan-500/30 text-cyan-200 border-cyan-500/40",
};

export default function CsNudgesPage() {
  const [result, setResult] = useState<MetricResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [axisFilter, setAxisFilter] = useState<string>("all");

  useEffect(() => {
    metrics
      .invoke("nudge_targets", { week_of: "2024-W01", top_n: 50, acquisition_source: "unstop" })
      .then(setResult)
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) {
    return (
      <div className="px-8 py-7 max-w-[1200px] mx-auto">
        <Card>
          <CardHeader><CardTitle>Nudge targets unavailable</CardTitle></CardHeader>
          <CardContent>
            <p className="text-sm text-[var(--muted-foreground)]">
              The nudge_targets metric returned an error. Verify make
              resolve + make skill have been run.
            </p>
            <pre className="mt-3 text-xs text-red-400 mono whitespace-pre-wrap">{err}</pre>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="px-8 py-7 max-w-[1200px] mx-auto text-sm text-[var(--muted-foreground)]">
        Loading nudge targets…
      </div>
    );
  }

  const b = result.breakdowns as NudgeBreakdowns;
  const all = b.targets;
  const targets = axisFilter === "all" ? all : all.filter((t) => t.biggest_gap_axis === axisFilter);

  const axisCounts = all.reduce<Record<string, number>>((acc, t) => {
    acc[t.biggest_gap_axis] = (acc[t.biggest_gap_axis] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="px-8 py-7 max-w-[1200px] mx-auto">
      <header className="mb-6">
        <div className="text-xs font-medium tracking-widest text-[var(--muted-foreground)] uppercase">Nudge targets</div>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Aspirants nearest to Gyaani-locked</h1>
        <p className="mt-1 text-sm text-[var(--muted-foreground)] max-w-2xl">
          {b.cohort_size} aspirants in the <span className="mono">{b.acquisition_source}</span> cohort.
          Surfacing the top {all.length} ranked by composite gap to locked
          (calls/10 + mu/200 + phi/50). Smaller gap = higher leverage. Each
          row's <em>nudge hook</em> names the specific axis the message
          should target.
        </p>
      </header>

      <div className="mb-4 flex flex-wrap gap-2">
        <FilterPill label={`All (${all.length})`} active={axisFilter === "all"} onClick={() => setAxisFilter("all")} />
        {Object.entries(axisCounts).map(([axis, n]) => (
          <FilterPill
            key={axis}
            label={`${axis}-short (${n})`}
            active={axisFilter === axis}
            onClick={() => setAxisFilter(axis)}
            tone={AXIS_TONE[axis]}
          />
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>
            Top {targets.length} nudge candidates
            <HintIcon content={"Lower gap_score = closer to locked. mu-short users need accuracy gains; calls-short users need volume; phi-short users need confidence convergence (more calls)."} />
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[var(--border)] text-[var(--muted-foreground)]">
                  <th className="text-left py-2 pl-1">#</th>
                  <th className="text-left">User</th>
                  <th className="text-left">Archetype</th>
                  <th className="text-right">Tier</th>
                  <th className="text-right">μ</th>
                  <th className="text-right">φ</th>
                  <th className="text-right">n</th>
                  <th className="text-right">Gap score</th>
                  <th className="text-right">Short axis</th>
                  <th className="text-left pl-3">Nudge hook</th>
                </tr>
              </thead>
              <tbody>
                {targets.map((t, i) => (
                  <tr key={t.user_id} className="border-b border-[var(--border)]/60">
                    <td className="py-1.5 pl-1 text-[var(--muted-foreground)] mono">{i + 1}</td>
                    <td className="mono text-[var(--foreground)]">{t.user_id.slice(0, 8)}…</td>
                    <td>{t.archetype}</td>
                    <td className="text-right">
                      <Badge variant="outline" className="text-[10px]">{t.tier}</Badge>
                    </td>
                    <td className="text-right mono tabular-nums">{t.mu.toFixed(0)}</td>
                    <td className="text-right mono tabular-nums">{t.phi.toFixed(0)}</td>
                    <td className="text-right mono tabular-nums">{t.n_resolved}</td>
                    <td className="text-right mono tabular-nums">{t.gap_score.toFixed(3)}</td>
                    <td className="text-right">
                      <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] border ${AXIS_TONE[t.biggest_gap_axis] || ""}`}>
                        {t.biggest_gap_axis}
                      </span>
                    </td>
                    <td className="pl-3 text-[var(--muted-foreground)]">{t.nudge_hook}</td>
                  </tr>
                ))}
                {targets.length === 0 && (
                  <tr>
                    <td colSpan={10} className="py-6 text-center text-[var(--muted-foreground)]">
                      No targets for this filter.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <div className="mt-4 text-[11px] text-[var(--muted-foreground)] mono">
        {result.interpretation}
      </div>
    </div>
  );
}

function FilterPill({ label, active, onClick, tone }: {
  label: string;
  active: boolean;
  onClick: () => void;
  tone?: string;
}) {
  const base = "px-2.5 py-1 rounded-md text-xs border transition-colors cursor-pointer";
  const cls = active
    ? (tone || "bg-[var(--accent)] text-[var(--foreground)] border-[var(--border)] font-medium")
    : "border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--accent)]/50";
  return (
    <button type="button" onClick={onClick} className={`${base} ${cls}`}>
      {label}
    </button>
  );
}
