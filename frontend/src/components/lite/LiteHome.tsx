"use client";

/** The simple view's first screen: one question, one place to add anything, one button.
 *  Research starts on its own in the background; the reader never sees it. */

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, Session } from "@/lib/api";
import { autoTitle, classifyText, Dropped, friendlyStatus, fromFile, ingestDropped, proLinks } from "@/lib/lite";
import Detail from "./Detail";
import { Switch } from "@/components/population/controls";
import { cn } from "@/lib/utils";
import { useLiteRoot } from "@/lib/lite";
import { ArrowRight, ArrowUpRight, FileText, Link2, Loader2, LogOut, Paperclip, Plus, Type, X, Youtube } from "lucide-react";

type Props = {
  userEmail?: string | null;
  onSignOut?: () => void;
  onSwitchToPro: () => void;
};

export default function LiteHome({ userEmail, onSignOut, onSwitchToPro }: Props) {
  useLiteRoot();
  const router = useRouter();
  const [question, setQuestion] = useState("");
  const [title, setTitle] = useState("");
  const [titleTouched, setTitleTouched] = useState(false);
  const [items, setItems] = useState<Dropped[]>([]);
  const [addText, setAddText] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [creating, setCreating] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [showAll, setShowAll] = useState(false);
  const [research, setResearch] = useState(true);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => { api.sessions.list("mine").then((s) => setSessions(s as Session[])).catch(() => {}); }, []);
  useEffect(() => { if (!titleTouched) setTitle(autoTitle(question)); }, [question, titleTouched]);

  function addFromText() {
    const d = classifyText(addText);
    if (!d) return;
    setItems((prev) => [...prev, d]);
    setAddText("");
  }
  function addFiles(files: FileList | File[]) {
    setItems((prev) => [...prev, ...Array.from(files).map(fromFile)]);
  }

  async function start(e: React.FormEvent) {
    e.preventDefault();
    if (!question.trim() || creating) return;
    setError(null);
    setCreating("Starting…");
    try {
      const s = (await api.sessions.create((title || autoTitle(question)).trim(), question.trim(), { auto_research: research })) as Session;
      for (let i = 0; i < items.length; i++) {
        setCreating(`Adding ${i + 1} of ${items.length}…`);
        try { await ingestDropped(s.id, items[i]); } catch (err) { console.error("ingest failed", err); }
      }
      router.push(`/lite/${s.id}`);
    } catch (err: any) {
      setError(err?.message || "Could not start. Is the server awake?");
      setCreating(null);
    }
  }

  const visible = showAll ? sessions : sessions.slice(0, 6);

  return (
    <div className="lite lite-bg min-h-screen text-foreground flex flex-col">
      <header className="h-14 px-4 sm:px-6 flex items-center gap-3">
        <span className="text-[14px] font-semibold tracking-tight">11 Minds Population</span>
        <span className="text-[12px] text-muted-foreground hidden sm:inline">Simple view</span>
        <div className="ml-auto flex items-center gap-2">
          <ModeSwitch mode="simple" onPro={onSwitchToPro} />
          {userEmail && (
            <>
              <span className="text-[12px] text-muted-foreground hidden md:inline max-w-[200px] truncate" title={userEmail}>{userEmail}</span>
              {onSignOut && (
                <button type="button" onClick={onSignOut} className="w-9 h-9 rounded-full inline-flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-foreground/5" title="Sign out">
                  <LogOut className="w-4 h-4" />
                </button>
              )}
            </>
          )}
        </div>
      </header>

      <main className="flex-1 px-5 sm:px-8 pb-24">
        <div className="max-w-6xl xl:max-w-7xl 2xl:max-w-[96rem] mx-auto pt-6 sm:pt-10 grid gap-6 xl:gap-x-16 2xl:gap-x-20 xl:gap-y-14 xl:grid-cols-[minmax(0,42rem)_minmax(0,1fr)] xl:grid-rows-[auto_auto] items-start">
          <Cover />
          <div className="min-w-0 xl:col-start-1 xl:row-start-1 xl:pt-6">
          <h1 className="lite-h1 animate-rise">What do you want to find out?</h1>
          <p className="lite-lead mt-3 max-w-xl animate-rise" style={{ animationDelay: "60ms" }}>
            Ask a question. We&apos;ll gather what&apos;s out there, create people who match your audience, let them talk it through, and write you the answer.
          </p>

          <form onSubmit={start} className="mt-8 animate-rise" style={{ animationDelay: "120ms" }}>
            <div
              className={cn("lite-card p-5 sm:p-6 transition-shadow", dragOver && "ring-2 ring-primary/40")}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => { e.preventDefault(); setDragOver(false); if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files); else { const t = e.dataTransfer.getData("text"); const d = classifyText(t); if (d) setItems((p) => [...p, d]); } }}
            >
              <textarea
                autoFocus
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                rows={3}
                placeholder="e.g. Would parents in London pay for a weekly meal-kit for toddlers?"
                className="lite-input text-[19px] sm:text-[21px] leading-snug font-medium"
              />

              {question.trim() && (
                <div className="mt-3 flex items-center gap-2 text-[13px] animate-fade-in">
                  <span className="text-muted-foreground shrink-0">Call it</span>
                  <input value={title} onChange={(e) => { setTitle(e.target.value); setTitleTouched(true); }} className="lite-input text-[13px] font-medium text-foreground/80 flex-1 min-w-0 border-b border-dashed border-border focus:border-primary/50 rounded-none" />
                </div>
              )}

              <div className="my-4 border-t border-border" />

              <p className="lite-label">Add anything <span className="text-muted-foreground font-normal">(optional)</span></p>
              <p className="lite-help mt-0.5">A file, a web page, a YouTube video or some text. Everything you add is read and remembered.</p>

              {items.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {items.map((it) => (
                    <span key={it.id} className="lite-pill max-w-full">
                      <ItemIcon kind={it.kind} />
                      <span className="truncate max-w-[220px]">{it.label}</span>
                      <button type="button" onClick={() => setItems((p) => p.filter((x) => x.id !== it.id))} className="text-muted-foreground hover:text-foreground -mr-1" title="Remove"><X className="w-3.5 h-3.5" /></button>
                    </span>
                  ))}
                </div>
              )}

              <div className="mt-3 flex items-center gap-2">
                <div className="flex-1 flex items-center gap-2 rounded-2xl border border-border bg-background px-3 h-11 focus-within:border-primary/50 focus-within:ring-2 focus-within:ring-primary/20 transition-all">
                  <Link2 className="w-4 h-4 text-muted-foreground shrink-0" />
                  <input
                    value={addText}
                    onChange={(e) => setAddText(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addFromText(); } }}
                    onPaste={(e) => { const t = e.clipboardData.getData("text"); if (t && t.length > 300) { e.preventDefault(); const d = classifyText(t); if (d) setItems((p) => [...p, d]); } }}
                    placeholder="Paste a link or some text, then press Enter"
                    className="lite-input text-[14px]"
                  />
                  {addText.trim() && (
                    <button type="button" onClick={addFromText} className="w-7 h-7 rounded-full bg-foreground text-background inline-flex items-center justify-center shrink-0" title="Add"><Plus className="w-4 h-4" /></button>
                  )}
                </div>
                <button type="button" onClick={() => fileRef.current?.click()} className="lite-btn-soft h-11 px-4 shrink-0" title="Add a file">
                  <Paperclip className="w-4 h-4" /> <span className="hidden sm:inline">File</span>
                </button>
                <input ref={fileRef} type="file" multiple className="hidden" onChange={(e) => { if (e.target.files?.length) addFiles(e.target.files); e.currentTarget.value = ""; }} />
              </div>
            </div>

            <label className="mt-4 flex items-start gap-3 cursor-pointer select-none">
              <span className="pt-0.5"><Switch on={research} onChange={setResearch} label="Research the web for me" /></span>
              <span className="min-w-0">
                <span className="lite-label block">Research the web for me</span>
                <span className="lite-help block mt-0.5">Looks up what people are saying online about your question and gives it to the people. Takes 3–5 minutes in the background; switch it off if you only want them to read what you add.</span>
              </span>
            </label>

            <div className="mt-5 flex items-center gap-4 flex-wrap">
              <button type="submit" disabled={!question.trim() || !!creating} className="lite-btn">
                {creating ? <><Loader2 className="w-4 h-4 animate-spin" /> {creating}</> : <>Start <ArrowRight className="w-4 h-4" /></>}
              </button>
              <p className="lite-help max-w-sm">Nothing to set up. We look things up ourselves while you describe who to ask.</p>
            </div>
            {error && <p className="mt-3 text-[13px] text-red-700 bg-red-500/10 rounded-xl px-3.5 py-2.5">{error}</p>}
          </form>
          </div>

          {sessions.length > 0 && (
            <section className="min-w-0 mt-14 xl:mt-0 xl:col-start-1 xl:row-start-2 animate-rise" style={{ animationDelay: "180ms" }}>
              <div className="flex items-baseline justify-between">
                <h2 className="text-[13px] font-semibold text-muted-foreground uppercase tracking-wider">Your questions</h2>
                {sessions.length > 6 && (
                  <button type="button" onClick={() => setShowAll((v) => !v)} className="text-[12.5px] text-muted-foreground hover:text-foreground">{showAll ? "Show fewer" : `Show all ${sessions.length}`}</button>
                )}
              </div>
              <div className="mt-3 space-y-2">
                {visible.map((s) => {
                  const st = friendlyStatus(s);
                  return (
                    <Detail key={s.id} href={proLinks.session(s.id)}>
                      <button type="button" onClick={() => router.push(`/lite/${s.id}`)} className="w-full text-left lite-card px-4 py-3.5 hover:border-foreground/20 transition-colors flex items-center gap-4">
                        <div className="min-w-0 flex-1">
                          <p className="text-[14.5px] font-medium text-foreground truncate">{s.title}</p>
                          <p className="text-[13px] text-muted-foreground truncate mt-0.5">{s.query}</p>
                        </div>
                        <span className="shrink-0 inline-flex items-center gap-1.5 text-[12.5px] text-muted-foreground">
                          <span className={cn("w-1.5 h-1.5 rounded-full", st.tone === "live" ? "bg-sky-500 animate-pulse" : st.tone === "done" ? "bg-primary" : "bg-muted-foreground/40")} />
                          {st.text}
                        </span>
                        <ArrowRight className="w-4 h-4 text-muted-foreground/60 shrink-0" />
                      </button>
                    </Detail>
                  );
                })}
              </div>
            </section>
          )}
        </div>
      </main>
    </div>
  );
}

/** The cover: a short looping film of three of the people (`/minds-people.mp4`). The film is drawn
 *  frame by frame onto a canvas and its white ground keyed out pixel by pixel, so the people stand
 *  on the page itself rather than in a box (a CSS blend mode is not honoured on video everywhere).
 *  Purely decorative; sits above the headline, or on a wide screen fills the right-hand column and
 *  is centred on the question block (headline to Start) beside it, the list of questions running on
 *  below. Shows only its first frame when the reader prefers reduced motion. */
function Cover() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const v = videoRef.current;
    const c = canvasRef.current;
    if (!v || !c) return;
    const ctx = c.getContext("2d", { willReadFrequently: true });
    if (!ctx) return;
    const W = 1280, H = 720;                                   // the film's own size, so it stays sharp when drawn large
    c.width = W; c.height = H;
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    let stopped = false;
    const draw = () => {
      if (v.readyState < 2) return;
      ctx.drawImage(v, 0, 0, W, H);
      const img = ctx.getImageData(0, 0, W, H);
      const d = img.data;
      for (let i = 0; i < d.length; i += 4) {
        const m = Math.min(d[i], d[i + 1], d[i + 2]);           // whiteness: how close to the ground
        if (m >= 250) d[i + 3] = 0;                              // the ground: gone
        else if (m >= 240) d[i + 3] = ((250 - m) * 25.5) | 0;   // a soft step on the outlines
      }
      ctx.putImageData(img, 0, 0);
    };
    const anyV = v as HTMLVideoElement & { requestVideoFrameCallback?: (cb: () => void) => number };
    const loop = () => {
      if (stopped) return;
      draw();
      if (anyV.requestVideoFrameCallback) anyV.requestVideoFrameCallback(loop); else requestAnimationFrame(loop);
    };
    const onReady = () => {
      if (still) { v.pause(); draw(); return; }
      v.play().catch(() => {});
      loop();
    };
    v.addEventListener("loadeddata", onReady);
    if (v.readyState >= 2) onReady();
    return () => { stopped = true; v.removeEventListener("loadeddata", onReady); };
  }, []);
  return (
    <div className="xl:col-start-2 xl:row-start-1 xl:self-center animate-rise" aria-hidden>
      <div className="relative aspect-video w-full max-w-lg xl:max-w-none">
        <video
          ref={videoRef}
          src="/minds-people.mp4"
          autoPlay
          muted
          loop
          playsInline
          preload="auto"
          className="absolute w-px h-px opacity-0 pointer-events-none"
        />
        <canvas ref={canvasRef} className="absolute inset-0 w-full h-full" />
      </div>
    </div>
  );
}

function ItemIcon({ kind }: { kind: Dropped["kind"] }) {
  const c = "w-3.5 h-3.5 text-muted-foreground";
  if (kind === "file") return <FileText className={c} />;
  if (kind === "youtube") return <Youtube className={c} />;
  if (kind === "url") return <Link2 className={c} />;
  return <Type className={c} />;
}

/** Simple ⇄ Pro. Shown on both landings so either kind of reader can find the other view. */
export function ModeSwitch({ mode, onPro, onSimple, className }: { mode: "simple" | "pro"; onPro?: () => void; onSimple?: () => void; className?: string }) {
  return (
    <div className={cn("seg", className)} role="tablist" aria-label="View">
      <button type="button" role="tab" data-on={mode === "simple"} onClick={onSimple} className="seg-item" title="The simple view: one step at a time, only what matters">Simple</button>
      <button type="button" role="tab" data-on={mode === "pro"} onClick={onPro} className="seg-item" title="The full portal: every tool and every figure">Pro <ArrowUpRight className="w-3 h-3 -ml-0.5 opacity-60" /></button>
    </div>
  );
}
