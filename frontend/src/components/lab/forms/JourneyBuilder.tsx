"use client";

/** The Journey tool's own input panel (brief L7-01): the ordered steps a person passes through
 *  on the way to the outcome in the question. Proposed by the backend from what the session
 *  knows the first time the tool is opened; the analyst renames, reorders, adds or removes steps
 *  before running. The last step is the outcome itself. */

import { useEffect, useState } from "react";
import { ArrowDown, ArrowUp, Plus, Sparkles, X } from "lucide-react";
import { api, JourneyDenominator, JourneyStage } from "@/lib/api";
import { InstrumentFormProps } from "./index";

const CONTROL = "w-full bg-input border border-border rounded-lg px-2.5 py-1.5 text-xs text-foreground";

export default function JourneyBuilder({ values, onChange, sessionId, context }: InstrumentFormProps) {
  const pastOutcomes = (context?.pastOutcomes || []).filter(Boolean);
  const stages: JourneyStage[] = Array.isArray(values.stages) ? values.stages : [];
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [basis, setBasis] = useState<{ outcome: string; basis: string; grounded: boolean } | null>(null);
  // Headcounts (brief L7-02): the in-scope slice the frame offers, or the analyst's own figure with a source.
  const [frameDenominator, setFrameDenominator] = useState<JourneyDenominator | null | undefined>(undefined);
  const [ownFigure, setOwnFigure] = useState<boolean>(Boolean(values.denominator?.people));
  const [knownOpen, setKnownOpen] = useState<Record<number, boolean>>({});
  const den = (values.denominator || {}) as { people?: string; source?: string; label?: string };
  const setDen = (patch: Partial<{ people: string; source: string; label: string }>) => onChange("denominator", { ...den, ...patch });
  const setStages = (s: JourneyStage[]) => onChange("stages", s.map((x, i) => ({ ...x, key: `step${i + 1}` })));

  const propose = async () => {
    if (!sessionId) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.lab.journeySuggest(sessionId);
      setStages(r.stages);
      setBasis({ outcome: r.outcome, basis: r.basis, grounded: r.grounded });
      setFrameDenominator(r.denominator || null);
    } catch (e: any) {
      setError(e?.message || "Could not propose the journey");
    } finally {
      setBusy(false);
    }
  };

  // First open: propose the journey rather than showing an empty list.
  useEffect(() => {
    if (stages.length === 0 && sessionId && !busy && !error) void propose();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const update = (i: number, patch: Partial<JourneyStage>) => setStages(stages.map((s, k) => (k === i ? { ...s, ...patch } : s)));
  const move = (i: number, d: -1 | 1) => {
    const j = i + d;
    if (j < 0 || j >= stages.length) return;
    const next = [...stages];
    [next[i], next[j]] = [next[j], next[i]];
    setStages(next);
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-xs text-muted-foreground">The journey · first step to the outcome</label>
        <button type="button" onClick={propose} disabled={busy || !sessionId}
          className="flex items-center gap-1 text-[11px] text-primary hover:underline disabled:opacity-50">
          <Sparkles className="w-3 h-3" /> {busy ? "Proposing…" : stages.length ? "Propose again" : "Propose"}
        </button>
      </div>
      {busy && stages.length === 0 && <p className="text-[11px] text-muted-foreground/70">Reading the question, the evidence and the frame to propose the steps…</p>}
      {error && <p className="text-[11px] text-red-400">{error}</p>}
      {stages.length > 0 && pastOutcomes.length > 0 && !pastOutcomes.some((o) => o.trim().toLowerCase() === String(stages[stages.length - 1]?.label || "").trim().toLowerCase()) && (
        <p className="text-[10px] text-amber-300/85 leading-snug rounded-lg border border-amber-400/30 bg-amber-500/5 px-2 py-1.5">
          Earlier runs of this tool ended at &ldquo;{pastOutcomes[0]}&rdquo;. A differently worded last step is a new journey: the report will show both, and Compare runs will not line them up. Keep the same steps to compare like with like.
        </p>
      )}
      {basis && (
        <p className="text-[10px] text-muted-foreground/70">
          Outcome: <span className="text-foreground/80">{basis.outcome}</span>
          {basis.basis ? <> · drawn from: {basis.basis}</> : null}
          {!basis.grounded && <> · <span className="text-yellow-300/80">no material gathered yet — from the question alone</span></>}
        </p>
      )}
      <ol className="space-y-1.5">
        {stages.map((s, i) => (
          <li key={s.key || i} className="rounded-lg border border-border/50 bg-card/30 p-2 space-y-1">
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-muted-foreground tabular-nums w-4">{i + 1}.</span>
              <input value={s.label} onChange={(e) => update(i, { label: e.target.value })} placeholder="The step, in 2-5 words" className={CONTROL} />
              <button type="button" onClick={() => move(i, -1)} disabled={i === 0} title="Move up" className="text-muted-foreground hover:text-foreground disabled:opacity-30"><ArrowUp className="w-3 h-3" /></button>
              <button type="button" onClick={() => move(i, 1)} disabled={i === stages.length - 1} title="Move down" className="text-muted-foreground hover:text-foreground disabled:opacity-30"><ArrowDown className="w-3 h-3" /></button>
              <button type="button" onClick={() => setStages(stages.filter((_, k) => k !== i))} title="Remove" className="text-muted-foreground hover:text-red-400"><X className="w-3 h-3" /></button>
            </div>
            <input value={s.definition || ""} onChange={(e) => update(i, { definition: e.target.value })} placeholder="Who counts as having reached it (one line)"
              className={`${CONTROL} ml-5 w-[calc(100%-1.25rem)] text-[11px] text-foreground/80`} />
            {knownOpen[i] || s.people ? (
              <div className="ml-5 flex items-center gap-1.5">
                <input value={s.people ?? ""} onChange={(e) => update(i, { people: e.target.value })} placeholder="known headcount, e.g. 20,000" inputMode="numeric"
                  className={`${CONTROL} w-36 text-[11px] tabular-nums`} title="A figure you know for this step: held fixed, the steps after it scaled from it" />
                <input value={s.people_source || ""} onChange={(e) => update(i, { people_source: e.target.value })} placeholder="its source (required)"
                  className={`${CONTROL} flex-1 text-[11px]`} />
                <button type="button" onClick={() => { update(i, { people: "", people_source: "" }); setKnownOpen((k) => ({ ...k, [i]: false })); }} title="Clear" className="text-muted-foreground hover:text-red-400"><X className="w-3 h-3" /></button>
              </div>
            ) : (
              <button type="button" onClick={() => setKnownOpen((k) => ({ ...k, [i]: true }))} className="ml-5 text-[10px] text-muted-foreground/60 hover:text-foreground">+ known headcount at this step</button>
            )}
          </li>
        ))}
      </ol>
      <button type="button" onClick={() => setStages([...stages, { key: "", label: "", definition: "" }])} disabled={stages.length >= 8}
        className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-40">
        <Plus className="w-3 h-3" /> Add a step
      </button>
      <p className="text-[10px] text-muted-foreground/60">
        3 to 8 steps. Every twin says the furthest step it (or the people it serves) has actually reached and whether the next one will happen; each step where twins are stuck becomes a candidate outcome.
      </p>

      {/* Headcounts (brief L7-02): the denominator the shares are multiplied through. Never guessed. */}
      <div className="rounded-lg border border-border/50 bg-card/30 p-2.5 space-y-1.5">
        <div className="flex items-center justify-between">
          <label className="text-xs text-muted-foreground">People in scope · for headcounts</label>
          <label className="flex items-center gap-1 text-[10px] text-muted-foreground cursor-pointer">
            <input type="checkbox" checked={ownFigure} onChange={(e) => { setOwnFigure(e.target.checked); if (!e.target.checked) onChange("denominator", undefined); }} className="accent-primary" />
            type my own
          </label>
        </div>
        {!ownFigure && (
          frameDenominator === undefined
            ? <p className="text-[10px] text-muted-foreground/60">Reading the frame&apos;s sizing figures…</p>
            : frameDenominator
              ? <p className="text-[11px] text-foreground/85">≈<span className="tabular-nums">{frameDenominator.people.toLocaleString()}</span> <span className="text-muted-foreground">· {frameDenominator.label}{frameDenominator.source ? ` · ${frameDenominator.source}` : ""}{frameDenominator.year ? ` ${frameDenominator.year}` : ""} · <span className="text-sky-300/80">official statistic</span></span></p>
              : <p className="text-[10px] text-yellow-300/70">No sizing figure on file for this population (the Studio found no in-scope headcount). The result will show shares only unless you type a figure with its source.</p>
        )}
        {ownFigure && (
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <input value={den.people ?? ""} onChange={(e) => setDen({ people: e.target.value })} placeholder="e.g. 141,000" inputMode="numeric" className={`${CONTROL} w-32 tabular-nums`} />
              <input value={den.label ?? ""} onChange={(e) => setDen({ label: e.target.value })} placeholder="what it counts (adults with…)" className={`${CONTROL} flex-1`} />
            </div>
            <input value={den.source ?? ""} onChange={(e) => setDen({ source: e.target.value })} placeholder="source (required) — e.g. client channel data, 2025" className={CONTROL} />
            <p className="text-[10px] text-pink-300/70">Labelled client supplied on every result and export.</p>
          </div>
        )}
      </div>
    </div>
  );
}
