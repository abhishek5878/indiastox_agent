"use client";

import { Card, CardContent, CardHeader, CardTitle, KpiTile } from "@/components/ui";
import { evalApi, llm, sim, EvalRun, Kpis } from "@/lib/api";
import { useEffect, useState } from "react";

export default function OverviewPage() {
  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [evalRun, setEvalRun] = useState<EvalRun | null>(null);

  useEffect(() => {
    sim.kpis().then(setKpis).catch(() => {});
    evalApi.latest().then(setEvalRun).catch(() => {});
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
          value={kpis ? `${(kpis.ghost_rate_unstop.value * 100).toFixed(1)}%` : "—"}
          tone={kpis && kpis.ghost_rate_unstop.value > 0.3 ? "bad" : "neutral"}
          delta={kpis ? `confidence ${kpis.ghost_rate_unstop.confidence.toFixed(2)}` : undefined}
        />
        <KpiTile
          label="Dark fraction"
          value={kpis ? `${(kpis.dark_fraction.value * 100).toFixed(1)}%` : "—"}
        />
        <KpiTile
          label="Latest eval"
          value={evalRun ? `${evalRun.total_score} / ${evalRun.max_total}` : "—"}
        />
        <KpiTile
          label="Personas resolved"
          value={kpis ? (2000 + kpis.sim_personas_new).toLocaleString() : "—"}
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

      <Card>
        <CardHeader><CardTitle>Dashboard mosaic — four panels, live</CardTitle></CardHeader>
        <CardContent>
          <img src={llm.asset("dashboard_mosaic.png")} alt="mosaic" className="rounded-md w-full" />
        </CardContent>
      </Card>
    </div>
  );
}
