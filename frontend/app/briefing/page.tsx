"use client";

import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { AutoProposalResult, metrics, MetricResult, proposals } from "@/lib/api";
import Link from "next/link";
import { useEffect, useState } from "react";

interface Umbrella {
  id: string;
  question: string;
  headline: string;
  interpretation: string;
  status: "shipped" | "partial" | "gated";
  cta_label: string;
  cta_href: string;
  source_metric: string;
}

interface TodayNudge {
  user_id: string;
  archetype: string;
  short_axis: string;
  hook: string;
}

interface TodayInsight {
  kind: string;
  surprise_score: number;
  summary: string;
  suggested_experiment: string;
}

interface BriefingBreakdowns {
  umbrellas: Umbrella[];
  today: {
    top_insights: TodayInsight[];
    top_nudges: TodayNudge[];
  };
  gated: { id: string; description: string; unlocked_by: string }[];
  week_of: string;
  shipped_count: number;
  partial_count: number;
}

const STATUS_TONE: Record<string, string> = {
  shipped: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
  partial: "bg-amber-500/20 text-amber-300 border-amber-500/30",
  gated: "bg-slate-500/20 text-slate-300 border-slate-500/30",
};

const STATUS_LABEL: Record<string, string> = {
  shipped: "✓ Shipped",
  partial: "◐ Partial",
  gated: "○ Gated",
};

export default function BriefingPage() {
  const [result, setResult] = useState<MetricResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    metrics.invoke("briefing", { week_of: "2024-W01" })
      .then(setResult)
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) {
    return (
      <div className="px-8 py-7 max-w-[1200px] mx-auto">
        <Card>
          <CardHeader><CardTitle>Briefing unavailable</CardTitle></CardHeader>
          <CardContent>
            <pre className="text-xs text-red-400 mono whitespace-pre-wrap">{err}</pre>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="px-8 py-7 max-w-[1200px] mx-auto text-sm text-[var(--muted-foreground)]">
        Loading briefing…
      </div>
    );
  }

  const b = result.breakdowns as BriefingBreakdowns;

  return (
    <div className="px-8 py-7 max-w-[1100px] mx-auto">
      <header className="mb-7">
        <div className="text-xs font-medium tracking-widest text-[var(--muted-foreground)] uppercase">Briefing</div>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">Where we stand — the 7 meeting questions</h1>
        <p className="mt-2 text-sm text-[var(--muted-foreground)] max-w-2xl">
          Plain answers to each of the seven umbrella terms from the
          strategy meeting. Read the headlines for the picture; click
          through for substrate detail. Week of <span className="mono">{b.week_of}</span>.
        </p>
        <div className="mt-3 flex gap-2 text-xs">
          <Badge variant="outline" className="bg-emerald-500/10 text-emerald-300 border-emerald-500/30">
            {b.shipped_count} shipped
          </Badge>
          <Badge variant="outline" className="bg-amber-500/10 text-amber-300 border-amber-500/30">
            {b.partial_count} partial
          </Badge>
          <Badge variant="outline">
            {b.gated.length} gated on next phase
          </Badge>
        </div>
      </header>

      {/* TODAY block — what to act on right now */}
      <section className="mb-8">
        <h2 className="text-xs font-semibold tracking-widest text-[var(--muted-foreground)] uppercase mb-3">Today</h2>
        <div className="grid grid-cols-2 gap-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-medium">Top 3 insights</CardTitle>
            </CardHeader>
            <CardContent>
              <ol className="space-y-3 text-sm">
                {b.today.top_insights.map((i, idx) => (
                  <li key={idx} className="border-l-2 border-[var(--primary)]/40 pl-3">
                    <div className="text-[var(--foreground)] leading-snug">{i.summary}</div>
                    <div className="text-[11px] text-[var(--muted-foreground)] mt-1">
                      <span className="mono">{i.kind}</span> · surprise {i.surprise_score.toFixed(2)}
                    </div>
                  </li>
                ))}
              </ol>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-medium">Top 5 nudgeable users</CardTitle>
            </CardHeader>
            <CardContent>
              <ol className="space-y-1.5 text-sm">
                {b.today.top_nudges.map((n, idx) => (
                  <li key={idx} className="flex justify-between gap-2 text-xs">
                    <span className="mono text-[var(--muted-foreground)]">{n.user_id.slice(0, 8)}…</span>
                    <span className="text-[var(--foreground)]">{n.archetype}</span>
                    <span className="text-[var(--muted-foreground)] truncate">{n.hook}</span>
                  </li>
                ))}
              </ol>
              <div className="mt-3">
                <Link href="/cs-nudges" className="text-xs text-[var(--primary)] hover:underline">
                  See the full list →
                </Link>
              </div>
            </CardContent>
          </Card>
        </div>
      </section>

      {/* SEVEN UMBRELLAS — the narrative spine */}
      <section className="mb-8">
        <h2 className="text-xs font-semibold tracking-widest text-[var(--muted-foreground)] uppercase mb-3">The 7 questions</h2>
        <div className="space-y-4">
          {b.umbrellas.map((u, idx) => (
            <Card key={u.id}>
              <CardContent className="pt-5">
                <div className="flex items-start gap-3 mb-2">
                  <div className="text-xs text-[var(--muted-foreground)] mono w-5 shrink-0 pt-0.5">{idx + 1}.</div>
                  <div className="flex-1">
                    <div className="flex items-start justify-between gap-3">
                      <h3 className="text-sm font-medium text-[var(--foreground)] leading-snug">{u.question}</h3>
                      <Badge variant="outline" className={`text-[10px] shrink-0 ${STATUS_TONE[u.status]}`}>
                        {STATUS_LABEL[u.status]}
                      </Badge>
                    </div>
                    <p className="mt-2 text-sm text-[var(--foreground)] leading-relaxed">{u.headline}</p>
                    <p className="mt-1.5 text-xs text-[var(--muted-foreground)] leading-relaxed">{u.interpretation}</p>
                    <div className="mt-3 flex items-center gap-3 text-[11px]">
                      <Link href={u.cta_href} className="text-[var(--primary)] hover:underline">
                        {u.cta_label} →
                      </Link>
                      <span className="text-[var(--muted-foreground)] mono opacity-60">
                        from: {u.source_metric}
                      </span>
                    </div>
                    {u.id === "growth_hack" && <AutoProposeButton />}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {/* GATED — what's still in flight */}
      <section className="mb-6">
        <h2 className="text-xs font-semibold tracking-widest text-[var(--muted-foreground)] uppercase mb-3">What's still gated</h2>
        <div className="space-y-2">
          {b.gated.map((g) => (
            <Card key={g.id}>
              <CardContent className="py-3">
                <div className="flex items-baseline justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium text-[var(--foreground)]">{g.description}</div>
                    <div className="text-[11px] text-[var(--muted-foreground)] mt-0.5">
                      Unlocked by: <span className="mono text-[var(--foreground)]">{g.unlocked_by}</span>
                    </div>
                  </div>
                  <Badge variant="outline" className="text-[10px] mono shrink-0">{g.id}</Badge>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <div className="text-[11px] text-[var(--muted-foreground)] mono">
        briefing v{result.definition_version} · {result.interpretation}
      </div>
    </div>
  );
}

function AutoProposeButton() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AutoProposalResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const fire = async () => {
    setLoading(true);
    setErr(null);
    try {
      const r = await proposals.auto("2024-W01");
      setResult(r);
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mt-3 pt-3 border-t border-[var(--border)]/60">
      <button
        onClick={fire}
        disabled={loading}
        className="px-3 py-1.5 text-xs rounded-md bg-[var(--primary)] text-white font-medium disabled:opacity-50"
      >
        {loading ? "Filing…" : "File top insight as Proposal"}
      </button>
      {result && result.filed && (
        <div className="mt-3 text-[11px]">
          <Badge variant="outline" className="bg-emerald-500/20 text-emerald-300 border-emerald-500/30">
            ✓ Filed {result.proposal_id}
          </Badge>
          <div className="mt-2 text-[var(--foreground)]">{result.insight?.summary}</div>
          <div className="mt-1 text-[var(--muted-foreground)]">
            Approve at <Link className="text-[var(--primary)] hover:underline" href="/proposals">/proposals</Link> to fire the experiment.
          </div>
        </div>
      )}
      {result && !result.filed && (
        <div className="mt-3 text-[11px] text-[var(--muted-foreground)]">
          Not filed: {result.reason}
        </div>
      )}
      {err && <div className="mt-3 text-[11px] text-red-400 mono">{err}</div>}
    </div>
  );
}
