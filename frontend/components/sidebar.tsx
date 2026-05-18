"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Living World", group: "demo" },
  { href: "/overview", label: "Overview", group: "demo" },
  { href: "/metrics", label: "Metric explorer", group: "explore" },
  { href: "/identity", label: "Identity explorer", group: "explore" },
  { href: "/eval", label: "Eval scorecard", group: "evaluate" },
  { href: "/proposals", label: "Proposals + critiques", group: "act" },
  { href: "/cs", label: "CS interventions", group: "act" },
  { href: "/chat", label: "LLM agent chat", group: "act" },
  { href: "/audit", label: "Audit trail", group: "evaluate" },
];

const GROUPS = ["demo", "explore", "evaluate", "act"] as const;
const GROUP_LABELS: Record<string, string> = {
  demo: "Demo",
  explore: "Explore",
  evaluate: "Evaluate",
  act: "Act",
};

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="w-60 flex-shrink-0 border-r border-[var(--border)] flex flex-col">
      <div className="px-5 py-5 border-b border-[var(--border)]">
        <div className="text-xs font-semibold text-[var(--muted-foreground)] uppercase tracking-wider">
          IndiaStox
        </div>
        <div className="text-sm text-[var(--foreground)] mt-0.5">Substrate console</div>
      </div>
      <nav className="flex-1 px-3 py-4 space-y-5">
        {GROUPS.map((g) => (
          <div key={g}>
            <div className="px-2 mb-1 text-[10px] font-semibold tracking-widest text-[var(--muted-foreground)] uppercase">
              {GROUP_LABELS[g]}
            </div>
            <div className="space-y-0.5">
              {NAV.filter((n) => n.group === g).map((n) => {
                const active = pathname === n.href;
                return (
                  <Link
                    key={n.href}
                    href={n.href}
                    className={cn(
                      "block rounded-md px-2 py-1.5 text-sm transition-colors",
                      active
                        ? "bg-[var(--accent)] text-[var(--foreground)] font-medium"
                        : "text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--accent)]/50",
                    )}
                  >
                    {n.label}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>
      <div className="px-5 py-3 border-t border-[var(--border)] text-[11px] text-[var(--muted-foreground)] mono">
        api · :8000
        <br />
        ui · :3000
      </div>
    </aside>
  );
}
