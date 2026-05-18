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
  const [question, setQuestion] = useState("What is the week-1 ghost rate for Unstop cohort?");
  const [busy, setBusy] = useState(false);
  const [final, setFinal] = useState<string>("");
  const [calls, setCalls] = useState<ToolCallTrace[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const evtSrcRef = useRef<EventSource | null>(null);

  useEffect(() => {
    llm.status().then((s) => { setHasKey(s.has_key); setModel(s.model); }).catch(() => setHasKey(false));
  }, []);

  function ask() {
    if (!question.trim()) return;
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
          body: JSON.stringify({ question }),
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
        <div className="text-xs font-medium tracking-widest text-[var(--muted-foreground)] uppercase">LLM agent</div>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">
          {model}
          <Badge className="ml-2 align-middle" variant={hasKey ? "success" : "destructive"}>
            {hasKey ? "key loaded" : "no key"}
          </Badge>
        </h1>
        <p className="mt-1 text-sm text-[var(--muted-foreground)] max-w-2xl">
          The same metric tools, exposed to Claude over tool-use. Tool calls flow through the audit-logged ToolSession;
          each call is visible below as it happens.
        </p>
      </header>

      <Card className="mb-5">
        <CardContent className="p-4">
          <div className="flex gap-2">
            <Input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask the Growth Agent…" />
            <Button onClick={ask} disabled={busy || !hasKey}>
              {busy ? <Spinner /> : "Ask"}
            </Button>
          </div>
          <div className="flex flex-wrap gap-1.5 mt-3">
            {PRESETS.map((p) => (
              <button
                key={p}
                onClick={() => setQuestion(p)}
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
