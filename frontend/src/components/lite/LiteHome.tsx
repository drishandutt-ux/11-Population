"use client";

/** The simple view's first screen: one question, one place to add anything, one button.
 *  Research starts on its own in the background; the reader never sees it. */

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, Session } from "@/lib/api";
import { autoTitle, classifyText, Dropped, friendlyStatus, fromFile, ingestDropped, proLinks } from "@/lib/lite";
import Detail from "./Detail";
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
      const s = (await api.sessions.create((title || autoTitle(question)).trim(), question.trim(), { auto_research: true })) as Session;
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
        <span className="text-[14px] font-semibold tracking-tight">11 Minds</span>
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
        <div className="max-w-2xl mx-auto pt-10 sm:pt-16">
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

            <div className="mt-5 flex items-center gap-4 flex-wrap">
              <button type="submit" disabled={!question.trim() || !!creating} className="lite-btn">
                {creating ? <><Loader2 className="w-4 h-4 animate-spin" /> {creating}</> : <>Start <ArrowRight className="w-4 h-4" /></>}
              </button>
              <p className="lite-help max-w-sm">Nothing to set up. We look things up ourselves while you describe who to ask.</p>
            </div>
            {error && <p className="mt-3 text-[13px] text-red-700 bg-red-500/10 rounded-xl px-3.5 py-2.5">{error}</p>}
          </form>

          {sessions.length > 0 && (
            <section className="mt-14 animate-rise" style={{ animationDelay: "180ms" }}>
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
