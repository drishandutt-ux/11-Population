"use client";

/** Live cost chip (2026-11-13): what this session has spent so far on LLM calls, web searches and
 *  images, read from the usage ledger every few seconds while the tab is open. The dot pulses while
 *  money is being spent (anything in the last minute). Hover for the breakdown. */

import { useEffect, useRef, useState } from "react";
import { api, SessionCost as Cost } from "@/lib/api";
import { cn } from "@/lib/utils";

const POLL_MS = 3000;          // visible tab
const POLL_HIDDEN_MS = 30000;  // background tab

function usd(n: number): string {
  if (n < 10) return `$${n.toFixed(2)}`;
  if (n < 1000) return `$${n.toFixed(1)}`;
  return `$${Math.round(n).toLocaleString()}`;
}

function modelName(m: string): string {
  if (/haiku/i.test(m)) return "Haiku";
  if (/sonnet/i.test(m)) return "Sonnet";
  if (/opus/i.test(m)) return "Opus";
  if (/image|gpt/i.test(m)) return "Images";
  return m;
}

export default function SessionCost({ sessionId, className, variant = "pro" }: { sessionId: string; className?: string; variant?: "pro" | "lite" }) {
  const [cost, setCost] = useState<Cost | null>(null);
  const shown = useRef(0);   // never count down: a row moving from buffer to database can dip for a moment

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const c = await api.sessions.cost(sessionId);
        if (!alive) return;
        shown.current = Math.max(shown.current, c.cost_usd);
        setCost({ ...c, cost_usd: shown.current });
      } catch {}
      if (alive) timer = setTimeout(tick, document.hidden ? POLL_HIDDEN_MS : POLL_MS);
    };
    const onVisible = () => { if (!document.hidden) { clearTimeout(timer); tick(); } };
    shown.current = 0;
    tick();
    document.addEventListener("visibilitychange", onVisible);
    return () => { alive = false; clearTimeout(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [sessionId]);

  const spending = !!cost && cost.last_minute_usd > 0;
  const capHit = !!cost && cost.search_cap.limit > 0 && cost.search_cap.used >= cost.search_cap.limit;
  const title = cost
    ? [
        `Spent on this session so far: ${usd(cost.cost_usd)}`,
        `${cost.calls.toLocaleString()} model calls · ${cost.web_searches.toLocaleString()} web searches`,
        ...cost.by_model.filter((m) => m.cost_usd > 0).map((m) => `  ${modelName(m.model)}: ${usd(m.cost_usd)}`),
        spending ? `Spending now: ${usd(cost.last_minute_usd)} in the last minute` : "Not spending right now",
        cost.search_cap.limit > 0
          ? `Web searches this hour: ${cost.search_cap.used} of ${cost.search_cap.limit}${capHit ? " (limit reached; builds carry on without new searches)" : ""}`
          : "",
      ].filter(Boolean).join("\n")
    : "Loading what this session has spent…";

  return (
    <span
      title={title}
      aria-live="polite"
      className={cn(
        "inline-flex items-center gap-1.5 shrink-0 tabular-nums select-none",
        variant === "lite" ? "lite-pill" : "text-[11px] px-2 h-6 rounded border border-border/60 text-muted-foreground",
        spending && "text-amber-600 dark:text-amber-300 border-amber-400/50",
        className,
      )}
    >
      <span className={cn("w-1.5 h-1.5 rounded-full", spending ? "bg-amber-500 animate-pulse" : "bg-muted-foreground/40")} />
      {cost ? usd(cost.cost_usd) : "$…"}
      {spending && <span className="opacity-70">+{usd(cost!.last_minute_usd)}/min</span>}
    </span>
  );
}
