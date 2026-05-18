"use client";

import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Spinner } from "@/components/ui";
import { llm } from "@/lib/api";
import { useEffect, useRef, useState } from "react";

interface ToolCallTrace {
  tool: string;
  args: any;
  result: any;
  is_error: boolean;
}

const PRESETS = [
  "What is the week-1 ghost rate for the Unstop cohort?",
  "Which channel has the worst CAC bound right now?",
  "Why did the Critic flag the latest growth proposal?",
  "How confident should we be in the brier_score for W01?",
];

export default function ChatPage() {
  const [hasKey, setHasKey] = useState<boolean | null>(null);
  const [model, setModel] = useState<string>("claude-sonnet-4-6");
  const [question, setQuestion] = useState(PRESETS[0]);
  const [busy, setBusy] = useState(false);
  const [final, setFinal] = useState<string>("");
  const [calls, setCalls] = useState<ToolCallTrace[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [autoStarted, setAutoStarted] = useState(false);
  const evtSrcRef = useRef<EventSource | null>(null);

  useEffect(() => {
    llm.status().then((s) => { setHasKey(s.has_key); setModel(s.model); }).catch(() => setHasKey(false));
  }, []);

  // Auto-demo: fire one preset on first visit if the key is loaded. Guarded
  // by sessionStorage so a refresh doesn't re-spam the API.
  useEffect(() => {
    if (autoStarted) return;
    if (hasKey !== true) return;
    if (typeof window !== "undefined" && sessionStorage.getItem("chat_auto_started") === "1") {
      setAutoStarted(true);
      return;
    }
    setAutoStarted(true);
    try { sessionStorage.setItem("chat_auto_started", "1"); } catch {}
    ask(PRESETS[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasKey]);

  function ask(override?: string) {
    const q = (override ?? question).trim();
    if (!q) return;
    if (override) setQuestion(override);
    setBusy(true);
    setFinal("");
    setCalls([]);
    setErr(null);

    // FastAPI's SSE chat endpoint expects a POST; EventSource only supports GET.
    // For simplicity we use fetch with manual stream reading.
    (async () => {
      try {
        const r = await fetch((process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000") + "/api/llm/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: q }),
        });
        if (!r.ok || !r.body) {
          setErr(`HTTP ${r.status}`);
          setBusy(false);
          return;
        }
        const reader = r.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        let running = true;
        while (running) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          const frames = buf.split("\n\n");
          buf = frames.pop() || "";
          for (const f of frames) {
            const lines = f.split("\n");
            const evt = lines.find((l) => l.startsWith("event:"))?.slice(6).trim();
            const dataLine = lines.find((l) => l.startsWith("data:"))?.slice(5).trim();
            if (!evt || !dataLine) continue;
            const data = JSON.parse(dataLine);
            if (evt === "tool_call") setCalls((prev) => [...prev, data]);
            if (evt === "final") setFinal(data.text || "");
            if (evt === "error") setErr(data.message || "error");
            if (evt === "end") running = false;
          }
        }
      } catch (e: any) {
        setErr(e.message);
      } finally {
        setBusy(false);
      }
    })();
  }

  return (
    <div className="px-8 py-7 max-w-[1100px] mx-auto">
      <header className="mb-6">
        <div className="text-xs font-medium tracking-widest text-[var(--muted-foreground)] uppercase">Ask the agent</div>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">
          The agent answers with tools, not with vibes.
          <Badge className="ml-2 align-middle" variant={hasKey ? "success" : "destructive"}>
            {hasKey ? model : "no key"}
          </Badge>
        </h1>
        <p className="mt-1 text-sm text-[var(--muted-foreground)] max-w-2xl">
          Every answer below is grounded in real tool calls visible in the trace. Same audit-logged ToolSession
          the dashboards, Critic, and CS agent use. No retrieval, no hallucinated numbers.
        </p>
        {busy && calls.length === 0 && !final && (
          <div className="mt-4 inline-flex items-center gap-2 rounded-md bg-[var(--primary)]/10 border border-[var(--primary)]/30 px-3 py-2 text-xs">
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--primary)] pulse-dot" />
            <span>Auto-demo running — watch the agent pick tools, parse confidence, and answer.</span>
          </div>
        )}
      </header>

      <Card className="mb-5">
        <CardContent className="p-4">
          <div className="flex gap-2">
            <Input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask the Growth Agent…" onKeyDown={(e) => { if (e.key === "Enter") ask(); }} />
            <Button onClick={() => ask()} disabled={busy || !hasKey}>
              {busy ? <Spinner /> : "Ask"}
            </Button>
          </div>
          <div className="flex flex-wrap gap-1.5 mt-3">
            {PRESETS.map((p) => (
              <button
                key={p}
                onClick={() => ask(p)}
                disabled={busy}
                className="px-2.5 py-1 rounded-full text-[11px] bg-[var(--muted)] text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)] transition-colors disabled:opacity-50"
              >
                {p}
              </button>
            ))}
          </div>
          {err && <Badge variant="destructive" className="mt-3">{err}</Badge>}
        </CardContent>
      </Card>

      {calls.length > 0 && (
        <Card className="mb-5">
          <CardHeader><CardTitle>Tool trace ({calls.length})</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-2">
              {calls.map((c, i) => (
                <details key={i} className="bg-[var(--muted)] rounded-md">
                  <summary className="px-3 py-2 cursor-pointer text-sm flex items-center gap-2">
                    <Badge variant={c.is_error ? "destructive" : "info"} className="mono">{c.tool}</Badge>
                    <span className="text-xs text-[var(--muted-foreground)] mono">{JSON.stringify(c.args)}</span>
                  </summary>
                  <pre className="px-3 pb-3 text-[11px] mono whitespace-pre-wrap text-[var(--muted-foreground)]">
                    {JSON.stringify(c.result, null, 2)}
                  </pre>
                </details>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {final && (
        <Card>
          <CardHeader><CardTitle>Agent answer</CardTitle></CardHeader>
          <CardContent>
            <pre className="text-sm whitespace-pre-wrap leading-relaxed">{final}</pre>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
