"use client";

import { Badge, Button, Card, CardContent, CardHeader, CardTitle, KpiTile, Separator, Spinner } from "@/components/ui";
import { Kpis, SimEvent, openSimEventsWS, sim } from "@/lib/api";
import { useEffect, useRef, useState } from "react";

const LENS_OPTIONS = [
  { id: "all", label: "All" },
  { id: "growth", label: "Growth" },
  { id: "cs", label: "CS" },
];

export default function LivingWorldPage() {
  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [events, setEvents] = useState<SimEvent[]>([]);
  const [lens, setLens] = useState<"all" | "growth" | "cs">("all");
  const [busy, setBusy] = useState(false);
  const [bgOn, setBgOn] = useState(false);
  const bgTimerRef = useRef<any>(null);

  async function loadAll() {
    const [k, e] = await Promise.all([
      sim.kpis(),
      sim.events(lens === "all" ? undefined : lens, 40),
    ]);
    setKpis(k);
    setEvents(e);
  }

  useEffect(() => { loadAll(); }, [lens]);

  // WebSocket — prepend incoming events.
  useEffect(() => {
    const ws = openSimEventsWS((evt) => {
      if (lens !== "all" && evt.lens !== lens && evt.lens !== "all") return;
      setEvents((prev) => [evt, ...prev].slice(0, 80));
    });
    return () => { ws.close(); };
  }, [lens]);

  // Background tick loop.
  useEffect(() => {
    if (bgOn) {
      bgTimerRef.current = setInterval(async () => {
        try {
          await sim.tick(60);
          await loadAll();
        } catch {}
      }, 2200);
    } else if (bgTimerRef.current) {
      clearInterval(bgTimerRef.current);
      bgTimerRef.current = null;
    }
    return () => { if (bgTimerRef.current) clearInterval(bgTimerRef.current); };
  }, [bgOn, lens]);

  async function doTick(minutes: number) {
    setBusy(true);
    try { await sim.tick(minutes); await loadAll(); } finally { setBusy(false); }
  }
  async function doReset() {
    setBusy(true);
    try { await sim.reset(); await loadAll(); } finally { setBusy(false); }
  }

  return (
    <div className="px-8 py-7 max-w-[1400px] mx-auto">
      <header className="flex items-start justify-between gap-6 mb-6">
        <div>
          <div className="text-xs font-medium tracking-widest text-[var(--muted-foreground)] uppercase">
            Living world
          </div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">The W01 cohort, in motion</h1>
          <p className="mt-1 text-sm text-[var(--muted-foreground)] max-w-2xl">
            Click a tick to advance synthetic time. Personas join, predict, ghost. Outcomes resolve at T+5d.
            Watchers fire when signals move. Two lenses isolate Growth vs CS concerns over the same substrate.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className={`h-2 w-2 rounded-full ${bgOn ? "bg-emerald-400 pulse-dot" : "bg-[var(--muted-foreground)]"}`}/>
          <span className="text-xs text-[var(--muted-foreground)]">{bgOn ? "live" : "paused"}</span>
        </div>
      </header>

      <Card className="mb-6">
        <CardContent className="p-5">
          <div className="flex flex-wrap items-center gap-5">
            <div>
              <div className="text-xs uppercase tracking-wider text-[var(--muted-foreground)]">Sim time</div>
              <div className="mono text-base mt-0.5">
                {kpis ? new Date(kpis.sim_now).toUTCString().replace(" GMT", "") : "—"}
              </div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wider text-[var(--muted-foreground)]">Tick #</div>
              <div className="mono text-base mt-0.5">{kpis?.tick_count ?? 0}</div>
            </div>
            <Separator className="!h-8 !w-px mx-2" />
            <div className="flex items-center gap-1">
              {LENS_OPTIONS.map((opt) => (
                <Button
                  key={opt.id}
                  variant={lens === opt.id ? "default" : "ghost"}
                  size="sm"
                  onClick={() => setLens(opt.id as any)}
                >
                  {opt.label}
                </Button>
              ))}
            </div>
            <Separator className="!h-8 !w-px mx-2" />
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" disabled={busy} onClick={() => doTick(60)}>Advance 1 hour</Button>
              <Button variant="secondary" disabled={busy} onClick={() => doTick(60 * 24)}>Advance 1 day</Button>
              <Button variant={bgOn ? "destructive" : "outline"} onClick={() => setBgOn((b) => !b)}>
                Background: {bgOn ? "ON" : "OFF"}
              </Button>
              <Button variant="outline" disabled={busy} onClick={doReset}>Reset to W01</Button>
              {busy && <Spinner />}
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-4 gap-4 mb-6">
        {kpis ? (
          lens === "cs" ? (
            <>
              <KpiTile label="At-risk users (3d quiet)" value={kpis.at_risk_3d.toLocaleString()} />
              <KpiTile label="Outcomes resolved (24h)" value={kpis.outcomes_resolved_24h.toLocaleString()} />
              <KpiTile
                label="Ghost rate (Unstop)"
                value={`${(kpis.ghost_rate_unstop.value * 100).toFixed(1)}%`}
                tone={kpis.ghost_rate_unstop.value > 0.3 ? "bad" : "neutral"}
                delta={`conf ${kpis.ghost_rate_unstop.confidence.toFixed(2)} · n ${kpis.ghost_rate_unstop.sample_n}`}
              />
              <KpiTile
                label="Dark channel fraction"
                value={`${(kpis.dark_fraction.value * 100).toFixed(1)}%`}
                hint="floor on attribution uncertainty"
              />
            </>
          ) : (
            <>
              <KpiTile
                label="Ghost rate (Unstop)"
                value={`${(kpis.ghost_rate_unstop.value * 100).toFixed(1)}%`}
                tone={kpis.ghost_rate_unstop.value > 0.3 ? "bad" : "neutral"}
                delta={`conf ${kpis.ghost_rate_unstop.confidence.toFixed(2)} · n ${kpis.ghost_rate_unstop.sample_n}`}
              />
              <KpiTile label="Dark fraction" value={`${(kpis.dark_fraction.value * 100).toFixed(1)}%`} hint="bounded CAC unknown" />
              <KpiTile label="New personas (sim)" value={kpis.sim_personas_new.toLocaleString()} />
              <KpiTile label="Predictions last 24h (sim)" value={kpis.sim_preds_24h.toLocaleString()} />
            </>
          )
        ) : (
          [0, 1, 2, 3].map((i) => (
            <Card key={i}>
              <CardHeader><CardTitle>—</CardTitle></CardHeader>
              <CardContent><div className="h-8 bg-[var(--muted)] rounded animate-pulse" /></CardContent>
            </Card>
          ))
        )}
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Event stream</CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant="info">{events.length} events</Badge>
            <Badge variant="outline">lens: {lens}</Badge>
          </div>
        </CardHeader>
        <CardContent>
          {events.length === 0 ? (
            <div className="text-sm text-[var(--muted-foreground)] py-6 text-center">
              No events yet — click <span className="font-medium">Advance 1 hour</span> to start the world.
            </div>
          ) : (
            <div className="mono text-[12px] max-h-[480px] overflow-auto divide-y divide-[var(--border)]">
              {events.map((evt) => <EventRow key={evt.event_id} evt={evt} />)}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function EventRow({ evt }: { evt: SimEvent }) {
  const tone =
    evt.kind === "growth_watcher_fired" ? "warning" :
    evt.kind === "cs_watcher_fired" ? "warning" :
    evt.kind === "outcome_resolved" ? "success" :
    evt.kind === "persona_joined" ? "info" :
    "default";
  const ts = evt.sim_ts ? new Date(evt.sim_ts).toISOString().slice(5, 16).replace("T", " ") : "";
  const summary = Object.entries(evt.payload || {})
    .slice(0, 3)
    .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`)
    .join(" · ");
  return (
    <div className="py-1.5 flex items-center gap-3 slide-in">
      <span className="text-[var(--muted-foreground)] tabular-nums">{ts}</span>
      <Badge variant={tone as any} className="min-w-[80px] justify-center">{evt.lens}</Badge>
      <span className="font-medium min-w-[200px]">{evt.kind}</span>
      <span className="text-[var(--muted-foreground)] truncate flex-1">{summary}</span>
    </div>
  );
}
