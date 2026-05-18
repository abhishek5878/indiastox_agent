"use client";

import { Badge, Button, Card, CardContent, CardHeader, CardTitle, KpiTile } from "@/components/ui";
import { Kpis, SimEvent, openSimEventsWS, sim } from "@/lib/api";
import { useEffect, useRef, useState } from "react";

const LENS_OPTIONS = [
  { id: "all", label: "Everything" },
  { id: "growth", label: "Growth lens" },
  { id: "cs", label: "CS lens" },
];

export default function LivingWorldPage() {
  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [events, setEvents] = useState<SimEvent[]>([]);
  const [lens, setLens] = useState<"all" | "growth" | "cs">("all");
  const [busy, setBusy] = useState(false);
  const [paused, setPaused] = useState(false);
  const [primed, setPrimed] = useState(false);
  const bgTimerRef = useRef<any>(null);
  const pollRef = useRef<any>(null);

  async function loadAll() {
    try {
      const [k, e] = await Promise.all([
        sim.kpis(),
        sim.events(lens === "all" ? undefined : lens, 40),
      ]);
      setKpis(k);
      setEvents(e);
    } catch {}
  }

  useEffect(() => { loadAll(); }, [lens]);

  // First-visit prime: run 3 quick ticks so the page has a story
  // before the user touches anything. Idempotent (guarded by `primed`).
  useEffect(() => {
    (async () => {
      if (primed) return;
      const k = await sim.kpis().catch(() => null);
      if (k && k.tick_count < 3) {
        for (let i = 0; i < 3; i++) {
          try { await sim.tick(60); } catch {}
        }
      }
      setPrimed(true);
      await loadAll();
    })();
  }, []);

  // WebSocket — prepend incoming events.
  useEffect(() => {
    const ws = openSimEventsWS((evt) => {
      if (lens !== "all" && evt.lens !== lens && evt.lens !== "all") return;
      setEvents((prev) => {
        if (prev.some((e) => e.event_id === evt.event_id)) return prev;
        return [evt, ...prev].slice(0, 80);
      });
    });
    return () => { ws.close(); };
  }, [lens]);

  // Live world: tick every 2.5s unless paused.
  useEffect(() => {
    if (!paused) {
      bgTimerRef.current = setInterval(async () => {
        try { await sim.tick(60); } catch {}
      }, 2500);
    }
    return () => { if (bgTimerRef.current) { clearInterval(bgTimerRef.current); bgTimerRef.current = null; } };
  }, [paused]);

  // KPI poll every 4s independent of tick loop so paused state still refreshes.
  useEffect(() => {
    pollRef.current = setInterval(() => { loadAll(); }, 4000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [lens]);

  async function doTick(minutes: number) {
    setBusy(true);
    try { await sim.tick(minutes); await loadAll(); } finally { setBusy(false); }
  }
  async function doReset() {
    setBusy(true);
    try { await sim.reset(); setEvents([]); await loadAll(); } finally { setBusy(false); }
  }

  const simWhen = kpis ? new Date(kpis.sim_now) : null;
  const simWhenStr = simWhen ? simWhen.toUTCString().replace(" GMT", "").replace(/^[A-Z][a-z]{2}, /, "") : "—";

  return (
    <div className="px-8 py-7 max-w-[1400px] mx-auto">
      <header className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <div className={`h-2.5 w-2.5 rounded-full ${paused ? "bg-amber-400" : "bg-emerald-400 pulse-dot"}`} />
          <div className="text-xs font-medium tracking-widest text-[var(--muted-foreground)] uppercase">
            {paused ? "Paused" : "Live · sim time advances every 2.5s"}
          </div>
          <span className="text-xs text-[var(--muted-foreground)] mono ml-auto">{simWhenStr} · tick #{kpis?.tick_count ?? 0}</span>
        </div>
        <h1 className="text-3xl font-semibold tracking-tight">The W01 cohort, in motion.</h1>
        <p className="mt-2 text-sm text-[var(--muted-foreground)] max-w-3xl leading-relaxed">
          A synthetic world running on the same agent-native substrate the real product would use. Personas join,
          predict, and ghost; outcomes resolve at T+5d; watchers fire when signals move. Switch lenses to see Growth
          vs CS reading the same event stream.
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-2 mb-6">
        {LENS_OPTIONS.map((opt) => (
          <button
            key={opt.id}
            onClick={() => setLens(opt.id as any)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
              lens === opt.id
                ? "bg-[var(--primary)] text-white"
                : "bg-[var(--muted)] text-[var(--muted-foreground)] hover:bg-[var(--accent)]"
            }`}
          >
            {opt.label}
          </button>
        ))}
        <div className="flex-1" />
        <Button variant="ghost" size="sm" disabled={busy} onClick={() => doTick(60 * 24)}>+1 day</Button>
        <Button variant={paused ? "default" : "outline"} size="sm" onClick={() => setPaused((p) => !p)}>
          {paused ? "Resume" : "Pause"}
        </Button>
        <Button variant="ghost" size="sm" disabled={busy} onClick={doReset}>Reset</Button>
      </div>

      <div className="grid grid-cols-4 gap-4 mb-6">
        {kpis ? (
          lens === "cs" ? (
            <>
              <KpiTile label="At-risk (3d silent)" value={kpis.at_risk_3d.toLocaleString()} tone={kpis.at_risk_3d > 800 ? "bad" : "neutral"} />
              <KpiTile label="Outcomes resolved (24h)" value={kpis.outcomes_resolved_24h.toLocaleString()} />
              <KpiTile
                label="Ghost rate · Unstop"
                value={`${(kpis.ghost_rate_unstop.value * 100).toFixed(1)}%`}
                tone={kpis.ghost_rate_unstop.value > 0.3 ? "bad" : "neutral"}
                delta={`conf ${kpis.ghost_rate_unstop.confidence.toFixed(2)} · n=${kpis.ghost_rate_unstop.sample_n}`}
              />
              <KpiTile label="Dark fraction" value={`${(kpis.dark_fraction.value * 100).toFixed(1)}%`} hint="floor on attribution uncertainty" />
            </>
          ) : (
            <>
              <KpiTile
                label="Ghost rate · Unstop"
                value={`${(kpis.ghost_rate_unstop.value * 100).toFixed(1)}%`}
                tone={kpis.ghost_rate_unstop.value > 0.3 ? "bad" : "neutral"}
                delta={`conf ${kpis.ghost_rate_unstop.confidence.toFixed(2)} · n=${kpis.ghost_rate_unstop.sample_n}`}
              />
              <KpiTile label="Dark fraction" value={`${(kpis.dark_fraction.value * 100).toFixed(1)}%`} hint="bounded-CAC unknown" />
              <KpiTile label="New personas" value={kpis.sim_personas_new.toLocaleString()} hint="sim.world joiners" />
              <KpiTile label="Predictions · 24h" value={kpis.sim_preds_24h.toLocaleString()} hint="rolling synthetic day" />
            </>
          )
        ) : (
          [0, 1, 2, 3].map((i) => (
            <Card key={i}>
              <CardContent className="p-5">
                <div className="h-3 w-24 bg-[var(--muted)] rounded mb-3 animate-pulse" />
                <div className="h-8 w-16 bg-[var(--muted)] rounded animate-pulse" />
              </CardContent>
            </Card>
          ))
        )}
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-sm font-medium">Event stream</CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-[10px]">{events.length} events</Badge>
            <Badge variant="info" className="text-[10px]">lens · {lens}</Badge>
          </div>
        </CardHeader>
        <CardContent>
          {events.length === 0 ? (
            <div className="text-sm text-[var(--muted-foreground)] py-12 text-center">
              <div className="inline-block h-2 w-2 rounded-full bg-emerald-400 pulse-dot mr-2 align-middle" />
              Warming up the world — first personas arriving…
            </div>
          ) : (
            <div className="mono text-[12px] max-h-[520px] overflow-auto divide-y divide-[var(--border)]">
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
    .join("  ·  ");
  return (
    <div className="py-1.5 flex items-center gap-3 slide-in">
      <span className="text-[var(--muted-foreground)] tabular-nums w-[88px] shrink-0">{ts}</span>
      <Badge variant={tone as any} className="min-w-[70px] justify-center text-[10px]">{evt.lens}</Badge>
      <span className="font-medium min-w-[180px] shrink-0">{evt.kind}</span>
      <span className="text-[var(--muted-foreground)] truncate flex-1">{summary}</span>
    </div>
  );
}
