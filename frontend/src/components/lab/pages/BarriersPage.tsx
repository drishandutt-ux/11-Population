"use client";

/** Barriers' own results page (brief L6-05): what stands in the way of an outcome, ranked. A
 *  plain list — barrier, how many twins, a bar for its weight. Open one for the twins who raised
 *  it in their own words, what they say would remove it, and the evidence those twins could see.
 *  The same "Read by" picker as the Verdict, so the ranking can be compared cut by cut. */

import { useMemo, useState } from "react";
import { ShareBar, pct } from "../Charts";
import { segmentLabel } from "../filters";
import ConfidenceBadge from "@/components/ConfidenceBadge";
import { InstrumentPageProps } from "./types";

const SPLIT_ORDER = ["deprivation", "stance", "age_band", "segment", "region", "income_band", "gender", "education", "humanity_band", "purchase_intent_prior"];
const rankOf = (v: string) => { const m = v.match(/^[QD](\d{1,2})/i); return m ? parseInt(m[1], 10) : 99; };

type Twin = { agent_id: string; name: string; role: string; blocked: string; barrier: string; removal: string; weight: number; reasoning: string; deprivation?: string };
type Barrier = { theme: string; count: number; share: number; low: number; high: number; weight_mean: number; score: number;
  removals: { value: string; count: number; share: number }[]; agent_ids: string[]; twins: Twin[];
  evidence: { unit_id: string; source_ref: string; provenance_class: string; trust_tier: string; text: string; twins: number; route: string }[] };

export default function BarriersPage({ probe, dynamicDials = [], agentsById = {} }: InstrumentPageProps) {
  const a: any = probe.aggregates;
  const answers = probe.answers || [];
  const [segKey, setSegKey] = useState("");
  const [segValue, setSegValue] = useState("");
  const [open, setOpen] = useState<string | null>(null);

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
  const cutIds = useMemo(() => new Set(answers.filter((r) => !filtered || r.segments?.[segKey] === segValue).map((r) => r.agent_id)), [answers, filtered, segKey, segValue]);

  // The ranking for the cut: recount each barrier over the twins in the cut (the stored answers
  // carry the coded barrier, so no call is needed).
  const ranked: Barrier[] = useMemo(() => {
    const all: Barrier[] = a?.barriers || [];
    if (!filtered) return all;
    const n = cutIds.size || 1;
    return all
      .map((b) => {
        const twins = (answers.filter((r) => cutIds.has(r.agent_id) && b.agent_ids.includes(r.agent_id)).map((r) => ({
          agent_id: r.agent_id, name: r.name, role: r.role, blocked: r.answer?.blocked, barrier: r.answer?.barrier, removal: r.answer?.removal,
          weight: r.answer?.weight || 0, reasoning: r.reasoning, deprivation: r.segments?.deprivation,
        })) as Twin[]).sort((x, y) => y.weight - x.weight);
        const w = twins.length ? twins.reduce((s, t) => s + t.weight, 0) / twins.length : 0;
        return { ...b, count: twins.length, share: twins.length / n, low: 0, high: 0, weight_mean: Math.round(w * 10) / 10, twins, agent_ids: twins.map((t) => t.agent_id) };
      })
      .filter((b) => b.count > 0)
      .sort((x, y) => y.count - x.count || y.weight_mean - x.weight_mean);
  }, [a, answers, cutIds, filtered]);

  if (!a || !a.n) return null;
  const maxCount = Math.max(1, ...ranked.map((b) => b.count));
  const blockedInCut = answers.filter((r) => cutIds.has(r.agent_id) && ["yes", "partly"].includes(r.answer?.blocked)).length;

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
                  className={`text-[11px] px-2 py-0.5 rounded-full border ${on ? "border-primary/60 text-primary bg-primary/10" : "border-border text-muted-foreground hover:text-foreground"}`}>
                  {v} <span className="opacity-60">{n}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="rounded-xl border border-border/60 bg-card/40 p-4">
        {a.outcome && <p className="text-xs text-muted-foreground mb-3">Outcome: “{a.outcome}”</p>}
        {filtered ? (
          <>
            <div className="text-[11px] text-muted-foreground mb-1">{segmentLabel(segKey, dynamicDials)} · <span className="text-foreground/85">{segValue}</span> · {cutIds.size} of {answers.length} twins</div>
            <div className="text-2xl font-semibold tabular-nums">{pct(cutIds.size ? blockedInCut / cutIds.size : 0)} <span className="text-xs font-normal text-muted-foreground">see a barrier ({blockedInCut} of {cutIds.size})</span></div>
            {cutIds.size < 8 && <p className="text-[11px] text-yellow-300/80 mt-1">Small cut: read the counts, not the shares.</p>}
          </>
        ) : (
          <>
            <ShareBar value={a.headline} label="See a barrier" />
            <p className="text-xs text-foreground/70 mt-3 leading-relaxed">{a.sentence}</p>
          </>
        )}
      </div>

      <div>
        <div className="text-xs text-muted-foreground mb-2">
          What&apos;s in the way, ranked{filtered ? <> for <span className="text-foreground/85">{segValue}</span></> : null}
          <span className="text-muted-foreground/60"> — by how many named it, then how much it matters · click one</span>
        </div>
        {ranked.length === 0 && <p className="text-xs text-muted-foreground/70">Nobody in this cut named a barrier.</p>}
        <ol className="space-y-1.5">
          {ranked.map((b, k) => {
            const isOpen = open === b.theme;
            return (
              <li key={b.theme} className={`rounded-lg border ${isOpen ? "border-primary/40" : "border-border/50"} bg-card/30`}>
                <button type="button" onClick={() => setOpen(isOpen ? null : b.theme)} className="w-full text-left px-3 py-2">
                  <div className="flex items-center gap-3 text-xs">
                    <span className="w-5 text-muted-foreground tabular-nums">{k + 1}.</span>
                    <span className="flex-1 text-foreground/95 font-medium first-letter:uppercase">{b.theme}</span>
                    <span className="text-muted-foreground tabular-nums">{b.count} twin{b.count === 1 ? "" : "s"} · {pct(b.share)}</span>
                    <span className="text-muted-foreground/70 tabular-nums w-20 text-right">weight {Math.round(b.weight_mean)}/100</span>
                  </div>
                  <div className="flex items-center gap-2 mt-1.5 pl-8">
                    <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
                      <div className="h-full bg-primary/70 rounded-full" style={{ width: `${Math.round((b.count / maxCount) * 100)}%` }} />
                    </div>
                    {b.removals?.length > 0 && <span className="text-[10px] text-muted-foreground/70 truncate max-w-[45%]">removed by: {b.removals.map((r) => r.value).join(" · ")}</span>}
                  </div>
                </button>
                {isOpen && (
                  <div className="px-3 pb-3 pl-11 space-y-3">
                    <div className="space-y-1.5">
                      <div className="text-[10px] uppercase tracking-wide text-muted-foreground/60">Who raised it — most weight first</div>
                      {b.twins.map((t) => (
                        <div key={t.agent_id} className="text-xs">
                          <span className="text-foreground/95 font-medium">{t.name}</span>
                          <span className="text-muted-foreground"> · {t.role}</span>
                          {t.deprivation && <span className="text-muted-foreground/70"> · {t.deprivation}</span>}
                          <span className="text-muted-foreground/70"> · {t.weight}/100</span>
                          {" "}<ConfidenceBadge validation={agentsById[t.agent_id]?.validation} size="xs" />
                          <div className="text-foreground/80 mt-0.5">“{t.barrier}”{t.removal ? <span className="text-muted-foreground"> — would be removed by: {t.removal}</span> : null}</div>
                          {t.reasoning && <div className="text-[11px] text-foreground/60 leading-relaxed">{t.reasoning}</div>}
                        </div>
                      ))}
                    </div>
                    {b.evidence?.length > 0 ? (
                      <div className="space-y-1">
                        <div className="text-[10px] uppercase tracking-wide text-muted-foreground/60">Evidence these twins could see that speaks to it</div>
                        {b.evidence.map((e) => (
                          <div key={e.unit_id} className="text-[11px] text-foreground/75 leading-snug">
                            <span className="text-muted-foreground">{e.provenance_class.replace(/_/g, " ")} · trust {e.trust_tier} · {e.twins} of these twins</span>
                            <div>{e.text}</div>
                            {e.source_ref && <div className="text-[10px] text-muted-foreground/60 truncate">{e.source_ref}</div>}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-[10px] text-muted-foreground/60">No scoped evidence traced to this barrier{a.barriers_coded ? "" : " yet"}.</p>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      </div>

      <p className="text-[10px] text-muted-foreground/60">
        Barriers are the twins&apos; own words coded into at most seven shared labels after the run. The report may only name barriers from this list, in this order.
      </p>
    </div>
  );
}
