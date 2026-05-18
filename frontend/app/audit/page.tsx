"use client";

import { Card, CardContent, CardHeader, CardTitle, KpiTile } from "@/components/ui";
import { AuditSummary, audit } from "@/lib/api";
import { useEffect, useState } from "react";

export default function AuditPage() {
  const [days, setDays] = useState(7);
  const [s, setS] = useState<AuditSummary | null>(null);

  useEffect(() => { audit.summary(days).then(setS).catch(() => {}); }, [days]);

  const sev = s?.critique_severity || {};

  return (
    <div className="px-8 py-7 max-w-[1400px] mx-auto">
      <header className="flex items-end justify-between mb-6">
        <div>
          <div className="text-xs font-medium tracking-widest text-[var(--muted-foreground)] uppercase">Audit trail</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">Every tool call. Every agent. Append-only.</h1>
        </div>
        <div className="flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
          window:
          {[1, 7, 30].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-2 py-1 rounded ${days === d ? "bg-[var(--accent)] text-[var(--foreground)]" : "hover:bg-[var(--accent)]/50"}`}
            >
              {d}d
            </button>
          ))}
        </div>
      </header>

      <div className="grid grid-cols-4 gap-4 mb-5">
        <KpiTile label="Total tool calls" value={(s?.total_calls ?? 0).toLocaleString()} />
        <KpiTile label="Tools used" value={(s?.tools?.length ?? 0).toString()} />
        <KpiTile label="Sessions" value={(s?.top_sessions?.length ?? 0).toString()} />
        <KpiTile label="Severities (h/m/l)" value={`${sev.high ?? 0}/${sev.medium ?? 0}/${sev.low ?? 0}`} />
      </div>

      <div className="grid grid-cols-2 gap-5">
        <Card>
          <CardHeader><CardTitle>Tool-call frequency</CardTitle></CardHeader>
          <CardContent>
            {!s?.tools?.length ? <div className="text-sm text-[var(--muted-foreground)]">No tool calls in window.</div> : (
              <div className="space-y-1.5">
                {s.tools.map((t) => {
                  const pct = (t.n / s.total_calls) * 100;
                  return (
                    <div key={t.name} className="text-xs">
                      <div className="flex justify-between mono mb-0.5">
                        <span>{t.name}</span>
                        <span className="text-[var(--muted-foreground)]">{t.n} · conf {t.mean_conf.toFixed(2)}</span>
                      </div>
                      <div className="h-1.5 bg-[var(--muted)] rounded overflow-hidden">
                        <div className="h-full bg-[var(--primary)]" style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Proposal status</CardTitle></CardHeader>
          <CardContent>
            {!s?.proposal_status?.length ? <div className="text-sm text-[var(--muted-foreground)]">No proposals.</div> : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider">
                    <th className="text-left p-2">status</th>
                    <th className="text-right p-2">count</th>
                  </tr>
                </thead>
                <tbody>
                  {s.proposal_status.map((row: any) => (
                    <tr key={row.status} className="border-t border-[var(--border)]">
                      <td className="p-2">{row.status}</td>
                      <td className="p-2 text-right mono">{row.n}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      </div>

      {s?.top_sessions && s.top_sessions.length > 0 && (
        <Card className="mt-5">
          <CardHeader><CardTitle>Top sessions</CardTitle></CardHeader>
          <CardContent>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider">
                  <th className="text-left p-2">session</th>
                  <th className="text-right p-2">calls</th>
                  <th className="text-right p-2">tools</th>
                  <th className="text-left p-2">first</th>
                  <th className="text-left p-2">last</th>
                </tr>
              </thead>
              <tbody>
                {s.top_sessions.map((row: any) => (
                  <tr key={row.session_id} className="border-t border-[var(--border)]">
                    <td className="p-2 mono text-xs">{row.session_id}</td>
                    <td className="p-2 text-right mono">{row.n}</td>
                    <td className="p-2 text-right mono">{row.tool_variety}</td>
                    <td className="p-2 mono text-xs text-[var(--muted-foreground)]">{String(row.first_at).slice(0, 19)}</td>
                    <td className="p-2 mono text-xs text-[var(--muted-foreground)]">{String(row.last_at).slice(0, 19)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
