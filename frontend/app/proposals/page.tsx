"use client";

import { Badge, Button, Card, CardContent, CardHeader, CardTitle, HintIcon, WowCallout } from "@/components/ui";
import { Proposal, proposals } from "@/lib/api";
import { CONFOUNDERS, METRICS, TERMS, humanizeConfounder, humanizeMetric } from "@/lib/glossary";
import { useEffect, useState } from "react";

const STATUS_TABS = ["pending", "approved", "executed", "rejected"] as const;

export default function ProposalsPage() {
  const [items, setItems] = useState<Proposal[]>([]);
  const [status, setStatus] = useState<typeof STATUS_TABS[number]>("pending");
  const [busy, setBusy] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

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

  // The featured proposal is the pending one with the highest count of fired
  // confounders — the clearest case the Critic earned its keep.
  const featured = status === "pending"
    ? items
        .filter((p) => p.critique?.confounder_checks?.some((c: any) => c.fired))
        .sort((a, b) => firedCount(b) - firedCount(a))[0]
    : undefined;
  const rest = featured ? items.filter((p) => p.proposal_id !== featured.proposal_id) : items;

  return (
    <div className="px-8 py-7 max-w-[1400px] mx-auto">
      <header className="mb-6">
        <div className="text-xs font-medium tracking-widest text-[var(--muted-foreground)] uppercase">Proposals</div>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Every proposal arrives with its strongest counter-argument.</h1>
        <p className="mt-1 text-sm text-[var(--muted-foreground)] max-w-2xl">
          {TERMS.critic.label} runs five confounder checks against live data before approval. If 2+ fire, you
          almost certainly want the alternative proposal, not the original.
        </p>
      </header>

      <div className="flex gap-1 mb-5">
        {STATUS_TABS.map((s) => (
          <Button key={s} variant={status === s ? "default" : "ghost"} size="sm" onClick={() => setStatus(s)}>
            {s}
          </Button>
        ))}
      </div>

      {featured && (
        <WowCallout
          tone="warn"
          kicker={`Featured · ${firedCount(featured)} of ${featured.critique?.confounder_checks?.length ?? 0} confounders fired`}
          title="The Critic just blocked this proposal — in plain English."
        >
          <FeaturedCritique p={featured} busy={busy === featured.proposal_id} onAct={act} />
        </WowCallout>
      )}

      {rest.length === 0 ? (
        <div className="text-sm text-[var(--muted-foreground)]">No {status} proposals.</div>
      ) : (
        <div className="space-y-4">
          {rest.map((p) => (
            <ProposalCard
              key={p.proposal_id}
              p={p}
              busy={busy === p.proposal_id}
              onAct={act}
              open={expanded === p.proposal_id}
              onToggle={() => setExpanded((e) => e === p.proposal_id ? null : p.proposal_id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function firedCount(p: Proposal): number {
  return (p.critique?.confounder_checks || []).filter((c: any) => c.fired).length;
}

function FeaturedCritique({ p, busy, onAct }: {
  p: Proposal;
  busy: boolean;
  onAct: (id: string, a: "approve" | "reject" | "execute") => void;
}) {
  const fired = (p.critique?.confounder_checks || []).filter((c: any) => c.fired);
  return (
    <div className="space-y-4">
      <div>
        <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1">Original hypothesis</div>
        <p className="text-sm leading-relaxed">{p.hypothesis}</p>
        <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-[var(--muted-foreground)]">
          <span>targets <span className="mono text-[var(--foreground)]">{humanizeMetric(p.affected_metric)}</span></span>
          <span>·</span>
          <span>expected lift <span className="mono text-[var(--foreground)]">{p.expected_lift_pct.toFixed(1)}pp</span></span>
          <span>·</span>
          <span>n needed <span className="mono text-[var(--foreground)]">{p.required_sample_n.toLocaleString()}</span></span>
          <span>·</span>
          <span><span className="mono text-[var(--foreground)]">{p.estimated_days}d</span> to read out</span>
        </div>
      </div>

      <div>
        <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
          Why the Critic is uncomfortable
        </div>
        <div className="space-y-2">
          {fired.map((c: any, i: number) => {
            const entry = CONFOUNDERS[c.name];
            return (
              <div key={i} className="flex items-start gap-3 rounded-md bg-[var(--background)]/60 border border-amber-500/20 p-3">
                <Badge variant="destructive" className="shrink-0 mt-0.5 text-[10px]">FIRED</Badge>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium">
                    {entry?.label || humanizeConfounder(c.name)}
                    {entry?.long && <HintIcon content={entry.long} />}
                  </div>
                  <div className="text-xs text-[var(--muted-foreground)] mt-0.5">{entry?.short || c.name}</div>
                  <div className="text-xs mono text-[var(--foreground)]/80 mt-1.5 leading-relaxed">{c.evidence}</div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {p.critique?.alternative_proposal && (
        <div>
          <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1">
            The Critic's alternative
          </div>
          <p className="text-sm leading-relaxed bg-emerald-500/5 border border-emerald-500/20 rounded-md p-3">
            {p.critique.alternative_proposal}
          </p>
        </div>
      )}

      {p.status === "pending" && (
        <div className="flex gap-2 pt-1">
          <Button size="sm" disabled={busy} onClick={() => onAct(p.proposal_id, "approve")}>Approve anyway</Button>
          <Button size="sm" variant="destructive" disabled={busy} onClick={() => onAct(p.proposal_id, "reject")}>Reject</Button>
        </div>
      )}
    </div>
  );
}

function ProposalCard({ p, busy, onAct, open, onToggle }: {
  p: Proposal;
  busy: boolean;
  onAct: (id: string, a: "approve" | "reject" | "execute") => void;
  open: boolean;
  onToggle: () => void;
}) {
  const sev = p.critique?.severity || "low";
  const sevVariant = sev === "high" ? "destructive" : sev === "medium" ? "warning" : "default";
  const fired = firedCount(p);
  const total = p.critique?.confounder_checks?.length || 0;
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <CardTitle className="mono text-sm">{p.proposal_id}</CardTitle>
            <Badge variant={sevVariant as any}>{sev}</Badge>
            <Badge variant="outline">{humanizeMetric(p.affected_metric)}</Badge>
            {fired > 0 && (
              <Badge variant="warning" className="text-[10px]">{fired}/{total} confounders fired</Badge>
            )}
          </div>
          <p className="text-sm text-[var(--foreground)] leading-snug">{p.hypothesis}</p>
        </div>
        <div className="flex gap-2 shrink-0 ml-3">
          <Button size="sm" variant="ghost" onClick={onToggle}>{open ? "Hide" : "Details"}</Button>
          {p.status === "pending" && (
            <>
              <Button size="sm" disabled={busy} onClick={() => onAct(p.proposal_id, "approve")}>Approve</Button>
              <Button size="sm" variant="destructive" disabled={busy} onClick={() => onAct(p.proposal_id, "reject")}>Reject</Button>
            </>
          )}
        </div>
      </CardHeader>
      {open && (
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
              {p.critique.confounder_checks && (
                <div>
                  <Label>Confounder checks</Label>
                  <div className="space-y-1">
                    {p.critique.confounder_checks.map((c: any, i: number) => {
                      const entry = CONFOUNDERS[c.name];
                      return (
                        <div key={i} className="text-xs flex gap-2 items-start">
                          <Badge variant={c.fired ? "destructive" : "outline"} className="shrink-0 min-w-[60px] justify-center text-[10px]">{c.fired ? "FIRED" : "—"}</Badge>
                          <div className="w-[220px] shrink-0">
                            <span className="font-medium">{entry?.label || humanizeConfounder(c.name)}</span>
                            {entry?.long && <HintIcon content={entry.long} />}
                          </div>
                          <div className="text-[var(--muted-foreground)] flex-1 mono text-[11px]">{c.evidence}</div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
              {p.critique.alternative_proposal && (
                <div>
                  <Label>Alternative proposal</Label>
                  <p className="text-sm bg-[var(--muted)] rounded-md p-3">{p.critique.alternative_proposal}</p>
                </div>
              )}
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1">{children}</div>;
}
function Stat({ label, value }: { label: string; value: string }) {
  return (<div><Label>{label}</Label><div className="mono">{value}</div></div>);
}
