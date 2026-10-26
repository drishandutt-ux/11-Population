"use client";

/** The Visual Lab studio — the Visuals instrument's input panel, given the whole Lab tab
 *  (steps 2 and 3, 2026-10-26).
 *
 *  Every image the session holds is a card in a tree: uploads at the root, remakes under the
 *  image they came from. From any card, in any order, as often as you like:
 *    · Show — put it in the run on the right and ask the population (the shell runs it)
 *    · Compare — tick two to six and run them against each other, choose-between or rate-each
 *    · Remake — say what to change (or let the agent read the twins' reactions and propose it);
 *      the keep-list is honoured and checked before the new version appears
 *    · Generate — a new image from what the session knows plus a note
 *  The right rail holds the run itself: which images, where they are seen, the question, and the
 *  shell's own controls (who answers, model, estimate, Run). */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, Experiment, ImageProposal, ImageRef, KeepCheck, KeepItem, Probe, SessionImage, SimMode } from "@/lib/api";
import { useSessionTier } from "@/components/sessions/TierSwitch";
import {
  AlertTriangle, Check, ChevronDown, ChevronLeft, ChevronRight, Eye, FlaskConical, ImagePlus, Loader2, Pencil, Plus, RefreshCw,
  ShieldCheck, ShieldAlert, Sparkles, Trash2, Wand2, X,
} from "lucide-react";
import { InstrumentFormProps } from "./index";
import { ago } from "./formUtils";
import { forgetImageUrl, useImageUrl } from "../useImageUrl";
import ExperimentPage from "../pages/ExperimentPage";

const KEYS = ["A", "B", "C", "D", "E", "F"];
const KEEP_LABEL: Record<KeepItem["type"], string> = { text: "Must read exactly", present: "Must show", absent: "Must not show" };
const SOURCE_LABEL: Record<SessionImage["source"], string> = { upload: "Uploaded", generated: "Generated", remake: "Remake" };
const CONTROL = "w-full bg-input border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary/50";

type Node = { image: SessionImage; children: Node[] };

function buildTree(images: SessionImage[]): Node[] {
  const byId = new Map(images.map((i) => [i.id, i]));
  const kids = new Map<string, SessionImage[]>();
  const roots: SessionImage[] = [];
  for (const img of images) {
    if (img.parent_id && byId.has(img.parent_id)) kids.set(img.parent_id, [...(kids.get(img.parent_id) || []), img]);
    else roots.push(img);
  }
  const newest = (a: SessionImage, b: SessionImage) => ((a.created_at || "") < (b.created_at || "") ? 1 : -1);
  const node = (img: SessionImage): Node => ({ image: img, children: (kids.get(img.id) || []).sort(newest).map(node) });
  return roots.sort(newest).map(node);
}

export default function VisualStudio({ instrument, values, onChange, sessionId = "", controls, aside, onBack }: InstrumentFormProps) {
  const [images, setImages] = useState<SessionImage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [probes, setProbes] = useState<Probe[]>([]);
  const [mode] = useSessionTier(sessionId);
  const [uploading, setUploading] = useState(0);
  const fileRef = useRef<HTMLInputElement>(null);

  // Generate panel.
  const [genOpen, setGenOpen] = useState(false);
  const [genNote, setGenNote] = useState("");
  const [genKeep, setGenKeep] = useState<KeepItem[]>([]);
  const [genBusy, setGenBusy] = useState(false);

  // Compare.
  const [compare, setCompare] = useState<string[]>([]);
  const [design, setDesign] = useState<"choice" | "within">("choice");
  const [experiment, setExperiment] = useState<Experiment | null>(null);
  const [compareBusy, setCompareBusy] = useState(false);

  const shown: ImageRef[] = Array.isArray(values.images) ? values.images : [];
  const setShown = (refs: ImageRef[]) => onChange("images", refs);

  const load = useCallback(async () => {
    if (!sessionId) return;
    try {
      const [r, p] = await Promise.all([api.images.list(sessionId), api.lab.probes(sessionId)]);
      setImages(r.images);
      setProbes(p.probes.filter((x) => x.instrument === "visual"));
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [sessionId]);
  useEffect(() => { load(); }, [load]);

  // Poll while anything is forming (a generation or a remake), and every so often for new runs.
  const forming = images.some((i) => i.status === "generating");
  useEffect(() => {
    const t = setInterval(load, forming ? 3000 : 15000);
    return () => clearInterval(t);
  }, [load, forming]);

  // Poll a running comparison until the verdict lands.
  useEffect(() => {
    if (!experiment || !(experiment.status === "queued" || experiment.status === "running")) return;
    const t = setInterval(async () => {
      const full = await api.lab.experiment(sessionId, experiment.id).catch(() => null);
      if (full) setExperiment(full);
    }, 3000);
    return () => clearInterval(t);
  }, [experiment, sessionId]);

  const runsFor = useMemo(() => {
    const out = new Map<string, Probe[]>();
    for (const p of probes) {
      const refs: ImageRef[] = Array.isArray(p.spec?.images) ? p.spec.images : [];
      if (refs.length === 1 && !p.experiment_id) out.set(refs[0].id, [...(out.get(refs[0].id) || []), p]);
    }
    for (const [k, v] of out) out.set(k, v.sort((a, b) => ((a.created_at || "") < (b.created_at || "") ? 1 : -1)));
    return out;
  }, [probes]);

  const tree = useMemo(() => buildTree(images), [images]);
  const byId = useMemo(() => new Map(images.map((i) => [i.id, i])), [images]);

  async function upload(files: FileList | null) {
    const list = Array.from(files || []);
    if (!list.length) return;
    setError(null); setUploading(list.length);
    for (const f of list) {
      try {
        const img = await api.images.upload(sessionId, f);
        setImages((prev) => [img, ...prev]);
      } catch (e: any) {
        setError(`${f.name}: ${e?.message || String(e)}`);
      } finally {
        setUploading((n) => n - 1);
      }
    }
  }

  async function generate() {
    setGenBusy(true); setError(null);
    try {
      const row = await api.images.generate(sessionId, { note: genNote.trim(), keep_list: genKeep, mode });
      setImages((prev) => [row, ...prev]);
      setGenOpen(false); setGenNote("");
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setGenBusy(false);
    }
  }

  async function runCompare() {
    const chosen = compare.map((id) => byId.get(id)).filter((x): x is SessionImage => !!x && x.status === "ready");
    if (chosen.length < 2) { setError("Tick at least two images to compare."); return; }
    setCompareBusy(true); setError(null);
    try {
      const question = String(values.question || instrument.question);
      const setting = String(values.setting || "");
      const e = await api.lab.runExperiment(sessionId, {
        instrument: "visual", design, name: chosen.map((c) => c.label || "image").join(" vs "), mode,
        ...(design === "choice" ? { question } : {}),
        variants: chosen.map((c, i) => ({ key: KEYS[i], label: c.label || c.filename || KEYS[i],
          spec: { images: [{ id: c.id, label: c.label || c.filename }], ...(setting ? { setting } : {}), question } })),
      });
      setExperiment(e);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setCompareBusy(false);
    }
  }

  function toggleShow(img: SessionImage) {
    if (shown.some((s) => s.id === img.id)) setShown(shown.filter((s) => s.id !== img.id));
    else setShown([...shown, { id: img.id, label: img.label || img.filename }]);
  }

  function toggleCompare(id: string) {
    setCompare((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : prev.length >= 6 ? prev : [...prev, id]));
  }

  const patchImage = (img: SessionImage) => setImages((prev) => prev.map((x) => (x.id === img.id ? img : x)));

  async function remove(img: SessionImage) {
    setError(null);
    try {
      await api.images.remove(sessionId, img.id);
      forgetImageUrl(sessionId, img.id);
      setImages((prev) => prev.filter((x) => x.id !== img.id));
      setShown(shown.filter((s) => s.id !== img.id));
      setCompare((prev) => prev.filter((x) => x !== img.id));
    } catch (e: any) {
      setError(e?.message || String(e));
    }
  }

  const question = typeof values.question === "string" ? values.question : "";
  const setting = typeof values.setting === "string" ? values.setting : "";
  const questionField = instrument.inputs.find((f) => f.key === "question");

  return (
    <div className="h-full flex min-h-0">
      <input ref={fileRef} type="file" accept="image/*" multiple className="hidden" onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />

      {/* ── the images ─────────────────────────────────────────────────────── */}
      <div className="flex-1 min-w-0 overflow-y-auto p-5 space-y-4">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            {onBack && (
              <button onClick={onBack} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground -ml-1 mb-1">
                <ChevronLeft className="w-3.5 h-3.5" /> All tools
              </button>
            )}
            <div className="text-sm font-medium">Visuals</div>
            <p className="text-[11px] text-muted-foreground mt-0.5 max-w-2xl">
              Upload or generate a poster, a pack, a page, an ad. Show it to the population, compare versions, and remake one from what they said — every version keeps the words that must stay.
            </p>
          </div>
          <div className="flex gap-2 shrink-0">
            <button type="button" onClick={() => fileRef.current?.click()} disabled={uploading > 0} className="btn btn-sm btn-secondary">
              {uploading > 0 ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ImagePlus className="w-3.5 h-3.5" />} Upload
            </button>
            <button type="button" onClick={() => setGenOpen((v) => !v)} className={`btn btn-sm ${genOpen ? "btn-secondary" : "btn-primary"}`}>
              <Sparkles className="w-3.5 h-3.5" /> Generate
            </button>
          </div>
        </div>

        {error && (
          <div className="flex gap-2 text-[11px] text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" /><span>{error}</span>
            <button className="ml-auto text-muted-foreground hover:text-foreground" onClick={() => setError(null)}><X className="w-3 h-3" /></button>
          </div>
        )}

        {genOpen && (
          <div className="rounded-xl border border-primary/30 bg-primary/5 p-4 space-y-3">
            <div className="text-xs font-medium flex items-center gap-1.5"><Sparkles className="w-3.5 h-3.5 text-primary" /> Generate a new image from what this session knows</div>
            <p className="text-[11px] text-muted-foreground">
              The agent writes the layout — headline, lines, call to action, colours, a picture brief — from the question, the Lab brief and what the Lab has found. The words are set in type by the system, never drawn by the image model, so anything on the keep-list reads exactly.
            </p>
            <div>
              <label className="text-xs text-muted-foreground block mb-1.5">A note (optional)</label>
              <textarea value={genNote} onChange={(e) => setGenNote(e.target.value)} rows={2} placeholder="A bus-stop poster for the school run · a leaflet for the GP's waiting room · lead with the price" className={`${CONTROL} resize-y`} />
            </div>
            <KeepListEditor value={genKeep} onChange={setGenKeep} />
            <div className="flex items-center gap-2">
              <button type="button" onClick={generate} disabled={genBusy} className="btn btn-sm btn-primary">
                {genBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wand2 className="w-3.5 h-3.5" />} Generate
              </button>
              <button type="button" onClick={() => setGenOpen(false)} className="btn btn-sm btn-ghost">Cancel</button>
              <span className="text-[10px] text-muted-foreground">Usually under a minute. The card appears at once and fills in.</span>
            </div>
          </div>
        )}

        {/* Compare bar */}
        <div className="rounded-xl border border-border/60 bg-card/30 px-4 py-2.5 flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1.5 text-xs"><FlaskConical className="w-3.5 h-3.5 text-primary" /> Compare</div>
          <span className="text-[11px] text-muted-foreground">{compare.length === 0 ? "Tick two to six images." : `${compare.length} ticked: ${compare.map((id) => byId.get(id)?.label || "image").join(" · ")}`}</span>
          <div className="ml-auto flex items-center gap-2">
            <div className="flex rounded-lg border border-border overflow-hidden">
              {([["choice", "Choose between"], ["within", "Rate each"]] as const).map(([k, l]) => (
                <button key={k} type="button" onClick={() => setDesign(k)} className={`text-[11px] px-2.5 py-1 ${design === k ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground"}`}>{l}</button>
              ))}
            </div>
            <button type="button" onClick={runCompare} disabled={compare.length < 2 || compareBusy} className="btn btn-sm btn-primary">
              {compareBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FlaskConical className="w-3.5 h-3.5" />} Compare
            </button>
            {compare.length > 0 && <button type="button" onClick={() => setCompare([])} className="text-[11px] text-muted-foreground hover:text-foreground">clear</button>}
          </div>
        </div>

        {experiment && (
          <div className="rounded-xl border border-border/60 bg-card/40 p-4 space-y-3">
            <div className="flex items-center gap-2">
              <div className="text-xs font-medium">{experiment.name || "Comparison"}</div>
              <span className="text-[10px] text-muted-foreground">{experiment.design === "choice" ? "chose between" : "rated each"} · {experiment.status}</span>
              {(experiment.status === "queued" || experiment.status === "running") && <Loader2 className="w-3 h-3 animate-spin text-muted-foreground" />}
              <button type="button" onClick={() => setExperiment(null)} className="ml-auto text-muted-foreground hover:text-foreground"><X className="w-3.5 h-3.5" /></button>
            </div>
            {experiment.error && <p className="text-[11px] text-red-400">{experiment.error}</p>}
            {experiment.results ? <ExperimentPage instrument={instrument} experiment={experiment} />
              : <p className="text-[11px] text-muted-foreground">The population is looking at the options… the verdict lands here.</p>}
          </div>
        )}

        {loading && <p className="text-[11px] text-muted-foreground">Loading images…</p>}
        {!loading && images.length === 0 && (
          <div className="rounded-xl border border-dashed border-border/70 p-8 text-center text-muted-foreground">
            <ImagePlus className="w-6 h-6 mx-auto opacity-40 mb-2" />
            <p className="text-sm">No images yet.</p>
            <p className="text-xs opacity-70 mt-1">Upload a poster, a pack shot, a page, an ad — or generate one from what the session knows.</p>
          </div>
        )}

        <div className="space-y-3">
          {tree.map((n) => (
            <TreeNode key={n.image.id} node={n} depth={0} sessionId={sessionId} mode={mode}
              shown={shown} compare={compare} runs={runsFor} byId={byId}
              onShow={toggleShow} onCompare={toggleCompare} onPatch={patchImage} onRemove={remove}
              onRemade={(row) => setImages((prev) => [row, ...prev])} onError={setError} />
          ))}
        </div>
      </div>

      {/* ── the run ────────────────────────────────────────────────────────── */}
      <div className="w-[340px] shrink-0 border-l border-border/60 overflow-y-auto p-4 space-y-4">
        <div>
          <div className="text-sm font-medium flex items-center gap-1.5"><Eye className="w-3.5 h-3.5 text-primary" /> Show to the population</div>
          <p className="text-[11px] text-muted-foreground mt-0.5">Pick images with <span className="text-foreground/80">Show</span> on their cards. Several are shown together as one piece.</p>
        </div>
        <div>
          <label className="text-xs text-muted-foreground block mb-1.5">What they see <span className="text-primary/70">*</span></label>
          {shown.length === 0 ? (
            <p className="text-[11px] text-muted-foreground/70 rounded-lg border border-dashed border-border/60 px-3 py-3">Nothing picked yet.</p>
          ) : (
            <div className="space-y-1.5">
              {shown.map((ref, k) => (
                <ShownRow key={ref.id} sessionId={sessionId} refItem={ref} index={k} count={shown.length} onRemove={() => setShown(shown.filter((s) => s.id !== ref.id))} />
              ))}
            </div>
          )}
        </div>
        <div>
          <label className="text-xs text-muted-foreground block mb-1.5">Where they come across it</label>
          <input value={setting} onChange={(e) => onChange("setting", e.target.value)} placeholder="A poster at a bus stop · a leaflet in the GP's waiting room · an ad in their feed" className={CONTROL} />
        </div>
        <div>
          <label className="text-xs text-muted-foreground block mb-1.5">What you want to know <span className="text-primary/70">*</span></label>
          <textarea value={question} onChange={(e) => onChange("question", e.target.value)} rows={2} className={`${CONTROL} resize-y`} placeholder={instrument.question} />
          {questionField && questionField.suggestions.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1.5">
              {questionField.suggestions.map((sug) => (
                <button key={sug} type="button" onClick={() => onChange("question", sug)}
                  className={`text-[10px] rounded px-1.5 py-0.5 border transition-colors ${question === sug ? "border-primary/60 text-primary bg-primary/10" : "border-border/60 text-muted-foreground hover:text-foreground"}`}>
                  {sug}
                </button>
              ))}
            </div>
          )}
        </div>
        {controls}
        {aside}
      </div>
    </div>
  );
}

function ShownRow({ sessionId, refItem, index, count, onRemove }: { sessionId: string; refItem: ImageRef; index: number; count: number; onRemove: () => void }) {
  const url = useImageUrl(sessionId, refItem.id);
  return (
    <div className="flex items-center gap-2 rounded-lg border border-border/60 bg-card/30 px-2 py-1.5">
      <div className="w-9 h-9 rounded-md overflow-hidden bg-muted/40 shrink-0">{url ? <img src={url} alt="" className="w-full h-full object-cover" /> : null}</div>
      <span className="text-[11px] truncate flex-1">{count > 1 ? `${index + 1}. ` : ""}{refItem.label || "image"}</span>
      <button type="button" onClick={onRemove} className="text-muted-foreground hover:text-foreground"><X className="w-3 h-3" /></button>
    </div>
  );
}

// ── one card ──────────────────────────────────────────────────────────────────

interface NodeProps {
  node: Node; depth: number; sessionId: string; mode: SimMode;
  shown: ImageRef[]; compare: string[]; runs: Map<string, Probe[]>; byId: Map<string, SessionImage>;
  onShow: (img: SessionImage) => void; onCompare: (id: string) => void; onPatch: (img: SessionImage) => void;
  onRemove: (img: SessionImage) => void; onRemade: (row: SessionImage) => void; onError: (m: string) => void;
}

function TreeNode(props: NodeProps) {
  const { node, depth } = props;
  return (
    <div className={depth ? "pl-6 border-l border-border/40 ml-4 space-y-3" : "space-y-3"}>
      <ImageCard {...props} image={node.image} />
      {node.children.map((c) => <TreeNode key={c.image.id} {...props} node={c} depth={depth + 1} />)}
    </div>
  );
}

function ImageCard({ image: img, depth, sessionId, mode, shown, compare, runs, byId, onShow, onCompare, onPatch, onRemove, onRemade, onError }: NodeProps & { image: SessionImage }) {
  const url = useImageUrl(sessionId, img.status === "ready" ? img.id : undefined);
  const [panel, setPanel] = useState<null | "remake" | "details" | "keep">(null);
  const [renaming, setRenaming] = useState(false);
  const [draft, setDraft] = useState(img.label);
  const [change, setChange] = useState("");
  const [keep, setKeep] = useState<KeepItem[]>(img.keep_list || []);
  const [proposal, setProposal] = useState<ImageProposal | null>(null);
  const [busy, setBusy] = useState<null | "propose" | "remake" | "check" | "read" | "keep">(null);
  const [confirm, setConfirm] = useState(false);
  useEffect(() => { setKeep(img.keep_list || []); setDraft(img.label); }, [img.keep_list, img.label]);

  const isShown = shown.findIndex((s) => s.id === img.id);
  const ticked = compare.includes(img.id);
  const myRuns = runs.get(img.id) || [];
  const latest = myRuns[0];
  const check = img.check_result;
  const issues = check ? check.items.filter((i) => !i.ok).length : 0;
  const parent = img.parent_id ? byId.get(img.parent_id) : undefined;
  const placeholderHero = img.source !== "upload" && img.brief?.hero_provider === "none";
  const forming = img.status === "generating";

  async function rename() {
    setRenaming(false);
    const label = draft.trim();
    if (!label || label === img.label) return;
    try { onPatch(await api.images.rename(sessionId, img.id, label)); } catch (e: any) { onError(e?.message || String(e)); }
  }
  async function saveKeep() {
    setBusy("keep");
    try { onPatch(await api.images.setKeepList(sessionId, img.id, keep)); setPanel(null); } catch (e: any) { onError(e?.message || String(e)); } finally { setBusy(null); }
  }
  async function propose() {
    setBusy("propose");
    try {
      const p = await api.images.propose(sessionId, img.id, { probe_id: latest?.id || null, mode });
      setProposal(p); setChange(p.change); setPanel("remake");
    } catch (e: any) { onError(e?.message || String(e)); } finally { setBusy(null); }
  }
  async function remake() {
    if (!change.trim()) { onError("Say what to change."); return; }
    setBusy("remake");
    try {
      const row = await api.images.remake(sessionId, img.id, { change: change.trim(), keep_list: keep, probe_id: proposal?.probe_id || latest?.id || null, proposal, mode });
      onRemade(row); setPanel(null); setChange(""); setProposal(null);
    } catch (e: any) { onError(e?.message || String(e)); } finally { setBusy(null); }
  }
  async function recheck() {
    setBusy("check");
    try { const r: KeepCheck = await api.images.check(sessionId, img.id, mode); onPatch({ ...img, check_result: r }); setPanel("details"); } catch (e: any) { onError(e?.message || String(e)); } finally { setBusy(null); }
  }
  async function read() {
    setBusy("read");
    try { const r = await api.images.read(sessionId, img.id, mode); onPatch({ ...img, layout: r.layout }); setPanel("details"); } catch (e: any) { onError(e?.message || String(e)); } finally { setBusy(null); }
  }

  return (
    <div className={`rounded-xl border ${isShown >= 0 ? "border-primary/50" : "border-border/60"} bg-card/40 p-3`}>
      <div className="flex gap-3">
        <div className="w-28 h-36 rounded-lg overflow-hidden bg-muted/40 shrink-0 border border-border/40 flex items-center justify-center">
          {forming ? <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
            : img.status === "failed" ? <AlertTriangle className="w-5 h-5 text-red-400" />
            : url ? <img src={url} alt={img.label} className="w-full h-full object-cover" /> : <div className="w-full h-full animate-pulse bg-muted/60" />}
        </div>
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex items-center gap-2 flex-wrap">
            {renaming ? (
              <span className="flex items-center gap-1">
                <input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") rename(); if (e.key === "Escape") setRenaming(false); }} className="bg-input border border-border rounded px-1.5 py-0.5 text-xs" />
                <button type="button" onClick={rename} className="text-primary"><Check className="w-3.5 h-3.5" /></button>
              </span>
            ) : (
              <button type="button" onClick={() => setRenaming(true)} className="text-sm font-medium text-left flex items-center gap-1 group">
                {img.label || img.filename || "image"} <Pencil className="w-3 h-3 opacity-0 group-hover:opacity-60" />
              </button>
            )}
            <span className="text-[10px] rounded px-1.5 py-0.5 bg-muted text-muted-foreground">{SOURCE_LABEL[img.source] || img.source}</span>
            {forming && <span className="text-[10px] rounded px-1.5 py-0.5 bg-primary/10 text-primary">forming…</span>}
            {img.status === "failed" && <span className="text-[10px] rounded px-1.5 py-0.5 bg-red-500/10 text-red-300" title={img.error || ""}>failed</span>}
            {check && (check.passed
              ? <span className="text-[10px] rounded px-1.5 py-0.5 bg-emerald-500/10 text-emerald-300 flex items-center gap-1"><ShieldCheck className="w-3 h-3" /> keep-list honoured</span>
              : <span className="text-[10px] rounded px-1.5 py-0.5 bg-amber-500/10 text-amber-300 flex items-center gap-1"><ShieldAlert className="w-3 h-3" /> {issues} keep-list issue{issues === 1 ? "" : "s"}</span>)}
            {isShown >= 0 && <span className="text-[10px] rounded px-1.5 py-0.5 bg-primary/15 text-primary">in the run{shown.length > 1 ? ` · ${isShown + 1}` : ""}</span>}
          </div>
          {parent && <p className="text-[11px] text-muted-foreground">Remade from <span className="text-foreground/80">{parent.label || "image"}</span>{img.change_note ? <> · change: <span className="text-foreground/80">{img.change_note}</span></> : null}</p>}
          {img.status === "failed" && img.error && <p className="text-[11px] text-red-300">{img.error}</p>}
          {placeholderHero && <p className="text-[10px] text-amber-300/80">The picture is a placeholder drawn in code — no image provider key is set. The words are set exactly as written.</p>}
          {(img.keep_list || []).length > 0 && (
            <div className="flex flex-wrap gap-1">
              {img.keep_list.map((k, i) => <span key={i} className="text-[10px] rounded px-1.5 py-0.5 border border-border/60 text-muted-foreground" title={KEEP_LABEL[k.type]}>{k.type === "text" ? "“" : k.type === "present" ? "show: " : "no: "}{k.value}{k.type === "text" ? "”" : ""}</span>)}
            </div>
          )}
          <p className="text-[11px] text-muted-foreground">
            {myRuns.length === 0 ? "Not shown to the population yet." : <>{myRuns.length} run{myRuns.length === 1 ? "" : "s"}{latest?.aggregates?.sentence ? <> · latest: <span className="text-foreground/80">{latest.aggregates.sentence}</span></> : latest ? ` · latest ${latest.status}` : ""}</>}
          </p>
          <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
            <button type="button" onClick={() => onShow(img)} disabled={img.status !== "ready"} className={`btn btn-sm ${isShown >= 0 ? "btn-primary" : "btn-secondary"}`}><Eye className="w-3.5 h-3.5" /> {isShown >= 0 ? "In the run" : "Show"}</button>
            <label className={`btn btn-sm btn-secondary cursor-pointer ${img.status !== "ready" ? "opacity-40 pointer-events-none" : ""}`}>
              <input type="checkbox" checked={ticked} onChange={() => onCompare(img.id)} className="accent-[hsl(var(--primary))]" /> Compare
            </label>
            <button type="button" onClick={() => setPanel(panel === "remake" ? null : "remake")} disabled={img.status !== "ready"} className="btn btn-sm btn-secondary"><Wand2 className="w-3.5 h-3.5" /> Remake…</button>
            <button type="button" onClick={propose} disabled={img.status !== "ready" || !latest || busy === "propose"} title={latest ? "Read the latest run on this image and propose the one change" : "Show it to the population first"} className="btn btn-sm btn-secondary">
              {busy === "propose" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />} Suggest a change
            </button>
            <button type="button" onClick={() => setPanel(panel === "keep" ? null : "keep")} className="btn btn-sm btn-ghost">Keep-list</button>
            <button type="button" onClick={() => setPanel(panel === "details" ? null : "details")} className="btn btn-sm btn-ghost">{panel === "details" ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />} Details</button>
            {confirm ? (
              <span className="text-[11px] flex items-center gap-1.5 ml-auto"><span className="text-muted-foreground">Delete?</span><button type="button" onClick={() => { setConfirm(false); onRemove(img); }} className="text-red-400 font-medium">Yes</button><button type="button" onClick={() => setConfirm(false)} className="text-muted-foreground">No</button></span>
            ) : (
              <button type="button" onClick={() => setConfirm(true)} className="ml-auto text-muted-foreground hover:text-red-400" title="Delete"><Trash2 className="w-3.5 h-3.5" /></button>
            )}
          </div>
        </div>
      </div>

      {panel === "keep" && (
        <div className="mt-3 rounded-lg border border-border/60 bg-background/40 p-3 space-y-2">
          <KeepListEditor value={keep} onChange={setKeep} />
          <div className="flex gap-2">
            <button type="button" onClick={saveKeep} disabled={busy === "keep"} className="btn btn-sm btn-primary">{busy === "keep" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />} Save keep-list</button>
            <button type="button" onClick={recheck} disabled={busy === "check" || img.status !== "ready"} className="btn btn-sm btn-secondary">{busy === "check" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ShieldCheck className="w-3.5 h-3.5" />} Check this image</button>
          </div>
        </div>
      )}

      {panel === "remake" && (
        <div className="mt-3 rounded-lg border border-primary/30 bg-primary/5 p-3 space-y-2">
          <div className="text-xs font-medium flex items-center gap-1.5"><Wand2 className="w-3.5 h-3.5 text-primary" /> Remake this image</div>
          {proposal && (
            <div className="rounded-lg border border-border/60 bg-background/50 p-2.5 text-[11px] space-y-1">
              <div className="text-foreground/90"><span className="text-muted-foreground">The agent proposes: </span>{proposal.change}</div>
              {proposal.why && <div className="text-muted-foreground">{proposal.why}</div>}
              {proposal.keep?.length > 0 && <div className="text-muted-foreground">Keep: <span className="text-foreground/80">{proposal.keep.join(" · ")}</span></div>}
              {proposal.cites?.length > 0 && <div className="text-muted-foreground">From: <span className="text-foreground/80">{proposal.cites.join(", ")}</span></div>}
              {proposal.expected && <div className="text-muted-foreground">Expected: <span className="text-foreground/80">{proposal.expected}</span></div>}
            </div>
          )}
          <textarea value={change} onChange={(e) => setChange(e.target.value)} rows={2} placeholder="What to change — make the price the headline · lose the stock photo · say who it is for" className={`${CONTROL} resize-y`} />
          <KeepListEditor value={keep} onChange={setKeep} compact />
          <div className="flex items-center gap-2">
            <button type="button" onClick={remake} disabled={busy === "remake"} className="btn btn-sm btn-primary">{busy === "remake" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wand2 className="w-3.5 h-3.5" />} Remake</button>
            {!proposal && latest && <button type="button" onClick={propose} disabled={busy === "propose"} className="btn btn-sm btn-secondary">{busy === "propose" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />} Suggest from the run</button>}
            <button type="button" onClick={() => { setPanel(null); setProposal(null); }} className="btn btn-sm btn-ghost">Cancel</button>
            <span className="text-[10px] text-muted-foreground">The new version appears under this one, checked against the keep-list.</span>
          </div>
        </div>
      )}

      {panel === "details" && (
        <div className="mt-3 rounded-lg border border-border/60 bg-background/40 p-3 text-[11px] space-y-2">
          {img.brief?.rationale && <p><span className="text-muted-foreground">Why it looks like this: </span>{img.brief.rationale}</p>}
          {img.brief?.note && <p><span className="text-muted-foreground">Note: </span>{img.brief.note}</p>}
          {img.brief?.hero_prompt && <p><span className="text-muted-foreground">Picture brief: </span>{img.brief.hero_prompt} <span className="text-muted-foreground">· drawn by {img.brief.hero_provider === "none" ? "a placeholder (no provider key)" : img.brief.hero_provider}</span>{img.brief.hero_error ? <span className="text-amber-300"> · provider failed: {img.brief.hero_error}</span> : null}</p>}
          {img.layout ? (
            <div>
              <div className="text-muted-foreground mb-0.5">{img.layout.read_from_image ? "What the system read on this image:" : "The words, as set:"}</div>
              <ul className="space-y-0.5 text-foreground/85">
                {img.layout.headline && <li className="font-medium">{img.layout.headline}</li>}
                {img.layout.subline && <li>{img.layout.subline}</li>}
                {(img.layout.body_lines || []).map((l: string, i: number) => <li key={`b${i}`}>{l}</li>)}
                {(img.layout.claim_lines || []).map((l: string, i: number) => <li key={`c${i}`} className="text-primary/90">“{l}”</li>)}
                {img.layout.cta && <li>→ {img.layout.cta}</li>}
                {img.layout.small_print && <li className="text-muted-foreground">{img.layout.small_print}</li>}
              </ul>
            </div>
          ) : img.source === "upload" ? (
            <button type="button" onClick={read} disabled={busy === "read"} className="btn btn-sm btn-secondary">{busy === "read" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Eye className="w-3.5 h-3.5" />} Read what is on it</button>
          ) : null}
          {check && (
            <div>
              <div className="text-muted-foreground mb-0.5 flex items-center gap-2">Keep-list check · {ago(check.checked_at)}
                <button type="button" onClick={recheck} disabled={busy === "check"} className="text-primary hover:underline flex items-center gap-1">{busy === "check" ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />} re-check</button>
              </div>
              <ul className="space-y-0.5">
                {check.items.map((it, i) => (
                  <li key={i} className="flex gap-1.5">
                    {it.ok ? <Check className="w-3.5 h-3.5 text-emerald-300 shrink-0" /> : <X className="w-3.5 h-3.5 text-red-300 shrink-0" />}
                    <span><span className="text-muted-foreground">{KEEP_LABEL[it.type]}:</span> {it.value} <span className="text-muted-foreground">· {it.note} ({it.how === "text" ? "set in type" : "seen by the model"})</span></span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <p className="text-muted-foreground">{img.width}×{img.height} · {Math.round(img.size_bytes / 1024)} KB · ~{img.tokens_per_showing.toLocaleString()} tokens a showing{img.created_at ? ` · ${ago(img.created_at)}` : ""}</p>
        </div>
      )}
    </div>
  );
}

// ── the keep-list editor ──────────────────────────────────────────────────────

export function KeepListEditor({ value, onChange, compact = false }: { value: KeepItem[]; onChange: (v: KeepItem[]) => void; compact?: boolean }) {
  const [type, setType] = useState<KeepItem["type"]>("text");
  const [text, setText] = useState("");
  function add() {
    const v = text.trim();
    if (!v) return;
    if (!value.some((k) => k.type === type && k.value.toLowerCase() === v.toLowerCase())) onChange([...value, { type, value: v }]);
    setText("");
  }
  return (
    <div className="space-y-1.5">
      {!compact && (
        <div>
          <label className="text-xs text-muted-foreground block">Keep-list</label>
          <p className="text-[10px] text-muted-foreground/70">What every version must honour: words that must read exactly (a claim, a price, a legal line), things that must show, things that must not.</p>
        </div>
      )}
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {value.map((k, i) => (
            <span key={i} className="text-[10px] rounded px-1.5 py-0.5 border border-border/60 text-foreground/80 flex items-center gap-1">
              <span className="text-muted-foreground">{KEEP_LABEL[k.type]}:</span> {k.value}
              <button type="button" onClick={() => onChange(value.filter((_, j) => j !== i))} className="text-muted-foreground hover:text-foreground"><X className="w-3 h-3" /></button>
            </span>
          ))}
        </div>
      )}
      <div className="flex gap-1.5">
        <select value={type} onChange={(e) => setType(e.target.value as KeepItem["type"])} className="bg-input border border-border rounded-lg px-2 py-1.5 text-[11px]">
          <option value="text">Must read exactly</option>
          <option value="present">Must show</option>
          <option value="absent">Must not show</option>
        </select>
        <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
          placeholder={type === "text" ? "£3.50 a meal" : type === "present" ? "the product pack" : "children"} className="flex-1 bg-input border border-border rounded-lg px-2 py-1.5 text-[11px]" />
        <button type="button" onClick={add} className="btn btn-sm btn-secondary"><Plus className="w-3.5 h-3.5" /></button>
      </div>
    </div>
  );
}
