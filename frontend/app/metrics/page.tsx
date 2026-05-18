"use client";

import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Spinner } from "@/components/ui";
import { metrics, MetricResult, ToolMeta } from "@/lib/api";
import { useEffect, useState } from "react";

export default function MetricsPage() {
  const [tools, setTools] = useState<ToolMeta[]>([]);
  const [selected, setSelected] = useState<string>("ghost_rate");
  const [args, setArgs] = useState<Record<string, string>>({});
  const [result, setResult] = useState<MetricResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    metrics.list().then((ts) => {
      setTools(ts);
      const cur = ts.find((t) => t.name === selected) || ts[0];
      if (cur) {
        setSelected(cur.name);
        const init: Record<string, string> = {};
        for (const p of cur.params) init[p.name] = p.default == null ? "" : String(p.default);
        setArgs(init);
      }
    });
  }, []);

  function pickTool(name: string) {
    setSelected(name);
    setResult(null);
    setErr(null);
    const tool = tools.find((t) => t.name === name);
    const init: Record<string, string> = {};
    if (tool) for (const p of tool.params) init[p.name] = p.default == null ? "" : String(p.default);
    setArgs(init);
  }

  async function run() {
    setBusy(true);
    setErr(null);
    try {
      const tool = tools.find((t) => t.name === selected);
      const typed: Record<string, any> = {};
      for (const p of tool?.params || []) {
        const v = args[p.name];
        if (v === "" || v == null) continue;
        if (p.type === "number") typed[p.name] = parseFloat(v);
        else if (p.type === "integer") typed[p.name] = parseInt(v, 10);
        else if (p.type === "boolean") typed[p.name] = v.toLowerCase() === "true";
        else typed[p.name] = v;
      }
      const r = await metrics.invoke(selected, typed);
      setResult(r);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  const tool = tools.find((t) => t.name === selected);

  return (
    <div className="px-8 py-7 max-w-[1400px] mx-auto">
      <header className="mb-6">
        <div className="text-xs font-medium tracking-widest text-[var(--muted-foreground)] uppercase">Metric explorer</div>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">12 tools. One contract.</h1>
        <p className="mt-1 text-sm text-[var(--muted-foreground)] max-w-2xl">
          Every metric returns the same typed MetricResult. Bare floats from tools raise TypeError at runtime.
        </p>
      </header>

      <div className="grid grid-cols-[280px,1fr] gap-5">
        <Card>
          <CardHeader><CardTitle>Tools</CardTitle></CardHeader>
          <CardContent className="p-2">
            <div className="space-y-0.5">
              {tools.map((t) => (
                <button
                  key={t.name}
                  onClick={() => pickTool(t.name)}
                  className={`w-full text-left rounded-md px-2 py-1.5 text-sm transition-colors mono ${
                    selected === t.name
                      ? "bg-[var(--accent)] text-[var(--foreground)]"
                      : "text-[var(--muted-foreground)] hover:bg-[var(--accent)]/50"
                  }`}
                >
                  {t.name}
                </button>
              ))}
            </div>
          </CardContent>
        </Card>

        <div className="space-y-5">
          <Card>
            <CardHeader>
              <CardTitle>{selected}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-[var(--muted-foreground)] mb-4">{tool?.description}</p>
              <div className="grid grid-cols-2 gap-3">
                {tool?.params.map((p) => (
                  <label key={p.name} className="block">
                    <span className="text-xs text-[var(--muted-foreground)]">{p.name} <span className="opacity-60">({p.type})</span></span>
                    <Input
                      className="mt-1"
                      value={args[p.name] ?? ""}
                      placeholder={p.default == null ? "" : String(p.default)}
                      onChange={(e) => setArgs({ ...args, [p.name]: e.target.value })}
                    />
                  </label>
                ))}
              </div>
              <div className="mt-4 flex gap-2">
                <Button onClick={run} disabled={busy}>{busy ? <Spinner /> : "Run"}</Button>
                {err && <Badge variant="destructive">{err}</Badge>}
              </div>
            </CardContent>
          </Card>

          {result && (
            <Card>
              <CardHeader>
                <CardTitle>Result, {result.metric_name} <span className="opacity-60 mono">({result.definition_version})</span></CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-4 gap-4 mb-4">
                  <Stat label="value" value={typeof result.value === "number" ? result.value.toFixed(4) : String(result.value)} />
                  <Stat label="confidence" value={result.confidence.toFixed(2)} />
                  <Stat label="sample_n" value={result.sample_n.toLocaleString()} />
                  <Stat label="window_open" value={String(result.window_open)} />
                </div>
                <div className="bg-[var(--muted)] rounded-md p-3 text-sm mb-4">
                  {result.interpretation}
                </div>
                <div className="mb-4">
                  <div className="text-xs font-semibold tracking-widest text-[var(--muted-foreground)] uppercase mb-2">Why this number?</div>
                  <ol className="space-y-1.5">
                    {result.trace.map((step, i) => (
                      <li key={i} className="text-sm flex gap-3">
                        <span className="text-[var(--muted-foreground)] mono w-4">[{i + 1}]</span>
                        <span>{step}</span>
                      </li>
                    ))}
                  </ol>
                </div>
                <details>
                  <summary className="text-xs text-[var(--muted-foreground)] cursor-pointer">Provenance + audit</summary>
                  <div className="mt-2 mono text-[11px] space-y-1 text-[var(--muted-foreground)]">
                    <div>definition_hash: {result.definition_hash.slice(0, 16)}…</div>
                    <div>audit_session: {result.session_id}</div>
                    {result.provenance.map((p, i) => <div key={i}>{p}</div>)}
                  </div>
                </details>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider">{label}</div>
      <div className="mono text-base mt-0.5">{value}</div>
    </div>
  );
}
