"use client";

/** Survey results, the way a form tool shows them — Summary, Question, Individual — but
 *  every chart is drawn for its question type, carries its interval, and clicking any mark
 *  shows the personas behind it and what they wrote. */

import { useMemo, useState } from "react";
import { ProbeAnswerRow, SurveyQuestionResult } from "@/lib/api";
import { CategoryBars, Donut, Histogram, OptionBars, SegmentTable, ShareBar, StackedRows, pct } from "../Charts";
import { InstrumentPageProps } from "./types";

type Tab = "summary" | "question" | "individual";
type Filter = { q: string; value: string; row?: string } | null;

function display(q: SurveyQuestionResult, v: any): string {
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) return v.join(", ");
  if (typeof v === "object") return Object.entries(v).map(([k, x]) => `${k}: ${x}`).join(" · ");
  return String(v);
}

function matches(q: SurveyQuestionResult, v: any, f: Filter): boolean {
  if (!f || f.q !== q.key) return true;
  if (q.type === "multi") return Array.isArray(v) && v.includes(f.value);
  if (q.type === "grid") return !!f.row && typeof v === "object" && v !== null && String((v as any)[f.row]) === f.value;
  if (q.type === "scale" || q.type === "number") {
    if (f.value.includes("–")) {                       // a bin "lo–hi"
      const [lo, hi] = f.value.split("–").map(Number);
      const n = Number(v);
      return n >= lo && n <= hi;
    }
    return String(Math.round(Number(v))) === f.value;
  }
  return String(v) === f.value;
}

export default function SurveyPage({ probe }: InstrumentPageProps) {
  const a: any = probe.aggregates;
  const answers: ProbeAnswerRow[] = probe.answers || [];
  const [tab, setTab] = useState<Tab>("summary");
  const [filter, setFilter] = useState<Filter>(null);
  const [qKey, setQKey] = useState<string>("");
  const [agentId, setAgentId] = useState<string>("");
  const questions: SurveyQuestionResult[] = a?.questions || [];
  const byQ = useMemo(() => Object.fromEntries(questions.map((q) => [q.key, q])), [questions]);
  if (!a || !a.n) return null;

  const current = byQ[qKey] || questions[0];
  const respondents = (q: SurveyQuestionResult | undefined, f: Filter) =>
    q ? answers.filter((r) => matches(q, r.answer?.[q.key], f)) : answers;
  const openAgent = (id: string) => { setAgentId(id); setTab("individual"); };
  const openQuestion = (key: string, f: Filter = null) => { setQKey(key); setFilter(f); setTab("question"); };

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-medium truncate">{a.title || "Survey"}</div>
          <p className="text-xs text-muted-foreground">{a.n} responses · {questions.length} questions</p>
        </div>
        <div className="flex rounded-lg border border-border/60 overflow-hidden text-xs shrink-0">
          {(["summary", "question", "individual"] as Tab[]).map((t) => (
            <button key={t} onClick={() => setTab(t)} className={`px-3 py-1.5 capitalize ${tab === t ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground"}`}>{t}</button>
          ))}
        </div>
      </div>

      {tab === "summary" && (
        <div className="space-y-4">
          {a.headline && "share" in a.headline && (
            <div className="rounded-xl border border-primary/30 bg-primary/5 p-4">
              <ShareBar value={a.headline} label={a.headline.label} />
              <p className="text-xs text-foreground/70 mt-3 leading-relaxed">{a.sentence}</p>
            </div>
          )}
          {a.headline && "mean" in a.headline && (
            <div className="rounded-xl border border-primary/30 bg-primary/5 p-4">
              <div className="text-xs text-muted-foreground">{a.headline.label}</div>
              <div className="text-3xl font-semibold tabular-nums text-primary">{a.headline.mean.mean}</div>
              <div className="text-[11px] text-muted-foreground tabular-nums">95% CI {a.headline.mean.low}–{a.headline.mean.high} · median {a.headline.mean.median}</div>
              <p className="text-xs text-foreground/70 mt-2 leading-relaxed">{a.sentence}</p>
            </div>
          )}

          {questions.map((q, i) => (
            <QuestionCard key={q.key} q={q} index={i} filter={filter?.q === q.key ? filter : null}
              onFilter={(f) => setFilter(f)} respondents={respondents(q, filter?.q === q.key ? filter : null)}
              showRespondents={filter?.q === q.key} onOpenAgent={openAgent} onOpenQuestion={() => openQuestion(q.key, filter?.q === q.key ? filter : null)} />
          ))}

          {a.segments && Object.keys(a.segments).length > 0 && (
            <div className="rounded-xl border border-border/60 bg-card/40 p-4">
              <div className="text-xs text-muted-foreground mb-3">Who answered "{a.headline?.label?.split(" — ").pop()}" — by segment</div>
              <div className="grid grid-cols-2 gap-5">
                {Object.entries(a.segments).map(([key, rows]) => <SegmentTable key={key} title={key} rows={rows as any} />)}
              </div>
            </div>
          )}
        </div>
      )}

      {tab === "question" && current && (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-1">
            {questions.map((q, i) => (
              <button key={q.key} onClick={() => { setQKey(q.key); setFilter(null); }}
                className={`text-[10px] rounded px-1.5 py-0.5 border transition-colors ${current.key === q.key ? "border-primary/60 text-primary bg-primary/10" : "border-border/60 text-muted-foreground hover:text-foreground"}`}>
                {i + 1}. {q.text.length > 34 ? q.text.slice(0, 34) + "…" : q.text}
              </button>
            ))}
          </div>
          <QuestionCard q={current} index={questions.indexOf(current)} filter={filter?.q === current.key ? filter : null}
            onFilter={(f) => setFilter(f)} respondents={respondents(current, filter?.q === current.key ? filter : null)}
            showRespondents onOpenAgent={openAgent} big />
        </div>
      )}

      {tab === "individual" && (
        <div className="grid grid-cols-[13rem_1fr] gap-4">
          <div className="space-y-0.5 max-h-[32rem] overflow-y-auto pr-1">
            {answers.length === 0 && <p className="text-xs text-muted-foreground">Responses load when the run is opened.</p>}
            {answers.map((r) => (
              <button key={r.agent_id} onClick={() => setAgentId(r.agent_id)}
                className={`w-full text-left rounded-lg px-2 py-1.5 ${agentId === r.agent_id ? "bg-muted/60" : "hover:bg-muted/40"}`}>
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full shrink-0" style={{ background: r.avatar_color }} />
                  <span className="text-xs text-foreground/90 truncate">{r.name}</span>
                </div>
                <div className="text-[10px] text-muted-foreground truncate pl-4">{r.role}</div>
              </button>
            ))}
          </div>
          <IndividualForm row={answers.find((r) => r.agent_id === agentId) || answers[0]} questions={questions} />
        </div>
      )}
    </div>
  );
}

function QuestionCard({ q, index, filter, onFilter, respondents, showRespondents, onOpenAgent, onOpenQuestion, big }: {
  q: SurveyQuestionResult; index: number; filter: Filter; onFilter: (f: Filter) => void;
  respondents: ProbeAnswerRow[]; showRespondents: boolean; onOpenAgent: (id: string) => void; onOpenQuestion?: () => void; big?: boolean;
}) {
  const sel = filter?.value ?? null;
  return (
    <div className={`rounded-xl border bg-card/40 p-4 space-y-3 ${q.primary ? "border-primary/30" : "border-border/60"}`}>
      <div className="flex items-baseline justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs text-muted-foreground">{index + 1} · {q.type === "yesno" ? "yes / no" : q.type}{q.primary ? " · primary" : ""}</div>
          <div className={`${big ? "text-sm" : "text-xs"} text-foreground/95 leading-relaxed`}>{q.text}</div>
        </div>
        <span className="text-[11px] text-muted-foreground tabular-nums shrink-0">{q.n} answered</span>
      </div>

      {(q.type === "single" || q.type === "yesno") && q.distribution && (
        <Donut rows={q.distribution} selected={sel} onSelect={(v) => onFilter(v ? { q: q.key, value: v } : null)} />
      )}
      {q.type === "multi" && q.distribution && (
        <OptionBars rows={q.distribution} selected={sel} onSelect={(v) => onFilter(v ? { q: q.key, value: v } : null)} />
      )}
      {(q.type === "scale" || q.type === "number") && q.distribution && (
        <div>
          <Histogram rows={q.distribution} mean={q.mean?.mean} selected={sel} onSelect={(v) => onFilter(v ? { q: q.key, value: v } : null)} />
          {q.mean && (
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground tabular-nums mt-1">
              <span>mean <span className="text-foreground/90">{q.mean.mean}</span> (CI {q.mean.low}–{q.mean.high})</span>
              <span>median {q.mean.median}</span>
              {q.top_two_box && <span>top two <span className="text-foreground/90">{pct(q.top_two_box.share)}</span></span>}
              {q.bottom_two_box && <span>bottom two <span className="text-foreground/90">{pct(q.bottom_two_box.share)}</span></span>}
            </div>
          )}
        </div>
      )}
      {q.type === "grid" && q.rows && q.columns && (
        <StackedRows rows={q.rows} columns={q.columns} selected={filter?.row ? { row: filter.row, value: filter.value } : null}
          onSelect={(s) => onFilter(s ? { q: q.key, value: s.value, row: s.row } : null)} />
      )}
      {q.type === "text" && (
        <div className="space-y-3">
          {q.themes && q.themes.length > 0 ? (
            <div>
              <div className="text-[11px] text-muted-foreground mb-1">Themes in the answers — click one</div>
              <div className="flex flex-wrap gap-1">
                {q.themes.map((t) => (
                  <button key={t.value} type="button" onClick={() => onFilter(sel === t.value ? null : { q: q.key, value: t.value })}
                    className={`text-[10px] rounded px-1.5 py-0.5 border ${sel === t.value ? "border-primary/60 text-primary bg-primary/10" : "border-border/60 text-muted-foreground hover:text-foreground"}`}>
                    {t.value} <span className="opacity-60">{pct(t.share)}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : <p className="text-[11px] text-muted-foreground">Themes are coded once the run finishes.</p>}
          {!showRespondents && q.responses && (
            <div className="space-y-1">
              {q.responses.slice(0, big ? 50 : 3).map((r) => (
                <p key={r.agent_id} className="text-xs text-foreground/75 leading-relaxed">
                  <button type="button" onClick={() => onOpenAgent(r.agent_id)} className="text-foreground/95 hover:text-primary">{r.name}</button>
                  <span className="text-muted-foreground"> · {r.role}</span>
                  {r.theme && <span className="ml-1.5 text-[10px] rounded px-1.5 py-0.5 bg-primary/10 text-primary/90">{r.theme}</span>}
                  {" "}— “{r.text}”
                </p>
              ))}
            </div>
          )}
        </div>
      )}

      <p className="text-[11px] text-foreground/60">{q.sentence}</p>

      {showRespondents && (
        <div className="border-t border-border/40 pt-2">
          <div className="text-[11px] text-muted-foreground mb-1">
            {filter ? <>Who answered <span className="text-foreground/90">{filter.row ? `${filter.row}: ` : ""}{filter.value}</span> · {respondents.length}</> : <>Every response · {respondents.length}</>}
            {filter && <button type="button" onClick={() => onFilter(null)} className="ml-2 text-muted-foreground hover:text-foreground">clear</button>}
          </div>
          <div className="space-y-1 max-h-72 overflow-y-auto pr-1">
            {respondents.length === 0 && <p className="text-xs text-muted-foreground">Responses load when the run is opened.</p>}
            {respondents.map((r) => (
              <div key={r.agent_id} className="text-xs leading-relaxed">
                <button type="button" onClick={() => onOpenAgent(r.agent_id)} className="text-foreground/95 hover:text-primary">{r.name}</button>
                <span className="text-muted-foreground"> · {r.role}</span>
                <span className="ml-2 text-[10px] rounded px-1.5 py-0.5 bg-muted text-foreground/80">{display(q, r.answer?.[q.key])}</span>
                {q.type === "text" && r.answer?.[`${q.key}__theme`] && <span className="ml-1 text-[10px] rounded px-1.5 py-0.5 bg-primary/10 text-primary/90">{r.answer[`${q.key}__theme`]}</span>}
                {q.type !== "text" && r.reasoning && <p className="text-muted-foreground/80 text-[11px] truncate">“{r.reasoning}”</p>}
              </div>
            ))}
          </div>
        </div>
      )}
      {!showRespondents && onOpenQuestion && (
        <button type="button" onClick={onOpenQuestion} className="text-[11px] text-muted-foreground hover:text-foreground">see every response →</button>
      )}
      {q.type === "text" && q.themes && q.themes.length > 0 && !showRespondents && (
        <CategoryBars rows={q.themes} title="" />
      )}
    </div>
  );
}

function IndividualForm({ row, questions }: { row: ProbeAnswerRow | undefined; questions: SurveyQuestionResult[] }) {
  if (!row) return <p className="text-xs text-muted-foreground">Pick a persona.</p>;
  return (
    <div className="rounded-xl border border-border/60 bg-card/40 p-4 space-y-3">
      <div>
        <div className="text-sm text-foreground">{row.name}</div>
        <div className="text-[11px] text-muted-foreground">{row.role} · {Object.entries(row.segments || {}).slice(0, 3).map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`).join(" · ")}</div>
      </div>
      {row.reasoning && <p className="text-xs text-foreground/75 leading-relaxed border-l-2 border-primary/40 pl-2.5">“{row.reasoning}”</p>}
      <div className="space-y-2.5">
        {questions.map((q, i) => (
          <div key={q.key}>
            <div className="text-[11px] text-muted-foreground">{i + 1}. {q.text}</div>
            <div className="text-xs text-foreground/90">
              {q.type === "grid" && typeof row.answer?.[q.key] === "object" && row.answer[q.key]
                ? q.rows?.map((r) => <span key={r.key} className="inline-block mr-3">{r.label}: <span className="text-foreground/70">{String(row.answer[q.key][r.key] ?? "—")}</span></span>)
                : display(q, row.answer?.[q.key])}
              {q.type === "text" && row.answer?.[`${q.key}__theme`] && <span className="ml-1.5 text-[10px] rounded px-1.5 py-0.5 bg-primary/10 text-primary/90">{row.answer[`${q.key}__theme`]}</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
