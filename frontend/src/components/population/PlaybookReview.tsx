"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api, Playbook, PlaybookLink, PlaybookVariable } from "@/lib/api";
import { X, Plus, Trash2, Download, Save, Check, Loader2, ArrowUp, ArrowDown } from "lucide-react";

const AXES = ["demographic", "behavioural", "value-based", "needs-based", "attitudinal", "other"];
const KIND_HINT: Record<PlaybookVariable["kind"], string> = {
  dial: "A degree every twin carries, 0–10: drawn inside its segment's range and pushing the standard dials below",
  category: "One label per twin, a cell on the population map",
  rule: "A behaviour, given to every twin as a rule of character",
};

export function downloadText(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

const fileName = (title: string) => `${(title || "playbook").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "playbook"}.md`;
const dialWords = (path: string) => path.split(".").slice(1).join(".").replace(/_/g, " ");

interface Props {
  playbook: Playbook;
  onClose: () => void;
  /** Use this playbook for the next build (and close). */
  onUse: (pb: Playbook) => void;
  /** Saved to the shared library (new or updated). */
  onSaved?: (pb: Playbook) => void;
}

/** "What I understood": the playbook as the Studio read it — approach, segments, each variable with
 *  where it lives and which standard dials it pushes, rules — all editable before anything is built. */
export default function PlaybookReview({ playbook, onClose, onUse, onSaved }: Props) {
  const [pb, setPb] = useState<Playbook>(playbook);
  const [dialPaths, setDialPaths] = useState<string[]>([]);
  const [busy, setBusy] = useState<"" | "save" | "download">("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { api.playbooks.dials().then((r) => setDialPaths(r.dial_paths)).catch(() => {}); }, []);

  const set = (patch: Partial<Playbook>) => { setPb((p) => ({ ...p, ...patch })); setSaved(false); };
  const setVar = (k: number, patch: Partial<PlaybookVariable>) => set({ variables: pb.variables.map((v, j) => (j === k ? { ...v, ...patch } : v)) });
  const setLink = (k: number, j: number, patch: Partial<PlaybookLink> | null) => {
    const links = pb.variables[k].links.slice();
    if (patch === null) links.splice(j, 1); else links[j] = { ...links[j], ...patch };
    setVar(k, { links });
  };
  const segNames = pb.segments.map((s) => s.name);
  const shareSum = pb.segments.filter((s) => s.share_mode === "given").reduce((n, s) => n + (s.share_pct || 0), 0);

  const save = async () => {
    setBusy("save"); setError(null);
    try {
      const r = pb.id ? await api.playbooks.update(pb.id, pb) : await api.playbooks.save(pb);
      const next = { ...r.playbook, id: r.id };
      setPb(next); setSaved(true); onSaved?.(next);
    } catch (e: any) { setError(e?.message || "Could not save the playbook"); } finally { setBusy(""); }
  };
  const download = async () => {
    setBusy("download"); setError(null);
    try { const r = await api.playbooks.render(pb); downloadText(fileName(pb.title), r.markdown); }
    catch (e: any) { setError(e?.message || "Could not write the file"); } finally { setBusy(""); }
  };

  // Portalled to <body>: the cards it opens from animate in with a transform, which would make them
  // the containing block of a fixed overlay and clip it to the card.
  if (typeof document === "undefined") return null;
  return createPortal(
    <div className="fixed inset-0 z-50 bg-black/60 flex items-start justify-center overflow-y-auto p-4 sm:p-6" onClick={onClose}>
      <div className="w-full max-w-4xl rounded-xl border border-border bg-background shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 px-5 py-4 border-b hairline">
          <div className="min-w-0">
            <div className="text-sm font-medium text-foreground">What I understood from your playbook</div>
            <p className="text-[11px] text-muted-foreground mt-0.5 leading-relaxed">
              Check each part before anything is built. Your segments and shares are kept as written; the research still runs and <span className="text-foreground/80">flags</span> anything it disagrees with, without changing it.
              {pb.parsed_by === "template" && " Read with the template reader (the model was unavailable) — free-form text may have been missed."}
            </p>
          </div>
          <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground shrink-0"><X className="w-4 h-4" /></button>
        </div>

        <div className="px-5 py-4 space-y-5 max-h-[calc(100vh-11rem)] overflow-y-auto">
          {/* Who */}
          <section className="grid sm:grid-cols-[1fr_1fr] gap-3">
            <label className="space-y-1"><span className="eyebrow block">Title</span><input value={pb.title} onChange={(e) => set({ title: e.target.value })} className="field field-sm" /></label>
            <label className="space-y-1"><span className="eyebrow block">Geography</span><input value={pb.geography} onChange={(e) => set({ geography: e.target.value })} className="field field-sm" /></label>
            <label className="space-y-1 sm:col-span-2"><span className="eyebrow block">Population</span><input value={pb.population} onChange={(e) => set({ population: e.target.value })} className="field field-sm" /></label>
          </section>

          {/* Approach */}
          <section className="space-y-2">
            <div className="text-[13px] font-medium text-foreground">Approach</div>
            <div className="grid sm:grid-cols-3 gap-3">
              <label className="space-y-1"><span className="eyebrow block">Segments are defined by</span>
                <select value={pb.approach.primary} onChange={(e) => set({ approach: { ...pb.approach, primary: e.target.value } })} className="field field-sm">
                  {AXES.map((a) => <option key={a} value={a}>{a}</option>)}
                </select>
              </label>
              <label className="space-y-1"><span className="eyebrow block">Then, inside each</span><input value={pb.approach.secondary} onChange={(e) => set({ approach: { ...pb.approach, secondary: e.target.value } })} placeholder="optional" className="field field-sm" /></label>
              <label className="space-y-1"><span className="eyebrow block">Match exactly on</span><input value={pb.approach.match_exactly.join(", ")} onChange={(e) => set({ approach: { ...pb.approach, match_exactly: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) } })} placeholder="role, region" className="field field-sm" /></label>
            </div>
            {pb.approach.why && <p className="hint">Why: {pb.approach.why}</p>}
          </section>

          {/* Segments */}
          <section className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-[13px] font-medium text-foreground">Segments</span>
              {pb.segments.length > 0 && <span className={`chip ${shareSum > 0 && Math.abs(shareSum - 100) > 0.5 ? "chip-warn" : ""}`}>stated shares sum to {shareSum}%</span>}
              <button type="button" onClick={() => set({ segments: [...pb.segments, { name: "", share_pct: null, share_mode: "planner", description: "", source: "" }] })} className="btn btn-xs btn-ghost ml-auto"><Plus className="w-3 h-3" /> Segment</button>
            </div>
            {pb.segments.length === 0 && <p className="hint">None named — the Studio proposes segments along your approach.</p>}
            {pb.segments.map((s, k) => (
              <div key={k} className="grid grid-cols-[1fr_8.5rem_4.5rem_auto] gap-2 items-center">
                <input value={s.name} onChange={(e) => set({ segments: pb.segments.map((x, j) => (j === k ? { ...x, name: e.target.value } : x)) })} placeholder="Segment name" className="field field-sm" title={s.description} />
                <select value={s.share_mode} onChange={(e) => set({ segments: pb.segments.map((x, j) => (j === k ? { ...x, share_mode: e.target.value as any, share_pct: e.target.value === "given" ? (x.share_pct ?? 10) : null } : x)) })} className="field field-sm">
                  <option value="given">share I state</option>
                  <option value="find">find it</option>
                  <option value="planner">planner&apos;s estimate</option>
                </select>
                <input type="number" min={0} max={100} disabled={s.share_mode !== "given"} value={s.share_mode === "given" ? (s.share_pct ?? "") : ""} onChange={(e) => set({ segments: pb.segments.map((x, j) => (j === k ? { ...x, share_pct: +e.target.value } : x)) })} className="field field-sm text-center tabular-nums" />
                <button type="button" title="Remove" onClick={() => set({ segments: pb.segments.filter((_, j) => j !== k) })} className="btn btn-xs btn-ghost px-1.5 text-muted-foreground/60 hover:text-red-300"><Trash2 className="w-3.5 h-3.5" /></button>
              </div>
            ))}
          </section>

          {/* Variables */}
          <section className="space-y-2">
            <div className="text-[13px] font-medium text-foreground">Variables — the extra forces you believe shape them</div>
            {pb.variables.length === 0 && <p className="hint">None — the Studio picks this question&apos;s extra dials on its own.</p>}
            {pb.variables.map((v, k) => (
              <div key={v.key} className="rounded-lg border border-border/50 bg-card/30 p-3 space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <input value={v.label} onChange={(e) => setVar(k, { label: e.target.value })} className="field field-sm max-w-[16rem] font-medium" />
                  <select value={v.kind} onChange={(e) => setVar(k, { kind: e.target.value as PlaybookVariable["kind"] })} className="field field-sm w-auto" title={KIND_HINT[v.kind]}>
                    <option value="dial">dial 0–10</option>
                    <option value="category">category</option>
                    <option value="rule">rule</option>
                  </select>
                  <span className={`chip ${v.evidence_mode === "none" ? "chip-warn" : ""}`} title={v.evidence}>{v.evidence_mode === "find" ? "evidence: look it up" : v.evidence_mode === "source" ? "evidence: source named" : "your hypothesis"}</span>
                  <button type="button" title="Remove variable" onClick={() => set({ variables: pb.variables.filter((_, j) => j !== k) })} className="btn btn-xs btn-ghost px-1.5 ml-auto text-muted-foreground/60 hover:text-red-300"><Trash2 className="w-3.5 h-3.5" /></button>
                </div>
                <p className="hint">{v.what ? `${v.what.charAt(0).toUpperCase()}${v.what.slice(1)} · ` : ""}{KIND_HINT[v.kind]}.</p>
                {v.kind === "dial" && (
                  <>
                    <div className="grid sm:grid-cols-2 gap-2">
                      <label className="space-y-1"><span className="eyebrow block">0 looks like</span><input value={v.low} onChange={(e) => setVar(k, { low: e.target.value })} className="field field-sm" /></label>
                      <label className="space-y-1"><span className="eyebrow block">10 looks like</span><input value={v.high} onChange={(e) => setVar(k, { high: e.target.value })} className="field field-sm" /></label>
                    </div>
                    <div className="space-y-1">
                      <span className="eyebrow block">Range by segment</span>
                      <div className="flex flex-wrap gap-1.5">
                        {v.by_segment.map((e, j) => (
                          <span key={j} className="inline-flex items-center gap-1 rounded-full border border-border/60 pl-2 pr-1 py-0.5 text-[11px]">
                            <span className={segNames.length && !segNames.includes(e.segment) ? "text-amber-300/90" : "text-foreground/85"} title={segNames.length && !segNames.includes(e.segment) ? "Not one of your named segments — matched to the plan's segments by meaning" : ""}>{e.segment}</span>
                            <input type="number" min={0} max={10} value={e.low ?? 0} onChange={(ev) => setVar(k, { by_segment: v.by_segment.map((x, i) => (i === j ? { ...x, low: Math.min(+ev.target.value, x.high ?? 10) } : x)) })} className="w-9 bg-transparent text-center tabular-nums" />
                            <span className="text-muted-foreground">–</span>
                            <input type="number" min={0} max={10} value={e.high ?? 10} onChange={(ev) => setVar(k, { by_segment: v.by_segment.map((x, i) => (i === j ? { ...x, high: Math.max(+ev.target.value, x.low ?? 0) } : x)) })} className="w-9 bg-transparent text-center tabular-nums" />
                          </span>
                        ))}
                        {v.by_segment.length === 0 && <span className="hint">{v.range ? `${v.range[0]}–${v.range[1]} for everyone` : "Not given — fitted to each planned segment from who it is"}</span>}
                      </div>
                    </div>
                    <div className="space-y-1">
                      <span className="eyebrow block">A high value pushes these standard dials</span>
                      <div className="flex flex-wrap gap-1.5 items-center">
                        {v.links.map((ln, j) => (
                          <span key={j} className="inline-flex items-center gap-1 rounded-full border border-border/60 pl-2 pr-1 py-0.5 text-[11px]">
                            <button type="button" onClick={() => setLink(k, j, { direction: ln.direction > 0 ? -1 : 1 })} title="Flip direction" className={ln.direction > 0 ? "text-emerald-300" : "text-sky-300"}>
                              {ln.direction > 0 ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />}
                            </button>
                            <span className="text-foreground/85" title={ln.dial}>{dialWords(ln.dial)}</span>
                            <select value={ln.strength} onChange={(e) => setLink(k, j, { strength: +e.target.value })} className="bg-transparent text-[11px] text-muted-foreground" title="Strength">
                              {[1, 2, 3].map((n) => <option key={n} value={n}>×{n}</option>)}
                            </select>
                            <button type="button" onClick={() => setLink(k, j, null)} className="text-muted-foreground/60 hover:text-red-300"><X className="w-3 h-3" /></button>
                          </span>
                        ))}
                        {dialPaths.length > 0 && v.links.length < 8 && (
                          <select value="" onChange={(e) => e.target.value && setVar(k, { links: [...v.links, { dial: e.target.value, direction: 1, strength: 2 }] })} className="field field-sm w-auto text-[11px]">
                            <option value="">+ dial…</option>
                            {dialPaths.filter((p) => !v.links.some((l) => l.dial === p)).map((p) => <option key={p} value={p}>{p.replace(".", " · ").replace(/_/g, " ")}</option>)}
                          </select>
                        )}
                      </div>
                      <p className="hint">At 10 a ×2 link moves its dial +2, at 0 by −2, at 5 not at all (total capped at ±4).</p>
                    </div>
                  </>
                )}
                {v.kind === "category" && (
                  <div className="space-y-1">
                    <label className="space-y-1 block"><span className="eyebrow block">Labels</span><input value={v.values.join(" · ")} onChange={(e) => setVar(k, { values: e.target.value.split("·").map((x) => x.trim()).filter(Boolean) })} className="field field-sm" /></label>
                    {v.by_segment.length > 0 && <p className="hint">{v.by_segment.map((e) => `${e.segment} → ${(e.values || []).join(" / ")}`).join(" · ")}</p>}
                  </div>
                )}
                <label className="space-y-1 block"><span className="eyebrow block">Shows up as</span><input value={v.shows_up_as} onChange={(e) => setVar(k, { shows_up_as: e.target.value })} placeholder="how it changes what they say and do" className="field field-sm" /></label>
              </div>
            ))}
          </section>

          {/* Rules */}
          <section className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-[13px] font-medium text-foreground">Rules of character</span>
              <button type="button" onClick={() => set({ rules: [...pb.rules, { segment: "", text: "" }] })} className="btn btn-xs btn-ghost ml-auto"><Plus className="w-3 h-3" /> Rule</button>
            </div>
            {pb.rules.map((r, k) => (
              <div key={k} className="grid grid-cols-[10rem_1fr_auto] gap-2 items-center">
                <select value={r.segment} onChange={(e) => set({ rules: pb.rules.map((x, j) => (j === k ? { ...x, segment: e.target.value } : x)) })} className="field field-sm">
                  <option value="">Everyone</option>
                  {[...new Set([...segNames, r.segment].filter(Boolean))].map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
                <input value={r.text} onChange={(e) => set({ rules: pb.rules.map((x, j) => (j === k ? { ...x, text: e.target.value } : x)) })} className="field field-sm" />
                <button type="button" onClick={() => set({ rules: pb.rules.filter((_, j) => j !== k) })} className="btn btn-xs btn-ghost px-1.5 text-muted-foreground/60 hover:text-red-300"><Trash2 className="w-3.5 h-3.5" /></button>
              </div>
            ))}
            {pb.rules.length === 0 && <p className="hint">None.</p>}
          </section>

          {pb.unsure.length > 0 && (
            <section className="space-y-1">
              <div className="text-[13px] font-medium text-foreground">You&apos;re not sure about</div>
              <ul className="list-disc pl-5 text-xs text-muted-foreground space-y-0.5">{pb.unsure.map((u, k) => <li key={k}>{u}</li>)}</ul>
              <p className="hint">The Studio asks about these only if the evidence cannot settle them.</p>
            </section>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2 px-5 py-3 border-t hairline">
          {error && <span className="text-[11px] text-red-300 mr-auto">{error}</span>}
          <button type="button" disabled={!!busy} onClick={download} className="btn btn-sm btn-ghost">{busy === "download" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />} Download .md</button>
          <button type="button" disabled={!!busy || !pb.title.trim()} onClick={save} className="btn btn-sm btn-secondary" title="Shared: everyone on the team can see and use it">
            {busy === "save" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : saved ? <Check className="w-3.5 h-3.5" /> : <Save className="w-3.5 h-3.5" />} {saved ? "Saved to the library" : pb.id ? "Save changes to the library" : "Save to the library"}
          </button>
          <button type="button" onClick={() => onUse(pb)} className="btn btn-sm btn-primary ml-auto"><Check className="w-3.5 h-3.5" /> Use for this build</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
