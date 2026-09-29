"use client";

/** The rule book (brief L4-02, the minimum of it): the session's calibration rules — what evidence
 *  shows a lever does to behaviour. A rule names the lever, who it applies to, which dials it moves
 *  and by how many points (bounded), the evidence it rests on, the basis, the author, and is signed
 *  off by name before the lever simulation (brief L7-04) will run against it. Nothing here is a
 *  hidden constant: every rule is listed, editable and exported in the run record. */

import { useEffect, useState } from "react";
import { Check, Pencil, Plus, Trash2, X } from "lucide-react";
import { api, CalibrationRule, RuleRequest } from "@/lib/api";

const CONTROL = "w-full bg-input border border-border rounded-lg px-2.5 py-1.5 text-xs text-foreground";
const APPLIES_KEYS: { key: string; label: string; options: string[] }[] = [
  { key: "deprivation", label: "Deprivation", options: ["Q1 most deprived", "Q2", "Q3", "Q4", "Q5 least deprived"] },
  { key: "stance", label: "Stance", options: ["direct", "indirect", "neutral"] },
  { key: "age_band", label: "Age", options: ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"] },
];

const EMPTY: RuleRequest = { lever: "", description: "", applies_to: {}, deltas: {}, bound: 4, evidence: [{ ref: "", note: "" }], basis: "", author: "" };

export default function RuleBook({ sessionId, initialLever, onClose, onChanged }: { sessionId: string; initialLever?: string; onClose: () => void; onChanged?: (rules: CalibrationRule[]) => void }) {
  const [rules, setRules] = useState<CalibrationRule[]>([]);
  const [dials, setDials] = useState<Record<string, string[]>>({});
  const [boundMax, setBoundMax] = useState(6);
  const [editing, setEditing] = useState<{ id?: string; form: RuleRequest } | null>(initialLever ? { form: { ...EMPTY, lever: initialLever } } : null);
  const [reviewer, setReviewer] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [group, setGroup] = useState("friction");

  const load = async () => {
    const r = await api.lab.rules(sessionId);
    setRules(r.rules); setDials(r.dials); setBoundMax(r.bound_max);
    onChanged?.(r.rules);
  };
  useEffect(() => { load().catch((e) => setError(e.message)); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [sessionId]);

  const save = async () => {
    if (!editing) return;
    setBusy(true); setError(null);
    try {
      const body: RuleRequest = { ...editing.form, evidence: editing.form.evidence.filter((e) => e.ref.trim()), deltas: Object.fromEntries(Object.entries(editing.form.deltas).filter(([, v]) => Number(v) !== 0)) };
      if (editing.id) await api.lab.updateRule(sessionId, editing.id, body); else await api.lab.createRule(sessionId, body);
      setEditing(null);
      await load();
    } catch (e: any) { setError(e?.message || "Could not save the rule"); } finally { setBusy(false); }
  };
  const review = async (r: CalibrationRule, approve: boolean) => {
    setBusy(true); setError(null);
    try { await api.lab.reviewRule(sessionId, r.id, reviewer, approve); await load(); }
    catch (e: any) { setError(e?.message || "Could not review the rule"); } finally { setBusy(false); }
  };
  const remove = async (r: CalibrationRule) => {
    setBusy(true); setError(null);
    try { await api.lab.deleteRule(sessionId, r.id); await load(); }
    catch (e: any) { setError(e?.message || "Could not delete the rule"); } finally { setBusy(false); }
  };
  const f = editing?.form;
  const setF = (patch: Partial<RuleRequest>) => setEditing((cur) => (cur ? { ...cur, form: { ...cur.form, ...patch } } : cur));

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-start justify-center overflow-y-auto p-6" onClick={onClose}>
      <div className="w-full max-w-3xl rounded-xl border border-border bg-background shadow-xl p-5 space-y-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-sm font-medium">Rule book · calibration rules</div>
            <p className="text-[11px] text-muted-foreground mt-0.5">
              What the evidence shows a lever does to behaviour: who it applies to, which dials it moves and by how much, the evidence it rests on. A lever is simulated only against a rule someone has reviewed by name. Every rule is exported with the run.
            </p>
          </div>
          <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground"><X className="w-4 h-4" /></button>
        </div>
        {error && <p className="text-[11px] text-red-400">{error}</p>}

        {!editing && (
          <div className="space-y-2">
            {rules.length === 0 && <p className="text-xs text-muted-foreground/70">No rules yet. Nothing can be simulated until one is written and reviewed.</p>}
            {rules.map((r) => (
              <div key={r.id} className="rounded-lg border border-border/50 bg-card/30 p-3 space-y-1">
                <div className="flex items-center gap-2 text-xs">
                  <span className="font-medium text-foreground/95">{r.lever}</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${r.status === "reviewed" ? "border-emerald-400/40 text-emerald-300/90" : "border-yellow-400/40 text-yellow-300/90"}`}>
                    {r.status === "reviewed" ? `reviewed · ${r.reviewed_by}` : "draft · not yet reviewed"}
                  </span>
                  <span className="ml-auto flex items-center gap-2">
                    <button type="button" title="Edit (sends it back to draft)" onClick={() => setEditing({ id: r.id, form: { lever: r.lever, description: r.description, applies_to: r.applies_to, deltas: r.deltas, bound: r.bound, evidence: r.evidence.length ? r.evidence : [{ ref: "", note: "" }], basis: r.basis, author: r.author } })} className="text-muted-foreground hover:text-foreground"><Pencil className="w-3.5 h-3.5" /></button>
                    <button type="button" title="Delete" onClick={() => remove(r)} className="text-muted-foreground hover:text-red-400"><Trash2 className="w-3.5 h-3.5" /></button>
                  </span>
                </div>
                {r.description && <p className="text-[11px] text-foreground/80">{r.description}</p>}
                <p className="text-[11px] text-muted-foreground">
                  applies to: {Object.keys(r.applies_to || {}).length ? Object.entries(r.applies_to).map(([k, v]) => `${k} = ${(v as string[]).join(" / ")}`).join("; ") : "everyone"}
                  {" · "}dials: {Object.entries(r.deltas).map(([k, v]) => `${k} ${v > 0 ? "+" : ""}${v}`).join(", ")} (bound ±{r.bound})
                </p>
                <p className="text-[11px] text-muted-foreground">evidence: {r.evidence.map((e) => e.ref + (e.note ? ` — ${e.note}` : "")).join("; ")}{r.basis ? ` · basis: ${r.basis}` : ""}{r.author ? ` · by ${r.author}` : ""}</p>
                <div className="flex items-center gap-2 pt-1">
                  {r.status !== "reviewed" ? (
                    <>
                      <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="reviewer's name" className={`${CONTROL} w-44`} />
                      <button type="button" disabled={busy || !reviewer.trim()} onClick={() => review(r, true)} className="flex items-center gap-1 text-[11px] text-emerald-300/90 hover:underline disabled:opacity-40"><Check className="w-3 h-3" /> Sign off</button>
                    </>
                  ) : (
                    <button type="button" disabled={busy} onClick={() => review(r, false)} className="text-[11px] text-muted-foreground hover:text-foreground">Withdraw review</button>
                  )}
                </div>
              </div>
            ))}
            <button type="button" onClick={() => setEditing({ form: { ...EMPTY } })} className="flex items-center gap-1 text-[11px] text-primary hover:underline"><Plus className="w-3 h-3" /> Write a rule</button>
          </div>
        )}

        {editing && f && (
          <div className="space-y-2">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-[10px] text-muted-foreground">The lever</label>
                <input value={f.lever} onChange={(e) => setF({ lever: e.target.value })} placeholder="nurse phone line" className={CONTROL} />
              </div>
              <div>
                <label className="text-[10px] text-muted-foreground">Author</label>
                <input value={f.author} onChange={(e) => setF({ author: e.target.value })} placeholder="who wrote this rule" className={CONTROL} />
              </div>
            </div>
            <div>
              <label className="text-[10px] text-muted-foreground">The change, as the twins will read it</label>
              <textarea value={f.description} onChange={(e) => setF({ description: e.target.value })} rows={2} placeholder="A nurse phone line, weeks 4 to 12 of treatment, answered the same day" className={CONTROL} />
            </div>
            <div>
              <label className="text-[10px] text-muted-foreground">Who it applies to · leave empty for everyone</label>
              <div className="flex flex-wrap gap-1.5">
                {APPLIES_KEYS.map((k) => (
                  <div key={k.key} className="flex flex-wrap items-center gap-1 rounded-lg border border-border/40 px-2 py-1">
                    <span className="text-[10px] text-muted-foreground mr-1">{k.label}:</span>
                    {k.options.map((o) => {
                      const on = (f.applies_to[k.key] || []).includes(o);
                      return (
                        <button key={o} type="button" onClick={() => { const cur = f.applies_to[k.key] || []; const next = on ? cur.filter((x) => x !== o) : [...cur, o]; setF({ applies_to: { ...f.applies_to, [k.key]: next } }); }}
                          className={`px-1.5 py-0.5 rounded-full text-[10px] border ${on ? "border-primary bg-primary/15 text-foreground" : "border-border/60 text-muted-foreground"}`}>{o}</button>
                      );
                    })}
                  </div>
                ))}
              </div>
            </div>
            <div>
              <div className="flex items-center justify-between">
                <label className="text-[10px] text-muted-foreground">Dial changes · points on the 0–10 scale, each within the bound</label>
                <label className="text-[10px] text-muted-foreground flex items-center gap-1">bound ± <input type="number" min={1} max={boundMax} value={f.bound} onChange={(e) => setF({ bound: Number(e.target.value) })} className={`${CONTROL} w-14 tabular-nums`} /></label>
              </div>
              <div className="flex gap-1 flex-wrap mb-1">
                {Object.keys(dials).map((g) => <button key={g} type="button" onClick={() => setGroup(g)} className={`px-1.5 py-0.5 rounded-full text-[10px] border ${group === g ? "border-primary bg-primary/15 text-foreground" : "border-border/60 text-muted-foreground"}`}>{g}</button>)}
              </div>
              <div className="grid grid-cols-3 gap-1">
                {(dials[group] || []).map((d) => {
                  const key = `${group}.${d}`;
                  const v = f.deltas[key] ?? 0;
                  return (
                    <label key={key} className={`flex items-center justify-between gap-1 rounded border px-2 py-1 text-[11px] ${v ? "border-primary/40 bg-primary/5" : "border-border/40"}`}>
                      <span className="truncate text-foreground/80">{d.replace(/_/g, " ")}</span>
                      <input type="number" min={-f.bound} max={f.bound} value={v} onChange={(e) => setF({ deltas: { ...f.deltas, [key]: Number(e.target.value) } })} className="w-12 bg-input border border-border rounded px-1 py-0.5 text-[11px] tabular-nums text-right" />
                    </label>
                  );
                })}
              </div>
              {Object.entries(f.deltas).filter(([, v]) => v).length > 0 && <p className="text-[10px] text-muted-foreground mt-1">set: {Object.entries(f.deltas).filter(([, v]) => v).map(([k, v]) => `${k} ${v > 0 ? "+" : ""}${v}`).join(", ")}</p>}
            </div>
            <div>
              <label className="text-[10px] text-muted-foreground">Evidence it rests on</label>
              {f.evidence.map((e, i) => (
                <div key={i} className="flex gap-1 mb-1">
                  <input value={e.ref} onChange={(ev) => setF({ evidence: f.evidence.map((x, k) => (k === i ? { ...x, ref: ev.target.value } : x)) })} placeholder="source, title or URL" className={CONTROL} />
                  <input value={e.note} onChange={(ev) => setF({ evidence: f.evidence.map((x, k) => (k === i ? { ...x, note: ev.target.value } : x)) })} placeholder="what it shows" className={CONTROL} />
                </div>
              ))}
              <button type="button" onClick={() => setF({ evidence: [...f.evidence, { ref: "", note: "" }] })} className="text-[10px] text-muted-foreground hover:text-foreground">+ another source</button>
            </div>
            <div>
              <label className="text-[10px] text-muted-foreground">Basis · how the evidence sets these values</label>
              <input value={f.basis} onChange={(e) => setF({ basis: e.target.value })} placeholder="Discontinuation halves in the audit where a nurse line exists, so emotional resistance −3" className={CONTROL} />
            </div>
            <div className="flex items-center gap-2 pt-1">
              <button type="button" disabled={busy} onClick={save} className="px-3 py-1.5 rounded-lg bg-primary text-primary-foreground text-xs disabled:opacity-50">{editing.id ? "Save (back to draft)" : "Save as draft"}</button>
              <button type="button" onClick={() => setEditing(null)} className="text-xs text-muted-foreground hover:text-foreground">Cancel</button>
              <span className="text-[10px] text-muted-foreground/60 ml-auto">A saved rule must be signed off by a named reviewer before a lever can be simulated.</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
