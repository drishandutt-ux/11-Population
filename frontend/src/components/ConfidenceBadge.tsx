"use client";

import { useState } from "react";
import { AgentValidation } from "@/lib/api";

/** What the score is, said once, wherever it appears. */
export const CONFIDENCE_TOOLTIP =
  "Behavioural confidence: how closely this twin behaved like its own record when the validation " +
  "battery ran — knowledge for its role, its own register, admitting what it cannot know, and " +
  "answering the same when the question is rephrased. It is fidelity to the persona, not " +
  "confidence that the answer is true of the real world.";

const PART_LABELS: Record<string, string> = {
  stability: "Stability",
  refusal: "Says what it can't know",
  knowledge: "Role knowledge",
  register: "Register",
};

const PART_HINTS: Record<string, string> = {
  stability: "The same question in different words, answered in a separate context — did the answer hold?",
  refusal: "Asked things this person cannot know: did it say so, or invent an answer?",
  knowledge: "What someone in this role would certainly know.",
  register: "Does it talk the way its own record says it talks?",
};

export function bandClass(band?: string | null) {
  if (band === "strong") return "text-emerald-400 border-emerald-500/30 bg-emerald-500/10";
  if (band === "fair") return "text-yellow-400 border-yellow-500/30 bg-yellow-500/10";
  if (band === "weak") return "text-red-400 border-red-500/30 bg-red-500/10";
  return "text-muted-foreground/60 border-border/50 bg-muted/30";
}

/** The twin's confidence score (brief L3-05), beside anything it says. Click for the parts. */
export default function ConfidenceBadge({
  validation,
  size = "sm",
  showLabel = false,
}: {
  validation?: AgentValidation | null;
  size?: "xs" | "sm";
  showLabel?: boolean;
}) {
  const [open, setOpen] = useState(false);
  if (!validation || validation.score == null) return null;

  const text = size === "xs" ? "text-[9px]" : "text-[10px]";
  const parts = Object.entries(validation.parts || {}).filter(([, v]) => typeof v === "number");

  return (
    <span className="relative inline-flex">
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
        title={CONFIDENCE_TOOLTIP}
        className={`inline-flex items-center gap-1 ${text} px-1.5 py-0.5 rounded border leading-none tabular-nums transition-colors ${bandClass(validation.band)}`}
      >
        <span className="opacity-70">{showLabel ? "confidence" : "conf"}</span>
        <span className="font-semibold">{validation.score}</span>
      </button>

      {open && (
        <>
          <span className="fixed inset-0 z-40" onClick={(e) => { e.stopPropagation(); setOpen(false); }} />
          <span className="absolute z-50 top-full left-0 mt-1 w-64 rounded-lg border border-border bg-background shadow-xl p-3 block">
            <span className="block text-[11px] font-semibold text-foreground mb-1">
              Behavioural confidence {validation.score}/100
            </span>
            <span className="block text-[10px] text-muted-foreground/80 leading-relaxed mb-2">
              How closely this twin behaved like its own record. Not a claim about the real world.
            </span>
            {parts.map(([key, value]) => (
              <span key={key} className="flex items-center gap-2 mb-1" title={PART_HINTS[key]}>
                <span className="text-[10px] text-muted-foreground w-[112px] shrink-0 truncate">{PART_LABELS[key] || key}</span>
                <span className="flex-1 h-1 bg-muted rounded-full overflow-hidden block">
                  <span
                    className={`h-full rounded-full block ${(value as number) >= 0.75 ? "bg-emerald-500" : (value as number) >= 0.5 ? "bg-yellow-500" : "bg-red-500"}`}
                    style={{ width: `${Math.round((value as number) * 100)}%` }}
                  />
                </span>
                <span className="text-[10px] tabular-nums text-muted-foreground w-6 text-right shrink-0">
                  {Math.round((value as number) * 100)}
                </span>
              </span>
            ))}
            {validation.at && (
              <span className="block text-[9px] text-muted-foreground/50 mt-2">
                scored {new Date(validation.at.endsWith("Z") ? validation.at : `${validation.at}Z`).toLocaleString()}
              </span>
            )}
          </span>
        </>
      )}
    </span>
  );
}
