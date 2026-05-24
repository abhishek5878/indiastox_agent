"use client";

import { Badge, Card, CardContent, CardHeader, CardTitle, HintIcon } from "@/components/ui";
import { metrics, MetricResult } from "@/lib/api";
import { useEffect, useState } from "react";

interface Stage {
  name: string;
  label: string;
  n: number;
  conversion_from_prior: number;
  share_of_signup: number;
}

interface DropOff {
  n: number;
  segment_mix: Record<string, number>;
}

interface FunnelBreakdowns {
  stages: Stage[];
  locked: number;
  drop_off: {
    after_signup: DropOff;
    after_first_call: DropOff;
    after_three_resolved: DropOff;
  };
  acquisition_source: string;
  week_of: string;
}

const SEGMENT_LABEL: Record<string, string> = {
  ghosted: "Ghosted",
  cooled_off: "Cooled off",
  tilted: "Tilted",
  alphas: "Alphas",
  anchored: "Anchored",
  concentrators: "Concentrators",
  diversifiers: "Diversifiers",
  shadows: "Shadows (stub)",
  "(none)": "Below scoring gate",
};

const SEGMENT_COLOR: Record<string, string> = {
  ghosted: "bg-slate-400/70",
  cooled_off: "bg-amber-500/80",
  tilted: "bg-red-500/80",
  alphas: "bg-emerald-500/80",
  anchored: "bg-cyan-500/80",
  concentrators: "bg-indigo-500/80",
  diversifiers: "bg-fuchsia-500/80",
  shadows: "bg-violet-400/60",
  "(none)": "bg-[var(--muted-foreground)]/40",
};

export default function FunnelPage() {
  const [funnel, setFunnel] = useState<MetricResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    metrics
      .invoke("funnel_stages", { week_of: "2024-W01", acquisition_source: "unstop" })
      .then(setFunnel)
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) {
    return (
      <div className="px-8 py-7 max-w-[1200px] mx-auto">
        <Card>
          <CardHeader><CardTitle>Funnel unavailable</CardTitle></CardHeader>
          <CardContent>
            <p className="text-sm text-[var(--muted-foreground)]">
              The funnel_stages metric returned an error. Verify the
              warehouse and skill ratings are present (make resolve, make
              skill).
            </p>
            <pre className="mt-3 text-xs text-red-400 mono whitespace-pre-wrap">{err}</pre>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!funnel) {
    return (
      <div className="px-8 py-7 max-w-[1200px] mx-auto text-sm text-[var(--muted-foreground)]">
        Loading funnel…
      </div>
    );
  }

  const b = funnel.breakdowns as FunnelBreakdowns;
  const stages = b.stages;
  const drop = b.drop_off;
  const headlinePct = (funnel.value * 100).toFixed(1);

  const gateTransitions = [
    { drop: drop.after_signup, fromLabel: stages[0].label, toLabel: stages[1].label },
    { drop: drop.after_first_call, fromLabel: stages[1].label, toLabel: stages[2].label },
    { drop: drop.after_three_resolved, fromLabel: stages[2].label, toLabel: stages[3].label },
  ];

  return (
    <div className="px-8 py-7 max-w-[1200px] mx-auto">
      <header className="mb-6">
        <div className="text-xs font-medium tracking-widest text-[var(--muted-foreground)] uppercase">Growth funnel</div>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Signup to Gyaani</h1>
        <p className="mt-1 text-sm text-[var(--muted-foreground)] max-w-2xl">
          Four stages, each a strict subset of the prior. Cohort:
          <span className="mono"> {b.acquisition_source}</span>, week
          <span className="mono"> {b.week_of}</span>. Headline conversion
          (signup → aspirant): <span className="font-semibold text-[var(--foreground)]">{headlinePct}%</span>.
          <span className="ml-1">Locked-tier badge holders: <span className="mono">{b.locked}</span>.</span>
        </p>
      </header>

      <Card className="mb-6">
        <CardHeader>
          <CardTitle>
            Stage progression
            <HintIcon content={"Each row's width is its share of the signup cohort. The percentage at right is the conversion rate from the prior stage."} />
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {stages.map((s, i) => {
              const widthPct = Math.max(0.5, s.share_of_signup * 100);
              const convPct = (s.conversion_from_prior * 100).toFixed(1);
              return (
                <div key={s.name}>
                  <div className="flex justify-between mb-1 text-xs">
                    <span className="text-[var(--foreground)] font-medium">
                      {i + 1}. {s.label}
                      <span className="ml-2 text-[var(--muted-foreground)] mono">n={s.n.toLocaleString()}</span>
                    </span>
                    <span className="text-[var(--muted-foreground)] mono">
                      {i === 0 ? "100% of signups" : `${convPct}% from prior · ${(s.share_of_signup * 100).toFixed(1)}% of signups`}
                    </span>
                  </div>
                  <div className="h-6 bg-[var(--muted)] rounded overflow-hidden">
                    <div
                      className="h-full bg-[var(--primary)] flex items-center justify-end pr-2 text-[10px] text-white font-medium"
                      style={{ width: `${widthPct}%` }}
                    >
                      {widthPct > 8 ? `${s.n.toLocaleString()}` : ""}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          <div className="mt-4 text-[11px] text-[var(--muted-foreground)]">
            {funnel.interpretation}
          </div>
        </CardContent>
      </Card>

      <div className="mb-3">
        <div className="text-xs font-medium tracking-widest text-[var(--muted-foreground)] uppercase">Drop-off by behavioral segment</div>
        <p className="text-xs text-[var(--muted-foreground)] mt-1">
          For each stage transition, the segment-mix of users who didn't progress (sampled).
          Drives which intervention surface each cohort needs.
        </p>
      </div>

      <div className="grid grid-cols-3 gap-4">
        {gateTransitions.map((g, idx) => (
          <DropOffCard
            key={idx}
            title={`${g.fromLabel} → ${g.toLabel}`}
            drop={g.drop}
          />
        ))}
      </div>
    </div>
  );
}

function DropOffCard({ title, drop }: { title: string; drop: DropOff }) {
  const entries = Object.entries(drop.segment_mix);
  const total = entries.reduce((acc, [, n]) => acc + n, 0);
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-sm font-medium">{title}</CardTitle>
          <Badge variant="outline" className="text-[10px] shrink-0 mono">
            {drop.n.toLocaleString()} stuck
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        {total === 0 ? (
          <div className="text-[11px] text-[var(--muted-foreground)] py-2">No drop-off at this gate.</div>
        ) : (
          <div className="space-y-2">
            {entries.map(([seg, n]) => {
              const pct = (n / total) * 100;
              return (
                <div key={seg}>
                  <div className="flex justify-between text-[11px] mb-1">
                    <span className="text-[var(--foreground)]">{SEGMENT_LABEL[seg] || seg}</span>
                    <span className="text-[var(--muted-foreground)] mono">{n} · {pct.toFixed(0)}%</span>
                  </div>
                  <div className="h-1.5 bg-[var(--muted)] rounded overflow-hidden">
                    <div
                      className={`h-full ${SEGMENT_COLOR[seg] || "bg-[var(--muted-foreground)]/40"}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
            <div className="text-[10px] text-[var(--muted-foreground)] mono pt-1">
              sampled {total} of {drop.n.toLocaleString()}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
