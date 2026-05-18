"use client";

import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input } from "@/components/ui";
import { IdentityEdge, IdentityUser, identity } from "@/lib/api";
import { useEffect, useState } from "react";

export default function IdentityPage() {
  const [q, setQ] = useState("");
  const [users, setUsers] = useState<IdentityUser[]>([]);
  const [picked, setPicked] = useState<string | null>(null);
  const [edges, setEdges] = useState<IdentityEdge[]>([]);
  const [blocked, setBlocked] = useState<any[]>([]);

  useEffect(() => { identity.blocked().then(setBlocked).catch(() => {}); }, []);
  useEffect(() => { if (picked) identity.edges(picked).then(setEdges); }, [picked]);

  async function search(e: React.FormEvent) {
    e.preventDefault();
    if (!q.trim()) return;
    const rows = await identity.search(q.trim());
    setUsers(rows);
  }

  return (
    <div className="px-8 py-7 max-w-[1400px] mx-auto">
      <header className="mb-6">
        <div className="text-xs font-medium tracking-widest text-[var(--muted-foreground)] uppercase">Identity graph</div>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">Confidence is a number — never a yes/no.</h1>
        <p className="mt-1 text-sm text-[var(--muted-foreground)] max-w-2xl">
          Every match between systems carries a typed float + provenance. Search a user; inspect their edges;
          browse the 170 shared-device pairs the resolver refused to merge.
        </p>
      </header>

      <form onSubmit={search} className="flex gap-2 mb-5">
        <Input placeholder="user_id, email, or name fragment…" value={q} onChange={(e) => setQ(e.target.value)} />
        <Button type="submit">Search</Button>
      </form>

      {users.length > 0 && (
        <Card className="mb-5">
          <CardHeader><CardTitle>Matches ({users.length})</CardTitle></CardHeader>
          <CardContent className="p-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider">
                  <th className="text-left p-3">user_id</th>
                  <th className="text-left p-3">name</th>
                  <th className="text-left p-3">email</th>
                  <th className="text-left p-3">channel</th>
                  <th className="text-left p-3">conf</th>
                </tr>
              </thead>
              <tbody>
                {users.slice(0, 20).map((u) => (
                  <tr
                    key={u.user_id}
                    onClick={() => setPicked(u.user_id)}
                    className={`cursor-pointer border-t border-[var(--border)] hover:bg-[var(--accent)] ${picked === u.user_id ? "bg-[var(--accent)]" : ""}`}
                  >
                    <td className="p-3 mono text-xs">{u.user_id.slice(0, 12)}…</td>
                    <td className="p-3">{u.full_name}</td>
                    <td className="p-3 text-[var(--muted-foreground)]">{u.personal_email}</td>
                    <td className="p-3"><Badge variant="outline">{u.acquisition_source}</Badge></td>
                    <td className="p-3 mono">{u.identity_confidence.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {picked && (
        <Card className="mb-5">
          <CardHeader><CardTitle>Edges for {picked.slice(0, 12)}…</CardTitle></CardHeader>
          <CardContent>
            {edges.length === 0 ? (
              <div className="text-sm text-[var(--muted-foreground)]">No edges.</div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider">
                    <th className="text-left p-2">source</th>
                    <th className="text-left p-2">key</th>
                    <th className="text-left p-2">conf</th>
                    <th className="text-left p-2">method</th>
                  </tr>
                </thead>
                <tbody>
                  {edges.map((e, i) => (
                    <tr key={i} className="border-t border-[var(--border)]">
                      <td className="p-2 mono text-xs">{e.source_system}</td>
                      <td className="p-2 mono text-xs">{e.source_key.slice(0, 30)}</td>
                      <td className="p-2 mono">{e.confidence.toFixed(2)}</td>
                      <td className="p-2 text-xs">{e.resolution_method}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader><CardTitle>Blocked shared-device pairs (Pass 3 anti-merge)</CardTitle></CardHeader>
        <CardContent>
          {blocked.length === 0 ? (
            <div className="text-sm text-[var(--muted-foreground)]">No blocked rows yet.</div>
          ) : (
            <div className="text-xs mono text-[var(--muted-foreground)] max-h-96 overflow-auto space-y-1">
              {blocked.slice(0, 30).map((b, i) => (
                <div key={i}>
                  {String(b.entity_id).slice(0, 16)}… · device {String(b.source_key).slice(0, 24)} · conf {b.confidence}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
