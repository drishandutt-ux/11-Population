"use client";

/** The survey's own input panel: a form builder.
 *
 *  Title, optional material shown first, then the questions — each with a type, its text and
 *  whatever that type needs (options, a scale range with end labels, grid rows and columns).
 *  Templates prefill a whole form. One question is marked primary: its result leads the
 *  summary and gets the segment splits. */

import { useState } from "react";
import { SurveyQuestion, SurveyQuestionType, SurveyTemplate } from "@/lib/api";
import { ChevronDown, ChevronUp, Plus, Star, Trash2 } from "lucide-react";
import { InstrumentFormProps } from "./index";

const CONTROL = "w-full bg-input border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary/50";
const SMALL = "w-full bg-input border border-border rounded-md px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-primary/50";

const TYPES: { key: SurveyQuestionType; label: string; hint: string }[] = [
  { key: "single", label: "Single choice", hint: "pick one option" },
  { key: "multi", label: "Multiple choice", hint: "pick any that apply" },
  { key: "scale", label: "Scale", hint: "1–5, 0–10…" },
  { key: "yesno", label: "Yes / no", hint: "" },
  { key: "number", label: "Number", hint: "a free number" },
  { key: "text", label: "Open text", hint: "in their own words, coded into themes" },
  { key: "grid", label: "Grid", hint: "rows × columns, e.g. agree–disagree" },
];

function blank(type: SurveyQuestionType, n: number): SurveyQuestion {
  const q: SurveyQuestion = { key: `q${n}`, type, text: "" };
  if (type === "single" || type === "multi") q.options = ["", ""];
  if (type === "scale") { q.min = 1; q.max = 5; q.min_label = ""; q.max_label = ""; }
  if (type === "grid") { q.rows = [""]; q.columns = ["strongly agree", "agree", "neutral", "disagree", "strongly disagree"]; }
  return q;
}

function nextKey(qs: SurveyQuestion[]): string {
  let n = qs.length + 1;
  while (qs.some((q) => q.key === `q${n}`)) n += 1;
  return `q${n}`;
}

export default function SurveyBuilder({ instrument, values, onChange }: InstrumentFormProps) {
  const questions: SurveyQuestion[] = Array.isArray(values.questions) ? values.questions : [];
  const [preview, setPreview] = useState(false);
  const templates: SurveyTemplate[] = instrument.templates || [];

  const setQuestions = (qs: SurveyQuestion[]) => onChange("questions", qs);
  const update = (i: number, patch: Partial<SurveyQuestion>) => setQuestions(questions.map((q, j) => (j === i ? { ...q, ...patch } : q)));
  const remove = (i: number) => setQuestions(questions.filter((_, j) => j !== i));
  const move = (i: number, d: -1 | 1) => {
    const j = i + d;
    if (j < 0 || j >= questions.length) return;
    const qs = [...questions];
    [qs[i], qs[j]] = [qs[j], qs[i]];
    setQuestions(qs);
  };
  const add = (type: SurveyQuestionType) => setQuestions([...questions, blank(type, 0) && { ...blank(type, 0), key: nextKey(questions) }]);
  const setPrimary = (i: number) => setQuestions(questions.map((q, j) => ({ ...q, primary: j === i })));
  const applyTemplate = (t: SurveyTemplate) => {
    onChange("title", t.title);
    setQuestions(t.questions.map((q) => ({ ...q, options: q.options ? [...q.options] : undefined, rows: q.rows ? [...q.rows] : undefined, columns: q.columns ? [...q.columns] : undefined })));
  };

  return (
    <div className="space-y-4">
      {templates.length > 0 && (
        <div>
          <label className="text-xs text-muted-foreground block mb-1.5">Start from a template</label>
          <div className="flex flex-wrap gap-1">
            {templates.map((t) => (
              <button key={t.key} type="button" onClick={() => applyTemplate(t)} title={t.description}
                className="text-[10px] rounded px-1.5 py-0.5 border border-border/60 text-muted-foreground hover:text-foreground hover:border-primary/50 transition-colors">
                {t.label}
              </button>
            ))}
          </div>
        </div>
      )}

      <div>
        <label className="text-xs text-muted-foreground block mb-1.5">Survey title</label>
        <input value={values.title ?? ""} onChange={(e) => onChange("title", e.target.value)} placeholder="Your reaction to the new plan" className={CONTROL} />
      </div>

      <div>
        <label className="text-xs text-muted-foreground block mb-1.5">What they see first <span className="opacity-60">(optional)</span></label>
        <textarea value={values.intro ?? ""} onChange={(e) => onChange("intro", e.target.value)} rows={4}
          placeholder="Paste the material — the email, the proposal, the poster copy — or leave the session topic." className={`${CONTROL} resize-y`} />
      </div>

      <div className="flex items-center justify-between">
        <label className="text-xs text-muted-foreground">Questions <span className="text-primary/70">*</span> <span className="opacity-60">({questions.length})</span></label>
        <button type="button" onClick={() => setPreview((p) => !p)} className="text-[10px] text-muted-foreground hover:text-foreground">
          {preview ? "edit" : "preview as they see it"}
        </button>
      </div>

      {preview ? (
        <div className="rounded-xl border border-border/60 bg-card/30 p-3 space-y-3 text-xs">
          {values.title && <div className="text-sm font-medium">{values.title}</div>}
          {questions.map((q, i) => (
            <div key={q.key}>
              <div className="text-foreground/90">{i + 1}. {q.text || <span className="text-muted-foreground italic">untitled</span>}</div>
              <div className="text-muted-foreground mt-0.5">
                {q.type === "single" && (q.options || []).filter(Boolean).map((o) => <span key={o} className="mr-2">○ {o}</span>)}
                {q.type === "multi" && (q.options || []).filter(Boolean).map((o) => <span key={o} className="mr-2">☐ {o}</span>)}
                {q.type === "yesno" && <span>○ yes ○ no</span>}
                {q.type === "scale" && <span>{q.min_label || q.min} {Array.from({ length: (q.max ?? 5) - (q.min ?? 1) + 1 }, (_, k) => (q.min ?? 1) + k).join(" · ")} {q.max_label || q.max}</span>}
                {q.type === "number" && <span>______</span>}
                {q.type === "text" && <span className="italic">in their own words</span>}
                {q.type === "grid" && <span>{(q.rows || []).filter(Boolean).join(" / ")} × {(q.columns || []).filter(Boolean).join(" / ")}</span>}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="space-y-2">
          {questions.map((q, i) => (
            <div key={q.key} className={`rounded-xl border p-3 space-y-2 ${q.primary ? "border-primary/40 bg-primary/5" : "border-border/60 bg-card/30"}`}>
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] text-muted-foreground w-5">{i + 1}.</span>
                <select value={q.type} onChange={(e) => {
                  const type = e.target.value as SurveyQuestionType;
                  const fresh = blank(type, 0);
                  update(i, { type, options: fresh.options, rows: fresh.rows, columns: fresh.columns, min: fresh.min, max: fresh.max, min_label: fresh.min_label, max_label: fresh.max_label });
                }} className="bg-input border border-border rounded-md px-1.5 py-1 text-[11px]">
                  {TYPES.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
                </select>
                <span className="flex-1" />
                <button type="button" title="Lead the summary with this question" onClick={() => setPrimary(i)} className={q.primary ? "text-primary" : "text-muted-foreground/60 hover:text-foreground"}>
                  <Star className="w-3.5 h-3.5" fill={q.primary ? "currentColor" : "none"} />
                </button>
                <button type="button" onClick={() => move(i, -1)} className="text-muted-foreground/60 hover:text-foreground"><ChevronUp className="w-3.5 h-3.5" /></button>
                <button type="button" onClick={() => move(i, 1)} className="text-muted-foreground/60 hover:text-foreground"><ChevronDown className="w-3.5 h-3.5" /></button>
                <button type="button" onClick={() => remove(i)} className="text-muted-foreground/60 hover:text-red-400"><Trash2 className="w-3.5 h-3.5" /></button>
              </div>
              <input value={q.text} onChange={(e) => update(i, { text: e.target.value })} placeholder="The question, as they would read it" className={SMALL} />

              {(q.type === "single" || q.type === "multi") && (
                <OptionList label="Options" items={q.options || []} onChange={(options) => update(i, { options })} placeholder="an option" />
              )}
              {q.type === "scale" && (
                <div className="grid grid-cols-[3rem_1fr_3rem_1fr] items-center gap-1.5">
                  <input type="number" value={q.min ?? 1} onChange={(e) => update(i, { min: Number(e.target.value) })} className={`${SMALL} tabular-nums`} />
                  <input value={q.min_label ?? ""} onChange={(e) => update(i, { min_label: e.target.value })} placeholder="low end label" className={SMALL} />
                  <input type="number" value={q.max ?? 5} onChange={(e) => update(i, { max: Number(e.target.value) })} className={`${SMALL} tabular-nums`} />
                  <input value={q.max_label ?? ""} onChange={(e) => update(i, { max_label: e.target.value })} placeholder="high end label" className={SMALL} />
                </div>
              )}
              {q.type === "grid" && (
                <div className="grid grid-cols-2 gap-2">
                  <OptionList label="Rows (statements)" items={q.rows || []} onChange={(rows) => update(i, { rows })} placeholder="a statement" />
                  <OptionList label="Columns (answers)" items={q.columns || []} onChange={(columns) => update(i, { columns })} placeholder="an answer" />
                </div>
              )}
              {TYPES.find((t) => t.key === q.type)?.hint && (
                <p className="text-[10px] text-muted-foreground/60">{TYPES.find((t) => t.key === q.type)?.hint}</p>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-1">
        {TYPES.map((t) => (
          <button key={t.key} type="button" onClick={() => add(t.key)}
            className="flex items-center gap-1 text-[10px] rounded px-1.5 py-0.5 border border-border/60 text-muted-foreground hover:text-foreground hover:border-primary/50 transition-colors">
            <Plus className="w-3 h-3" /> {t.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function OptionList({ label, items, onChange, placeholder }: { label: string; items: string[]; onChange: (v: string[]) => void; placeholder: string }) {
  return (
    <div>
      <div className="text-[10px] text-muted-foreground mb-1">{label}</div>
      <div className="space-y-1">
        {items.map((o, k) => (
          <div key={k} className="flex items-center gap-1">
            <input value={o} onChange={(e) => onChange(items.map((x, j) => (j === k ? e.target.value : x)))} placeholder={placeholder} className={SMALL} />
            <button type="button" onClick={() => onChange(items.filter((_, j) => j !== k))} className="text-muted-foreground/50 hover:text-red-400 shrink-0"><Trash2 className="w-3 h-3" /></button>
          </div>
        ))}
        <button type="button" onClick={() => onChange([...items, ""])} className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground">
          <Plus className="w-3 h-3" /> add
        </button>
      </div>
    </div>
  );
}
