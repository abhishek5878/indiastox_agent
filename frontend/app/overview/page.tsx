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
  const [influence, setInfluence] = useState<MetricResult | null>(null);
  const [disengagement, setDisengagement] = useState<MetricResult | null>(null);
  const [reasons, setReasons] = useState<{ reason: string; n: number }[]>([]);

  useEffect(() => {
    sim.kpis().then(setKpis).catch(() => {});
    evalApi.latest().then(setEvalRun).catch(() => {});
    metrics.invoke("call_consensus_divergence", { week_of: "2024-W01" }).then(setDivergence).catch(() => {});
    metrics.invoke("ai_content_flagged_share", {}).then(setAiContent).catch(() => {});
    metrics.invoke("pre_ipo_call_interest", { week_of: "2024-W01" }).then(setPreIpo).catch(() => {});
    metrics.invoke("behavioral_concentration_index", { week_of: "2024-W01" }).then(setConcentration).catch(() => {});
    metrics.invoke("cascade_followon_lift", { week_of: "2024-W01" }).then(setCascadeLift).catch(() => {});
    metrics.invoke("gyaani_influence_index", { week_of: "2024-W01" }).then(setInfluence).catch(() => {});
    metrics.invoke("user_disengagement_rate", {}).then(setDisengagement).catch(() => {});
    sim.reasons().then(setReasons).catch(() => {});
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
        <div className="grid grid-cols-4 gap-4 mb-4">
          <ProductCard
            title="Behavioral concentration"
            valueText={concentration ? concentration.value.toFixed(2) : ""}
            subtitle={concentration ? `${concentration.sample_n} users, ${((concentration.breakdowns as any)?.mean_distinct || 0).toFixed(1)} tickers` : "loading"}
            hint={METRICS.behavioral_concentration_index.long || METRICS.behavioral_concentration_index.short}
            body={concentration?.interpretation || "Mean per-user Herfindahl on ticker distribution. Typical retail lands 0.35-0.55."}
            badge={concentration && (concentration.breakdowns as any)?.buckets ? (() => {
              const b: any = (concentration.breakdowns as any).buckets;
              return `${b.concentrated_0_75_plus}c · ${b.exploratory_under_0_25}e`;
            })() : null}
          />
          <ProductCard
            title="Cascade follow-on"
            valueText={cascadeLift ? `${cascadeLift.value.toFixed(2)}x` : ""}
            subtitle={cascadeLift ? `${cascadeLift.sample_n} cascades · 7d` : "no cascades yet"}
            hint={METRICS.cascade_followon_lift.long || METRICS.cascade_followon_lift.short}
            body={cascadeLift?.interpretation || "Post-cascade call rate vs baseline. Lift > 1 = organic FOMO follow-on."}
            badge={cascadeLift && cascadeLift.value > 1.5 ? "strong" : cascadeLift && cascadeLift.value > 1 ? "mild" : null}
            tone="info"
          />
          <ProductCard
            title="Gyaani influence"
            valueText={influence ? `${(influence.value * 100).toFixed(1)}%` : ""}
            subtitle={influence ? `${influence.sample_n} calls in window` : "no sim data yet"}
            hint={METRICS.gyaani_influence_index.long || METRICS.gyaani_influence_index.short}
            body={influence?.interpretation || "Share of calls placed via social-proof shadowing of high-Gyaani users."}
            badge={influence && influence.value > 0.05 ? "leaders move cohort" : influence && influence.value > 0 ? "modest shadow" : null}
            tone="info"
          />
          <ProductCard
            title="Disengagement rate"
            valueText={disengagement ? `${(disengagement.value * 100).toFixed(1)}%` : ""}
            subtitle={disengagement ? `${((disengagement.breakdowns as any)?.ghosted || 0).toLocaleString()} ghosted · ${((disengagement.breakdowns as any)?.active_7d || 0).toLocaleString()} active` : "loading"}
            hint={METRICS.user_disengagement_rate.long || METRICS.user_disengagement_rate.short}
            body={disengagement?.interpretation || "Share of users 5+ sim-days quiet. The CS agent's re-engagement target pool."}
            badge={disengagement && disengagement.value > 0.3 ? "cs target pool" : null}
            tone="info"
          />
        </div>
        <BehaviorFingerprint reasons={reasons} />
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

const REASON_LABELS: Record<string, string> = {
  sector_affinity: "Sector affinity (occupation bias)",
  watchlist: "Watchlist (returns to top-5)",
  fomo_followon: "FOMO follow-on (cascade echo)",
  social_proof: "Social proof (shadowing Gyaani leaders)",
  anchor: "Anchor (back to first call)",
  loss_aversion: "Loss aversion (revenge re-call)",
  wildcard: "Wildcard (uniform pick)",
  unknown: "Unattributed",
};

const REASON_COLORS: Record<string, string> = {
  sector_affinity: "bg-[var(--primary)]",
  watchlist: "bg-emerald-500/80",
  fomo_followon: "bg-amber-500/80",
  social_proof: "bg-fuchsia-500/80",
  anchor: "bg-cyan-500/80",
  loss_aversion: "bg-red-500/80",
  wildcard: "bg-[var(--muted-foreground)]/60",
  unknown: "bg-[var(--muted-foreground)]/30",
};

function BehaviorFingerprint({ reasons }: { reasons: { reason: string; n: number }[] }) {
  const total = reasons.reduce((acc, r) => acc + r.n, 0);
  if (total === 0) {
    return (
      <Card>
        <CardHeader><CardTitle className="text-sm font-medium">Behavior fingerprint</CardTitle></CardHeader>
        <CardContent>
          <div className="text-xs text-[var(--muted-foreground)] py-4 text-center">
            Tick the world (head to /) to populate the call-reason distribution.
          </div>
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium">
          Behavior fingerprint
          <HintIcon content={"Distribution of WHY each call was placed. Each call's reason is set by sim.world._ticker_for_user and stored in the prediction_made payload. Read this as the shape of the cohort's habits."} />
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {reasons.map((r) => {
            const pct = (r.n / total) * 100;
            return (
              <div key={r.reason} className="text-xs">
                <div className="flex justify-between mb-1">
                  <span>{REASON_LABELS[r.reason] || r.reason}</span>
                  <span className="text-[var(--muted-foreground)] mono">{r.n} · {pct.toFixed(1)}%</span>
                </div>
                <div className="h-2 bg-[var(--muted)] rounded overflow-hidden">
                  <div
                    className={`h-full ${REASON_COLORS[r.reason] || "bg-[var(--muted-foreground)]/40"}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
        <div className="mt-3 text-[11px] text-[var(--muted-foreground)] mono">total: {total.toLocaleString()} calls</div>
      </CardContent>
    </Card>
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
