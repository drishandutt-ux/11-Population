"use client";

/** The Forms studio — the Survey instrument's input panel, given the whole Lab tab.
 *
 *  Three ways to a questionnaire, all reading the session's Lab brief (what the session has
 *  established, written once by the model and kept per session):
 *    · upload or paste one you already have → typed questions
 *    · "write it for me" → a form that goes after the brief's open questions, or your goal
 *    · a research colleague in the chat who brainstorms and edits the form on screen
 *  The form in the middle is always the thing that runs; the chat and the writers only ever
 *  hand back a complete form, which replaces (or extends) it with an undo. The shell's own
 *  run controls — who answers, model, estimate, Run — sit in the right rail. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api, FormDraft, FormQuestion, FormsChatMessage, LabBriefState, SurveyQuestion, SurveyQuestionType, SurveyTemplate,
} from "@/lib/api";
import {
  ArrowUp, BookOpen, ChevronDown, ChevronLeft, ChevronRight, Eye, FileUp, LayoutTemplate, Loader2, MessageSquare, Pencil,
  Plus, RefreshCw, Sparkles, Undo2, X,
} from "lucide-react";
import { InstrumentFormProps } from "./index";
import QuestionEditor, { FormPreview, TYPES, blank, nextKey, problemsOf } from "./QuestionEditor";
import { Draft, Md, ago, appendQuestions, changedKeys, readDraft } from "./formUtils";

// Draft, readDraft, changedKeys, appendQuestions, ago and Md live in formUtils, shared with the simple view.
type ChatItem = FormsChatMessage & { chips?: string[]; note?: string };
type Panel = null | "import" | "write" | "templates";
type Toast = { text: string; undo: Draft | null } | null;

const MAX_HISTORY = 24;
const draftKey = (sid: string) => `forms:draft:${sid}`;
const chatKey = (sid: string) => `forms:chat:${sid}`;

export default function FormsStudio({ instrument, values, onChange, sessionId = "", controls, aside, onBack }: InstrumentFormProps) {
  const draft = useMemo(() => readDraft(values), [values]);
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const hasForm = draft.questions.length > 0;
  const templates: SurveyTemplate[] = instrument.templates || [];

  // The brief: what the assistants know. Loaded on open; built (or rebuilt when stale) in the background.
  const [brief, setBrief] = useState<LabBriefState | null>(null);
  const [briefBusy, setBriefBusy] = useState(false);
  const [briefOpen, setBriefOpen] = useState(false);
  const [briefError, setBriefError] = useState<string | null>(null);

  // The chat.
  const [messages, setMessages] = useState<ChatItem[]>([]);
  const [chatBusy, setChatBusy] = useState(false);
  const [input, setInput] = useState("");
  const [chatOpen, setChatOpen] = useState(false);     // the drawer below xl
  const [chatError, setChatError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const openingAsked = useRef(false);

  // The panels and the form's own chrome.
  const [panel, setPanel] = useState<Panel>(null);
  const [preview, setPreview] = useState(false);
  const [introOpen, setIntroOpen] = useState(false);
  const [pasteText, setPasteText] = useState("");
  const [importBusy, setImportBusy] = useState(false);
  const [goal, setGoal] = useState("");
  const [length, setLength] = useState<"short" | "standard" | "deep">("standard");
  const [writeBusy, setWriteBusy] = useState<string | null>(null);   // which goal is being written
  const [dragging, setDragging] = useState(false);
  const [toast, setToast] = useState<Toast>(null);
  const [flash, setFlash] = useState<Set<string>>(new Set());
  const [actionError, setActionError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const setDraft = useCallback((next: Draft) => {
    onChange("title", next.title);
    onChange("intro", next.intro);
    onChange("questions", next.questions);
  }, [onChange]);

  // ── persistence: the draft and the chat survive a tab switch ─────────────────
  useEffect(() => {
    if (!sessionId) return;
    try {
      if (draftRef.current.questions.length === 0 && !draftRef.current.title) {
        const raw = sessionStorage.getItem(draftKey(sessionId));
        if (raw) { const d = JSON.parse(raw) as Draft; if (d && Array.isArray(d.questions) && d.questions.length) setDraft(d); }
      }
      const rawChat = sessionStorage.getItem(chatKey(sessionId));
      if (rawChat) { const m = JSON.parse(rawChat); if (Array.isArray(m) && m.length) { setMessages(m); openingAsked.current = true; } }
    } catch { /* private mode */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    const t = setTimeout(() => { try { sessionStorage.setItem(draftKey(sessionId), JSON.stringify(draft)); } catch { /* private mode */ } }, 300);
    return () => clearTimeout(t);
  }, [draft, sessionId]);

  useEffect(() => {
    if (!sessionId || !messages.length) return;
    try { sessionStorage.setItem(chatKey(sessionId), JSON.stringify(messages.slice(-60))); } catch { /* private mode */ }
  }, [messages, sessionId]);

  // ── the brief, then the opening line ───────────────────────────────────────────
  const loadBrief = useCallback(async (force = false) => {
    if (!sessionId) return null;
    setBriefBusy(true); setBriefError(null);
    try {
      let b = force ? null : await api.lab.brief(sessionId);
      if (!b || !b.brief || b.stale || force) b = await api.lab.buildBrief(sessionId, force);
      setBrief(b);
      return b;
    } catch (e: any) {
      setBriefError(e?.message || "Could not read the session");
      return null;
    } finally {
      setBriefBusy(false);
    }
  }, [sessionId]);

  const askOpening = useCallback(async () => {
    if (!sessionId || openingAsked.current) return;
    openingAsked.current = true;
    try {
      const r = await api.lab.formsChat(sessionId, { messages: [], form: draftRef.current.questions.length ? draftRef.current : null });
      setMessages((m) => (m.length ? m : [{ role: "assistant", content: r.reply, chips: r.chips }]));
    } catch { /* the chat still works; the analyst just types first */ }
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    (async () => { await loadBrief(); await askOpening(); })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, chatBusy, chatOpen]);

  // ── applying what the model hands back ─────────────────────────────────────────
  const applyForm = useCallback((next: FormDraft, how: "replace" | "append", note: string) => {
    const prev = draftRef.current;
    const merged: Draft = how === "append" && prev.questions.length
      ? { title: prev.title || next.title, intro: prev.intro || next.intro, questions: appendQuestions(prev, next.questions) }
      : { title: next.title || prev.title, intro: next.intro !== undefined && next.intro !== "" ? next.intro : prev.intro, questions: next.questions };
    const changed = changedKeys(prev, merged);
    setDraft(merged);
    setFlash(changed);
    setTimeout(() => setFlash(new Set()), 2600);
    const extra = next.notes?.length ? ` · ${next.notes[0]}` : "";
    setToast({ text: (note || (how === "append" ? `Added ${next.questions.length} question${next.questions.length === 1 ? "" : "s"}` : `Form updated · ${merged.questions.length} question${merged.questions.length === 1 ? "" : "s"}`)) + extra, undo: prev.questions.length || prev.title ? prev : null });
    setPanel(null);
    setPreview(false);
    if (merged.intro) setIntroOpen(true);
  }, [setDraft]);

  const undo = () => {
    if (!toast?.undo) return;
    setDraft(toast.undo);
    setToast(null);
  };

  // ── the three ways in ──────────────────────────────────────────────────────────
  const importText = async (text: string) => {
    if (!sessionId || !text.trim()) return;
    setImportBusy(true); setActionError(null);
    try {
      const r = await api.lab.formsImportText(sessionId, text);
      if (!r.questions.length) { setActionError("I couldn't find questions in that. Try pasting just the questions, one per line."); return; }
      applyForm(r, hasForm ? "append" : "replace", `Typed up ${r.questions.length} question${r.questions.length === 1 ? "" : "s"}`);
      setPasteText("");
    } catch (e: any) {
      setActionError(e?.message || "Import failed");
    } finally {
      setImportBusy(false);
    }
  };

  const importFile = async (file: File | undefined | null) => {
    if (!sessionId || !file) return;
    setImportBusy(true); setActionError(null);
    try {
      const r = await api.lab.formsImportFile(sessionId, file);
      if (!r.questions.length) { setActionError(`I couldn't find questions in ${file.name}.`); return; }
      applyForm(r, hasForm ? "append" : "replace", `Read ${r.questions.length} question${r.questions.length === 1 ? "" : "s"} from ${file.name}`);
    } catch (e: any) {
      setActionError(e?.message || "Import failed");
    } finally {
      setImportBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const write = async (g: string, len = length) => {
    if (!sessionId) return;
    setWriteBusy(g || "_"); setActionError(null);
    try {
      const r = await api.lab.formsGenerate(sessionId, { goal: g, length: len, existing: hasForm ? draftRef.current : null });
      if (!r.questions.length) { setActionError("Nothing came back — try again, or say what you want in the chat."); return; }
      applyForm(r, "replace", r.rationale ? `Written · ${r.rationale}` : "Written from what the session knows");
      setMessages((m) => [...m, { role: "assistant", content: `I've written ${r.questions.length} questions${g ? ` on *${g}*` : " from the session's open questions"}.${r.rationale ? ` ${r.rationale}` : ""} Tell me what to change.`, chips: ["Make it shorter", "Add a why question", "Tighten the wording", "Run it"] }]);
    } catch (e: any) {
      setActionError(e?.message || "Could not write the form");
    } finally {
      setWriteBusy(null);
    }
  };

  const applyTemplate = (t: SurveyTemplate) => {
    const qs = t.questions.map((q) => ({ ...q, options: q.options ? [...q.options] : undefined, rows: q.rows ? [...q.rows] : undefined, columns: q.columns ? [...q.columns] : undefined }));
    applyForm({ title: t.title, intro: "", questions: qs, notes: [], problems: [] }, "replace", `Template · ${t.label}`);
  };

  const send = async (text: string) => {
    const t = text.trim();
    if (!t || !sessionId || chatBusy) return;
    setInput("");
    setChatError(null);
    const history: ChatItem[] = [...messages, { role: "user", content: t }];
    setMessages(history);
    setChatBusy(true);
    try {
      const r = await api.lab.formsChat(sessionId, {
        messages: history.slice(-MAX_HISTORY).map(({ role, content }) => ({ role, content })),
        form: draftRef.current.questions.length || draftRef.current.title ? draftRef.current : null,
      });
      setMessages((m) => [...m, { role: "assistant", content: r.reply, chips: r.chips, note: r.form_changed ? (r.change_note || "updated the form") : undefined }]);
      if (r.form_changed && r.form) applyForm(r.form, "replace", r.change_note || "Updated from the chat");
    } catch (e: any) {
      setChatError(e?.message || "The chat failed");
    } finally {
      setChatBusy(false);
    }
  };

  // Chips that are commands act directly; the rest are sent as the analyst's words.
  const tapChip = (c: string) => {
    const low = c.toLowerCase();
    if (low === "write it for me") { setPanel("write"); setChatOpen(false); return; }
    if (low === "i have a questionnaire") { setPanel("import"); setChatOpen(false); return; }
    if (low.startsWith("draft: ")) { void write(c.slice(7)); return; }
    if (low === "run it") { document.getElementById("forms-run")?.scrollIntoView({ behavior: "smooth", block: "center" }); document.getElementById("forms-run")?.focus(); return; }
    void send(c);
  };

  // ── editing the form by hand ───────────────────────────────────────────────────
  const questions = draft.questions;
  const setQuestions = (qs: FormQuestion[]) => onChange("questions", qs);
  const update = (i: number, patch: Partial<SurveyQuestion>) => setQuestions(questions.map((q, j) => (j === i ? { ...q, ...patch } : q)));
  const remove = (i: number) => setQuestions(questions.filter((_, j) => j !== i));
  const move = (i: number, d: -1 | 1) => {
    const j = i + d;
    if (j < 0 || j >= questions.length) return;
    const qs = [...questions];
    [qs[i], qs[j]] = [qs[j], qs[i]];
    setQuestions(qs);
  };
  const add = (type: SurveyQuestionType) => setQuestions([...questions, blank(type, nextKey(questions))]);
  const setPrimary = (i: number) => setQuestions(questions.map((q, j) => ({ ...q, primary: j === i })));
  const problemCount = questions.reduce((n, q) => n + (problemsOf(q).length ? 1 : 0), 0);
  const challenges = brief?.brief?.challenges || [];
  const topChallenge = challenges[0]?.title || "";

  const briefState: "none" | "building" | "ready" | "stale" | "failed" =
    briefBusy ? "building" : !brief || !brief.brief ? (briefError ? "failed" : "none") : brief.stale ? "stale" : "ready";

  // ── pieces ─────────────────────────────────────────────────────────────────────
  const briefChip = (
    <button type="button" onClick={() => { setBriefOpen((v) => !v); if (window.innerWidth < 1280) setChatOpen(true); }}
      title={briefState === "ready" ? `Built ${ago(brief?.built_at || null)} from ${(brief?.brief?.sources || []).join(", ") || "the question"}` : undefined}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] transition-colors ${briefState === "ready" ? "border-primary/40 text-primary bg-primary/5 hover:bg-primary/10" : briefState === "building" ? "border-border/60 text-muted-foreground" : "border-amber-400/40 text-amber-300/90 bg-amber-500/5"}`}>
      {briefState === "building" ? <Loader2 className="w-3 h-3 animate-spin" /> : <BookOpen className="w-3 h-3" />}
      {briefState === "building" && "Reading the session…"}
      {briefState === "ready" && `Knows this session · ${challenges.length} open question${challenges.length === 1 ? "" : "s"}`}
      {briefState === "stale" && "Session has moved on · refresh"}
      {briefState === "none" && "Nothing read yet"}
      {briefState === "failed" && "Couldn't read the session"}
    </button>
  );

  const briefCard = brief?.brief && (
    <div className="rounded-xl border border-border/60 bg-card/40 p-3 space-y-2.5 text-[11px] leading-relaxed">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-foreground">What I know about this session</span>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => void loadBrief(true)} disabled={briefBusy} className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground disabled:opacity-50" title="Read the session again">
            <RefreshCw className={`w-3 h-3 ${briefBusy ? "animate-spin" : ""}`} /> refresh
          </button>
          <button type="button" onClick={() => setBriefOpen(false)} className="text-muted-foreground hover:text-foreground"><X className="w-3.5 h-3.5" /></button>
        </div>
      </div>
      <p className="text-foreground/85">{brief.brief.summary}</p>
      {brief.brief.population && <p className="text-muted-foreground"><span className="text-foreground/80">Who:</span> {brief.brief.population}</p>}
      {challenges.length > 0 && (
        <div>
          <div className="text-foreground/80 mb-1">Open questions worth a form</div>
          <ol className="list-decimal pl-4 space-y-0.5 text-muted-foreground">{challenges.map((c, i) => <li key={i}><span className="text-foreground/85">{c.title}</span> — {c.measure}</li>)}</ol>
        </div>
      )}
      {brief.brief.tensions?.length > 0 && <p className="text-muted-foreground"><span className="text-foreground/80">Where they split:</span> {brief.brief.tensions.slice(0, 3).join(" · ")}</p>}
      {brief.brief.already_measured?.length > 0 && <p className="text-muted-foreground"><span className="text-foreground/80">Already measured:</span> {brief.brief.already_measured.slice(0, 4).join(" · ")}</p>}
      {brief.brief.gaps?.length > 0 && <p className="text-muted-foreground"><span className="text-foreground/80">Gaps:</span> {brief.brief.gaps.slice(0, 3).join(" · ")}</p>}
      <p className="text-[10px] text-muted-foreground/60">Read from {(brief.brief.sources || []).join(", ") || "the question alone"} · {ago(brief.built_at)}{brief.stale ? " · the session has moved on since" : ""}</p>
    </div>
  );

  const chatPane = (
    <div className="h-full flex flex-col min-h-0">
      <div className="px-4 pt-3 pb-2 flex items-center justify-between gap-2 shrink-0">
        <div className="min-w-0">
          <div className="text-xs font-medium flex items-center gap-1.5"><MessageSquare className="w-3.5 h-3.5 text-primary" /> Talk it through</div>
          <p className="text-[10px] text-muted-foreground truncate">A research colleague who has read this session</p>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {!briefOpen && brief?.brief && (
            <button type="button" onClick={() => setBriefOpen(true)} className="text-[10px] text-muted-foreground hover:text-foreground inline-flex items-center gap-1" title="What it knows"><BookOpen className="w-3 h-3" /> what I know</button>
          )}
          <button type="button" onClick={() => setChatOpen(false)} className="xl:hidden text-muted-foreground hover:text-foreground p-1"><X className="w-4 h-4" /></button>
        </div>
      </div>
      <div ref={listRef} className="flex-1 min-h-0 overflow-y-auto px-4 pb-3 space-y-3">
        {briefOpen && briefCard}
        {briefState === "failed" && briefError && (
          <p className="text-[11px] text-amber-300/85">{briefError}. <button type="button" onClick={() => void loadBrief(true)} className="underline">Try again</button></p>
        )}
        {messages.length === 0 && (
          <div className="text-[11px] text-muted-foreground flex items-center gap-2 pt-2"><Loader2 className="w-3 h-3 animate-spin" /> Reading the session…</div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "flex justify-end" : ""}>
            <div className={`max-w-[92%] text-xs leading-relaxed ${m.role === "user" ? "rounded-2xl rounded-br-md bg-primary/15 text-foreground px-3 py-2" : "text-foreground/90"}`}>
              {m.role === "user" ? <span className="whitespace-pre-wrap">{m.content}</span> : <Md text={m.content} />}
              {m.note && <p className="mt-1.5 text-[10px] text-primary/90 inline-flex items-center gap-1"><Pencil className="w-3 h-3" /> {m.note}</p>}
            </div>
            {m.role === "assistant" && i === messages.length - 1 && m.chips && m.chips.length > 0 && !chatBusy && (
              <div className="flex flex-wrap gap-1 mt-2">
                {m.chips.map((c) => (
                  <button key={c} type="button" onClick={() => tapChip(c)} className="text-[11px] rounded-full border border-border/70 px-2.5 py-1 text-foreground/80 hover:border-primary/60 hover:text-primary transition-colors">{c}</button>
                ))}
              </div>
            )}
          </div>
        ))}
        {chatBusy && <div className="text-[11px] text-muted-foreground flex items-center gap-2"><Loader2 className="w-3 h-3 animate-spin" /> thinking…</div>}
        {chatError && <p className="text-[11px] text-red-400">{chatError}</p>}
      </div>
      <div className="p-3 border-t border-border/60 shrink-0">
        <div className="flex items-end gap-2 rounded-xl border border-border/70 bg-input/40 focus-within:border-primary/50 px-3 py-2">
          <textarea value={input} onChange={(e) => setInput(e.target.value)} rows={Math.min(4, Math.max(1, input.split("\n").length))}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(input); } }}
            placeholder={hasForm ? "Change something, or ask what's missing…" : "What do you want to find out?"}
            className="flex-1 bg-transparent text-sm resize-none focus:outline-none placeholder:text-muted-foreground/50 leading-relaxed" />
          <button type="button" onClick={() => void send(input)} disabled={!input.trim() || chatBusy} title="Send (Enter)"
            className="h-7 w-7 rounded-lg bg-primary text-primary-foreground disabled:opacity-30 flex items-center justify-center shrink-0">
            <ArrowUp className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );

  const importPanel = (
    <div className="rounded-xl border border-border/60 bg-card/30 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-xs font-medium flex items-center gap-1.5"><FileUp className="w-3.5 h-3.5 text-primary" /> Have one already?</div>
        {hasForm && <button type="button" onClick={() => setPanel(null)} className="text-muted-foreground hover:text-foreground"><X className="w-3.5 h-3.5" /></button>}
      </div>
      <div onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); void importFile(e.dataTransfer.files?.[0]); }}
        onClick={() => fileRef.current?.click()} role="button" tabIndex={0}
        className={`rounded-lg border border-dashed px-3 py-5 text-center text-[11px] cursor-pointer transition-colors ${dragging ? "border-primary bg-primary/5 text-primary" : "border-border/70 text-muted-foreground hover:border-primary/50 hover:text-foreground"}`}>
        {importBusy ? <span className="inline-flex items-center gap-2"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Reading and typing it up…</span> : <>Drop a questionnaire here, or click to choose · PDF, Word, text, CSV</>}
        <input ref={fileRef} type="file" accept=".pdf,.docx,.txt,.md,.csv,.tsv,.json" className="hidden" onChange={(e) => void importFile(e.target.files?.[0])} />
      </div>
      <div className="text-[10px] text-muted-foreground/60 text-center">or paste it</div>
      <textarea value={pasteText} onChange={(e) => setPasteText(e.target.value)} rows={4} placeholder={"1. Would you switch? yes / no\n2. Why?\n3. Which matter most? (tick all that apply)\n- price\n- theft cover"}
        className="w-full bg-input/60 border border-border/60 rounded-lg px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-primary/50 resize-y font-mono" />
      <button type="button" onClick={() => void importText(pasteText)} disabled={!pasteText.trim() || importBusy} className="btn btn-sm btn-secondary w-full">
        {importBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FileUp className="w-3.5 h-3.5" />} Type it up{hasForm ? " and add to the form" : ""}
      </button>
    </div>
  );

  const writePanel = (
    <div className="rounded-xl border border-border/60 bg-card/30 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-xs font-medium flex items-center gap-1.5"><Sparkles className="w-3.5 h-3.5 text-primary" /> Write it for me</div>
        {hasForm && <button type="button" onClick={() => setPanel(null)} className="text-muted-foreground hover:text-foreground"><X className="w-3.5 h-3.5" /></button>}
      </div>
      <p className="text-[11px] text-muted-foreground leading-relaxed">
        {briefState === "ready" ? <>From what the session knows{topChallenge ? <> — the biggest open question is <span className="text-foreground/85">{topChallenge}</span></> : ""}.</> : briefState === "building" ? "Reading the session first…" : "From the question alone until the session is read."}
      </p>
      <input value={goal} onChange={(e) => setGoal(e.target.value)} placeholder={topChallenge ? `What for? e.g. ${topChallenge}` : "What do you want to find out? (optional)"}
        onKeyDown={(e) => { if (e.key === "Enter") void write(goal); }}
        className="w-full bg-input/60 border border-border/60 rounded-lg px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-primary/50" />
      <div className="flex items-center gap-1">
        {(["short", "standard", "deep"] as const).map((l) => (
          <button key={l} type="button" onClick={() => setLength(l)} className={`text-[11px] rounded-full border px-2.5 py-1 capitalize transition-colors ${length === l ? "border-primary/60 text-primary bg-primary/10" : "border-border/60 text-muted-foreground hover:text-foreground"}`}>{l}</button>
        ))}
        <span className="text-[10px] text-muted-foreground/60 ml-1">{length === "short" ? "4–6" : length === "standard" ? "7–10" : "11–16"} questions</span>
      </div>
      <button type="button" onClick={() => void write(goal)} disabled={!!writeBusy} className="btn btn-sm btn-primary w-full">
        {writeBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />} {writeBusy ? "Writing…" : hasForm ? "Rewrite with this in mind" : "Write the form"}
      </button>
    </div>
  );

  const templatesPanel = (
    <div className="rounded-xl border border-border/60 bg-card/30 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-xs font-medium flex items-center gap-1.5"><LayoutTemplate className="w-3.5 h-3.5 text-primary" /> Start from a template</div>
        {hasForm && <button type="button" onClick={() => setPanel(null)} className="text-muted-foreground hover:text-foreground"><X className="w-3.5 h-3.5" /></button>}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
        {templates.map((t) => (
          <button key={t.key} type="button" onClick={() => applyTemplate(t)} className="text-left rounded-lg border border-border/60 px-3 py-2 hover:border-primary/50 transition-colors">
            <div className="text-xs text-foreground">{t.label} <span className="text-muted-foreground/60">· {t.questions.length} q</span></div>
            <div className="text-[10px] text-muted-foreground leading-snug">{t.description}</div>
          </button>
        ))}
      </div>
    </div>
  );

  const entry = (
    <div className="space-y-5">
      <div>
        <h3 className="text-base font-medium">Build the form</h3>
        <p className="text-xs text-muted-foreground mt-1 max-w-xl">Three ways in — pick whichever is quickest. Everything you get can be edited here before it runs, and every persona fills the whole form in one go.</p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-3 items-start">
        {importPanel}
        {writePanel}
        <div className="rounded-xl border border-border/60 bg-card/30 p-4 space-y-3 md:col-span-2 2xl:col-span-1">
          <div className="text-xs font-medium flex items-center gap-1.5"><MessageSquare className="w-3.5 h-3.5 text-primary" /> Or just talk it through</div>
          <p className="text-[11px] text-muted-foreground leading-relaxed">Say what the decision is and the colleague on the left will suggest the questions, write them in, and change them as you go.</p>
          <div className="flex flex-wrap gap-1">
            {(challenges.length ? challenges.slice(0, 3).map((c) => `Draft: ${c.title}`) : ["What should we measure?", "Write it for me"]).map((c) => (
              <button key={c} type="button" onClick={() => tapChip(c)} className="text-[11px] rounded-full border border-border/70 px-2.5 py-1 text-foreground/80 hover:border-primary/60 hover:text-primary transition-colors">{c}</button>
            ))}
          </div>
          <button type="button" onClick={() => setChatOpen(true)} className="xl:hidden btn btn-sm btn-secondary w-full"><MessageSquare className="w-3.5 h-3.5" /> Open the chat</button>
        </div>
      </div>
      {templates.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
          <span>Or a template:</span>
          {templates.map((t) => (
            <button key={t.key} type="button" onClick={() => applyTemplate(t)} title={t.description} className="rounded-full border border-border/60 px-2 py-0.5 hover:border-primary/50 hover:text-foreground transition-colors">{t.label}</button>
          ))}
        </div>
      )}
    </div>
  );

  const formEditor = (
    <div className="space-y-4">
      {panel === "import" && importPanel}
      {panel === "write" && writePanel}
      {panel === "templates" && templatesPanel}

      <div className="space-y-2">
        <input value={draft.title} onChange={(e) => onChange("title", e.target.value)} placeholder="Give the form a title"
          className="w-full bg-transparent text-lg font-medium focus:outline-none placeholder:text-muted-foreground/40 border-b border-transparent focus:border-border/60 pb-1" />
        {introOpen || draft.intro ? (
          <div>
            <div className="flex items-center justify-between">
              <label className="text-[11px] text-muted-foreground">What they see first <span className="opacity-60">· the offer, the email, the proposal</span></label>
              {!draft.intro && <button type="button" onClick={() => setIntroOpen(false)} className="text-[10px] text-muted-foreground hover:text-foreground">hide</button>}
            </div>
            <textarea value={draft.intro} onChange={(e) => onChange("intro", e.target.value)} rows={Math.min(10, Math.max(3, draft.intro.split("\n").length + 1))}
              placeholder="Paste the material the twins should read before answering — or leave empty to ask about the session topic."
              className="mt-1 w-full bg-input/40 border border-border/60 rounded-lg px-3 py-2 text-xs focus:outline-none focus:ring-1 focus:ring-primary/50 resize-y" />
          </div>
        ) : (
          <button type="button" onClick={() => setIntroOpen(true)} className="text-[11px] text-muted-foreground hover:text-foreground inline-flex items-center gap-1"><Plus className="w-3 h-3" /> show them something first (an offer, an email, a proposal)</button>
        )}
      </div>

      <div className="flex items-center justify-between text-[11px] text-muted-foreground">
        <span>{questions.length} question{questions.length === 1 ? "" : "s"}{questions.some((q) => q.primary) ? "" : " · pick a primary (★)"}{problemCount ? <span className="text-amber-300/85"> · {problemCount} need{problemCount === 1 ? "s" : ""} attention</span> : null}</span>
        <button type="button" onClick={() => setPreview((p) => !p)} className="inline-flex items-center gap-1 hover:text-foreground"><Eye className="w-3 h-3" /> {preview ? "back to editing" : "preview as they see it"}</button>
      </div>

      {preview ? <FormPreview title={draft.title} intro={draft.intro} questions={questions} /> : (
        <div className="space-y-2">
          {questions.map((q, i) => (
            <QuestionEditor key={q.key} q={q} index={i} total={questions.length} flash={flash.has(q.key)}
              onChange={(patch) => update(i, patch)} onRemove={() => remove(i)} onMove={(d) => move(i, d)} onPrimary={() => setPrimary(i)} />
          ))}
        </div>
      )}

      {!preview && (
        <div className="flex flex-wrap items-center gap-1 pt-1">
          <span className="text-[11px] text-muted-foreground mr-1">Add</span>
          {TYPES.map((t) => (
            <button key={t.key} type="button" onClick={() => add(t.key)} title={t.hint}
              className="inline-flex items-center gap-1 text-[11px] rounded-full border border-border/60 px-2.5 py-1 text-muted-foreground hover:text-foreground hover:border-primary/50 transition-colors">
              <Plus className="w-3 h-3" /> {t.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );

  return (
    <div className="h-full flex flex-col min-h-0 relative">
      {/* Header */}
      <div className="h-12 shrink-0 border-b border-border/60 px-4 flex items-center gap-3">
        <button type="button" onClick={onBack} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground -ml-1"><ChevronLeft className="w-3.5 h-3.5" /> All tools</button>
        <span className="text-border/80">|</span>
        <div className="text-sm font-medium">{instrument.label}</div>
        {briefChip}
        <div className="ml-auto flex items-center gap-1">
          {hasForm && (
            <>
              <button type="button" onClick={() => setPanel(panel === "import" ? null : "import")} className={`btn btn-sm ${panel === "import" ? "btn-secondary" : "btn-ghost"}`}><FileUp className="w-3.5 h-3.5" /> Import</button>
              <button type="button" onClick={() => setPanel(panel === "write" ? null : "write")} className={`btn btn-sm ${panel === "write" ? "btn-secondary" : "btn-ghost"}`}><Sparkles className="w-3.5 h-3.5" /> Write it for me</button>
              {templates.length > 0 && <button type="button" onClick={() => setPanel(panel === "templates" ? null : "templates")} className={`btn btn-sm ${panel === "templates" ? "btn-secondary" : "btn-ghost"}`}><LayoutTemplate className="w-3.5 h-3.5" /> Templates</button>}
            </>
          )}
          <button type="button" onClick={() => setChatOpen(true)} className="xl:hidden btn btn-sm btn-ghost"><MessageSquare className="w-3.5 h-3.5" /> Chat</button>
        </div>
      </div>

      {/* Body: chat · form · run rail. The chat is a column from xl up and a drawer below. */}
      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_300px] xl:grid-cols-[400px_minmax(0,1fr)_300px]">
        <div className="hidden xl:block border-r border-border/60 min-h-0">{chatPane}</div>

        <div className="min-h-0 overflow-y-auto">
          <div className="p-5 max-w-[920px] mx-auto space-y-4">
            {toast && (
              <div className="flex items-center gap-3 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-[11px]">
                <span className="text-foreground/90 flex-1 truncate">{toast.text}</span>
                {toast.undo && <button type="button" onClick={undo} className="inline-flex items-center gap-1 text-primary hover:underline"><Undo2 className="w-3 h-3" /> Undo</button>}
                <button type="button" onClick={() => setToast(null)} className="text-muted-foreground hover:text-foreground"><X className="w-3.5 h-3.5" /></button>
              </div>
            )}
            {actionError && (
              <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-300 flex items-center gap-2">
                <span className="flex-1">{actionError}</span>
                <button type="button" onClick={() => setActionError(null)} className="hover:text-foreground"><X className="w-3.5 h-3.5" /></button>
              </div>
            )}
            {hasForm ? formEditor : entry}
          </div>
        </div>

        <aside className="border-t lg:border-t-0 lg:border-l border-border/60 min-h-0 overflow-y-auto p-4 space-y-5">
          <div id="forms-run" tabIndex={-1} className="space-y-4 outline-none">{controls}</div>
          {challenges.length > 0 && (
            <div>
              <div className="text-[11px] text-muted-foreground mb-1.5 flex items-center gap-1.5"><Sparkles className="w-3 h-3" /> Worth measuring <span className="opacity-60">· from the session</span></div>
              <div className="space-y-1">
                {challenges.slice(0, 6).map((c, i) => (
                  <div key={i} className="group rounded-lg border border-border/50 bg-card/30 px-2.5 py-2">
                    <div className="flex items-start gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="text-[11px] text-foreground/90 leading-snug">{c.title}</div>
                        <div className="text-[10px] text-muted-foreground leading-snug mt-0.5">{c.measure}</div>
                      </div>
                      <button type="button" onClick={() => void write(c.title + (c.measure ? ` — ${c.measure}` : ""))} disabled={!!writeBusy}
                        title={hasForm ? "Rewrite the form to go after this" : "Write a form that goes after this"}
                        className="shrink-0 inline-flex items-center gap-1 text-[10px] text-primary opacity-70 group-hover:opacity-100 disabled:opacity-40">
                        {writeBusy && writeBusy.startsWith(c.title) ? <Loader2 className="w-3 h-3 animate-spin" /> : <ChevronRight className="w-3 h-3" />} draft
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {aside}
        </aside>
      </div>

      {/* The chat as a drawer below xl. */}
      {chatOpen && (
        <div className="xl:hidden fixed inset-0 z-40">
          <div className="absolute inset-0 bg-black/40" onClick={() => setChatOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-[420px] max-w-[92vw] bg-background border-r border-border shadow-2xl">{chatPane}</div>
        </div>
      )}
      {!chatOpen && (
        <button type="button" onClick={() => setChatOpen(true)} className="xl:hidden absolute left-4 bottom-4 z-30 btn btn-sm btn-primary shadow-lg">
          <MessageSquare className="w-3.5 h-3.5" /> Chat
        </button>
      )}
      <span className="hidden"><ChevronDown className="w-3 h-3" /></span>
    </div>
  );
}
