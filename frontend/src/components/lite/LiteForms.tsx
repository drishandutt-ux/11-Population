"use client";

/** Forms in the simple view: ask these people a few questions, with as little friction as
 *  the pro studio allows and plainer words. The colleague in the chat has read the whole
 *  session (the Lab brief); the reader can have the questions written, paste or drop a
 *  questionnaire they already have, or just say what they want to know. The form builds up
 *  beside the chat, one big button asks the people, and the answers come back as the same
 *  results page the pro Lab draws — one "See in detail" away from the full thing. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, Agent, FormDraft, FormQuestion, Instrument, LabBriefState, Probe, ProbeAnswerRow, SurveyQuestion, SurveyQuestionType, SurveyTemplate } from "@/lib/api";
import { LITE_DEFAULTS, proLinks } from "@/lib/lite";
import { cn } from "@/lib/utils";
import { ArrowRight, ArrowUp, BookOpen, Check, ChevronLeft, FileUp, Loader2, MessageCircle, Plus, RefreshCw, Sparkles, Star, Undo2, X } from "lucide-react";
import Detail from "./Detail";
import ErrorBoundary from "@/components/ErrorBoundary";
import SurveyPage from "@/components/lab/pages/SurveyPage";
import { Draft, Md, ago, appendQuestions, changedKeys } from "@/components/lab/forms/formUtils";
import { blank, nextKey, problemsOf } from "@/components/lab/forms/QuestionEditor";

type ChatItem = { role: "user" | "assistant"; content: string; chips?: string[]; note?: string };
type Stage = "compose" | "running" | "results";
type Toast = { text: string; undo: Draft | null } | null;

const EMPTY: Draft = { title: "", intro: "", questions: [] };
const MAX_HISTORY = 24;
const draftKey = (sid: string) => `lite:forms:draft:${sid}`;
const chatKey = (sid: string) => `lite:forms:chat:${sid}`;

/** The question types in plain words. */
const KINDS: { key: SurveyQuestionType; label: string }[] = [
  { key: "single", label: "pick one" },
  { key: "multi", label: "pick any" },
  { key: "yesno", label: "yes or no" },
  { key: "scale", label: "a score" },
  { key: "number", label: "a number" },
  { key: "text", label: "their own words" },
  { key: "grid", label: "rate a few things" },
];

type Props = { sessionId: string; agents: Agent[]; onBack: () => void };

export default function LiteForms({ sessionId, agents, onBack }: Props) {
  const [draft, setDraftState] = useState<Draft>(EMPTY);
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const hasForm = draft.questions.length > 0;
  const setDraft = (d: Draft) => setDraftState(d);

  const [brief, setBrief] = useState<LabBriefState | null>(null);
  const [briefBusy, setBriefBusy] = useState(false);
  const [briefOpen, setBriefOpen] = useState(false);
  const [messages, setMessages] = useState<ChatItem[]>([]);
  const [chatBusy, setChatBusy] = useState(false);
  const [input, setInput] = useState("");
  const [chatOpen, setChatOpen] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const openingAsked = useRef(false);

  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteText, setPasteText] = useState("");
  const [importBusy, setImportBusy] = useState(false);
  const [goal, setGoal] = useState("");
  const [writeBusy, setWriteBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [toast, setToast] = useState<Toast>(null);
  const [flash, setFlash] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const [stage, setStage] = useState<Stage>("compose");
  const [probe, setProbe] = useState<(Probe & { answers?: ProbeAnswerRow[] }) | null>(null);
  const [instrument, setInstrument] = useState<Instrument | null>(null);
  const [past, setPast] = useState<Probe[]>([]);
  const [running, setRunning] = useState(false);
  const agentsById = useMemo(() => Object.fromEntries(agents.map((a) => [a.id, a])), [agents]);
  const templates: SurveyTemplate[] = instrument?.templates || [];

  // ── what survives a tab switch ───────────────────────────────────────────
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(draftKey(sessionId));
      if (raw) { const d = JSON.parse(raw) as Draft; if (d && Array.isArray(d.questions)) setDraftState(d); }
      const rawChat = sessionStorage.getItem(chatKey(sessionId));
      if (rawChat) { const m = JSON.parse(rawChat); if (Array.isArray(m) && m.length) { setMessages(m); openingAsked.current = true; } }
    } catch { /* private mode */ }
  }, [sessionId]);
  useEffect(() => {
    const t = setTimeout(() => { try { sessionStorage.setItem(draftKey(sessionId), JSON.stringify(draft)); } catch { /* private mode */ } }, 300);
    return () => clearTimeout(t);
  }, [draft, sessionId]);
  useEffect(() => {
    if (!messages.length) return;
    try { sessionStorage.setItem(chatKey(sessionId), JSON.stringify(messages.slice(-60))); } catch { /* private mode */ }
  }, [messages, sessionId]);

  // ── the instrument, past forms, the brief, the opening line ────────────────
  useEffect(() => {
    api.lab.instruments().then((r) => setInstrument(r.instruments.find((i) => i.key === "survey") || null)).catch(() => null);
    api.lab.probes(sessionId).then((r) => setPast(r.probes.filter((p) => p.instrument === "survey" && !p.experiment_id))).catch(() => null);
  }, [sessionId]);

  const loadBrief = useCallback(async (force = false) => {
    setBriefBusy(true);
    try {
      let b = force ? null : await api.lab.brief(sessionId);
      if (!b || !b.brief || b.stale || force) b = await api.lab.buildBrief(sessionId, force);
      setBrief(b);
    } catch { /* the chat still works */ } finally { setBriefBusy(false); }
  }, [sessionId]);

  const askOpening = useCallback(async () => {
    if (openingAsked.current) return;
    openingAsked.current = true;
    try {
      const r = await api.lab.formsChat(sessionId, { messages: [], form: draftRef.current.questions.length ? draftRef.current : null });
      setMessages((m) => (m.length ? m : [{ role: "assistant", content: r.reply, chips: r.chips }]));
    } catch { /* the reader types first */ }
  }, [sessionId]);

  useEffect(() => { (async () => { await loadBrief(); await askOpening(); })(); }, [loadBrief, askOpening]);
  useEffect(() => { const el = listRef.current; if (el) el.scrollTop = el.scrollHeight; }, [messages, chatBusy, chatOpen]);

  // ── applying what comes back ─────────────────────────────────────────────
  const applyForm = useCallback((next: FormDraft, how: "replace" | "append", note: string) => {
    const prev = draftRef.current;
    const merged: Draft = how === "append" && prev.questions.length
      ? { title: prev.title || next.title, intro: prev.intro || next.intro, questions: appendQuestions(prev, next.questions) }
      : { title: next.title || prev.title, intro: next.intro || prev.intro, questions: next.questions };
    setDraft(merged);
    setFlash(changedKeys(prev, merged));
    setTimeout(() => setFlash(new Set()), 2600);
    setToast({ text: note, undo: prev.questions.length ? prev : null });
    setPasteOpen(false);
    setStage("compose");
  }, []);

  const write = async (g: string) => {
    setWriteBusy(true); setError(null);
    try {
      const r = await api.lab.formsGenerate(sessionId, { goal: g, length: "short", existing: hasForm ? draftRef.current : null });
      if (!r.questions.length) { setError("Nothing came back. Try again, or say what you want in the chat."); return; }
      applyForm(r, "replace", `${r.questions.length} questions written${g ? ` about ${g}` : ""}`);
      setMessages((m) => [...m, { role: "assistant", content: `I've written ${r.questions.length} questions${g ? ` about **${g}**` : ""}. ${r.rationale || ""} Change anything, or ask the people when you're ready.`.trim(), chips: ["Make it shorter", "Add a why question", "Ask the people"] }]);
    } catch (e: any) { setError(e?.message || "Could not write the questions"); } finally { setWriteBusy(false); }
  };

  const importText = async (text: string) => {
    if (!text.trim()) return;
    setImportBusy(true); setError(null);
    try {
      const r = await api.lab.formsImportText(sessionId, text);
      if (!r.questions.length) { setError("I couldn't find questions in that. Paste just the questions, one per line."); return; }
      applyForm(r, hasForm ? "append" : "replace", `${r.questions.length} questions typed up`);
      setPasteText("");
    } catch (e: any) { setError(e?.message || "Could not read that"); } finally { setImportBusy(false); }
  };

  const importFile = async (file: File | undefined | null) => {
    if (!file) return;
    setImportBusy(true); setError(null);
    try {
      const r = await api.lab.formsImportFile(sessionId, file);
      if (!r.questions.length) { setError(`I couldn't find questions in ${file.name}.`); return; }
      applyForm(r, hasForm ? "append" : "replace", `${r.questions.length} questions read from ${file.name}`);
    } catch (e: any) { setError(e?.message || "Could not read the file"); } finally { setImportBusy(false); if (fileRef.current) fileRef.current.value = ""; }
  };

  const applyTemplate = (t: SurveyTemplate) => applyForm({ title: t.title, intro: "", questions: t.questions.map((q) => ({ ...q })), notes: [], problems: [] }, "replace", `Started from "${t.label}"`);

  const send = async (text: string) => {
    const t = text.trim();
    if (!t || chatBusy) return;
    setInput("");
    const history: ChatItem[] = [...messages, { role: "user", content: t }];
    setMessages(history);
    setChatBusy(true);
    try {
      const r = await api.lab.formsChat(sessionId, { messages: history.slice(-MAX_HISTORY).map(({ role, content }) => ({ role, content })), form: hasForm || draft.title ? draftRef.current : null });
      setMessages((m) => [...m, { role: "assistant", content: r.reply, chips: r.chips, note: r.form_changed ? (r.change_note || "changed the questions") : undefined }]);
      if (r.form_changed && r.form) applyForm(r.form, "replace", r.change_note || "Questions updated");
    } catch (e: any) {
      setMessages((m) => [...m, { role: "assistant", content: `Sorry — that didn't go through. ${e?.message || ""}`.trim() }]);
    } finally { setChatBusy(false); }
  };

  const tapChip = (c: string) => {
    const low = c.toLowerCase();
    if (low === "write it for me") { void write(goal); return; }
    if (low === "i have a questionnaire") { setPasteOpen(true); setChatOpen(false); return; }
    if (low.startsWith("draft: ")) { void write(c.slice(7)); return; }
    if (low === "run it" || low === "ask the people") { void run(); return; }
    void send(c);
  };

  // ── the form by hand ─────────────────────────────────────────────────────
  const qs = draft.questions;
  const setQs = (questions: FormQuestion[]) => setDraft({ ...draftRef.current, questions });
  const update = (i: number, patch: Partial<SurveyQuestion>) => setQs(qs.map((q, j) => (j === i ? { ...q, ...patch } : q)));
  const problems = qs.map((q) => problemsOf(q));
  const problemCount = problems.filter((p) => p.length).length;

  // ── asking the people ────────────────────────────────────────────────────
  const run = async () => {
    if (!hasForm || running) return;
    if (problemCount) { setError(`Question ${problems.findIndex((p) => p.length) + 1} ${problems.find((p) => p.length)![0]}.`); return; }
    setRunning(true); setError(null);
    try {
      const questions = qs.some((q) => q.primary) ? qs : qs.map((q, i) => ({ ...q, primary: i === qs.findIndex((x) => x.type !== "text") || (i === 0 && qs.every((x) => x.type === "text")) }));
      const p = await api.lab.run(sessionId, { instrument: "survey", mode: LITE_DEFAULTS.mode, spec: { title: draft.title || "A few questions", intro: draft.intro, questions } });
      setProbe(p);
      setStage("running");
    } catch (e: any) { setError(e?.message || "Could not ask them"); } finally { setRunning(false); }
  };

  // Poll the run until it lands (the simple view does not wait on the socket).
  useEffect(() => {
    if (stage !== "running" || !probe) return;
    let alive = true;
    const tick = async () => {
      try {
        const full = await api.lab.probe(sessionId, probe.id);
        if (!alive) return;
        setProbe(full);
        if (full.status !== "queued" && full.status !== "running") {
          setStage("results");
          api.lab.probes(sessionId).then((r) => setPast(r.probes.filter((x) => x.instrument === "survey" && !x.experiment_id))).catch(() => null);
        }
      } catch { /* try again */ }
    };
    const id = setInterval(tick, 2500);
    void tick();
    return () => { alive = false; clearInterval(id); };
  }, [stage, probe?.id, sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  const openPast = async (p: Probe) => {
    setProbe(p);
    setStage(p.status === "queued" || p.status === "running" ? "running" : "results");
    const full = await api.lab.probe(sessionId, p.id).catch(() => null);
    if (full) setProbe(full);
  };

  const challenges = brief?.brief?.challenges || [];
  const topChallenge = challenges[0]?.title || "";
  const n = agents.length;

  // ── no people yet ──────────────────────────────────────────────────────────
  if (n === 0) {
    return (
      <div className="max-w-xl mx-auto pt-16 px-6 animate-rise text-center">
        <div className="lite-card p-8">
          <h1 className="text-[24px] font-semibold tracking-tight">Make the people first</h1>
          <p className="lite-lead mt-2">Forms ask the people in this question. Once they exist, come back here.</p>
          <button type="button" onClick={onBack} className="lite-btn mt-6">Back</button>
        </div>
      </div>
    );
  }

  // ── running ────────────────────────────────────────────────────────────────
  if (stage === "running" && probe) {
    const answered = probe.answer_count || 0;
    const total = probe.agent_count || n;
    return (
      <div className="max-w-xl mx-auto pt-16 px-6 animate-rise">
        <div className="lite-card p-8 text-center">
          <div className="lite-dots inline-flex gap-1.5"><span /><span /><span /></div>
          <h1 className="text-[24px] font-semibold tracking-tight mt-4">Asking {total} people</h1>
          <p className="lite-lead mt-2">Each one fills in the whole form as themselves. This usually takes under a minute.</p>
          <div className="mt-6 h-2 rounded-full bg-foreground/[0.06] overflow-hidden"><div className="h-full bg-primary transition-all duration-500" style={{ width: `${Math.max(3, Math.round((answered / Math.max(1, total)) * 100))}%` }} /></div>
          <p className="text-[13px] text-muted-foreground mt-2 tabular-nums">{answered} of {total} answered</p>
          <button type="button" onClick={() => api.lab.stop(sessionId, probe.id).catch(() => null)} className="lite-btn-soft lite-btn-sm mt-6">Stop here</button>
        </div>
      </div>
    );
  }

  // ── results ────────────────────────────────────────────────────────────────
  if (stage === "results" && probe) {
    const ok = probe.status === "complete" && probe.aggregates && probe.aggregates.n > 0;
    return (
      <div className="flex-1 min-h-0 flex flex-col max-w-6xl w-full mx-auto px-3 sm:px-6 pb-6">
        <div className="flex items-center gap-3 py-3 shrink-0 flex-wrap">
          <button type="button" onClick={() => setStage("compose")} className="lite-pill"><ChevronLeft className="w-3.5 h-3.5" /> Change the questions</button>
          <div className="min-w-0">
            <h1 className="text-[20px] font-semibold tracking-tight truncate">{(probe.spec as any)?.title || "What they said"}</h1>
            <p className="text-[12.5px] text-muted-foreground">{probe.answer_count} of {probe.agent_count} answered{probe.created_at ? ` · ${ago(probe.created_at)}` : ""}{probe.status !== "complete" ? ` · ${probe.status}` : ""}</p>
          </div>
          <button type="button" onClick={() => { setDraft(EMPTY); setStage("compose"); }} className="lite-btn-soft lite-btn-sm ml-auto"><Plus className="w-3.5 h-3.5" /> Ask something else</button>
        </div>
        <Detail href={proLinks.lab(sessionId)} className="flex-1 min-h-0">
          <div className="lite-card p-4 sm:p-6 h-full overflow-y-auto">
            {ok && instrument ? (
              <ErrorBoundary label="The answers"><SurveyPage instrument={instrument} probe={probe} agentsById={agentsById} /></ErrorBoundary>
            ) : (
              <p className="lite-lead">{probe.error || (probe.status === "stopped" ? "Stopped before anyone answered." : "Nobody could answer this one.")}</p>
            )}
          </div>
        </Detail>
      </div>
    );
  }

  // ── compose ────────────────────────────────────────────────────────────────
  const chat = (
    <div className="h-full flex flex-col min-h-0">
      <div className="px-5 pt-4 pb-2 flex items-center gap-2 shrink-0">
        <div className="min-w-0 flex-1">
          <div className="text-[14px] font-semibold flex items-center gap-2"><MessageCircle className="w-4 h-4 text-primary" /> Think it through with me</div>
          <button type="button" onClick={() => setBriefOpen((v) => !v)} className="text-[12px] text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 mt-0.5">
            {briefBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : <BookOpen className="w-3 h-3" />}
            {briefBusy ? "Reading everything in this question…" : brief?.brief ? `I've read this whole question${brief.stale ? " (a little while ago)" : ""} · what I know` : "Nothing read yet"}
          </button>
        </div>
        <button type="button" onClick={() => setChatOpen(false)} className="lg:hidden w-9 h-9 rounded-full inline-flex items-center justify-center text-muted-foreground hover:bg-foreground/5"><X className="w-4 h-4" /></button>
      </div>
      <div ref={listRef} className="flex-1 min-h-0 overflow-y-auto px-5 pb-3 space-y-4">
        {briefOpen && brief?.brief && (
          <div className="rounded-2xl bg-foreground/[0.04] p-4 text-[13px] leading-relaxed space-y-2">
            <p>{brief.brief.summary}</p>
            {challenges.length > 0 && <div><div className="font-medium">Worth asking about</div><ul className="list-disc pl-4 text-muted-foreground">{challenges.map((c, i) => <li key={i}><span className="text-foreground">{c.title}</span> — {c.measure}</li>)}</ul></div>}
            {brief.brief.gaps?.length > 0 && <p className="text-muted-foreground">Nobody has asked yet: {brief.brief.gaps.slice(0, 3).join("; ")}</p>}
            <button type="button" onClick={() => void loadBrief(true)} disabled={briefBusy} className="inline-flex items-center gap-1 text-[12px] text-muted-foreground hover:text-foreground"><RefreshCw className={cn("w-3 h-3", briefBusy && "animate-spin")} /> read it again</button>
          </div>
        )}
        {messages.length === 0 && <p className="text-[13px] text-muted-foreground inline-flex items-center gap-2 pt-2"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Reading everything in this question…</p>}
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "flex justify-end" : ""}>
            <div className={cn("max-w-[92%] text-[14px] leading-relaxed", m.role === "user" ? "rounded-2xl rounded-br-md bg-foreground text-background px-4 py-2.5" : "text-foreground")}>
              {m.role === "user" ? <span className="whitespace-pre-wrap">{m.content}</span> : <Md text={m.content} />}
              {m.note && <p className="mt-1.5 text-[12px] text-primary inline-flex items-center gap-1"><Check className="w-3.5 h-3.5" /> {m.note}</p>}
            </div>
            {m.role === "assistant" && i === messages.length - 1 && m.chips && m.chips.length > 0 && !chatBusy && (
              <div className="flex flex-wrap gap-1.5 mt-2.5">
                {m.chips.map((c) => <button key={c} type="button" onClick={() => tapChip(c)} className="lite-pill hover:text-primary hover:border-primary/40 transition-colors">{c}</button>)}
              </div>
            )}
          </div>
        ))}
        {chatBusy && <p className="text-[13px] text-muted-foreground inline-flex items-center gap-2"><span className="lite-dots flex gap-1"><span /><span /><span /></span> thinking</p>}
      </div>
      <div className="p-4 shrink-0">
        <div className="lite-field flex items-end gap-2 py-2 pr-2">
          <textarea value={input} onChange={(e) => setInput(e.target.value)} rows={Math.min(4, Math.max(1, input.split("\n").length))}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(input); } }}
            placeholder={hasForm ? "Change something, or ask what's missing…" : "What do you want to find out?"} className="lite-input flex-1 text-[15px] leading-relaxed" />
          <button type="button" onClick={() => void send(input)} disabled={!input.trim() || chatBusy} className="w-9 h-9 rounded-full bg-foreground text-background disabled:opacity-30 inline-flex items-center justify-center shrink-0"><ArrowUp className="w-4 h-4" /></button>
        </div>
      </div>
    </div>
  );

  const dropZone = (
    <div onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); void importFile(e.dataTransfer.files?.[0]); }}
      onClick={() => fileRef.current?.click()} role="button" tabIndex={0}
      className={cn("rounded-2xl border border-dashed px-4 py-6 text-center text-[13.5px] cursor-pointer transition-colors", dragging ? "border-primary bg-primary/5 text-primary" : "border-border text-muted-foreground hover:border-primary/50 hover:text-foreground")}>
      {importBusy ? <span className="inline-flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Reading it…</span> : <>Drop the file here, or click to choose<br /><span className="text-[12px] opacity-70">PDF, Word, text, CSV</span></>}
      <input ref={fileRef} type="file" accept=".pdf,.docx,.txt,.md,.csv,.tsv,.json" className="hidden" onChange={(e) => void importFile(e.target.files?.[0])} />
    </div>
  );

  const pastePanel = (
    <div className="space-y-2">
      <textarea value={pasteText} onChange={(e) => setPasteText(e.target.value)} rows={5} placeholder={"1. Would you switch? yes / no\n2. Why?\n3. Which matter most?\n- price\n- theft cover"} className="lite-field text-[14px] font-mono" />
      <div className="flex gap-2">
        <button type="button" onClick={() => void importText(pasteText)} disabled={!pasteText.trim() || importBusy} className="lite-btn lite-btn-sm">{importBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileUp className="w-4 h-4" />} Type it up</button>
        <button type="button" onClick={() => setPasteOpen(false)} className="lite-btn-soft lite-btn-sm">Cancel</button>
      </div>
    </div>
  );

  const entry = (
    <div className="animate-rise space-y-6">
      <div>
        <h1 className="text-[28px] sm:text-[32px] font-semibold tracking-tight">Ask these {n} people some questions</h1>
        <p className="lite-lead mt-2 max-w-xl">Have the questions written for you, bring your own, or talk it through. Every person fills in the whole form, and you get the answers counted up.</p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
        <div className="lite-card p-5 space-y-3">
          <div className="text-[15px] font-semibold flex items-center gap-2"><Sparkles className="w-4 h-4 text-primary" /> Write the questions for me</div>
          <p className="lite-help">{briefBusy ? "Reading everything in this question first…" : topChallenge ? <>The biggest open question I see is <span className="text-foreground font-medium">{topChallenge}</span>.</> : "From the question and everything added to it."}</p>
          <input value={goal} onChange={(e) => setGoal(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void write(goal); }} placeholder={topChallenge ? `What about? e.g. ${topChallenge}` : "What do you want to find out? (optional)"} className="lite-field text-[14px] py-2.5" />
          {challenges.length > 1 && (
            <div className="flex flex-wrap gap-1.5">{challenges.slice(0, 4).map((c) => <button key={c.title} type="button" onClick={() => void write(c.title)} disabled={writeBusy} className="lite-pill hover:text-primary hover:border-primary/40 transition-colors">{c.title}</button>)}</div>
          )}
          <button type="button" onClick={() => void write(goal)} disabled={writeBusy} className="lite-btn w-full">{writeBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />} {writeBusy ? "Writing…" : "Write them for me"}</button>
        </div>
        <div className="lite-card p-5 space-y-3">
          <div className="text-[15px] font-semibold flex items-center gap-2"><FileUp className="w-4 h-4 text-primary" /> I already have questions</div>
          <p className="lite-help">A questionnaire you have written, in any file — I will type it up here.</p>
          {pasteOpen ? pastePanel : (<>{dropZone}<button type="button" onClick={() => setPasteOpen(true)} className="text-[13px] text-muted-foreground hover:text-foreground">or paste them in</button></>)}
        </div>
      </div>
      {templates.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-[13px] text-muted-foreground">
          <span>Or start from a ready-made one:</span>
          {templates.map((t) => <button key={t.key} type="button" onClick={() => applyTemplate(t)} title={t.description} className="lite-pill hover:text-primary hover:border-primary/40 transition-colors">{t.label}</button>)}
        </div>
      )}
      {past.length > 0 && (
        <div className="space-y-2">
          <div className="text-[13px] font-medium">Earlier forms</div>
          <div className="flex flex-wrap gap-2">
            {past.slice(0, 6).map((p) => (
              <button key={p.id} type="button" onClick={() => void openPast(p)} className="lite-card px-4 py-2.5 text-left hover:border-primary/40 transition-colors max-w-xs">
                <div className="text-[13.5px] font-medium truncate">{(p.spec as any)?.title || "A few questions"}</div>
                <div className="text-[12px] text-muted-foreground">{p.answer_count} answered · {ago(p.created_at || null)}</div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );

  const form = (
    <div className="animate-rise space-y-5 pb-28">
      <div className="flex items-start gap-3 flex-wrap">
        <input value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} placeholder="Give it a name" className="lite-input text-[26px] sm:text-[30px] font-semibold tracking-tight flex-1 min-w-[12rem]" />
        <div className="flex items-center gap-1.5">
          <button type="button" onClick={() => setPasteOpen((v) => !v)} className="lite-pill hover:text-primary"><FileUp className="w-3.5 h-3.5" /> Add from a file</button>
          <button type="button" onClick={() => void write(goal || topChallenge)} disabled={writeBusy} className="lite-pill hover:text-primary">{writeBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />} Rewrite for me</button>
        </div>
      </div>
      {pasteOpen && <div className="lite-card p-4 space-y-3">{dropZone}{pastePanel}</div>}
      <div className="space-y-3">
        {qs.map((q, i) => (
          <div key={q.key} className={cn("lite-card p-4 sm:p-5 transition-shadow", flash.has(q.key) && "ring-2 ring-primary/40")}>
            <div className="flex items-start gap-3">
              <span className="text-[13px] text-muted-foreground tabular-nums pt-2 w-5 shrink-0">{i + 1}.</span>
              <div className="min-w-0 flex-1 space-y-2.5">
                <input value={q.text} onChange={(e) => update(i, { text: e.target.value })} placeholder="The question, as they would read it" className="lite-input text-[16px] font-medium" />
                <div className="flex items-center gap-2 flex-wrap text-[12.5px] text-muted-foreground">
                  <span>They answer with</span>
                  <select value={q.type} onChange={(e) => { const type = e.target.value as SurveyQuestionType; const f = blank(type, q.key); update(i, { type, options: f.options, rows: f.rows, columns: f.columns, min: f.min, max: f.max, min_label: f.min_label, max_label: f.max_label }); }}
                    className="rounded-full bg-foreground/5 px-2.5 h-7 text-foreground text-[12.5px] font-medium focus:outline-none">
                    {KINDS.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
                  </select>
                  <button type="button" onClick={() => setQs(qs.map((x, j) => ({ ...x, primary: j === i })))} title="Lead the summary with this one" className={cn("inline-flex items-center gap-1 rounded-full px-2 h-7", q.primary ? "text-primary bg-primary/10" : "hover:text-foreground")}>
                    <Star className="w-3.5 h-3.5" fill={q.primary ? "currentColor" : "none"} /> {q.primary ? "the main one" : "make it the main one"}
                  </button>
                </div>
                {(q.type === "single" || q.type === "multi") && (
                  <div className="space-y-1.5">
                    {(q.options || []).map((o, k) => (
                      <div key={k} className="flex items-center gap-2">
                        <span className="text-muted-foreground/60 text-[13px] w-3">{q.type === "single" ? "○" : "☐"}</span>
                        <input value={o} onChange={(e) => update(i, { options: (q.options || []).map((x, j) => (j === k ? e.target.value : x)) })} placeholder="an answer they could pick" className="lite-field text-[14px] py-1.5 rounded-xl"
                          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); const opts = q.options || []; update(i, { options: [...opts.slice(0, k + 1), "", ...opts.slice(k + 1)] }); } }} />
                        <button type="button" onClick={() => update(i, { options: (q.options || []).filter((_, j) => j !== k) })} className="text-muted-foreground/50 hover:text-red-600"><X className="w-3.5 h-3.5" /></button>
                      </div>
                    ))}
                    <button type="button" onClick={() => update(i, { options: [...(q.options || []), ""] })} className="text-[12.5px] text-muted-foreground hover:text-foreground inline-flex items-center gap-1"><Plus className="w-3.5 h-3.5" /> another answer</button>
                  </div>
                )}
                {q.type === "scale" && (
                  <div className="grid grid-cols-[3.5rem_1fr_3.5rem_1fr] items-center gap-2 text-[13px]">
                    <input type="number" value={q.min ?? 1} onChange={(e) => update(i, { min: Number(e.target.value) })} className="lite-field py-1.5 rounded-xl text-center tabular-nums" />
                    <input value={q.min_label ?? ""} onChange={(e) => update(i, { min_label: e.target.value })} placeholder="what the low end means" className="lite-field py-1.5 rounded-xl text-[13px]" />
                    <input type="number" value={q.max ?? 5} onChange={(e) => update(i, { max: Number(e.target.value) })} className="lite-field py-1.5 rounded-xl text-center tabular-nums" />
                    <input value={q.max_label ?? ""} onChange={(e) => update(i, { max_label: e.target.value })} placeholder="what the high end means" className="lite-field py-1.5 rounded-xl text-[13px]" />
                  </div>
                )}
                {q.type === "grid" && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-[13px]">
                    {(["rows", "columns"] as const).map((field) => (
                      <div key={field} className="space-y-1.5">
                        <div className="text-[12px] text-muted-foreground">{field === "rows" ? "The things to rate" : "The answers, best first"}</div>
                        {(q[field] || []).map((o, k) => (
                          <div key={k} className="flex items-center gap-2">
                            <input value={o} onChange={(e) => update(i, { [field]: (q[field] || []).map((x, j) => (j === k ? e.target.value : x)) } as any)} className="lite-field py-1.5 rounded-xl text-[13px]" />
                            <button type="button" onClick={() => update(i, { [field]: (q[field] || []).filter((_, j) => j !== k) } as any)} className="text-muted-foreground/50 hover:text-red-600"><X className="w-3.5 h-3.5" /></button>
                          </div>
                        ))}
                        <button type="button" onClick={() => update(i, { [field]: [...(q[field] || []), ""] } as any)} className="text-[12.5px] text-muted-foreground hover:text-foreground inline-flex items-center gap-1"><Plus className="w-3.5 h-3.5" /> add</button>
                      </div>
                    ))}
                  </div>
                )}
                {problems[i].length > 0 && <p className="text-[12.5px] text-amber-700">This question {problems[i].join("; ")}.</p>}
              </div>
              <button type="button" onClick={() => setQs(qs.filter((_, j) => j !== i))} title="Remove" className="w-8 h-8 rounded-full inline-flex items-center justify-center text-muted-foreground/60 hover:text-red-600 hover:bg-red-500/10 shrink-0"><X className="w-4 h-4" /></button>
            </div>
          </div>
        ))}
      </div>
      <button type="button" onClick={() => setQs([...qs, blank("single", nextKey(qs))])} className="lite-btn-soft lite-btn-sm"><Plus className="w-4 h-4" /> Add a question</button>
    </div>
  );

  return (
    <div className="flex-1 min-h-0 relative">
      <div className="h-full grid grid-cols-1 lg:grid-cols-[minmax(340px,420px)_minmax(0,1fr)]">
        <div className="hidden lg:block border-r border-border min-h-0">{chat}</div>
        <div className="min-h-0 overflow-y-auto">
          <div className="max-w-[880px] mx-auto px-4 sm:px-8 pt-6">
            <div className="flex items-center gap-2 mb-4">
              <button type="button" onClick={onBack} className="lite-pill"><ChevronLeft className="w-3.5 h-3.5" /> Back</button>
              <span className="text-[12px] uppercase tracking-wide text-muted-foreground">Lab tools · Forms</span>
            </div>
            {toast && (
              <div className="mb-4 flex items-center gap-3 rounded-2xl bg-primary/10 px-4 py-2.5 text-[13px] animate-rise">
                <Check className="w-4 h-4 text-primary shrink-0" /><span className="flex-1 truncate">{toast.text}</span>
                {toast.undo && <button type="button" onClick={() => { setDraft(toast.undo!); setToast(null); }} className="inline-flex items-center gap-1 font-medium text-primary"><Undo2 className="w-3.5 h-3.5" /> Undo</button>}
                <button type="button" onClick={() => setToast(null)} className="text-muted-foreground hover:text-foreground"><X className="w-4 h-4" /></button>
              </div>
            )}
            {error && (
              <div className="mb-4 flex items-center gap-3 rounded-2xl bg-red-500/10 px-4 py-2.5 text-[13px] text-red-700">
                <span className="flex-1">{error}</span>
                <button type="button" onClick={() => setError(null)}><X className="w-4 h-4" /></button>
              </div>
            )}
            {hasForm ? form : entry}
          </div>
        </div>
      </div>

      {/* Ask the people: one big button once there is a form. */}
      {hasForm && (
        <div className="fixed bottom-5 left-1/2 -translate-x-1/2 lg:left-[calc(50%+210px)] z-30 max-w-[calc(100vw-2rem)]">
          <div className="lite-float px-2 py-2 flex items-center gap-1.5 animate-rise">
            <span className="hidden sm:inline text-[13px] text-muted-foreground pl-3">{qs.length} question{qs.length === 1 ? "" : "s"}</span>
            <button type="button" onClick={() => { setDraft(EMPTY); setToast({ text: "Cleared", undo: draft }); }} className="lite-btn-soft h-11 px-4">Start over</button>
            <button type="button" onClick={() => void run()} disabled={running} className="lite-btn h-11 px-5">{running ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowRight className="w-4 h-4" />} Ask the {n} people</button>
          </div>
        </div>
      )}

      {/* The chat below lg: a drawer, with a launcher. */}
      {chatOpen && (
        <div className="lg:hidden fixed inset-0 z-40">
          <div className="absolute inset-0 bg-black/30" onClick={() => setChatOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-[420px] max-w-[94vw] bg-background shadow-2xl">{chat}</div>
        </div>
      )}
      {!chatOpen && (
        <button type="button" onClick={() => setChatOpen(true)} className="lg:hidden fixed bottom-5 left-4 z-30 lite-btn-soft h-11 px-4 shadow-lg"><MessageCircle className="w-4 h-4" /> Think it through</button>
      )}
    </div>
  );
}
