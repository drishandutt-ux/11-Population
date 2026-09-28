"use client";

/** The Verdict's own results page: every twin's position on the session question, readable by
 *  any cut of the population. Pick a segment (deprivation first — equity by default, L6-04) and
 *  a value, and the headline, the position mix and the twins' own words narrow to that cut, so
 *  "why would the most deprived say yes?" is answered by the twins who did. */

import { useMemo, useState } from "react";
import { CategoryBars, SegmentTable, ShareBar, pct } from "../Charts";
import { segmentLabel } from "../filters";
import ConfidenceBadge from "@/components/ConfidenceBadge";
import { InstrumentPageProps } from "./types";

const POSITIONS = ["for", "mixed", "against"] as const;
type Position = (typeof POSITIONS)[number];
const POSITION_TONE: Record<Position, string> = {
  for: "border-emerald-500/40 text-emerald-300 bg-emerald-500/10",
  mixed: "border-yellow-500/40 text-yellow-300 bg-yellow-500/10",
  against: "border-red-500/40 text-red-300 bg-red-500/10",
};
/** Equity first, then the population's own splits, then the question's dials. */
const SPLIT_ORDER = ["deprivation", "stance", "age_band", "segment", "region", "income_band", "gender", "education", "humanity_band", "purchase_intent_prior"];

/** Wilson interval, the same one the backend uses for every share. */
function wilson(k: number, n: number): { share: number; low: number; high: number } {
  if (!n) return { share: 0, low: 0, high: 0 };
  const z = 1.96, p = k / n, d = 1 + (z * z) / n;
  const c = (p + (z * z) / (2 * n)) / d, h = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / d;
  return { share: p, low: Math.max(0, c - h), high: Math.min(1, c + h) };
}

function rankOf(v: string): number {
  const m = v.match(/^[QD](\d{1,2})/i);
  return m ? parseInt(m[1], 10) : 99;
}

export default function VerdictPage({ probe, dynamicDials = [], agentsById = {} }: InstrumentPageProps) {
  const a: any = probe.aggregates;
  const answers = probe.answers || [];
  const [segKey, setSegKey] = useState<string>("");
  const [segValue, setSegValue] = useState<string>("");
  const [position, setPosition] = useState<Position | "">("");

  // Which cuts exist on this population, in a fixed order; a dynamic dial reads as its own name.
  const splitKeys = useMemo(() => {
    const keys = new Set<string>();
    answers.forEach((r) => Object.keys(r.segments || {}).forEach((k) => keys.add(k)));
    const known = SPLIT_ORDER.filter((k) => keys.has(k));
    const rest = [...keys].filter((k) => !SPLIT_ORDER.includes(k)).sort();
    return [...known, ...rest];
  }, [answers]);
  const valuesFor = (key: string) => {
    const vs = new Set<string>();
    answers.forEach((r) => { const v = r.segments?.[key]; if (v) vs.add(v); });
    return [...vs].sort((x, y) => (key === "deprivation" ? rankOf(x) - rankOf(y) : x.localeCompare(y)));
  };

  // The cut: the rows the segment filter keeps, before the position filter.
  const cut = useMemo(() => answers.filter((r) => !segKey || !segValue || r.segments?.[segKey] === segValue), [answers, segKey, segValue]);
  const shown = useMemo(() => cut.filter((r) => !position || r.answer?.position === position)
    .slice().sort((x, y) => (y.answer?.confidence || 0) - (x.answer?.confidence || 0)), [cut, position]);
  const counts = POSITIONS.map((p) => ({ value: p, count: cut.filter((r) => r.answer?.position === p).length }))
    .map((c) => ({ ...c, share: cut.length ? c.count / cut.length : 0 }));
  const forShare = wilson(counts[0].count, cut.length);
  const filtered = Boolean(segKey && segValue);

  if (!a || !a.n) return null;
  const question = probe.spec?.question;

  return (
    <div className="space-y-5">
      {/* The cut picker: deprivation first, then any split the population carries. */}
      <div className="rounded-xl border border-border/60 bg-card/40 p-3 flex flex-wrap items-center gap-2">
        <span className="text-[11px] text-muted-foreground">Read by</span>
        <select value={segKey} onChange={(e) => { setSegKey(e.target.value); setSegValue(""); }}
          className="bg-input border border-border rounded-lg px-2 py-1 text-xs text-foreground" aria-label="Segment">
          <option value="">everyone</option>
          {splitKeys.map((k) => <option key={k} value={k}>{segmentLabel(k, dynamicDials)}</option>)}
        </select>
        {segKey && (
          <div className="flex flex-wrap gap-1">
            {valuesFor(segKey).map((v) => {
              const n = answers.filter((r) => r.segments?.[segKey] === v).length;
              const on = segValue === v;
              return (
                <button key={v} type="button" onClick={() => setSegValue(on ? "" : v)}
                  className={`text-[11px] px-2 py-0.5 rounded-full border ${on ? "border-primary/60 text-primary bg-primary/10" : "border-border text-muted-foreground hover:text-foreground"}`}>
                  {v} <span className="opacity-60">{n}</span>
                </button>
              );
            })}
          </div>
        )}
        <span className="ml-auto flex gap-1">
          {POSITIONS.map((p) => (
            <button key={p} type="button" onClick={() => setPosition(position === p ? "" : p)}
              className={`text-[11px] px-2 py-0.5 rounded-full border capitalize ${position === p ? POSITION_TONE[p] : "border-border text-muted-foreground hover:text-foreground"}`}>
              {p}
            </button>
          ))}
        </span>
      </div>

      <div className="rounded-xl border border-border/60 bg-card/40 p-4">
        {question && <p className="text-xs text-muted-foreground mb-3">“{question}”</p>}
        {filtered ? (
          <>
            <div className="text-[11px] text-muted-foreground mb-1">{segmentLabel(segKey, dynamicDials)} · <span className="text-foreground/85">{segValue}</span> · {cut.length} of {answers.length} twins</div>
            <ShareBar value={forShare as any} label="In favour" />
            <p className="text-xs text-foreground/70 mt-3 leading-relaxed">
              {pct(forShare.share)} of these {cut.length} come down in favour ({counts[0].count} of {cut.length}); {pct(counts[2].share)} against, {pct(counts[1].share)} torn.
              {cut.length < 8 && <span className="text-yellow-300/80"> Small cut: read the interval, not the point.</span>}
            </p>
          </>
        ) : (
          <>
            <ShareBar value={a.headline} label="In favour" />
            <p className="text-xs text-foreground/70 mt-3 leading-relaxed">{a.sentence}</p>
          </>
        )}
      </div>

      <div className="grid grid-cols-2 gap-5">
        <CategoryBars rows={filtered ? counts : a.position} title={filtered ? `Position · ${segValue}` : "Position"} />
        {a.confidence && (
          <div className="rounded-lg border border-border/60 bg-card/40 px-3 py-2 self-start">
            <div className="text-[11px] text-muted-foreground">How sure they are (0–100)</div>
            <div className="text-lg font-semibold tabular-nums">{Math.round(filtered ? (cut.reduce((s, r) => s + (r.answer?.confidence || 0), 0) / (cut.length || 1)) : a.confidence.mean)}</div>
            {!filtered && <div className="text-[10px] text-muted-foreground tabular-nums">CI {Math.round(a.confidence.low)}–{Math.round(a.confidence.high)}</div>}
          </div>
        )}
      </div>

      {a.segments && Object.keys(a.segments).length > 0 && (
        <div>
          <div className="text-xs text-muted-foreground mb-2">In favour, by cut <span className="text-muted-foreground/60">— click a heading to read that cut</span></div>
          <div className="grid grid-cols-2 gap-5">
            {[...Object.entries(a.segments)].sort(([x], [y]) => (SPLIT_ORDER.indexOf(x) + 1 || 99) - (SPLIT_ORDER.indexOf(y) + 1 || 99)).map(([key, rows]) => (
              <button key={key} type="button" onClick={() => { setSegKey(key); setSegValue(""); }}
                className={`text-left rounded-lg p-2 -m-2 hover:bg-muted/30 ${segKey === key ? "ring-1 ring-primary/40" : ""}`}>
                <SegmentTable title={segmentLabel(key, dynamicDials)} rows={(key === "deprivation" ? (rows as any[]).slice().sort((p, q) => rankOf(p.value) - rankOf(q.value)) : rows) as any} />
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="space-y-2">
        <div className="text-xs text-muted-foreground">
          In their own words · {shown.length} twin{shown.length === 1 ? "" : "s"}
          {filtered && <> in <span className="text-foreground/85">{segValue}</span></>}
          {position && <> who are <span className="text-foreground/85">{position}</span></>}
          <span className="text-muted-foreground/60"> — most confident first</span>
        </div>
        {shown.length === 0 && <p className="text-xs text-muted-foreground/70">Nobody in this cut.</p>}
        <div className="space-y-2">
          {shown.map((r) => {
            const p = (r.answer?.position || "") as Position;
            return (
              <div key={r.agent_id} className="rounded-lg border border-border/50 bg-card/30 px-3 py-2">
                <div className="flex flex-wrap items-center gap-1.5 text-xs">
                  <span className="w-5 h-5 rounded-md flex items-center justify-center text-[10px] font-bold text-white" style={{ backgroundColor: r.avatar_color }}>{(r.name || "?").charAt(0)}</span>
                  <span className="text-foreground/95 font-medium">{r.name}</span>
                  <span className="text-muted-foreground">· {r.role}</span>
                  {POSITION_TONE[p] && <span className={`text-[10px] px-1.5 py-px rounded border capitalize ${POSITION_TONE[p]}`}>{p}</span>}
                  <span className="text-[10px] text-muted-foreground/70">{r.answer?.confidence ?? 0}/100 sure</span>
                  {r.segments?.deprivation && <span className="text-[10px] px-1.5 py-px rounded border border-fuchsia-500/30 text-fuchsia-300 bg-fuchsia-500/10">{r.segments.deprivation}</span>}
                  <ConfidenceBadge validation={agentsById[r.agent_id]?.validation} size="xs" />
                </div>
                {r.answer?.verdict && <p className="text-xs text-foreground/90 mt-1">“{r.answer.verdict}”</p>}
                {r.reasoning && <p className="text-[11px] text-foreground/65 mt-0.5 leading-relaxed">{r.reasoning}</p>}
              </div>
            );
          })}
        </div>
      </div>

      <p className="text-[10px] text-muted-foreground/60">
        This is the report&apos;s headline outcome record. A cut recomputes from the stored answers; the report cites the whole population.
      </p>
    </div>
  );
}
