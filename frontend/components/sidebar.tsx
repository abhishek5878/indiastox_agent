"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { llm } from "@/lib/api";
import { cn } from "@/lib/utils";

const NAV = [
  // Story — the consumption entry points
  { href: "/briefing", label: "Briefing",        group: "story" },
  { href: "/",         label: "Living world",    group: "story" },
  { href: "/funnel",   label: "Growth funnel",   group: "story" },
  // Act — what to do today
  { href: "/cs-nudges", label: "Nudge targets",  group: "act" },
  { href: "/cs",        label: "CS interventions", group: "act" },
  { href: "/proposals", label: "Proposals",      group: "act" },
  { href: "/chat",      label: "Ask the agent",  group: "act" },
  // Drill — per-user / per-substrate detail
  { href: "/fingerprint", label: "User fingerprint", group: "drill" },
  { href: "/overview",  label: "Substrate overview", group: "drill" },
  { href: "/metrics",   label: "Metrics catalog", group: "drill" },
  { href: "/identity",  label: "Identity graph", group: "drill" },
  // Deep — engineering / audit
  { href: "/audit",     label: "Audit trail",    group: "deep" },
  { href: "/eval",      label: "Eval scorecard", group: "deep" },
];

const GROUPS = ["story", "act", "drill", "deep"] as const;
const GROUP_LABELS: Record<string, string> = {
  story: "See the story",
  act: "Take action",
  drill: "Drill in",
  deep: "Engineering / audit",
};

export function Sidebar() {
  const pathname = usePathname();
  const [agentUp, setAgentUp] = useState<boolean | null>(null);

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
