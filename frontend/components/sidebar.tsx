"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { llm } from "@/lib/api";
import { cn } from "@/lib/utils";

const NAV = [
  // Quick read — single-screen exec views
  { href: "/today",    label: "Today",          group: "exec" },
  // Briefings — for product / growth peers
  { href: "/briefing", label: "Full briefing",  group: "product" },
  { href: "/funnel",   label: "Growth funnel",  group: "product" },
  { href: "/cs-nudges", label: "Nudge list",    group: "product" },
  // Act — what to do today
  { href: "/proposals", label: "Proposals",     group: "act" },
  { href: "/cs",        label: "CS interventions", group: "act" },
  { href: "/chat",      label: "Ask the agent", group: "act" },
  // Engineering — substrate detail
  { href: "/",         label: "Living world",   group: "eng" },
  { href: "/overview", label: "Substrate overview", group: "eng" },
  { href: "/fingerprint", label: "User fingerprint", group: "eng" },
  { href: "/metrics",  label: "Metrics catalog", group: "eng" },
  { href: "/identity", label: "Identity graph", group: "eng" },
  { href: "/audit",    label: "Audit trail",    group: "eng" },
  { href: "/eval",     label: "Eval scorecard", group: "eng" },
];

const GROUPS = ["exec", "product", "act", "eng"] as const;
const GROUP_LABELS: Record<string, string> = {
  exec: "Quick read",
  product: "Product / growth",
  act: "Take action",
  eng: "Engineering",
};

export function Sidebar() {
  const pathname = usePathname();
  const [agentUp, setAgentUp] = useState<boolean | null>(null);

  // /today is the single-screen shareable exec view — no sidebar. The
  // page is meant to be pasted in Slack / opened on a phone / dropped
  // in a deck; a 14-item nav next to it would defeat the simplification.
  if (pathname === "/today") {
    return null;
  }

  useEffect(() => {
    llm.status().then((s) => setAgentUp(!!s.has_key)).catch(() => setAgentUp(false));
  }, []);

  return (
    <aside className="w-60 flex-shrink-0 border-r border-[var(--border)] flex flex-col">
      <div className="px-5 py-5 border-b border-[var(--border)]">
        <div className="flex items-center gap-2">
          <div className="h-6 w-6 rounded-md bg-[var(--primary)] flex items-center justify-center text-white text-[11px] font-bold">IS</div>
          <div>
            <div className="text-sm font-semibold text-[var(--foreground)] leading-tight">IndiaStox</div>
            <div className="text-[10px] text-[var(--muted-foreground)] tracking-wide">Substrate console</div>
          </div>
        </div>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-5 overflow-y-auto">
        {GROUPS.map((g) => (
          <div key={g}>
            <div className="px-2 mb-1.5 text-[10px] font-semibold tracking-widest text-[var(--muted-foreground)] uppercase">
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
                      "block rounded-md px-2.5 py-1.5 text-sm transition-colors",
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

      <div className="px-5 py-3 border-t border-[var(--border)] flex items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
        <div className={cn(
          "h-2 w-2 rounded-full",
          agentUp === null ? "bg-[var(--muted-foreground)]" :
          agentUp ? "bg-emerald-400 pulse-dot" : "bg-amber-400",
        )} />
        <span>{agentUp === null ? "checking…" : agentUp ? "agent live" : "agent offline"}</span>
      </div>
    </aside>
  );
}
