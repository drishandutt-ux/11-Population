"use client";

import { useEffect, useRef, useState } from "react";
import { PopulationBuild, PopulationLogEntry, PopulationQuestion } from "@/lib/api";
import { Loader2, ArrowRight, SkipForward, ChevronDown } from "lucide-react";

const STAGES: { key: string; label: string }[] = [
  { key: "detect", label: "Detect" },
  { key: "gather", label: "Gather" },
  { key: "clarify", label: "Clarify" },
  { key: "plan", label: "Plan" },
  { key: "review", label: "Review" },
  { key: "spawn", label: "Build" },
];

const STATUS_STAGE: Record<string, number> = {
  queued: 0, detecting: 0, gathering: 1, clarifying: 2, planning: 3, awaiting_review: 4, spawning: 5, complete: 6, stopped: -1, error: -1,
};

export const STATUS_LABEL: Record<string, string> = {
  queued: "starting…", detecting: "detecting what we know…", gathering: "gathering statistics…", clarifying: "waiting for your answers",
  planning: "composing segments…", awaiting_review: "plan ready — review it", spawning: "building the population…", complete: "population built",
  stopped: "stopped", error: "failed",
};

export function isActive(status: string | undefined) {
  return !!status && ["queued", "detecting", "gathering", "planning", "spawning"].includes(status);
}

/** One dot per log level; colour carries the meaning, no icon vocabulary to learn. */
function LevelDot({ level }: { level: PopulationLogEntry["level"] }) {
  const cls =
    level === "ok" ? "bg-emerald-400" :
    level === "warn" ? "bg-amber-400" :
    level === "error" ? "bg-red-400" :
    level === "question" ? "bg-sky-400" :
    level === "decision" ? "bg-violet-400" :
    "bg-muted-foreground/40";
  return <span className={`dot ${cls}`} />;
}

/** The six stages as a rail: a filled track for what is done, a live dot on what is running. */
export function Stepper({ status }: { status: string | undefined }) {
  const at = status ? STATUS_STAGE[status] ?? 0 : -2;
  const failed = status === "error" || status === "stopped";
  return (
    <ol className="flex items-stretch gap-1.5 w-full" aria-label="Build stages">
      {STAGES.map((s, k) => {
        const done = at > k;
        const now = at === k;
        return (
          <li key={s.key} className="flex-1 min-w-0">
            <div className={`h-[3px] rounded-full transition-colors ${done ? "bg-primary/70" : now ? "bg-primary" : failed ? "bg-border" : "bg-border"}`} />
            <div className={`mt-1.5 flex items-center gap-1 text-[11px] leading-none ${now ? "text-foreground font-medium" : done ? "text-muted-foreground" : "text-muted-foreground/45"}`}>
              {now && isActive(status) && <span className="dot bg-primary animate-pulse" />}
              <span className="truncate">{s.label}</span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/**
 * The build's narration. Open while something runs; folded to a one-line summary once a plan
 * is on the page (`quiet`), so the plan — not the log — is what the analyst reads.
 */
export function BuildLog({ entries, active, quiet = false }: { entries: PopulationLogEntry[]; active: boolean; quiet?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const [stick, setStick] = useState(true);
  const [open, setOpen] = useState(!quiet);
  useEffect(() => { setOpen(!quiet); }, [quiet]);
  useEffect(() => {
    if (open && stick && ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [entries.length, stick, open]);
  const last = entries[entries.length - 1];
  return (
    <div className="surface rounded-xl overflow-hidden">
      <button type="button" onClick={() => setOpen((o) => !o)} className="w-full flex items-center gap-2.5 px-4 h-11 text-left hover:bg-foreground/[0.03] transition-colors">
        {active ? <Loader2 className="w-3.5 h-3.5 text-primary animate-spin shrink-0" /> : <ChevronDown className={`w-3.5 h-3.5 text-muted-foreground/70 shrink-0 transition-transform ${open ? "" : "-rotate-90"}`} />}
        <span className="text-[13px] font-medium text-foreground">Activity</span>
        <span className="text-[11px] text-muted-foreground/60 tabular-nums">{entries.length}</span>
        {!open && last && <span className="ml-2 min-w-0 flex-1 truncate text-xs text-muted-foreground">{last.message}</span>}
        {open && active && <span className="ml-auto text-[11px] text-primary">working</span>}
      </button>
      {open && (
        <div
          ref={ref}
          onScroll={(e) => { const el = e.currentTarget; setStick(el.scrollHeight - el.scrollTop - el.clientHeight < 24); }}
          className="max-h-[300px] overflow-y-auto border-t hairline px-2 py-1.5"
        >
          {entries.length === 0 && <p className="text-xs text-muted-foreground/60 px-2 py-2.5">Nothing yet. Set the dials and press Detect &amp; plan.</p>}
          {entries.map((e, k) => (
            <div key={k} className="grid grid-cols-[10px_58px_minmax(0,1fr)_auto] items-start gap-x-2.5 px-2 py-1.5 rounded-md hover:bg-foreground/[0.03]">
              <span className="pt-[5px]"><LevelDot level={e.level} /></span>
              <span className="text-[10.5px] text-muted-foreground/60 pt-px capitalize truncate">{e.stage}</span>
              <div className="min-w-0">
                <p className={`text-xs leading-snug ${e.level === "error" ? "text-red-300" : e.level === "decision" ? "text-violet-200" : "text-foreground/90"}`}>{e.message}</p>
                {e.detail && <p className="text-[11px] text-muted-foreground/70 leading-snug mt-0.5">{e.detail}</p>}
              </div>
              <span className="text-[10px] text-muted-foreground/40 tabular-nums pt-px">{e.ts?.slice(11, 19)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function QuestionsCard({ build, onAnswer, busy }: { build: PopulationBuild; onAnswer: (answers: Record<string, string>, skip: boolean) => Promise<void>; busy: boolean }) {
  const qs: PopulationQuestion[] = build.questions || [];
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const answered = qs.filter((q) => (answers[q.id] || "").trim()).length;
  return (
    <div className="surface rounded-xl p-5 space-y-4 ring-1 ring-sky-500/20 animate-fade-in">
      <div className="flex items-baseline gap-2 flex-wrap">
        <h3 className="text-[15px] font-semibold text-foreground tracking-tight">Before I plan, {qs.length === 1 ? "one question" : `${qs.length} questions`}</h3>
        <span className="text-[11px] text-muted-foreground/70 ml-auto">answer what you know · the rest uses the default</span>
      </div>
      <ol className="space-y-3">
        {qs.map((q, n) => (
          <li key={q.id} className="rounded-lg surface-raised px-4 py-3 space-y-2">
            <p className="text-[13px] text-foreground font-medium leading-snug"><span className="text-muted-foreground/60 tabular-nums mr-1.5">{n + 1}.</span>{q.text}</p>
            <p className="hint">{q.why}</p>
            <div className="flex flex-wrap gap-1.5">
              {(q.suggested || []).map((s) => (
                <button key={s} type="button" onClick={() => setAnswers((a) => ({ ...a, [q.id]: s }))} className={`chip transition-colors ${answers[q.id] === s ? "chip-info" : "hover:text-foreground"}`}>{s}</button>
              ))}
            </div>
            <input value={answers[q.id] || ""} onChange={(e) => setAnswers((a) => ({ ...a, [q.id]: e.target.value }))} placeholder={`Default if unanswered: ${q.default}`} className="field field-sm" />
          </li>
        ))}
      </ol>
      <div className="flex gap-2 justify-end">
        <button disabled={busy} onClick={() => onAnswer({}, true)} className="btn btn-sm btn-ghost">
          <SkipForward className="w-3.5 h-3.5" /> Skip, use defaults
        </button>
        <button disabled={busy} onClick={() => onAnswer(answers, false)} className="btn btn-sm btn-primary">
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ArrowRight className="w-3.5 h-3.5" />} Answer{answered ? ` (${answered})` : ""} &amp; plan
        </button>
      </div>
    </div>
  );
}
