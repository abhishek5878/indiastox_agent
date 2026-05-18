"use client";

import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { EvalRun, evalApi } from "@/lib/api";
import { useEffect, useState } from "react";

const DIMS = ["accuracy", "calibration", "action"] as const;

export default function EvalPage() {
  const [run, setRun] = useState<EvalRun | null>(null);
  const [picked, setPicked] = useState<string | null>(null);

  useEffect(() => { evalApi.latest().then(setRun).catch(() => {}); }, []);

  if (!run) return (
    <div className="px-8 py-7">
      <div className="text-sm text-[var(--muted-foreground)]">No eval runs yet. Run `make eval`.</div>
    </div>
  );

  const chosen = picked ? run.results.find((r) => r.id === picked) : null;
  const pass = run.total_score < 31;

  return (
    <div className="px-8 py-7 max-w-[1400px] mx-auto">
      <header className="mb-6">
        <div className="text-xs font-medium tracking-widest text-[var(--muted-foreground)] uppercase">Eval</div>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">
          Scorecard, {run.total_score} / {run.max_total}{" "}
          <Badge variant={pass ? "success" : "destructive"} className="ml-2 align-middle">
            FM6 {pass ? "PASS" : "FAIL"} (threshold &lt; 31)
          </Badge>
        </h1>
        <p className="mt-1 text-sm text-[var(--muted-foreground)] max-w-2xl">
          Click any cell to drill into the agent's answer + ground truth + scoring.
        </p>
      </header>

      <Card className="mb-5">
        <CardContent className="p-5">
          <div className="overflow-x-auto">
            <table className="border-collapse">
              <thead>
                <tr>
                  <th className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider text-right pr-3 pb-2">dim</th>
                  {run.results.map((r) => (
                    <th key={r.id} className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider px-1 pb-2">
                      {r.id}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {DIMS.map((dim) => (
                  <tr key={dim}>
                    <td className="text-sm font-medium text-right pr-3 py-1">{dim}</td>
                    {run.results.map((r) => {
                      const v = r.scores[dim];
                      const isHit = v === 1;
                      return (
                        <td key={r.id} className="px-1 py-1">
                          <button
                            onClick={() => setPicked(r.id)}
                            className={`h-10 w-10 rounded-sm flex items-center justify-center font-semibold text-sm transition-transform hover:scale-105 ${
                              isHit ? "bg-emerald-700/70 text-emerald-100" : "bg-red-800/70 text-red-100"
                            } ${picked === r.id ? "ring-2 ring-white/50" : ""}`}
                          >
                            {v}
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
                <tr>
                  <td className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider text-right pr-3 pt-2">total</td>
                  {run.results.map((r) => (
                    <td key={r.id} className="text-center text-xs mono pt-2">
                      {r.scores.total}/{r.scores.max}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {chosen && (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <CardTitle>{chosen.id}</CardTitle>
              <Badge variant="outline">{chosen.ground_truth_kind}</Badge>
            </div>
            <p className="mt-2 text-sm">{chosen.text}</p>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <Label>Agent value</Label>
                <div className="mono">{String(chosen.agent_value)}</div>
              </div>
              <div>
                <Label>Ground truth</Label>
                <div className="mono">{String(chosen.ground_truth)}</div>
              </div>
              <div className="col-span-2">
                <Label>Calibration string</Label>
                <p className="text-sm bg-[var(--muted)] rounded-md p-3">{chosen.agent_calibration}</p>
              </div>
              <div className="col-span-2">
                <Label>Proposed action</Label>
                <p className="text-sm bg-[var(--muted)] rounded-md p-3">{chosen.agent_action}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1">{children}</div>;
}
