"use client";

/** The Journey tool's own input panel (brief L7-01): the ordered steps a person passes through
 *  on the way to the outcome in the question. Proposed by the backend from what the session
 *  knows the first time the tool is opened; the analyst renames, reorders, adds or removes steps
 *  before running. The last step is the outcome itself. */

import { useEffect, useState } from "react";
import { ArrowDown, ArrowUp, Plus, Sparkles, X } from "lucide-react";
import { api, JourneyStage } from "@/lib/api";
import { InstrumentFormProps } from "./index";

const CONTROL = "w-full bg-input border border-border rounded-lg px-2.5 py-1.5 text-xs text-foreground";

export default function JourneyBuilder({ values, onChange, sessionId }: InstrumentFormProps) {
  const stages: JourneyStage[] = Array.isArray(values.stages) ? values.stages : [];
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [basis, setBasis] = useState<{ outcome: string; basis: string; grounded: boolean } | null>(null);
  const setStages = (s: JourneyStage[]) => onChange("stages", s.map((x, i) => ({ ...x, key: `step${i + 1}` })));

  const propose = async () => {
    if (!sessionId) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.lab.journeySuggest(sessionId);
      setStages(r.stages);
      setBasis({ outcome: r.outcome, basis: r.basis, grounded: r.grounded });
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
    </div>
  );
}
