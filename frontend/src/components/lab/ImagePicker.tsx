"use client";

/** The Visual Lab's image input (step 1, 2026-10-26).
 *
 *  A session's images as thumbnails: tap to put one in the run (several are shown together as
 *  one piece), upload more, rename, delete. The value is the spec's `images: [{id, label}]`,
 *  so the picker is the only thing that knows images are chosen from a store — the instrument
 *  just declared an input of type "images". */

import { ChangeEvent, useCallback, useEffect, useRef, useState } from "react";
import { api, ImageRef, SessionImage } from "@/lib/api";
import { AlertTriangle, Check, ImagePlus, Loader2, Pencil, Trash2, X } from "lucide-react";
import { forgetImageUrl, useImageUrl } from "./useImageUrl";

interface Props {
  sessionId: string;
  value: ImageRef[];
  onChange: (value: ImageRef[]) => void;
  /** Only one image in the run (a variant of a choose-between test reads better with one). */
  single?: boolean;
}

export default function ImagePicker({ sessionId, value, onChange, single = false }: Props) {
  const [images, setImages] = useState<SessionImage[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const r = await api.images.list(sessionId);
      setImages(r.images);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [sessionId]);
  useEffect(() => { load(); }, [load]);

  const chosen = new Set(value.map((v) => v.id));

  function toggle(img: SessionImage) {
    if (chosen.has(img.id)) onChange(value.filter((v) => v.id !== img.id));
    else if (single) onChange([{ id: img.id, label: img.label || img.filename }]);
    else onChange([...value, { id: img.id, label: img.label || img.filename }]);
  }

  async function upload(e: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    if (!files.length) return;
    setError(null);
    setUploading(files.length);
    const added: ImageRef[] = [];
    for (const f of files) {
      try {
        const img = await api.images.upload(sessionId, f);
        setImages((prev) => [img, ...prev]);
        added.push({ id: img.id, label: img.label || img.filename });
      } catch (err: any) {
        setError(`${f.name}: ${err?.message || String(err)}`);
      } finally {
        setUploading((n) => n - 1);
      }
    }
    // What was just uploaded is what the analyst wants to show; put it straight in the run.
    if (added.length) onChange(single ? [added[0]] : [...value, ...added]);
  }

  async function rename(img: SessionImage) {
    const label = draft.trim();
    setRenaming(null);
    if (!label || label === img.label) return;
    try {
      const updated = await api.images.rename(sessionId, img.id, label);
      setImages((prev) => prev.map((x) => (x.id === img.id ? updated : x)));
      if (chosen.has(img.id)) onChange(value.map((v) => (v.id === img.id ? { ...v, label } : v)));
    } catch (e: any) {
      setError(e?.message || String(e));
    }
  }

  async function remove(img: SessionImage) {
    setConfirming(null);
    setError(null);
    try {
      await api.images.remove(sessionId, img.id);
      forgetImageUrl(sessionId, img.id);
      setImages((prev) => prev.filter((x) => x.id !== img.id));
      if (chosen.has(img.id)) onChange(value.filter((v) => v.id !== img.id));
    } catch (e: any) {
      setError(e?.message || String(e));
    }
  }

  return (
    <div className="space-y-2">
      <input ref={fileInput} type="file" accept="image/*" multiple={!single} className="hidden" onChange={upload} />
      <div className="grid grid-cols-3 gap-1.5">
        <button type="button" onClick={() => fileInput.current?.click()} disabled={uploading > 0}
          className="aspect-square rounded-lg border border-dashed border-border/70 hover:border-primary/60 hover:text-primary text-muted-foreground flex flex-col items-center justify-center gap-1 text-[10px] transition-colors disabled:opacity-50">
          {uploading > 0 ? <Loader2 className="w-4 h-4 animate-spin" /> : <ImagePlus className="w-4 h-4" />}
          {uploading > 0 ? `${uploading} left…` : "Upload"}
        </button>
        {images.map((img) => (
          <Thumb
            key={img.id}
            sessionId={sessionId}
            image={img}
            selected={chosen.has(img.id)}
            order={value.findIndex((v) => v.id === img.id)}
            showOrder={!single && value.length > 1}
            onToggle={() => toggle(img)}
            renaming={renaming === img.id}
            draft={draft}
            setDraft={setDraft}
            onStartRename={() => { setRenaming(img.id); setDraft(img.label || img.filename); }}
            onRename={() => rename(img)}
            onCancelRename={() => setRenaming(null)}
            confirming={confirming === img.id}
            onAskDelete={() => setConfirming(img.id)}
            onCancelDelete={() => setConfirming(null)}
            onDelete={() => remove(img)}
          />
        ))}
      </div>
      {loading && <p className="text-[10px] text-muted-foreground">Loading images…</p>}
      {!loading && images.length === 0 && (
        <p className="text-[10px] text-muted-foreground/70">No images in this session yet. Upload a poster, a pack shot, a page, an ad.</p>
      )}
      {value.length > 0 && (
        <p className="text-[10px] text-muted-foreground">
          {value.length === 1 ? "Showing" : `Showing ${value.length} together:`} {value.map((v) => v.label || "image").join(" · ")}
        </p>
      )}
      {error && (
        <div className="flex gap-2 text-[11px] text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" /><span>{error}</span>
        </div>
      )}
    </div>
  );
}

function Thumb({
  sessionId, image, selected, order, showOrder, onToggle, renaming, draft, setDraft, onStartRename, onRename, onCancelRename,
  confirming, onAskDelete, onCancelDelete, onDelete,
}: {
  sessionId: string; image: SessionImage; selected: boolean; order: number; showOrder: boolean; onToggle: () => void;
  renaming: boolean; draft: string; setDraft: (v: string) => void; onStartRename: () => void; onRename: () => void; onCancelRename: () => void;
  confirming: boolean; onAskDelete: () => void; onCancelDelete: () => void; onDelete: () => void;
}) {
  const url = useImageUrl(sessionId, image.id);
  const label = image.label || image.filename || "image";
  return (
    <div className={`group relative aspect-square rounded-lg overflow-hidden border transition-colors ${selected ? "border-primary ring-1 ring-primary/50" : "border-border/60 hover:border-border"}`}>
      <button type="button" onClick={onToggle} title={label} className="absolute inset-0 w-full h-full bg-muted/40">
        {url ? <img src={url} alt={label} className="w-full h-full object-cover" /> : <div className="w-full h-full animate-pulse bg-muted/60" />}
      </button>
      {selected && (
        <span className="absolute top-1 left-1 w-4 h-4 rounded-full bg-primary text-primary-foreground text-[9px] font-medium flex items-center justify-center pointer-events-none">
          {showOrder ? order + 1 : <Check className="w-2.5 h-2.5" />}
        </span>
      )}
      {!renaming && !confirming && (
        <div className="absolute top-1 right-1 hidden group-hover:flex gap-0.5">
          <button type="button" onClick={onStartRename} title="Rename" className="w-5 h-5 rounded bg-background/80 text-muted-foreground hover:text-foreground flex items-center justify-center"><Pencil className="w-3 h-3" /></button>
          <button type="button" onClick={onAskDelete} title="Delete" className="w-5 h-5 rounded bg-background/80 text-muted-foreground hover:text-red-400 flex items-center justify-center"><Trash2 className="w-3 h-3" /></button>
        </div>
      )}
      {renaming ? (
        <div className="absolute inset-x-0 bottom-0 bg-background/90 p-1 flex gap-1">
          <input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") onRename(); if (e.key === "Escape") onCancelRename(); }}
            className="flex-1 min-w-0 bg-input border border-border rounded px-1 text-[10px]" />
          <button type="button" onClick={onRename} className="text-primary"><Check className="w-3 h-3" /></button>
          <button type="button" onClick={onCancelRename} className="text-muted-foreground"><X className="w-3 h-3" /></button>
        </div>
      ) : confirming ? (
        <div className="absolute inset-x-0 bottom-0 bg-background/90 p-1 flex items-center justify-between gap-1 text-[10px]">
          <span className="text-muted-foreground truncate">Delete?</span>
          <button type="button" onClick={onDelete} className="text-red-400 font-medium">Yes</button>
          <button type="button" onClick={onCancelDelete} className="text-muted-foreground">No</button>
        </div>
      ) : (
        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-background/90 to-transparent px-1.5 pt-3 pb-1 pointer-events-none">
          <span className="block text-[10px] text-foreground/90 truncate">{label}</span>
        </div>
      )}
    </div>
  );
}

/** The images a run was made on, as a row of thumbnails — for results pages and the A/B arms list. */
export function ImageStrip({ sessionId, images, size = 96, captions = false }: { sessionId: string; images: ImageRef[]; size?: number; captions?: boolean }) {
  if (!images.length) return null;
  return (
    <div className="flex flex-wrap gap-2 shrink-0">
      {images.map((ref, k) => <StripThumb key={`${ref.id}-${k}`} sessionId={sessionId} image={ref} size={size} caption={captions} />)}
    </div>
  );
}

function StripThumb({ sessionId, image, size, caption }: { sessionId: string; image: ImageRef; size: number; caption: boolean }) {
  const url = useImageUrl(sessionId, image.id);
  const label = image.option ? `${image.option} · ${image.label || "image"}` : image.label || "image";
  return (
    <figure className="m-0" style={{ width: size }}>
      <div className="rounded-md overflow-hidden border border-border/60 bg-muted/40" style={{ width: size, height: size }} title={label}>
        {url ? <img src={url} alt={label} className="w-full h-full object-cover" /> : <div className="w-full h-full animate-pulse bg-muted/60" />}
      </div>
      {caption && <figcaption className="text-[10px] text-muted-foreground truncate mt-0.5">{label}</figcaption>}
    </figure>
  );
}

/** One image at reading size, with a lightbox on click — the top of the Visuals results page. */
export function ImageHero({ sessionId, images }: { sessionId: string; images: ImageRef[] }) {
  const [open, setOpen] = useState<ImageRef | null>(null);
  if (!images.length) return null;
  return (
    <>
      <div className="flex flex-wrap gap-3">
        {images.map((ref, k) => <HeroThumb key={`${ref.id}-${k}`} sessionId={sessionId} image={ref} onOpen={() => setOpen(ref)} />)}
      </div>
      {open && <Lightbox sessionId={sessionId} image={open} onClose={() => setOpen(null)} />}
    </>
  );
}

function HeroThumb({ sessionId, image, onOpen }: { sessionId: string; image: ImageRef; onOpen: () => void }) {
  const url = useImageUrl(sessionId, image.id);
  const label = image.option ? `Option ${image.option} · ${image.label || "image"}` : image.label || "image";
  return (
    <figure className="m-0">
      <button type="button" onClick={onOpen} className="block rounded-lg overflow-hidden border border-border/60 bg-muted/40 max-h-72" title="Open full size">
        {url ? <img src={url} alt={label} className="max-h-72 w-auto object-contain" /> : <div className="w-48 h-48 animate-pulse bg-muted/60" />}
      </button>
      <figcaption className="text-[11px] text-muted-foreground mt-1">{label}</figcaption>
    </figure>
  );
}

function Lightbox({ sessionId, image, onClose }: { sessionId: string; image: ImageRef; onClose: () => void }) {
  const url = useImageUrl(sessionId, image.id);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 bg-background/90 flex items-center justify-center p-6" onClick={onClose}>
      {url && <img src={url} alt={image.label || "image"} className="max-w-full max-h-full object-contain rounded-lg shadow-2xl" />}
      <button type="button" onClick={onClose} className="absolute top-4 right-4 text-muted-foreground hover:text-foreground"><X className="w-5 h-5" /></button>
    </div>
  );
}
