"use client";

import { Badge, Button, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { Proposal, proposals } from "@/lib/api";
import { useEffect, useState } from "react";

const STATUS_TABS = ["pending", "approved", "executed", "rejected"] as const;

export default function ProposalsPage() {
  const [items, setItems] = useState<Proposal[]>([]);
  const [status, setStatus] = useState<typeof STATUS_TABS[number]>("pending");
  const [busy, setBusy] = useState<string | null>(null);

  async function load() {
    setItems(await proposals.list(status));
  }
  useEffect(() => { load(); }, [status]);

  async function act(id: string, action: "approve" | "reject" | "execute") {
    setBusy(id);
    try {
      await proposals.act(id, action);
      await load();
    } finally { setBusy(null); }
  }

  return (
    <div className="px-8 py-7 max-w-[1400px] mx-auto">
      <header className="mb-6">
        <div className="text-xs font-medium tracking-widest text-[var(--muted-foreground)] uppercase">Proposals</div>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Critique-paired inbox</h1>
        <p className="mt-1 text-sm text-[var(--muted-foreground)] max-w-2xl">
          Every proposal lands with its strongest counter-argument inline. Approve only after reading the critique.
        </p>
      </header>

      <div className="flex gap-1 mb-5">
        {STATUS_TABS.map((s) => (
          <Button key={s} variant={status === s ? "default" : "ghost"} size="sm" onClick={() => setStatus(s)}>
            {s} ({items.filter((i) => i.status === s).length || (status === s ? items.length : "")})
          </Button>
        ))}
      </div>

      {items.length === 0 ? (
        <div className="text-sm text-[var(--muted-foreground)]">No {status} proposals.</div>
      ) : (
        <div className="space-y-4">
          {items.map((p) => <ProposalCard key={p.proposal_id} p={p} busy={busy === p.proposal_id} onAct={act} />)}
        </div>
      )}
    </div>
  );
}

function ProposalCard({ p, busy, onAct }: { p: Proposal; busy: boolean; onAct: (id: string, a: "approve" | "reject" | "execute") => void }) {
  const sev = p.critique?.severity || "low";
  const sevVariant = sev === "high" ? "destructive" : sev === "medium" ? "warning" : "default";
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <CardTitle>{p.proposal_id}</CardTitle>
            <Badge variant={sevVariant as any}>severity: {sev}</Badge>
            <Badge variant="outline">{p.status}</Badge>
            <Badge variant="info">{p.affected_metric}</Badge>
          </div>
          <p className="text-sm text-[var(--foreground)]">{p.hypothesis}</p>
        </div>
        {p.status === "pending" && (
          <div className="flex gap-2 shrink-0">
            <Button size="sm" disabled={busy} onClick={() => onAct(p.proposal_id, "approve")}>Approve</Button>
            <Button size="sm" variant="destructive" disabled={busy} onClick={() => onAct(p.proposal_id, "reject")}>Reject</Button>
          </div>
        )}
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-3 gap-4 text-xs mb-3">
          <Stat label="expected lift" value={`${p.expected_lift_pct.toFixed(1)}pp`} />
          <Stat label="required n" value={p.required_sample_n.toLocaleString()} />
          <Stat label="est. days" value={p.estimated_days.toString()} />
        </div>
        {p.proposed_experiment && (
          <div className="mb-3">
            <Label>Proposed experiment</Label>
            <p className="text-sm">{p.proposed_experiment}</p>
          </div>
        )}
        {p.critique && (
          <div className="border-t border-[var(--border)] pt-3 mt-3 space-y-3">
            <div>
              <Label>Critic v{p.critique.critic_version} counter-argument</Label>
              <pre className="text-xs whitespace-pre-wrap text-[var(--foreground)]/90">{p.critique.counter_argument}</pre>
            </div>
            {p.critique.confounder_checks && (
              <div>
                <Label>Confounder checks ({p.critique.confounder_checks.filter((c: any) => c.fired).length}/{p.critique.confounder_checks.length} fired)</Label>
                <div className="space-y-1">
                  {p.critique.confounder_checks.map((c: any, i: number) => (
                    <div key={i} className="text-xs flex gap-2 items-start">
                      <Badge variant={c.fired ? "destructive" : "outline"} className="shrink-0 min-w-[60px] justify-center">{c.fired ? "FIRED" : "—"}</Badge>
                      <div className="mono w-[260px] shrink-0">{c.name}</div>
                      <div className="text-[var(--muted-foreground)] flex-1">{c.evidence}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            <div>
              <Label>Alternative proposal</Label>
              <p className="text-sm bg-[var(--muted)] rounded-md p-3">{p.critique.alternative_proposal}</p>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1">{children}</div>;
}
function Stat({ label, value }: { label: string; value: string }) {
  return (<div><Label>{label}</Label><div className="mono">{value}</div></div>);
}
