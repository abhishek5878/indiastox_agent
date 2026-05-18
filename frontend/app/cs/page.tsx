"use client";

import { Badge, Button, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { Intervention, interventions } from "@/lib/api";
import { useEffect, useState } from "react";

export default function CSPage() {
  const [items, setItems] = useState<Intervention[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  async function load() { setItems(await interventions.list("pending")); }
  useEffect(() => { load(); }, []);

  async function act(userId: string, action: "approve" | "reject") {
    setBusy(userId);
    try { await interventions.act(userId, action); await load(); } finally { setBusy(null); }
  }

  return (
    <div className="px-8 py-7 max-w-[1400px] mx-auto">
      <header className="mb-6">
        <div className="text-xs font-medium tracking-widest text-[var(--muted-foreground)] uppercase">CS interventions</div>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">The CS agent drafts the nudge. You approve the send.</h1>
        <p className="mt-1 text-sm text-[var(--muted-foreground)] max-w-2xl">
          Same metric layer, identity graph, audit trail — different agent archetype. Each nudge references the user's actual last BULL/BEAR call and how it resolved, not just their tickers.
        </p>
      </header>

      {items.length === 0 ? (
        <div className="text-sm text-[var(--muted-foreground)]">No pending interventions. Run `make cs-run`.</div>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {items.map((iv) => (
            <Card key={iv.user_id}>
              <CardHeader>
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline">{iv.tone}</Badge>
                    <Badge variant="info">{iv.channel}</Badge>
                  </div>
                  <span className="text-xs text-[var(--muted-foreground)] mono">{iv.user_id.slice(0, 8)}</span>
                </div>
              </CardHeader>
              <CardContent>
                <p className="text-sm mb-3">{iv.intervention_text}</p>
                <div className="grid grid-cols-3 gap-2 text-xs mb-3">
                  <Stat label="risk" value={iv.risk_score?.toFixed(2)} />
                  <Stat label="calls landed" value={`${iv.n_correct ?? 0}/${iv.n_predictions ?? 0}`} />
                  <Stat label="est. lift" value={iv.estimated_reactivation_lift ? `${(iv.estimated_reactivation_lift * 100).toFixed(0)}%` : "—"} />
                </div>
                <details>
                  <summary className="text-xs text-[var(--muted-foreground)] cursor-pointer mb-2">Grounding facts ({iv.grounding_facts.length})</summary>
                  <ul className="text-xs space-y-0.5 mono text-[var(--muted-foreground)]">
                    {iv.grounding_facts.map((g, i) => <li key={i}>· {g}</li>)}
                  </ul>
                </details>
                <div className="flex gap-2 mt-3">
                  <Button size="sm" disabled={busy === iv.user_id} onClick={() => act(iv.user_id, "approve")}>Approve</Button>
                  <Button size="sm" variant="destructive" disabled={busy === iv.user_id} onClick={() => act(iv.user_id, "reject")}>Reject</Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: any }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)]">{label}</div>
      <div className="mono">{value ?? "—"}</div>
    </div>
  );
}
