"use client";

/** The Journey tool's own results page (brief L7-01): the funnel — share reaching each step —
 *  then the candidate outcomes ranked: the step where twins drop off, how many get through, how
 *  many are stuck, the barriers at that step and who raised them. The same "Read by" picker as
 *  the Verdict and Barriers pages: the funnel and the ranking are recounted inside the cut from
 *  the stored answers, so no call is needed. */

import { useMemo, useState } from "react";
import { DrewOn, pct } from "../Charts";
import { segmentLabel } from "../filters";
import ConfidenceBadge from "@/components/ConfidenceBadge";
import { InstrumentPageProps } from "./types";

const SPLIT_ORDER = ["deprivation", "stance", "age_band", "segment", "region", "income_band", "gender", "education", "humanity_band"];
const rankOf = (v: string) => { const m = v.match(/^[QD](\d{1,2})/i); return m ? parseInt(m[1], 10) : 99; };
const STUCK = ["unlikely", "no"];

type Stage = { key: string; label: string; definition?: string };
type Row = { agent_id: string; name: string; role: string; answer: Record<string, any>; reasoning?: string; segments?: Record<string, string> };
type Twin = { agent_id: string; name: string; role: string; answering_for: string; barrier: string; removal: string; weight: number; reasoning: string; deprivation?: string; used_units?: any[] };
type Barrier = { theme: string; count: number; weight_mean: number; removals: string[]; twins: Twin[]; evidence: any[] };
type Candidate = { id: string; step: number; from: Stage; to: Stage; n: number; through: number; stuck: number; conversion: number; low: number; high: number; barriers: Barrier[]; equity?: any; confidence?: { score: number; drivers: string[] } };

// Wilson interval, the same as the backend's, so a cut reads with its own uncertainty.
function wilson(k: number, n: number) {
  if (!n) return { share: 0, low: 0, high: 0 };
  const z = 1.96, p = k / n, d = 1 + (z * z) / n;
  const c = (p + (z * z) / (2 * n)) / d, h = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / d;
  return { share: p, low: Math.max(0, c - h), high: Math.min(1, c + h) };
}

function compute(rows: Row[], stages: Stage[], stored: Candidate[]) {
  const idx: Record<string, number> = {};
  stages.forEach((s, i) => { idx[s.key] = i; });
  const at = (r: Row) => (r.answer.reached in idx ? idx[r.answer.reached] : -1);
  const placed = rows.filter((r) => at(r) >= 0);
  const n = placed.length;
  const funnel = stages.map((s, k) => {
    const reached = placed.filter((r) => at(r) >= k).length;
    return { ...s, reached, atExactly: placed.filter((r) => at(r) === k).length, ...wilson(reached, n) };
  });
  const evidenceFor = (id: string, theme: string) => stored.find((c) => c.id === id)?.barriers.find((b) => b.theme === theme)?.evidence || [];
  const transitions: Candidate[] = [];
  for (let k = 0; k < stages.length - 1; k++) {
    const atRisk = placed.filter((r) => at(r) >= k);
    const through = atRisk.filter((r) => at(r) > k || (at(r) === k && r.answer.progress === "yes"));
    const stuck = atRisk.filter((r) => at(r) === k && STUCK.includes(r.answer.progress));
    const groups: Record<string, Row[]> = {};
    stuck.forEach((r) => { const key = String(r.answer.barrier__theme || r.answer.barrier || "").trim(); if (key) (groups[key] ||= []).push(r); });
    const id = `${stages[k].key}->${stages[k + 1].key}`;
    const barriers: Barrier[] = Object.entries(groups).map(([theme, rs]) => {
      const twins: Twin[] = rs.map((r) => ({ agent_id: r.agent_id, name: r.name, role: r.role, answering_for: r.answer.answering_for || "", barrier: r.answer.barrier || "",
        removal: r.answer.removal || "", weight: Number(r.answer.weight || 0), reasoning: r.reasoning || r.answer.reasoning || "", deprivation: r.segments?.deprivation, used_units: r.answer.used_units }))
        .sort((x, y) => y.weight - x.weight);
      const removals = [...new Set(rs.map((r) => String(r.answer.removal__theme || r.answer.removal || "").trim()).filter(Boolean))].slice(0, 4);
      return { theme, count: rs.length, weight_mean: twins.reduce((s, t) => s + t.weight, 0) / (twins.length || 1), removals, twins, evidence: evidenceFor(id, theme) };
    }).sort((x, y) => y.count - x.count || y.weight_mean - x.weight_mean);
    transitions.push({ id, step: k + 1, from: stages[k], to: stages[k + 1], n: atRisk.length, through: through.length, stuck: stuck.length, ...wilson(through.length, atRisk.length), conversion: atRisk.length ? through.length / atRisk.length : 0, barriers });
  }
  const candidates = transitions.filter((t) => t.stuck > 0).sort((x, y) => y.stuck - x.stuck || x.conversion - y.conversion || x.step - y.step);
  return { n, funnel, transitions, candidates, completed: wilson(placed.filter((r) => at(r) === stages.length - 1).length, n) };
}

export default function JourneyPage({ probe, dynamicDials = [], agentsById = {} }: InstrumentPageProps) {
  const a: any = probe.aggregates;
  const answers = (probe.answers || []) as unknown as Row[];
  const stages: Stage[] = a?.stages || [];
  const [segKey, setSegKey] = useState("");
  const [segValue, setSegValue] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [openBarrier, setOpenBarrier] = useState<string | null>(null);

  const splitKeys = useMemo(() => {
    const keys = new Set<string>();
    answers.forEach((r) => Object.keys(r.segments || {}).forEach((k) => keys.add(k)));
    return [...SPLIT_ORDER.filter((k) => keys.has(k)), ...[...keys].filter((k) => !SPLIT_ORDER.includes(k)).sort()];
  }, [answers]);
  const valuesFor = (key: string) => {
    const vs = new Set<string>();
    answers.forEach((r) => { const v = r.segments?.[key]; if (v) vs.add(v); });
    return [...vs].sort((x, y) => (key === "deprivation" ? rankOf(x) - rankOf(y) : x.localeCompare(y)));
  };
  const filtered = Boolean(segKey && segValue);
  const rows = useMemo(() => answers.filter((r) => !filtered || r.segments?.[segKey] === segValue), [answers, filtered, segKey, segValue]);
  const view = useMemo(() => compute(rows, stages, (a?.candidates || []) as Candidate[]), [rows, stages, a]);

  if (!a || !a.n || !stages.length) return null;
  const last = stages[stages.length - 1];
  const stored: Candidate[] = a.candidates || [];
  const equityFor = (id: string) => stored.find((c) => c.id === id)?.equity;

  return (
    <div className="space-y-5">
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
                  className={`px-2 py-0.5 rounded-full text-[11px] border ${on ? "border-primary bg-primary/15 text-foreground" : "border-border/60 text-muted-foreground hover:text-foreground"}`}>
                  {v} <span className="opacity-60">{n}</span>
                </button>
              );
            })}
          </div>
        )}
        <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">{view.n} twin{view.n === 1 ? "" : "s"}{filtered ? " in this cut" : ""}</span>
      </div>

      {/* The funnel: share of everyone who reached each step. */}
      <div className="rounded-xl border border-border/60 bg-card/40 p-4">
        <div className="text-xs text-muted-foreground mb-2">
          The journey{filtered ? <> for <span className="text-foreground/85">{segValue}</span></> : null}
          <span className="text-muted-foreground/60"> — share who have reached each step</span>
        </div>
        <div className="space-y-1.5">
          {view.funnel.map((f, k) => (
            <div key={f.key} className="flex items-center gap-3 text-xs">
              <span className="w-5 text-muted-foreground tabular-nums">{k + 1}.</span>
              <span className="w-44 truncate text-foreground/90" title={f.definition}>{f.label}</span>
              <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                <div className={`h-full rounded-full ${k === stages.length - 1 ? "bg-emerald-400/70" : "bg-primary/70"}`} style={{ width: `${Math.round(f.share * 100)}%` }} />
              </div>
              <span className="w-28 text-right text-muted-foreground tabular-nums">{pct(f.share)} <span className="opacity-60">({f.reached})</span></span>
            </div>
          ))}
        </div>
        <p className="text-[11px] text-foreground/70 mt-3 leading-relaxed">
          {!filtered && a.sentence
            ? a.sentence
            : <>{pct(view.completed.share)} reach &lsquo;{last.label}&rsquo; (±{Math.round(((view.completed.high - view.completed.low) / 2) * 100)} points) in this cut.</>}
        </p>
      </div>

      {/* The candidates: one per step where twins drop off, ranked. */}
      <div>
        <div className="text-xs text-muted-foreground mb-2">
          Candidate outcomes — where the population drops off
          <span className="text-muted-foreground/60"> · ranked by how many are stuck there, then by the size of the gap · click one</span>
        </div>
        {view.candidates.length === 0 && <p className="text-xs text-muted-foreground/70">Nobody in this cut reports being stuck at any step.</p>}
        <ol className="space-y-1.5">
          {view.candidates.map((c, k) => {
            const isOpen = open === c.id;
            const eq = !filtered ? equityFor(c.id) : null;
            const conf = stored.find((s) => s.id === c.id)?.confidence;
            return (
              <li key={c.id} className={`rounded-lg border ${isOpen ? "border-primary/40" : "border-border/50"} bg-card/30`}>
                <button type="button" onClick={() => setOpen(isOpen ? null : c.id)} className="w-full text-left px-3 py-2">
                  <div className="flex items-center gap-3 text-xs">
                    <span className="w-5 text-muted-foreground tabular-nums">{k + 1}.</span>
                    <span className="flex-1 text-foreground/95 font-medium">{c.from.label} <span className="text-muted-foreground font-normal">→</span> {c.to.label}</span>
                    <span className="text-muted-foreground tabular-nums">{pct(c.conversion)} get through <span className="opacity-60">({pct(c.low)}–{pct(c.high)})</span></span>
                    <span className="text-muted-foreground/80 tabular-nums w-24 text-right">{c.stuck} of {c.n} stuck</span>
                  </div>
                  <div className="flex items-center gap-2 mt-1.5 pl-8">
                    <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden flex">
                      <div className="h-full bg-primary/70" style={{ width: `${Math.round(c.conversion * 100)}%` }} />
                      <div className="h-full bg-red-400/60" style={{ width: `${Math.round((c.stuck / (c.n || 1)) * 100)}%` }} />
                    </div>
                    <span className="text-[10px] text-muted-foreground/70 truncate max-w-[50%]">
                      {c.barriers.length ? <>barriers: {c.barriers.slice(0, 3).map((b) => `${b.theme} (${b.count})`).join(" · ")}</> : "no barrier named"}
                    </span>
                  </div>
                  {(eq?.available || conf) && (
                    <div className="pl-8 mt-1 text-[10px] text-muted-foreground/70">
                      {eq?.available && <>Equity: {eq.most.label} {pct(eq.most.share ?? 0)} vs {eq.least.label} {pct(eq.least.share ?? 0)}{eq.gap != null ? ` · gap ${eq.gap > 0 ? "+" : ""}${eq.gap} pts` : ""} · {eq.significant ? "a real gap" : eq.significant === false ? "not distinguishable at this size" : "untested"}</>}
                      {conf && <>{eq?.available ? " · " : ""}confidence {conf.score}/100 · computed</>}
                    </div>
                  )}
                </button>
                {isOpen && (
                  <div className="px-3 pb-3 pl-11 space-y-3">
                    <p className="text-[11px] text-foreground/70">
                      Candidate outcome: <span className="text-foreground/90">share of those at &lsquo;{c.from.label}&rsquo; who reach &lsquo;{c.to.label}&rsquo;</span> — modelled at {pct(c.conversion)} today, so the gap is {pct(1 - c.conversion)} of {c.n}.
                    </p>
                    <div className="text-[10px] uppercase tracking-wide text-muted-foreground/60">What stops the next step — by how many named it, then weight</div>
                    {c.barriers.length === 0 && <p className="text-[11px] text-muted-foreground/70">The stuck twins named no barrier.</p>}
                    <ol className="space-y-1.5">
                      {c.barriers.map((b, j) => {
                        const bid = `${c.id}|${b.theme}`;
                        const bOpen = openBarrier === bid;
                        return (
                          <li key={b.theme} className="rounded-md border border-border/40 bg-card/20">
                            <button type="button" onClick={() => setOpenBarrier(bOpen ? null : bid)} className="w-full text-left px-2.5 py-1.5">
                              <div className="flex items-center gap-2 text-xs">
                                <span className="w-4 text-muted-foreground tabular-nums">{j + 1}.</span>
                                <span className="flex-1 text-foreground/90 first-letter:uppercase">{b.theme}</span>
                                <span className="text-muted-foreground tabular-nums">{b.count} twin{b.count === 1 ? "" : "s"} · weight {Math.round(b.weight_mean)}/100</span>
                              </div>
                              {b.removals.length > 0 && <div className="pl-6 text-[10px] text-muted-foreground/70">removed by: {b.removals.join(" · ")}</div>}
                            </button>
                            {bOpen && (
                              <div className="px-2.5 pb-2.5 pl-8 space-y-2">
                                {b.twins.map((t) => (
                                  <div key={t.agent_id} className="text-xs">
                                    <span className="text-foreground/95 font-medium">{t.name}</span>
                                    <span className="text-muted-foreground"> · {t.role}</span>
                                    {t.answering_for === "people I serve" && <span className="text-muted-foreground/70"> · for the people they serve</span>}
                                    {t.deprivation && <span className="text-muted-foreground/70"> · {t.deprivation}</span>}
                                    <span className="text-muted-foreground/70"> · {t.weight}/100</span>
                                    {" "}<ConfidenceBadge validation={agentsById[t.agent_id]?.validation} size="xs" />
                                    <div className="text-foreground/80 mt-0.5">“{t.barrier}”{t.removal ? <span className="text-muted-foreground"> — would be removed by: {t.removal}</span> : null}</div>
                                    {t.reasoning && <div className="text-[11px] text-foreground/60 leading-relaxed">{t.reasoning}</div>}
                                    <DrewOn units={t.used_units} />
                                  </div>
                                ))}
                                {b.evidence?.length > 0 && (
                                  <div className="space-y-1">
                                    <div className="text-[10px] uppercase tracking-wide text-muted-foreground/60">{b.evidence[0]?.basis === "could_see" ? "Evidence these twins could see that speaks to it (none cited)" : "Documents these twins drew on"}</div>
                                    {b.evidence.map((e: any) => (
                                      <div key={e.unit_id} className="text-[11px] text-foreground/75 leading-snug">
                                        <span className="text-muted-foreground">{String(e.provenance_class || "").replace(/_/g, " ")} · trust {e.trust_tier} · {e.basis === "could_see" ? "could see" : "cited by"} {e.twins} of these twins</span>
                                        <div>{e.text}</div>
                                        {e.source_ref && <div className="text-[10px] text-muted-foreground/60 truncate">{e.source_ref}</div>}
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            )}
                          </li>
                        );
                      })}
                    </ol>
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      </div>

      <p className="text-[10px] text-muted-foreground/60">
        Every number here is counted from the twins&apos; own placements; barriers are their words coded into shared labels after the run. The report may only name candidate outcomes from this list, in this order. Headcounts (L7-02) and movability (L7-03) are the next steps.
      </p>
    </div>
  );
}
