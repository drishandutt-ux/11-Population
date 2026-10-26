"use client";

/** From a finished Visuals run to the next version (the Visual Lab, step 4, 2026-10-26).
 *
 *  Sits on the Visuals results page. One button asks the agent to read the whole run — what most
 *  people asked for, what few said that is still hard-hitting, the verdict split — and propose the
 *  next version: which image to build on (when several were shown as one piece), the changes with
 *  who said each and how many, what is working and must stay, and what should move. The analyst
 *  ticks, edits or adds to the changes, then one more button makes it: a remake of the base image
 *  with the keep-list honoured and checked. When it is ready the page offers the two next steps —
 *  show it to the population, or compare it with the original — so the loop closes in the tool. */

import { useEffect, useState } from "react";
import { AlertTriangle, Check, Eye, FlaskConical, Loader2, Sparkles, Wand2, X } from "lucide-react";
import { api, ImageProposal, ImageRef, KeepItem, Probe, SessionImage } from "@/lib/api";
import { useImageUrl } from "./useImageUrl";
import { InstrumentPageProps } from "./pages/types";

const BASIS: Record<string, { label: string; cls: string }> = {
  "most said": { label: "most said", cls: "bg-primary/15 text-primary" },
  "few said, hard-hitting": { label: "few said · hard-hitting", cls: "bg-amber-500/15 text-amber-300" },
  "from the numbers": { label: "from the numbers", cls: "bg-muted text-muted-foreground" },
};
const CONTROL = "w-full bg-background border border-border rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:border-primary/60";

type Props = { probe: Probe; onOpenTool?: InstrumentPageProps["onOpenTool"] };

export default function NextVersion({ probe, onOpenTool }: Props) {
  const sessionId = probe.session_id;
  const shown: ImageRef[] = Array.isArray(probe.spec?.images) ? probe.spec.images : [];
  const [images, setImages] = useState<SessionImage[]>([]);
  const [proposal, setProposal] = useState<ImageProposal | null>(null);
  const [edits, setEdits] = useState<string[]>([]);
  const [ticked, setTicked] = useState<boolean[]>([]);
  const [keepOn, setKeepOn] = useState<boolean[]>([]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<null | "propose" | "make">(null);
  const [error, setError] = useState<string | null>(null);
  const [child, setChild] = useState<SessionImage | null>(null);

  useEffect(() => { api.images.list(sessionId).then((r) => setImages(r.images)).catch(() => undefined); }, [sessionId]);

  // The new version forms in the background; poll it until it is ready or failed.
  useEffect(() => {
    if (!child || child.status !== "generating") return;
    const t = setInterval(async () => {
      const r = await api.images.list(sessionId).catch(() => null);
      if (!r) return;
      setImages(r.images);
      const fresh = r.images.find((i) => i.id === child.id);
      if (fresh) setChild(fresh);
    }, 3000);
    return () => clearInterval(t);
  }, [child, sessionId]);

  async function propose(baseId?: string) {
    setBusy("propose"); setError(null); setChild(null);
    try {
      const p = await api.images.proposeNext(sessionId, { probe_id: probe.id, base_image_id: baseId || null });
      setProposal(p);
      setEdits(p.changes.map((c) => c.change));
      setTicked(p.changes.map(() => true));
      setKeepOn(p.keep.map(() => true));
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setBusy(null);
    }
  }

  async function make() {
    if (!proposal) return;
    const chosenIdx = ticked.map((t, i) => (t && edits[i].trim() ? i : -1)).filter((i) => i >= 0);
    const chosen = chosenIdx.map((i) => edits[i].trim());
    if (!chosen.length && !note.trim()) { setError("Tick at least one change, or write your own below."); return; }
    const base = images.find((i) => i.id === proposal.base_image_id);
    const parentKeep: KeepItem[] = base?.keep_list || [];
    const extra: KeepItem[] = proposal.keep.filter((_, i) => keepOn[i]).map((v) => ({ type: "present" as const, value: v }));
    const keep = [...parentKeep, ...extra.filter((e) => !parentKeep.some((k) => k.value.toLowerCase() === e.value.toLowerCase()))];
    const lines = (chosen.length > 1 ? chosen.map((c, i) => `${i + 1}) ${c}`) : chosen).concat(note.trim() ? [`Also: ${note.trim()}`] : []);
    setBusy("make"); setError(null);
    try {
      const row = await api.images.remake(sessionId, proposal.base_image_id, {
        change: lines.join("\n"), keep_list: keep, probe_id: probe.id, selected: chosenIdx, note: note.trim(),
        proposal: { ...proposal, changes: proposal.changes.map((c, i) => ({ ...c, change: edits[i] })) },
      });
      setChild(row);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setBusy(null);
    }
  }

  const baseRef = proposal ? shown.find((s) => s.id === proposal.base_image_id) || { id: proposal.base_image_id, label: proposal.base_label } : null;
  const question = typeof probe.spec?.question === "string" ? probe.spec.question : "";
  const setting = typeof probe.spec?.setting === "string" ? probe.spec.setting : "";

  return (
    <div className="rounded-xl border border-primary/30 bg-primary/5 p-4 space-y-3">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-xs font-medium flex items-center gap-1.5"><Sparkles className="w-3.5 h-3.5 text-primary" /> Next version</div>
          <p className="text-[11px] text-muted-foreground mt-0.5">
            Turn what they said into the next poster. The agent reads the whole run — what most people asked for, and what few said that still matters — and proposes the changes with who said each. You tick, edit or add; nothing is made until you say so.
          </p>
        </div>
        {!proposal && (
          <button type="button" onClick={() => propose()} disabled={busy === "propose"} className="btn btn-sm btn-primary shrink-0">
            {busy === "propose" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />} Propose the next version
          </button>
        )}
      </div>

      {error && (
        <div className="flex gap-2 text-[11px] text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" /><span>{error}</span>
          <button className="ml-auto text-muted-foreground hover:text-foreground" onClick={() => setError(null)}><X className="w-3 h-3" /></button>
        </div>
      )}

      {proposal && baseRef && (
        <div className="space-y-3">
          {/* The base */}
          <div className="flex items-start gap-3">
            <Thumb sessionId={sessionId} image={baseRef} size={72} />
            <div className="min-w-0 flex-1 text-[11px]">
              <div className="text-muted-foreground">Build on <span className="text-foreground/90">{baseRef.label || "this image"}</span></div>
              {proposal.base_why && <p className="text-foreground/75 mt-0.5">{proposal.base_why}</p>}
              {shown.length > 1 && (
                <div className="flex flex-wrap items-center gap-1 mt-1.5">
                  <span className="text-muted-foreground">Build on another instead:</span>
                  {shown.filter((s) => s.id !== proposal.base_image_id).map((s) => (
                    <button key={s.id} type="button" onClick={() => propose(s.id)} disabled={busy === "propose"} className="rounded border border-border/60 px-1.5 py-0.5 hover:text-foreground text-muted-foreground">
                      {s.label || "image"}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* The changes */}
          <div>
            <div className="text-[11px] text-muted-foreground mb-1.5">The changes — tick what to make, edit the words if you like</div>
            <ul className="space-y-2">
              {proposal.changes.map((c, i) => {
                const b = BASIS[c.basis] || BASIS["most said"];
                return (
                  <li key={i} className={`rounded-lg border p-2.5 ${ticked[i] ? "border-primary/30 bg-background/60" : "border-border/50 bg-background/30 opacity-70"}`}>
                    <div className="flex items-start gap-2">
                      <input type="checkbox" checked={!!ticked[i]} onChange={() => setTicked((prev) => prev.map((t, k) => (k === i ? !t : t)))} className="mt-1 accent-[hsl(var(--primary))]" />
                      <div className="min-w-0 flex-1 space-y-1">
                        <textarea value={edits[i] ?? ""} onChange={(e) => setEdits((prev) => prev.map((t, k) => (k === i ? e.target.value : t)))} rows={2} className={`${CONTROL} resize-y`} />
                        <div className="flex flex-wrap items-center gap-1.5 text-[10px]">
                          <span className={`rounded px-1.5 py-0.5 ${b.cls}`}>{b.label}</span>
                          {c.share && <span className="text-muted-foreground">{c.share}</span>}
                        </div>
                        {c.why && <p className="text-[11px] text-foreground/75">{c.why}</p>}
                        {c.cites?.length > 0 && <p className="text-[10px] text-muted-foreground">From: <span className="text-foreground/70">{c.cites.join(", ")}</span></p>}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>

          {/* What stays */}
          {proposal.keep.length > 0 && (
            <div>
              <div className="text-[11px] text-muted-foreground mb-1">What is working and stays (added to the keep-list)</div>
              <div className="flex flex-wrap gap-1">
                {proposal.keep.map((k, i) => (
                  <button key={i} type="button" onClick={() => setKeepOn((prev) => prev.map((t, j) => (j === i ? !t : t)))}
                    className={`text-[10px] rounded px-1.5 py-0.5 border flex items-center gap-1 ${keepOn[i] ? "border-primary/40 text-primary bg-primary/10" : "border-border/60 text-muted-foreground line-through"}`}>
                    {keepOn[i] ? <Check className="w-3 h-3" /> : <X className="w-3 h-3" />} {k}
                  </button>
                ))}
              </div>
            </div>
          )}

          {proposal.expected && <p className="text-[11px] text-muted-foreground">Expected: <span className="text-foreground/80">{proposal.expected}</span></p>}

          <div>
            <label className="text-[11px] text-muted-foreground block mb-1">Anything to add</label>
            <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="Your own change, in a line — keep it to one page · make the phone number the biggest thing on it" className={`${CONTROL} resize-y`} />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={make} disabled={busy !== null || (child?.status === "generating")} className="btn btn-sm btn-primary">
              {busy === "make" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wand2 className="w-3.5 h-3.5" />} Make the new version
            </button>
            <button type="button" onClick={() => propose()} disabled={busy !== null} className="btn btn-sm btn-secondary">
              {busy === "propose" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />} Propose again
            </button>
            <span className="text-[10px] text-muted-foreground">Usually under a minute. The words are set in type by the system and checked against the keep-list.</span>
          </div>
        </div>
      )}

      {child && (
        <div className="rounded-lg border border-border/60 bg-background/60 p-3 flex items-start gap-3">
          {child.status === "ready" ? <Thumb sessionId={sessionId} image={{ id: child.id, label: child.label }} size={96} /> : (
            <div className="w-24 h-24 rounded-md border border-border/60 bg-muted/40 flex items-center justify-center shrink-0">
              {child.status === "failed" ? <AlertTriangle className="w-5 h-5 text-red-400" /> : <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />}
            </div>
          )}
          <div className="min-w-0 flex-1 text-[11px] space-y-1.5">
            <div className="text-foreground/90 font-medium">{child.label}</div>
            {child.status === "generating" && <p className="text-muted-foreground">Forming — the layout is being written, the picture drawn, the words set in type, then the keep-list checked.</p>}
            {child.status === "failed" && <p className="text-red-300">Did not finish: {child.error || "unknown error"}</p>}
            {child.status === "ready" && (
              <>
                <p className="text-muted-foreground">
                  Ready{child.check_result ? <> · keep-list {child.check_result.passed ? "honoured" : `check: ${child.check_result.items.filter((i) => !i.ok).length} item(s) to look at`}</> : null}
                  {child.brief?.hero_provider === "none" ? " · the picture is a placeholder (no image provider key on the server)" : ""}
                </p>
                <div className="flex flex-wrap gap-2 pt-0.5">
                  {onOpenTool ? (
                    <>
                      <button type="button" className="btn btn-sm btn-primary"
                        onClick={() => onOpenTool("visual", { values: { images: [{ id: child.id, label: child.label }], ...(question ? { question } : {}), ...(setting ? { setting } : {}) } })}>
                        <Eye className="w-3.5 h-3.5" /> Show it to the population
                      </button>
                      <button type="button" className="btn btn-sm btn-secondary" onClick={() => onOpenTool("visual", { compare: [proposal?.base_image_id || child.parent_id || "", child.id].filter(Boolean) })}>
                        <FlaskConical className="w-3.5 h-3.5" /> Compare it with the original
                      </button>
                    </>
                  ) : (
                    <span className="text-muted-foreground">It is in the Visuals tool, under the image it came from.</span>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Thumb({ sessionId, image, size }: { sessionId: string; image: ImageRef; size: number }) {
  const url = useImageUrl(sessionId, image.id);
  return (
    <div className="rounded-md overflow-hidden border border-border/60 bg-muted/40 shrink-0" style={{ width: size, height: size }} title={image.label}>
      {url ? <img src={url} alt={image.label || "image"} className="w-full h-full object-cover" /> : <div className="w-full h-full animate-pulse bg-muted/60" />}
    </div>
  );
}
