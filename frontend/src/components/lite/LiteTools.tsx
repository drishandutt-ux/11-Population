"use client";

/** The Lab tools in the simple view (2026-10-19): the colleague's chat stays on the left, and
 *  the tools are icons on the right — tap one to open it. Forms (ask a few questions) is the
 *  simple Forms tool as it was; Barriers (what stands in the way) is set up by the chat, which
 *  asks each setting with its recommended answer and runs the tool once everything is settled.
 *  Drishan: *the chat option should be rigid, but Survey and Barrier shown as icons which can be
 *  clicked to open that tool.* */

import { useCallback, useEffect, useRef, useState } from "react";
import { api, Agent, LabBriefState, Probe } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ArrowUp, BookOpen, ChevronLeft, Construction, ListChecks, Loader2, MessageCircle, RefreshCw, Route, X } from "lucide-react";
import LiteForms from "./LiteForms";
import LiteBarriers from "./LiteBarriers";
import LiteJourney from "./LiteJourney";
import ErrorBoundary from "@/components/ErrorBoundary";
import { Md, ago } from "@/components/lab/forms/formUtils";

type Tool = "menu" | "survey" | "barriers" | "journey";
type ChatItem = { role: "user" | "assistant"; content: string; chips?: string[] };
const MAX_HISTORY = 24;
const toolKey = (sid: string) => `lite:tools:tool:${sid}`;
const chatKey = (sid: string) => `lite:tools:chat:${sid}`;
const draftKey = (sid: string) => `lite:forms:draft:${sid}`;

const TOOLS: { key: Tool; title: string; lead: string; icon: typeof ListChecks }[] = [
  { key: "survey", title: "Ask a few questions", lead: "A short form everyone fills in as themselves. Have it written, bring your own, or talk it through.", icon: ListChecks },
  { key: "barriers", title: "What stands in the way", lead: "Each person names the one thing stopping an outcome for them and what would remove it. Grouped and ranked.", icon: Construction },
  { key: "journey", title: "Where people drop off", lead: "The steps to the outcome, proposed for you. Each person says how far they get and what stops them; then try a change and see what moves.", icon: Route },
];

type Props = { sessionId: string; agents: Agent[]; onBack: () => void };

export default function LiteTools({ sessionId, agents, onBack }: Props) {
  const [tool, setToolState] = useState<Tool>("menu");
  const [initialGoal, setInitialGoal] = useState("");
  const setTool = (t: Tool) => { setToolState(t); try { sessionStorage.setItem(toolKey(sessionId), t); } catch { /* private mode */ } };
  useEffect(() => { try { const t = sessionStorage.getItem(toolKey(sessionId)) as Tool | null; if (t === "survey" || t === "barriers" || t === "journey") setToolState(t); } catch { /* private mode */ } }, [sessionId]);

  const [brief, setBrief] = useState<LabBriefState | null>(null);
  const [briefBusy, setBriefBusy] = useState(false);
  const [briefOpen, setBriefOpen] = useState(false);
  const [messages, setMessages] = useState<ChatItem[]>([]);
  const [chatBusy, setChatBusy] = useState(false);
  const [input, setInput] = useState("");
  const [chatOpen, setChatOpen] = useState(false);
  const [past, setPast] = useState<Probe[]>([]);
  const listRef = useRef<HTMLDivElement>(null);
  const openingAsked = useRef(false);
  const n = agents.length;

  useEffect(() => {
    try { const raw = sessionStorage.getItem(chatKey(sessionId)); if (raw) { const m = JSON.parse(raw); if (Array.isArray(m) && m.length) { setMessages(m); openingAsked.current = true; } } } catch { /* private mode */ }
    api.lab.probes(sessionId).then((r) => setPast(r.probes.filter((p) => (p.instrument === "survey" || p.instrument === "barriers" || p.instrument === "journey") && !p.experiment_id && !(p.spec as any)?.amendments))).catch(() => null);
  }, [sessionId, tool]);
  useEffect(() => { if (messages.length) { try { sessionStorage.setItem(chatKey(sessionId), JSON.stringify(messages.slice(-60))); } catch { /* private mode */ } } }, [messages, sessionId]);

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
      const r = await api.lab.formsChat(sessionId, { messages: [], form: null });
      setMessages((m) => (m.length ? m : [{ role: "assistant", content: r.reply, chips: [...(r.chips || []).filter((c) => /^draft:/i.test(c)).slice(0, 2), "What's in the way?"] }]));
    } catch { /* the reader types first */ }
  }, [sessionId]);
  useEffect(() => { if (tool === "menu") { (async () => { await loadBrief(); await askOpening(); })(); } }, [tool, loadBrief, askOpening]);
  useEffect(() => { const el = listRef.current; if (el) el.scrollTop = el.scrollHeight; }, [messages, chatBusy, chatOpen]);

  /** Open the Forms tool with a goal (the colleague writes the questions on arrival). */
  const openSurvey = (goal = "") => { setInitialGoal(goal); setTool("survey"); };

  const send = async (text: string) => {
    const t = text.trim();
    if (!t || chatBusy) return;
    setInput("");
    const history: ChatItem[] = [...messages, { role: "user", content: t }];
    setMessages(history);
    setChatBusy(true);
    try {
      const r = await api.lab.formsChat(sessionId, { messages: history.slice(-MAX_HISTORY).map(({ role, content }) => ({ role, content })), form: null });
      setMessages((m) => [...m, { role: "assistant", content: r.reply, chips: r.chips }]);
      // A form drafted from the chat opens the Forms tool with it on screen.
      if (r.form_changed && r.form && r.form.questions?.length) {
        try { sessionStorage.setItem(draftKey(sessionId), JSON.stringify({ title: r.form.title || "", intro: r.form.intro || "", questions: r.form.questions })); } catch { /* private mode */ }
        openSurvey();
      }
    } catch (e: any) {
      setMessages((m) => [...m, { role: "assistant", content: `Sorry — that didn't go through. ${e?.message || ""}`.trim() }]);
    } finally { setChatBusy(false); }
  };
  const tapChip = (c: string) => {
    const low = c.toLowerCase();
    if (low.startsWith("draft: ")) { openSurvey(c.slice(7)); return; }
    if (low === "write it for me") { openSurvey(""); return; }
    if (low === "i have a questionnaire") { openSurvey(""); return; }
    if (low === "what's in the way?" || low === "what's in the way") { setTool("barriers"); return; }
    void send(c);
  };

  if (tool === "survey") return <ErrorBoundary label="Forms"><LiteForms sessionId={sessionId} agents={agents} onBack={() => setTool("menu")} initialGoal={initialGoal} /></ErrorBoundary>;
  if (tool === "barriers") return <ErrorBoundary label="Barriers"><LiteBarriers sessionId={sessionId} agents={agents} onBack={() => setTool("menu")} /></ErrorBoundary>;
  if (tool === "journey") return <ErrorBoundary label="Journey"><LiteJourney sessionId={sessionId} agents={agents} onBack={() => setTool("menu")} /></ErrorBoundary>;

  const challenges = brief?.brief?.challenges || [];
  const chat = (
    <div className="h-full flex flex-col min-h-0">
      <div className="px-5 pt-4 pb-2 flex items-center gap-2 shrink-0">
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-semibold">Think it through</div>
          <button type="button" onClick={() => setBriefOpen((v) => !v)} className="text-[12px] text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 mt-0.5">
            {briefBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : <BookOpen className="w-3 h-3" />}
            {briefBusy ? "Reading everything in this question…" : brief?.brief ? `What I know${brief.stale ? " (a little while ago)" : ""}` : "Nothing read yet"}
          </button>
        </div>
        <button type="button" onClick={() => setChatOpen(false)} className="lg:hidden w-9 h-9 rounded-full inline-flex items-center justify-center text-muted-foreground hover:bg-foreground/5"><X className="w-4 h-4" /></button>
      </div>
      <div ref={listRef} className="flex-1 min-h-0 overflow-y-auto px-5 pb-3 space-y-4">
        {briefOpen && brief?.brief && (
          <div className="rounded-2xl bg-foreground/[0.04] p-4 text-[13px] leading-relaxed space-y-2">
            <p>{brief.brief.summary}</p>
            {challenges.length > 0 && <div><div className="font-medium">Worth asking about</div><ul className="list-disc pl-4 text-muted-foreground">{challenges.map((c, i) => <li key={i}><span className="text-foreground">{c.title}</span> — {c.measure}</li>)}</ul></div>}
            <button type="button" onClick={() => void loadBrief(true)} disabled={briefBusy} className="inline-flex items-center gap-1 text-[12px] text-muted-foreground hover:text-foreground"><RefreshCw className={cn("w-3 h-3", briefBusy && "animate-spin")} /> read it again</button>
          </div>
        )}
        {messages.length === 0 && <p className="text-[13px] text-muted-foreground inline-flex items-center gap-2 pt-2"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Reading everything in this question…</p>}
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "flex justify-end" : ""}>
            <div className={cn("max-w-[92%] text-[14px] leading-relaxed", m.role === "user" ? "rounded-2xl rounded-br-md bg-foreground text-background px-4 py-2.5" : "text-foreground")}>
              {m.role === "user" ? <span className="whitespace-pre-wrap">{m.content}</span> : <Md text={m.content} />}
            </div>
            {m.role === "assistant" && i === messages.length - 1 && m.chips && m.chips.length > 0 && !chatBusy && (
              <div className="flex flex-wrap gap-1.5 mt-2.5">
                {m.chips.slice(0, 3).map((c) => <button key={c} type="button" onClick={() => tapChip(c)} className="lite-pill-quiet">{c.replace(/^Draft: /i, "")}</button>)}
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
            placeholder="What do you want to find out?" className="lite-input flex-1 text-[15px] leading-relaxed" />
          <button type="button" onClick={() => void send(input)} disabled={!input.trim() || chatBusy} className="w-9 h-9 rounded-full bg-foreground text-background disabled:opacity-30 inline-flex items-center justify-center shrink-0"><ArrowUp className="w-4 h-4" /></button>
        </div>
      </div>
    </div>
  );

  return (
    <div className="flex-1 min-h-0 relative">
      <div className="h-full grid grid-cols-1 lg:grid-cols-[minmax(340px,420px)_minmax(0,1fr)]">
        <div className="hidden lg:block border-r border-border min-h-0">{chat}</div>
        <div className="min-h-0 overflow-y-auto">
          <div className="max-w-[880px] mx-auto px-4 sm:px-8 pt-6 pb-16">
            <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-[13px] text-muted-foreground hover:text-foreground mb-6"><ChevronLeft className="w-3.5 h-3.5" /> Back</button>
            <div className="animate-rise space-y-10">
              <div>
                <h1 className="text-[26px] sm:text-[30px] font-semibold tracking-tight">Lab tools</h1>
                <p className="lite-lead mt-2">{n > 0 ? `Put a question to the ${n} people in a structured way. Pick a tool, or talk it through on the left.` : "Make the people first, then come back here."}</p>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                {TOOLS.map((t) => (
                  <button key={t.key} type="button" onClick={() => (t.key === "survey" ? openSurvey("") : setTool(t.key))} disabled={n === 0}
                    className="lite-card p-6 text-left transition-transform hover:-translate-y-0.5 disabled:opacity-50 disabled:hover:translate-y-0 group">
                    <div className="w-12 h-12 rounded-2xl bg-primary/10 text-primary inline-flex items-center justify-center group-hover:bg-primary/15 transition-colors"><t.icon className="w-6 h-6" /></div>
                    <div className="text-[18px] font-semibold tracking-tight mt-4">{t.title}</div>
                    <p className="text-[13.5px] text-muted-foreground mt-1.5 leading-relaxed">{t.lead}</p>
                  </button>
                ))}
              </div>
              {past.length > 0 && (
                <section>
                  <div className="text-[13px] text-muted-foreground">Earlier runs</div>
                  <div className="divide-y divide-border">
                    {past.slice(0, 8).map((p) => (
                      <button key={p.id} type="button" onClick={() => setTool(p.instrument === "barriers" ? "barriers" : p.instrument === "journey" ? "journey" : "survey")} className="w-full flex items-baseline gap-3 py-2.5 text-left group">
                        <span className="text-[12px] uppercase tracking-wide text-muted-foreground w-16 shrink-0">{p.instrument === "barriers" ? "barriers" : p.instrument === "journey" ? "journey" : "form"}</span>
                        <span className="text-[14px] font-medium truncate flex-1 group-hover:text-primary transition-colors">{String((p.spec as any)?.title || (p.spec as any)?.outcome || ((p.spec as any)?.stages || []).slice(-1)[0]?.label || "A run")}</span>
                        <span className="text-[12px] text-muted-foreground shrink-0 tabular-nums">{p.answer_count} answered · {ago(p.created_at || null)}</span>
                      </button>
                    ))}
                  </div>
                </section>
              )}
            </div>
          </div>
        </div>
      </div>
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
