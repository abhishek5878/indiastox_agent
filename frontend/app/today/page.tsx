"use client";

import { metrics, MetricResult } from "@/lib/api";
import Link from "next/link";
import { useEffect, useState } from "react";

interface TodayBreakdowns {
  headline_pct: number;
  headline_sentence: string;
  this_week_numbers: { label: string; value: string }[];
  top_action: {
    title: string;
    detail: string;
    button_label: string;
    action_endpoint: string;
    count: number;
  };
  footer_note: string;
  week_of: string;
}

export default function TodayPage() {
  const [result, setResult] = useState<MetricResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    metrics.invoke("today_glance", { week_of: "2024-W01" })
      .then(setResult)
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) {
    return (
      <div className="min-h-screen flex items-center justify-center px-6">
        <div className="text-sm text-[var(--muted-foreground)]">
          Today view unavailable.
          <pre className="mt-2 text-xs text-red-400 mono whitespace-pre-wrap max-w-md">{err}</pre>
        </div>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="min-h-screen flex items-center justify-center text-sm text-[var(--muted-foreground)]">
        Loading…
      </div>
    );
  }

  const b = result.breakdowns as TodayBreakdowns;

  return (
    <div className="min-h-screen px-6 sm:px-10 py-12 sm:py-20 max-w-[680px] mx-auto">

      {/* HERO — one number, one sentence */}
      <section className="mb-12 sm:mb-16">
        <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-3">
          This week
        </div>
        <div className="text-7xl sm:text-8xl font-semibold tabular-nums tracking-tight leading-none">
          {b.headline_pct.toFixed(0)}<span className="text-3xl sm:text-4xl text-[var(--muted-foreground)] ml-1">%</span>
        </div>
        <p className="mt-5 text-base sm:text-lg text-[var(--foreground)] leading-snug">
          {b.headline_sentence}
        </p>
      </section>

      {/* THREE NUMBERS — tight strip */}
      <section className="mb-12 sm:mb-16">
        <div className="grid grid-cols-3 gap-4 sm:gap-8 border-t border-b border-[var(--border)] py-5 sm:py-6">
          {b.this_week_numbers.map((n, idx) => (
            <div key={idx}>
              <div className="text-2xl sm:text-3xl font-semibold tabular-nums tracking-tight">
                {n.value}
              </div>
              <div className="mt-1 text-[11px] sm:text-xs text-[var(--muted-foreground)] leading-tight">
                {n.label}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ONE ACTION — the only call-to-action on the page */}
      <section className="mb-16">
        <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-3">
          Do this
        </div>
        <h2 className="text-xl sm:text-2xl font-medium text-[var(--foreground)] leading-snug">
          {b.top_action.title}
        </h2>
        <p className="mt-3 text-sm sm:text-base text-[var(--muted-foreground)] leading-relaxed">
          {b.top_action.detail}
        </p>
        <Link
          href={b.top_action.action_endpoint}
          className="mt-5 inline-block px-5 py-2.5 rounded-md bg-[var(--primary)] text-white text-sm font-medium hover:opacity-90"
        >
          {b.top_action.button_label} →
        </Link>
      </section>

      {/* FOOTER — small text, link to deeper views */}
      <footer className="pt-8 border-t border-[var(--border)] text-xs text-[var(--muted-foreground)] flex flex-wrap gap-4 items-center">
        <span>{b.footer_note}</span>
        <Link href="/briefing" className="text-[var(--primary)] hover:underline">
          Full briefing →
        </Link>
        <Link href="/overview" className="text-[var(--primary)] hover:underline">
          Engineering view →
        </Link>
      </footer>
    </div>
  );
}
