"use client";

/** One question in the Forms studio: its type, its text and whatever the type needs — options,
 *  a scale with labelled ends, grid rows and columns — plus the primary star, reordering and
 *  delete. The same card whether the question was typed, uploaded, written by the model or
 *  changed in the chat; a `flash` ring marks what the model just changed. */

import { FormQuestion, SurveyQuestion, SurveyQuestionType } from "@/lib/api";
import { ChevronDown, ChevronUp, Plus, Star, Trash2, X } from "lucide-react";

export const TYPES: { key: SurveyQuestionType; label: string; hint: string }[] = [
  { key: "single", label: "Single choice", hint: "pick one option" },
  { key: "multi", label: "Multiple choice", hint: "pick any that apply" },
  { key: "scale", label: "Scale", hint: "1–5, 0–10…" },
  { key: "yesno", label: "Yes / no", hint: "" },
  { key: "number", label: "Number", hint: "a free number" },
  { key: "text", label: "Open text", hint: "in their own words, coded into themes" },
  { key: "grid", label: "Grid", hint: "rows × columns, e.g. agree–disagree" },
];

export function blank(type: SurveyQuestionType, key: string): SurveyQuestion {
  const q: SurveyQuestion = { key, type, text: "" };
  if (type === "single" || type === "multi") q.options = ["", ""];
  if (type === "scale") { q.min = 1; q.max = 5; q.min_label = ""; q.max_label = ""; }
  if (type === "grid") { q.rows = [""]; q.columns = ["strongly agree", "agree", "neutral", "disagree", "strongly disagree"]; }
  return q;
}

export function nextKey(qs: SurveyQuestion[]): string {
  let n = qs.length + 1;
  while (qs.some((q) => q.key === `q${n}`)) n += 1;
  return `q${n}`;
}

/** The instrument's own rules, mirrored so a problem shows before the run is refused. */
export function problemsOf(q: SurveyQuestion): string[] {
  const out: string[] = [];
  if (!q.text.trim()) out.push("needs its text");
  if ((q.type === "single" || q.type === "multi") && (q.options || []).filter((o) => o.trim()).length < 2) out.push("needs at least two options");
  if (q.type === "grid" && ((q.rows || []).filter((r) => r.trim()).length < 1 || (q.columns || []).filter((c) => c.trim()).length < 2)) out.push("needs a row and two columns");
  if (q.type === "scale" && (q.max ?? 5) <= (q.min ?? 1)) out.push("the scale's top must be above its bottom");
  return out;
}

const INPUT = "w-full bg-transparent border-0 border-b border-border/50 focus:border-primary/60 focus:outline-none px-0 py-1 text-sm text-foreground placeholder:text-muted-foreground/50";
const SMALL = "w-full bg-input/60 border border-border/60 rounded-md px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-primary/50";

export default function QuestionEditor({ q, index, total, flash, onChange, onRemove, onMove, onPrimary }: {
  q: FormQuestion; index: number; total: number; flash?: boolean;
  onChange: (patch: Partial<SurveyQuestion>) => void; onRemove: () => void; onMove: (d: -1 | 1) => void; onPrimary: () => void;
}) {
  const problems = problemsOf(q);
  const typeMeta = TYPES.find((t) => t.key === q.type);
  return (
    <div className={`group rounded-xl border p-3.5 space-y-2 transition-shadow ${q.primary ? "border-primary/40 bg-primary/[0.04]" : "border-border/60 bg-card/30"} ${flash ? "ring-2 ring-primary/50 shadow-[0_0_0_4px_hsl(var(--primary)/0.08)]" : ""}`}>
      <div className="flex items-start gap-2">
        <span className="text-[11px] text-muted-foreground tabular-nums w-5 pt-1.5 shrink-0">{index + 1}.</span>
        <div className="min-w-0 flex-1">
          <input value={q.text} onChange={(e) => onChange({ text: e.target.value })} placeholder="The question, as they would read it" className={INPUT} />
          {q.why && <p className="text-[10px] text-muted-foreground/60 mt-1 leading-snug">{q.why}</p>}
        </div>
        <div className="flex items-center gap-0.5 shrink-0 pt-0.5">
          <select value={q.type} onChange={(e) => {
            const type = e.target.value as SurveyQuestionType;
            const fresh = blank(type, q.key);
            onChange({ type, options: fresh.options, rows: fresh.rows, columns: fresh.columns, min: fresh.min, max: fresh.max, min_label: fresh.min_label, max_label: fresh.max_label });
          }} title={typeMeta?.hint || ""} className="bg-input/60 border border-border/60 rounded-md px-1.5 py-1 text-[11px] text-muted-foreground mr-1">
            {TYPES.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
          </select>
          <button type="button" title={q.primary ? "The summary leads with this question" : "Lead the summary with this question"} onClick={onPrimary} className={`p-1 rounded ${q.primary ? "text-primary" : "text-muted-foreground/50 hover:text-foreground"}`}>
            <Star className="w-3.5 h-3.5" fill={q.primary ? "currentColor" : "none"} />
          </button>
          <button type="button" onClick={() => onMove(-1)} disabled={index === 0} title="Move up" className="p-1 rounded text-muted-foreground/50 hover:text-foreground disabled:opacity-20"><ChevronUp className="w-3.5 h-3.5" /></button>
          <button type="button" onClick={() => onMove(1)} disabled={index === total - 1} title="Move down" className="p-1 rounded text-muted-foreground/50 hover:text-foreground disabled:opacity-20"><ChevronDown className="w-3.5 h-3.5" /></button>
          <button type="button" onClick={onRemove} title="Remove" className="p-1 rounded text-muted-foreground/50 hover:text-red-400"><Trash2 className="w-3.5 h-3.5" /></button>
        </div>
      </div>

      <div className="pl-7">
        {(q.type === "single" || q.type === "multi") && (
          <OptionList items={q.options || []} onChange={(options) => onChange({ options })} placeholder="an option" marker={q.type === "single" ? "○" : "☐"} />
        )}
        {q.type === "scale" && (
          <div className="grid grid-cols-[3.25rem_1fr_3.25rem_1fr] items-center gap-1.5">
            <input type="number" value={q.min ?? 1} onChange={(e) => onChange({ min: Number(e.target.value) })} className={`${SMALL} tabular-nums`} aria-label="low end" />
            <input value={q.min_label ?? ""} onChange={(e) => onChange({ min_label: e.target.value })} placeholder="what the low end means" className={SMALL} />
            <input type="number" value={q.max ?? 5} onChange={(e) => onChange({ max: Number(e.target.value) })} className={`${SMALL} tabular-nums`} aria-label="high end" />
            <input value={q.max_label ?? ""} onChange={(e) => onChange({ max_label: e.target.value })} placeholder="what the high end means" className={SMALL} />
          </div>
        )}
        {q.type === "grid" && (
          <div className="grid grid-cols-2 gap-3">
            <OptionList label="Statements" items={q.rows || []} onChange={(rows) => onChange({ rows })} placeholder="a statement" />
            <OptionList label="Answers · strongest first" items={q.columns || []} onChange={(columns) => onChange({ columns })} placeholder="an answer" />
          </div>
        )}
        {q.type === "yesno" && <p className="text-[11px] text-muted-foreground/60">○ yes &nbsp; ○ no</p>}
        {q.type === "number" && <p className="text-[11px] text-muted-foreground/60">a number</p>}
        {q.type === "text" && <p className="text-[11px] text-muted-foreground/60">in their own words · coded into themes after the run</p>}
        {problems.length > 0 && <p className="text-[10px] text-amber-300/80 mt-1.5">This question {problems.join("; ")}.</p>}
      </div>
    </div>
  );
}

export function OptionList({ label, items, onChange, placeholder, marker }: { label?: string; items: string[]; onChange: (v: string[]) => void; placeholder: string; marker?: string }) {
  return (
    <div>
      {label && <div className="text-[10px] text-muted-foreground mb-1">{label}</div>}
      <div className="space-y-1">
        {items.map((o, k) => (
          <div key={k} className="flex items-center gap-1.5">
            {marker && <span className="text-[11px] text-muted-foreground/50 w-3">{marker}</span>}
            <input value={o} onChange={(e) => onChange(items.map((x, j) => (j === k ? e.target.value : x)))} placeholder={placeholder} className={SMALL}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); onChange([...items.slice(0, k + 1), "", ...items.slice(k + 1)]); } }} />
            <button type="button" onClick={() => onChange(items.filter((_, j) => j !== k))} title="Remove" className="text-muted-foreground/40 hover:text-red-400 shrink-0"><X className="w-3 h-3" /></button>
          </div>
        ))}
        <button type="button" onClick={() => onChange([...items, ""])} className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground">
          <Plus className="w-3 h-3" /> add
        </button>
      </div>
    </div>
  );
}

/** The form as the twins will read it. */
export function FormPreview({ title, intro, questions }: { title?: string; intro?: string; questions: SurveyQuestion[] }) {
  return (
    <div className="rounded-xl border border-border/60 bg-card/30 p-5 space-y-4 text-sm max-w-2xl">
      {title && <div className="text-base font-medium">{title}</div>}
      {intro && <p className="text-xs text-foreground/75 whitespace-pre-wrap leading-relaxed border-l-2 border-border/60 pl-3">{intro}</p>}
      {questions.map((q, i) => (
        <div key={q.key}>
          <div className="text-foreground/90">{i + 1}. {q.text || <span className="text-muted-foreground italic">untitled</span>}</div>
          <div className="text-xs text-muted-foreground mt-1 space-x-3">
            {q.type === "single" && (q.options || []).filter(Boolean).map((o) => <span key={o}>○ {o}</span>)}
            {q.type === "multi" && (q.options || []).filter(Boolean).map((o) => <span key={o}>☐ {o}</span>)}
            {q.type === "yesno" && <span>○ yes &nbsp; ○ no</span>}
            {q.type === "scale" && <span>{q.min_label || q.min} &nbsp; {Array.from({ length: Math.max(0, (q.max ?? 5) - (q.min ?? 1) + 1) }, (_, k) => (q.min ?? 1) + k).join(" · ")} &nbsp; {q.max_label || q.max}</span>}
            {q.type === "number" && <span>______</span>}
            {q.type === "text" && <span className="italic">in their own words</span>}
            {q.type === "grid" && <span>{(q.rows || []).filter(Boolean).join(" / ")} &nbsp;×&nbsp; {(q.columns || []).filter(Boolean).join(" / ")}</span>}
          </div>
        </div>
      ))}
      {questions.length === 0 && <p className="text-xs text-muted-foreground">No questions yet.</p>}
    </div>
  );
}
