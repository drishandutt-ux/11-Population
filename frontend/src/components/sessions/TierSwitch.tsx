"use client";

/** Model tier (2026-10-23): the one place the model is chosen. Fast runs every LLM call a session
 *  makes on Haiku, Pro on Sonnet; Opus is never used. The switch on the main page sets the tier
 *  for new sessions (remembered per browser); a session's badge switches that session. */

import { useEffect, useState } from "react";
import { Zap, Brain, Loader2 } from "lucide-react";
import { api, Session, SimMode } from "@/lib/api";
import { cn } from "@/lib/utils";

const KEY = "model_tier";

export const TIER_TITLE: Record<SimMode, string> = {
  fast: "Fast: Haiku for every part of the session. Cheapest.",
  pro: "Pro: Sonnet for every part of the session. Richer, roughly 3× the cost.",
};

/** The tier new sessions are created with. `fast` until read, and when nothing is stored. */
export function useNewSessionTier(): [SimMode, (t: SimMode) => void] {
  const [tier, setTier] = useState<SimMode>("fast");
  useEffect(() => {
    try { if (localStorage.getItem(KEY) === "pro") setTier("pro"); } catch {}
  }, []);
  return [tier, (t) => { try { localStorage.setItem(KEY, t); } catch {} setTier(t); }];
}

export function TierSwitch({ tier, onChange, className }: { tier: SimMode; onChange: (t: SimMode) => void; className?: string }) {
  return (
    <div className={cn("flex items-center gap-1.5", className)}>
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">Model</span>
      <div className="seg" role="tablist" aria-label="Model tier for new sessions">
        <button type="button" role="tab" data-on={tier === "fast"} onClick={() => onChange("fast")} className="seg-item" title={TIER_TITLE.fast}>
          <Zap className="w-3 h-3" /> Fast
        </button>
        <button type="button" role="tab" data-on={tier === "pro"} onClick={() => onChange("pro")} className="seg-item" title={TIER_TITLE.pro}>
          <Brain className="w-3 h-3" /> Pro
        </button>
      </div>
    </div>
  );
}

/** A session's tier as a small chip; clicking it switches that session (owner only). */
export function TierBadge({ session, onChanged, editable = true }: { session: Session; onChanged?: (s: Session) => void; editable?: boolean }) {
  const tier: SimMode = session.model_tier === "pro" ? "pro" : "fast";
  const [busy, setBusy] = useState(false);
  async function flip(e: React.MouseEvent) {
    e.stopPropagation();
    e.preventDefault();
    if (!editable || busy) return;
    setBusy(true);
    try { const n = await api.sessions.setTier(session.id, tier === "pro" ? "fast" : "pro"); publish(n.id, n.model_tier === "pro" ? "pro" : "fast"); onChanged?.(n); } catch {} finally { setBusy(false); }
  }
  return (
    <button
      type="button"
      onClick={flip}
      disabled={!editable}
      title={`${TIER_TITLE[tier]}${editable ? " Click to switch." : ""}`}
      className={cn(
        "inline-flex items-center gap-1 text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded border shrink-0",
        tier === "pro" ? "border-primary/40 text-primary bg-primary/10" : "border-border/60 text-muted-foreground",
        editable && "hover:bg-foreground/5",
      )}
    >
      {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : tier === "pro" ? <Brain className="w-3 h-3" /> : <Zap className="w-3 h-3" />}
      {tier === "pro" ? "Pro" : "Fast"}
    </button>
  );
}

// ── Inside a session ────────────────────────────────────────────────────────
// Every in-session Fast/Pro picker (Studio, Agents, Lab, Experiments) is this same setting:
// it reads the session's tier and switching it switches the whole session.

const tiers = new Map<string, SimMode>();
const listeners = new Map<string, Set<(t: SimMode) => void>>();

function publish(id: string, t: SimMode) {
  tiers.set(id, t);
  listeners.get(id)?.forEach((fn) => fn(t));
}

export function useSessionTier(sessionId: string): [SimMode, (t: SimMode) => void] {
  const [tier, setTierState] = useState<SimMode>(tiers.get(sessionId) ?? "fast");
  useEffect(() => {
    const set = listeners.get(sessionId) ?? new Set();
    set.add(setTierState);
    listeners.set(sessionId, set);
    if (tiers.has(sessionId)) setTierState(tiers.get(sessionId)!);
    else api.sessions.get(sessionId).then((s: any) => publish(sessionId, s?.model_tier === "pro" ? "pro" : "fast")).catch(() => {});
    return () => { set.delete(setTierState); };
  }, [sessionId]);
  return [tier, (t) => {
    if (t === tiers.get(sessionId)) return;
    publish(sessionId, t);
    api.sessions.setTier(sessionId, t).catch(() => {});
  }];
}
