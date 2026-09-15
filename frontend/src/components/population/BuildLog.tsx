"use client";

import { useEffect, useRef, useState } from "react";
import { PopulationBuild, PopulationLogEntry, PopulationQuestion } from "@/lib/api";
import { CheckCircle2, AlertTriangle, XCircle, HelpCircle, Hand, Info, Loader2, ScrollText, ArrowRight, SkipForward } from "lucide-react";

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

function Icon({ level }: { level: PopulationLogEntry["level"] }) {
  switch (level) {
    case "ok": return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />;
    case "warn": return <AlertTriangle className="w-3.5 h-3.5 text-yellow-400" />;
    case "error": return <XCircle className="w-3.5 h-3.5 text-red-400" />;
    case "question": return <HelpCircle className="w-3.5 h-3.5 text-sky-400" />;
    case "decision": return <Hand className="w-3.5 h-3.5 text-purple-400" />;
    default: return <Info className="w-3.5 h-3.5 text-muted-foreground/60" />;
  }
}

const STAGE_COLOR: Record<string, string> = {
  detect: "text-sky-300 border-sky-500/30", gather: "text-emerald-300 border-emerald-500/30", clarify: "text-amber-300 border-amber-500/30",
  plan: "text-purple-300 border-purple-500/30", review: "text-pink-300 border-pink-500/30", spawn: "text-primary border-primary/30", error: "text-red-300 border-red-500/30",
};

export function Stepper({ status }: { status: string | undefined }) {
  const at = status ? STATUS_STAGE[status] ?? 0 : -2;
  return (
    <div className="flex items-center gap-1">
      {STAGES.map((s, k) => {
        const done = at > k;
        const now = at === k;
        return (
          <div key={s.key} className="flex items-center gap-1">
            <span className={`text-[10px] px-2 py-0.5 rounded-full border ${done ? "border-emerald-500/40 text-emerald-300 bg-emerald-500/10" : now ? "border-primary/60 text-primary bg-primary/10" : "border-border/40 text-muted-foreground/50"}`}>
              {now && isActive(status) ? <Loader2 className="w-2.5 h-2.5 inline animate-spin mr-1" /> : null}{s.label}
            </span>
            {k < STAGES.length - 1 && <span className="text-muted-foreground/30 text-[10px]">›</span>}
          </div>
        );
      })}
    </div>
  );
}

export function BuildLog({ entries, active }: { entries: PopulationLogEntry[]; active: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const [stick, setStick] = useState(true);
  useEffect(() => {
    if (stick && ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [entries.length, stick]);
  return (
    <div className="glass rounded-2xl overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border/40">
        <ScrollText className="w-3.5 h-3.5 text-primary" />
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Build log</span>
        <span className="text-[10px] text-muted-foreground/50">{entries.length} step{entries.length === 1 ? "" : "s"}</span>
        {active && <span className="ml-auto flex items-center gap-1.5 text-[10px] text-primary"><Loader2 className="w-3 h-3 animate-spin" /> working</span>}
      </div>
      <div
        ref={ref}
        onScroll={(e) => { const el = e.currentTarget; setStick(el.scrollHeight - el.scrollTop - el.clientHeight < 24); }}
        className="max-h-[320px] overflow-y-auto px-3 py-2 space-y-0.5 font-mono"
      >
        {entries.length === 0 && <p className="text-[11px] text-muted-foreground/50 px-1 py-2 font-sans">Nothing yet. Set the dials and press Detect &amp; plan.</p>}
        {entries.map((e, k) => (
          <div key={k} className="flex items-start gap-2 px-1 py-1 rounded hover:bg-muted/30">
            <span className="mt-0.5 shrink-0"><Icon level={e.level} /></span>
            <span className={`shrink-0 text-[9px] uppercase tracking-wide px-1 rounded border mt-0.5 ${STAGE_COLOR[e.stage] || "text-muted-foreground border-border/40"}`}>{e.stage}</span>
            <div className="flex-1 min-w-0 font-sans">
              <p className={`text-[11px] leading-snug ${e.level === "error" ? "text-red-300" : e.level === "decision" ? "text-purple-200" : "text-foreground/90"}`}>{e.message}</p>
              {e.detail && <p className="text-[10px] text-muted-foreground/65 leading-snug mt-0.5">{e.detail}</p>}
            </div>
            <span className="shrink-0 text-[9px] text-muted-foreground/40 tabular-nums mt-0.5">{e.ts?.slice(11, 19)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function QuestionsCard({ build, onAnswer, busy }: { build: PopulationBuild; onAnswer: (answers: Record<string, string>, skip: boolean) => Promise<void>; busy: boolean }) {
  const qs: PopulationQuestion[] = build.questions || [];
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const answered = qs.filter((q) => (answers[q.id] || "").trim()).length;
  return (
    <div className="glass rounded-2xl p-4 space-y-3 border border-sky-500/25">
      <div className="flex items-center gap-2">
        <HelpCircle className="w-4 h-4 text-sky-400" />
        <span className="text-sm font-semibold text-foreground">Before I plan, {qs.length === 1 ? "one question" : `${qs.length} questions`}</span>
        <span className="text-[10px] text-muted-foreground/60 ml-auto">answer what you know · the rest uses the default</span>
      </div>
      {qs.map((q, n) => (
        <div key={q.id} className="rounded-xl border border-border/40 bg-muted/20 px-3 py-2.5 space-y-1.5">
          <p className="text-xs text-foreground/90 font-medium">{n + 1}. {q.text}</p>
          <p className="text-[10px] text-muted-foreground/70 leading-snug">{q.why}</p>
          <div className="flex flex-wrap gap-1">
            {(q.suggested || []).map((s) => (
              <button key={s} onClick={() => setAnswers((a) => ({ ...a, [q.id]: s }))} className={`text-[10px] px-2 py-1 rounded-lg border transition-colors ${answers[q.id] === s ? "border-sky-500/50 bg-sky-500/10 text-sky-200" : "border-border/50 text-muted-foreground hover:text-foreground"}`}>{s}</button>
            ))}
          </div>
          <input value={answers[q.id] || ""} onChange={(e) => setAnswers((a) => ({ ...a, [q.id]: e.target.value }))} placeholder={`Default if unanswered: ${q.default}`} className="w-full bg-muted/50 border border-border rounded-lg px-2.5 py-1.5 text-[11px] text-foreground placeholder-muted-foreground/40 focus:outline-none focus:ring-1 focus:ring-sky-500/50" />
        </div>
      ))}
      <div className="flex gap-2 justify-end">
        <button disabled={busy} onClick={() => onAnswer({}, true)} className="flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg border border-border/60 text-muted-foreground hover:text-foreground disabled:opacity-40">
          <SkipForward className="w-3.5 h-3.5" /> Skip, use defaults
        </button>
        <button disabled={busy} onClick={() => onAnswer(answers, false)} className="flex items-center gap-1.5 text-xs font-semibold px-4 py-2 rounded-lg bg-sky-500/20 border border-sky-500/40 text-sky-200 hover:bg-sky-500/30 disabled:opacity-40">
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ArrowRight className="w-3.5 h-3.5" />} Answer{answered ? ` (${answered})` : ""} &amp; plan
        </button>
      </div>
    </div>
  );
}
