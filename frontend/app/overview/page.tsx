"use client";

import { Badge, Card, CardContent, CardHeader, CardTitle, HintIcon, KpiTile } from "@/components/ui";
import { evalApi, llm, metrics, sim, EvalRun, Kpis, MetricResult } from "@/lib/api";
import { METRICS } from "@/lib/glossary";
import { useEffect, useState } from "react";

export default function OverviewPage() {
  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [evalRun, setEvalRun] = useState<EvalRun | null>(null);
  const [divergence, setDivergence] = useState<MetricResult | null>(null);
  const [aiContent, setAiContent] = useState<MetricResult | null>(null);
  const [preIpo, setPreIpo] = useState<MetricResult | null>(null);
  const [concentration, setConcentration] = useState<MetricResult | null>(null);
  const [cascadeLift, setCascadeLift] = useState<MetricResult | null>(null);

  useEffect(() => {
    sim.kpis().then(setKpis).catch(() => {});
    evalApi.latest().then(setEvalRun).catch(() => {});
    metrics.invoke("call_consensus_divergence", { week_of: "2024-W01" }).then(setDivergence).catch(() => {});
    metrics.invoke("ai_content_flagged_share", {}).then(setAiContent).catch(() => {});
    metrics.invoke("pre_ipo_call_interest", { week_of: "2024-W01" }).then(setPreIpo).catch(() => {});
    metrics.invoke("behavioral_concentration_index", { week_of: "2024-W01" }).then(setConcentration).catch(() => {});
    metrics.invoke("cascade_followon_lift", { week_of: "2024-W01" }).then(setCascadeLift).catch(() => {});
  }, []);

  return (
    <div className="px-8 py-7 max-w-[1400px] mx-auto">
      <header className="mb-6">
        <div className="text-xs font-medium tracking-widest text-[var(--muted-foreground)] uppercase">Overview</div>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Substrate at a glance</h1>
        <p className="mt-1 text-sm text-[var(--muted-foreground)] max-w-2xl">
          Four headline KPIs from the live warehouse, the three baked visualisations, and the latest eval score.
        </p>
      </header>

      <div className="grid grid-cols-4 gap-4 mb-6">
        <KpiTile
          label="Ghost rate (Unstop)"
          value={kpis ? `${(kpis.ghost_rate_unstop.value * 100).toFixed(1)}%` : ""}
          tone={kpis && kpis.ghost_rate_unstop.value > 0.3 ? "bad" : "neutral"}
          delta={kpis ? `confidence ${kpis.ghost_rate_unstop.confidence.toFixed(2)}` : undefined}
        />
        <KpiTile
          label="Dark fraction"
          value={kpis ? `${(kpis.dark_fraction.value * 100).toFixed(1)}%` : ""}
        />
        <KpiTile
          label="Latest eval"
          value={evalRun ? `${evalRun.total_score} / ${evalRun.max_total}` : ""}
        />
        <KpiTile
          label="Personas resolved"
          value={kpis ? (2000 + kpis.sim_personas_new).toLocaleString() : ""}
          hint="baseline + sim joiners"
        />
      </div>

      <div className="grid grid-cols-2 gap-5 mb-5">
        <Card>
          <CardHeader><CardTitle>Call calibration</CardTitle></CardHeader>
          <CardContent>
            <img src={llm.asset("calibration_curve.png")} alt="calibration" className="rounded-md w-full" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Agent eval scorecard</CardTitle></CardHeader>
          <CardContent>
            <img src={llm.asset("eval_scorecard.png")} alt="scorecard" className="rounded-md w-full" />
          </CardContent>
        </Card>
      </div>

      <div className="mb-5">
        <div className="text-xs font-medium tracking-widest text-[var(--muted-foreground)] uppercase mb-3">Product surfaces</div>
        <div className="grid grid-cols-3 gap-4">
          <ProductCard
            title="Call consensus divergence"
            valueText={divergence ? `${(divergence.value * 100).toFixed(1)}%` : ""}
            subtitle={divergence ? `${divergence.sample_n} tickers, conf ${divergence.confidence.toFixed(2)}` : "loading"}
            hint={METRICS.call_consensus_divergence.long || METRICS.call_consensus_divergence.short}
            body={divergence?.interpretation || "Feed-weighting signal: how far is retail BULL consensus from outcome reality?"}
            badge={divergence && divergence.breakdowns ? (() => {
              const entries: any[] = Object.entries(divergence.breakdowns as any);
              if (entries.length === 0) return null;
              const worst = entries.reduce((a, b) => (a[1].divergence > b[1].divergence ? a : b));
              return `worst: ${worst[0]} (${(Number(worst[1].divergence) * 100).toFixed(0)}pp gap)`;
            })() : null}
          />
          <ProductCard
            title="AI-content flagged share"
            valueText={aiContent ? `${(aiContent.value * 100).toFixed(1)}%` : ""}
            subtitle={aiContent ? `n=${aiContent.sample_n} sampled, FPR ${((aiContent.breakdowns as any)?.false_positive_rate * 100 || 0).toFixed(1)}%` : "loading"}
            hint={METRICS.ai_content_flagged_share.long || METRICS.ai_content_flagged_share.short}
            body={aiContent?.interpretation || "Content-policy surface: shadow-mode detector for AI-authored analysis posts."}
            badge="shadow mode"
            tone="info"
          />
          <ProductCard
            title="Pre-IPO call interest"
            valueText={preIpo ? `${(preIpo.value * 100).toFixed(1)}%` : ""}
            subtitle={preIpo ? `${preIpo.sample_n.toLocaleString()} W01 calls` : "loading"}
            hint={METRICS.pre_ipo_call_interest.long || METRICS.pre_ipo_call_interest.short}
            body={preIpo?.interpretation || "Pre-IPO tray engagement, a leading indicator on tray-positioning decisions."}
            badge={preIpo && preIpo.breakdowns ? (() => {
              const entries: any[] = Object.entries(preIpo.breakdowns as any);
              if (entries.length === 0) return null;
              const top = entries.sort((a, b) => Number(b[1]) - Number(a[1]))[0];
              return `top: ${top[0]} (${top[1]} calls)`;
            })() : null}
          />
        </div>
      </div>

      <div className="mb-5">
        <div className="text-xs font-medium tracking-widest text-[var(--muted-foreground)] uppercase mb-3">Consumer behavior</div>
        <div className="grid grid-cols-2 gap-4">
          <ProductCard
            title="Behavioral concentration"
            valueText={concentration ? concentration.value.toFixed(2) : ""}
            subtitle={concentration ? `${concentration.sample_n} users, mean ${((concentration.breakdowns as any)?.mean_distinct || 0).toFixed(1)} tickers each` : "loading"}
            hint={METRICS.behavioral_concentration_index.long || METRICS.behavioral_concentration_index.short}
            body={concentration?.interpretation || "Mean per-user Herfindahl on ticker distribution. Typical retail lands 0.35-0.55."}
            badge={concentration && (concentration.breakdowns as any)?.buckets ? (() => {
              const b: any = (concentration.breakdowns as any).buckets;
              return `${b.concentrated_0_75_plus} concentrated · ${b.exploratory_under_0_25} exploring`;
            })() : null}
          />
          <ProductCard
            title="Cascade follow-on lift"
            valueText={cascadeLift ? `${cascadeLift.value.toFixed(2)}x` : ""}
            subtitle={cascadeLift ? `${cascadeLift.sample_n} cascades, last 7d sim` : "no cascades yet"}
            hint={METRICS.cascade_followon_lift.long || METRICS.cascade_followon_lift.short}
            body={cascadeLift?.interpretation || "Ratio of post-cascade call rate to baseline on the same ticker. Lift > 1 = organic FOMO follow-on."}
            badge={cascadeLift && cascadeLift.value > 1.5 ? "strong follow-on" : cascadeLift && cascadeLift.value > 1 ? "mild follow-on" : null}
            tone="info"
          />
        </div>
      </div>

      <Card>
        <CardHeader><CardTitle>Dashboard mosaic. Four panels, live</CardTitle></CardHeader>
        <CardContent>
          <img src={llm.asset("dashboard_mosaic.png")} alt="mosaic" className="rounded-md w-full" />
        </CardContent>
      </Card>
    </div>
  );
}

function ProductCard({ title, valueText, subtitle, hint, body, badge, tone = "neutral" }: {
  title: string;
  valueText: string;
  subtitle: string;
  hint: string;
  body: string;
  badge?: string | null;
  tone?: "neutral" | "info";
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between">
          <CardTitle className="text-sm font-medium">
            {title}
            <HintIcon content={hint} />
          </CardTitle>
          {badge && <Badge variant={tone === "info" ? "info" : "outline"} className="text-[10px] shrink-0">{badge}</Badge>}
        </div>
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-semibold tabular-nums tracking-tight">{valueText || "."}</div>
        <div className="text-[11px] text-[var(--muted-foreground)] mono mt-1">{subtitle}</div>
        <p className="text-xs text-[var(--muted-foreground)] mt-3 leading-relaxed">{body}</p>
      </CardContent>
    </Card>
  );
}
