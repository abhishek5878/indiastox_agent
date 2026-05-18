"use client";

import { cn } from "@/lib/utils";
import * as React from "react";

// ----- Button -----
export const Button = React.forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: "default" | "ghost" | "outline" | "destructive" | "secondary";
    size?: "sm" | "md" | "lg";
  }
>(({ className, variant = "default", size = "md", ...props }, ref) => {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 disabled:opacity-50 disabled:cursor-not-allowed";
  const v = {
    default: "bg-[var(--primary)] text-[var(--primary-foreground)] hover:opacity-90",
    secondary: "bg-[var(--accent)] text-[var(--accent-foreground)] hover:bg-[var(--border-strong)]",
    ghost: "hover:bg-[var(--accent)] text-[var(--foreground)]",
    outline: "border border-[var(--border-strong)] hover:bg-[var(--accent)]",
    destructive: "bg-[var(--destructive)] text-white hover:opacity-90",
  }[variant];
  const s = { sm: "h-7 px-2 text-xs", md: "h-9 px-3 text-sm", lg: "h-10 px-4 text-sm" }[size];
  return <button ref={ref} className={cn(base, v, s, className)} {...props} />;
});
Button.displayName = "Button";

// ----- Card -----
export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-lg border bg-[var(--card)] text-[var(--card-foreground)] shadow-sm",
        className,
      )}
      {...props}
    />
  );
}
export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-4 pb-2", className)} {...props} />;
}
export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn("text-sm font-semibold tracking-tight text-[var(--muted-foreground)] uppercase", className)} {...props} />;
}
export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-4 pt-2", className)} {...props} />;
}

// ----- Badge -----
export function Badge({
  className,
  variant = "default",
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & {
  variant?: "default" | "outline" | "success" | "warning" | "destructive" | "info";
}) {
  const v = {
    default: "bg-[var(--accent)] text-[var(--accent-foreground)]",
    outline: "border border-[var(--border-strong)] text-[var(--foreground)]",
    success: "bg-emerald-950/60 text-emerald-300 border border-emerald-800/60",
    warning: "bg-amber-950/60 text-amber-300 border border-amber-800/60",
    destructive: "bg-red-950/60 text-red-300 border border-red-800/60",
    info: "bg-blue-950/60 text-blue-300 border border-blue-800/60",
  }[variant];
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        v,
        className,
      )}
      {...props}
    />
  );
}

// ----- Input -----
export const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(({ className, ...props }, ref) => (
  <input
    ref={ref}
    className={cn(
      "h-9 w-full rounded-md border border-[var(--border-strong)] bg-[var(--muted)] px-3 text-sm placeholder:text-[var(--muted-foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
      className,
    )}
    {...props}
  />
));
Input.displayName = "Input";

// ----- Separator -----
export function Separator({ className }: { className?: string }) {
  return <div className={cn("h-px w-full bg-[var(--border)]", className)} />;
}

// ----- Spinner -----
export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-r-transparent",
        className,
      )}
      aria-label="loading"
    />
  );
}

// ----- Tooltip -----
// Lightweight CSS-only popover; no Radix dependency.
export function Tooltip({ children, content, side = "top" }: {
  children: React.ReactNode;
  content: React.ReactNode;
  side?: "top" | "bottom";
}) {
  return (
    <span className="relative inline-flex group cursor-help">
      {children}
      <span
        className={cn(
          "pointer-events-none absolute left-1/2 -translate-x-1/2 z-50 w-[280px] rounded-md border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-xs font-normal leading-snug text-[var(--foreground)] shadow-lg opacity-0 transition-opacity duration-150 group-hover:opacity-100",
          side === "top" ? "bottom-full mb-2" : "top-full mt-2",
        )}
      >
        {content}
      </span>
    </span>
  );
}

// ----- Hint icon — pairs with Tooltip -----
export function HintIcon({ content }: { content: React.ReactNode }) {
  return (
    <Tooltip content={content}>
      <span className="ml-1 inline-flex h-3.5 w-3.5 items-center justify-center rounded-full border border-[var(--border)] text-[9px] text-[var(--muted-foreground)] align-middle">?</span>
    </Tooltip>
  );
}

// ----- WowCallout — for hero/featured cards that need emphasis -----
export function WowCallout({ kicker, title, children, tone = "info" }: {
  kicker: string;
  title: string;
  children: React.ReactNode;
  tone?: "info" | "warn" | "good";
}) {
  const toneClass = {
    info: "border-[var(--primary)]/40 from-[var(--primary)]/10",
    warn: "border-amber-500/40 from-amber-500/10",
    good: "border-emerald-500/40 from-emerald-500/10",
  }[tone];
  return (
    <div className={cn("rounded-lg border bg-gradient-to-b to-transparent p-5 mb-6", toneClass)}>
      <div className="text-[10px] font-semibold tracking-widest uppercase text-[var(--muted-foreground)] mb-1">{kicker}</div>
      <div className="text-base font-semibold mb-3">{title}</div>
      <div>{children}</div>
    </div>
  );
}

// ----- KPI Tile -----
export function KpiTile({
  label,
  value,
  hint,
  delta,
  tone = "neutral",
}: {
  label: string;
  value: string | number;
  hint?: string;
  delta?: string;
  tone?: "neutral" | "good" | "warn" | "bad";
}) {
  const toneClass = {
    neutral: "text-[var(--foreground)]",
    good: "text-emerald-300",
    warn: "text-amber-300",
    bad: "text-red-300",
  }[tone];
  return (
    <Card>
      <CardHeader>
        <CardTitle>{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className={cn("text-2xl font-semibold tabular-nums tracking-tight", toneClass)}>
          {value}
        </div>
        {delta && (
          <div className="mt-1 text-xs text-[var(--muted-foreground)]">{delta}</div>
        )}
        {hint && <div className="mt-1 text-xs text-[var(--muted-foreground)] truncate" title={hint}>{hint}</div>}
      </CardContent>
    </Card>
  );
}
