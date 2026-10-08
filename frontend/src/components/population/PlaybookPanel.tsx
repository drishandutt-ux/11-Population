"use client";

import { useEffect, useRef, useState } from "react";
import { api, Playbook, PlaybookSection, PlaybookSummary, PopulationBuild } from "@/lib/api";
import PlaybookReview, { downloadText } from "@/components/population/PlaybookReview";
import { BookOpen, Upload, ClipboardPaste, FileDown, Loader2, Trash2, Pencil, X, AlertTriangle, CheckCircle2, HelpCircle } from "lucide-react";

interface Props {
  /** The playbook the next build follows (constraints.playbook), or null. */
  active: Playbook | null;
  onChange: (pb: Playbook | null) => void;
  disabled?: boolean;
}

/** "Bring your own segmentation": upload, paste or pick a playbook from the shared library; the
 *  Studio shows what it understood, and the next Detect & plan follows it. */
export default function PlaybookPanel({ active, onChange, disabled }: Props) {
  const [library, setLibrary] = useState<PlaybookSummary[]>([]);
  const [reviewing, setReviewing] = useState<{ pb: Playbook; view: PlaybookSection[] | null } | null>(null);
  const [paste, setPaste] = useState<string | null>(null);
  const [busy, setBusy] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const loadLibrary = () => api.playbooks.list().then((r) => setLibrary(r.playbooks)).catch(() => {});
  useEffect(() => { loadLibrary(); }, []);

  const read = async (markdown: string) => {
    setBusy("read"); setError(null);
    try { const r = await api.playbooks.parse(markdown); setReviewing({ pb: r.playbook, view: r.view }); setPaste(null); }
    catch (e: any) { setError(e?.message || "Could not read the playbook"); } finally { setBusy(""); }
  };
  const onFile = async (f: File | undefined) => {
    if (!f) return;
    if (/\.(docx?|pdf)$/i.test(f.name)) { setError("Save it as .md or .txt, or paste the text in."); return; }
    read(await f.text());
  };
  const open = async (id: string) => {
    setBusy(id); setError(null);
    try { const r = await api.playbooks.get(id); setReviewing({ pb: { ...r.playbook, id: r.id }, view: r.view }); }
    catch (e: any) { setError(e?.message || "Could not open it"); } finally { setBusy(""); }
  };
  const remove = async (p: PlaybookSummary) => {
    if (!window.confirm(`Delete "${p.title}" from the shared library? Everyone loses it.`)) return;
    try { await api.playbooks.delete(p.id); setLibrary((l) => l.filter((x) => x.id !== p.id)); if (active?.id === p.id) onChange(null); } catch {}
  };
  const download = async (which: "template" | "example") => {
    try { const t = await api.playbooks.template(); downloadText(which === "template" ? "segmentation-playbook-template.md" : "example-migraine-hcps-london.md", t[which]); } catch {}
  };

  const review = reviewing && (
    <PlaybookReview playbook={reviewing.pb} view={reviewing.view} onClose={() => setReviewing(null)} onSaved={() => loadLibrary()}
      onUse={(pb) => { onChange(pb); setReviewing(null); }} />
  );

  if (active) {
    const dials = active.variables.filter((v) => v.kind === "dial");
    return (
      <div className="surface rounded-xl px-4 py-3 space-y-1.5 ring-1 ring-primary/25 animate-fade-in text-left">
        <div className="flex items-center gap-2">
          <BookOpen className="w-3.5 h-3.5 text-primary" />
          <span className="text-[13px] font-medium text-foreground">Following your playbook: {active.title}</span>
          <span className="ml-auto flex items-center gap-1">
            <button disabled={disabled} onClick={() => setReviewing({ pb: active, view: null })} className="btn btn-xs btn-ghost"><Pencil className="w-3 h-3" /> Edit</button>
            <button disabled={disabled} onClick={() => onChange(null)} className="btn btn-xs btn-ghost" title="Plan without the playbook"><X className="w-3 h-3" /> Remove</button>
          </span>
        </div>
        <p className="hint">
          Segments by {active.approach.primary}{active.approach.secondary ? `, then ${active.approach.secondary}` : ""} · {active.segments.length ? `${active.segments.length} segments kept as you named them` : "segments proposed your way"}
          {dials.length ? ` · ${dials.map((d) => d.label).join(", ")} pinned on every twin` : ""}{active.rules.length ? ` · ${active.rules.length} rule${active.rules.length === 1 ? "" : "s"}` : ""}{active.extras?.length ? ` · ${active.extras.length} more section${active.extras.length === 1 ? "" : "s"} kept as written` : ""}. Research still runs and flags disagreements without changing your choices.
        </p>
        {review}
      </div>
    );
  }

  return (
    <div className="surface rounded-xl overflow-hidden animate-fade-in text-left">
      <div className="flex items-center gap-2 px-4 h-11 border-b hairline">
        <BookOpen className="w-3.5 h-3.5 text-muted-foreground" />
        <span className="text-[13px] font-medium text-foreground">Or bring your own segmentation playbook</span>
        <span className="ml-auto flex items-center gap-1">
          <button onClick={() => download("template")} className="btn btn-xs btn-ghost" title="A blank .md to fill in"><FileDown className="w-3 h-3" /> Template</button>
          <button onClick={() => download("example")} className="btn btn-xs btn-ghost" title="Migraine HCPs in London, filled in"><FileDown className="w-3 h-3" /> Example</button>
        </span>
      </div>
      <div className="px-4 py-3 space-y-3">
        <p className="hint">How you want the population cut (demographic, behavioural, value-based…), the segments you expect, and the extra forces you believe matter — burnout, travel, formulary pressure. The Studio shows what it understood before anything is built.</p>
        <div className="flex flex-wrap gap-2">
          <input ref={fileRef} type="file" accept=".md,.markdown,.txt,text/markdown,text/plain" className="hidden" onChange={(e) => { onFile(e.target.files?.[0]); e.target.value = ""; }} />
          <button disabled={disabled || !!busy} onClick={() => fileRef.current?.click()} className="btn btn-sm btn-secondary">{busy === "read" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />} Upload .md</button>
          <button disabled={disabled || !!busy} onClick={() => setPaste(paste === null ? "" : null)} className="btn btn-sm btn-ghost"><ClipboardPaste className="w-3.5 h-3.5" /> Paste text</button>
        </div>
        {paste !== null && (
          <div className="space-y-2">
            <textarea value={paste} onChange={(e) => setPaste(e.target.value)} rows={8} placeholder="Paste your playbook — the template's shape or your own notes" className="field text-xs font-mono w-full" />
            <button disabled={!paste.trim() || !!busy} onClick={() => read(paste)} className="btn btn-sm btn-primary">{busy === "read" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null} Read it</button>
          </div>
        )}
        {busy === "read" && <p className="hint">Reading the playbook — about half a minute.</p>}
        {error && <p className="text-[11px] text-red-300">{error}</p>}
        {library.length > 0 && (
          <div className="space-y-1">
            <p className="eyebrow">Shared library</p>
            <ul className="divide-y divide-border/50 rounded-lg border border-border/50">
              {library.map((p) => (
                <li key={p.id} className="flex items-center gap-3 px-3 py-2">
                  <div className="flex-1 min-w-0">
                    <div className="text-[13px] text-foreground truncate">{p.title}</div>
                    <div className="text-[11px] text-muted-foreground truncate">{p.approach} · {p.segments} segments · {p.variables} variables{p.author ? ` · ${p.author}` : ""}</div>
                  </div>
                  <button disabled={disabled || !!busy} onClick={() => open(p.id)} className="btn btn-sm btn-secondary">{busy === p.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null} Use</button>
                  <button onClick={() => remove(p)} className="btn btn-xs btn-ghost px-1.5 text-muted-foreground/50 hover:text-red-300" title="Delete from the shared library"><Trash2 className="w-3.5 h-3.5" /></button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
      {review}
    </div>
  );
}

/** After planning: what the playbook did — each segment's ranges, and every flag where the evidence disagrees. */
export function PlaybookChecks({ build }: { build: PopulationBuild }) {
  const pb = build.plan?.playbook;
  const book = build.constraints?.playbook;
  if (!pb) return null;
  const labels = Object.fromEntries((book?.variables || []).map((v) => [v.key, v.label]));
  const flags = pb.checks.filter((c) => c.status === "contradicted");
  const ok = pb.checks.filter((c) => c.status === "supported");
  const segs = (build.plan?.segments || []).filter((s) => s.decision !== "rejected" && s.playbook_fit);
  return (
    <div className="surface rounded-xl px-5 py-4 space-y-3 animate-fade-in">
      <div className="flex items-center gap-2">
        <BookOpen className="w-3.5 h-3.5 text-primary" />
        <span className="text-[13px] font-medium text-foreground">Your playbook: {pb.title}</span>
        <span className="ml-auto flex items-center gap-1.5">
          {flags.length > 0 && <span className="chip chip-warn">{flags.length} flag{flags.length === 1 ? "" : "s"}</span>}
          {ok.length > 0 && <span className="chip chip-ok">{ok.length} supported</span>}
        </span>
      </div>
      {flags.length > 0 && (
        <ul className="space-y-1.5">
          {flags.map((c, k) => (
            <li key={k} className="flex gap-2 text-xs"><AlertTriangle className="w-3.5 h-3.5 text-amber-300 shrink-0 mt-0.5" />
              <span><span className="text-foreground/90">{c.item}</span> — {c.note}{c.source ? <span className="text-muted-foreground"> ({c.source})</span> : null}. <span className="text-muted-foreground">Your choice is kept; edit the segment to follow the evidence instead.</span></span></li>
          ))}
        </ul>
      )}
      {ok.length > 0 && (
        <ul className="space-y-1">
          {ok.map((c, k) => (
            <li key={k} className="flex gap-2 text-xs text-muted-foreground"><CheckCircle2 className="w-3.5 h-3.5 text-emerald-300/80 shrink-0 mt-0.5" /><span><span className="text-foreground/85">{c.item}</span> — {c.source || c.note}</span></li>
          ))}
        </ul>
      )}
      {pb.hypotheses.length > 0 && (
        <p className="flex gap-2 text-xs text-muted-foreground"><HelpCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" /><span>Your hypotheses, with nothing on file either way: {pb.hypotheses.join(", ")}. The report states them as your assumptions.</span></p>
      )}
      {segs.length > 0 && (
        <div className="space-y-1 pt-1">
          <p className="eyebrow">What each segment&apos;s twins are drawn from</p>
          {segs.map((s) => {
            const fit = s.playbook_fit!;
            const bits = [
              ...Object.entries(fit.ranges).map(([k, r]) => `${labels[k] || k} ${r[0]}–${r[1]}`),
              ...Object.entries(fit.values).map(([k, v]) => `${labels[k] || k}: ${v.join(" / ")}`),
            ];
            return (
              <div key={s.id} className="text-xs flex gap-2">
                <span className="text-foreground/90 shrink-0">{s.name}</span>
                {s.share_source === "analyst" && <span className="text-[10px] text-primary/80 shrink-0">share yours</span>}
                <span className="text-muted-foreground truncate" title={bits.join(" · ")}>{bits.join(" · ") || "—"}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
