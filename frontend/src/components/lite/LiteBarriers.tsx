"use client";

/** Barriers in the simple view (2026-10-19): what stands in the way of an outcome, set up
 *  entirely by the colleague in the chat. It asks for each setting the tool needs with its own
 *  recommended answer; the reader says "use that" or changes it; the moment every setting is
 *  settled the tool runs by itself, and the answers come back as the same ranked list the pro
 *  Lab draws — one "See in detail" away from the full thing. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, Agent, ConfigureChatReply, Instrument, InstrumentInput, Probe, ProbeAnswerRow } from "@/lib/api";
import { LITE_DEFAULTS, proLinks } from "@/lib/lite";
import { cn } from "@/lib/utils";
import { ArrowRight, ArrowUp, Check, ChevronLeft, Loader2, MessageCircle, Plus, Sparkles, X } from "lucide-react";
import Detail from "./Detail";
import ErrorBoundary from "@/components/ErrorBoundary";
import BarriersPage from "@/components/lab/pages/BarriersPage";
import { Md, ago } from "@/components/lab/forms/formUtils";

type ChatItem = { role: "user" | "assistant"; content: string; chips?: string[] };
type Stage = "compose" | "running" | "results";
const MAX_HISTORY = 24;
const INSTRUMENT = "barriers";
const stateKey = (sid: string) => `lite:barriers:state:${sid}`;

type Props = { sessionId: string; agents: Agent[]; onBack: () => void };

export default function LiteBarriers({ sessionId, agents, onBack }: Props) {
  const [messages, setMessages] = useState<ChatItem[]>([]);
  const [settings, setSettings] = useState<Record<string, any>>({});
  const [inputs, setInputs] = useState<InstrumentInput[]>([]);
  const [asking, setAsking] = useState("");
  const [recommended, setRecommended] = useState("");
  const [ready, setReady] = useState(false);
  const [chatBusy, setChatBusy] = useState(false);
  const [input, setInput] = useState("");
  const [chatOpen, setChatOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const openingAsked = useRef(false);
  const settingsRef = useRef(settings);
  settingsRef.current = settings;

  const [stage, setStage] = useState<Stage>("compose");
  const [probe, setProbe] = useState<(Probe & { answers?: ProbeAnswerRow[] }) | null>(null);
  const [instrument, setInstrument] = useState<Instrument | null>(null);
  const [past, setPast] = useState<Probe[]>([]);
  const [running, setRunning] = useState(false);
  const autoRan = useRef(false);
  const agentsById = useMemo(() => Object.fromEntries(agents.map((a) => [a.id, a])), [agents]);
  const n = agents.length;

  // ── what survives a tab switch ───────────────────────────────────────────
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(stateKey(sessionId));
      if (raw) {
        const st = JSON.parse(raw);
        if (Array.isArray(st.messages) && st.messages.length) { setMessages(st.messages); openingAsked.current = true; }
        if (st.settings && typeof st.settings === "object") setSettings(st.settings);
        if (typeof st.asking === "string") setAsking(st.asking);
        if (typeof st.recommended === "string") setRecommended(st.recommended);
        if (Array.isArray(st.inputs)) setInputs(st.inputs);
        if (st.ready) { setReady(true); autoRan.current = true; }
      }
    } catch { /* private mode */ }
  }, [sessionId]);
  useEffect(() => {
    if (!messages.length) return;
    try { sessionStorage.setItem(stateKey(sessionId), JSON.stringify({ messages: messages.slice(-60), settings, asking, recommended, inputs, ready })); } catch { /* private mode */ }
  }, [messages, settings, asking, recommended, inputs, ready, sessionId]);

  const loadPast = useCallback(() => {
    api.lab.probes(sessionId).then((r) => setPast(r.probes.filter((p) => p.instrument === INSTRUMENT && !p.experiment_id))).catch(() => null);
  }, [sessionId]);
  useEffect(() => {
    api.lab.instruments().then((r) => { const inst = r.instruments.find((i) => i.key === INSTRUMENT) || null; setInstrument(inst); if (inst && !inputs.length) setInputs(inst.inputs); }).catch(() => null);
    loadPast();
  }, [sessionId, loadPast]); // eslint-disable-line react-hooks/exhaustive-deps

  const applyReply = useCallback((r: ConfigureChatReply) => {
    setSettings(r.settings || {});
    setAsking(r.asking || "");
    setRecommended(r.recommended || "");
    if (r.inputs?.length) setInputs(r.inputs);
    setReady(Boolean(r.ready));
    setMessages((m) => [...m, { role: "assistant", content: r.reply, chips: r.chips }]);
  }, []);

  const askOpening = useCallback(async () => {
    if (openingAsked.current) return;
    openingAsked.current = true;
    setChatBusy(true);
    try {
      const r = await api.lab.configureChat(sessionId, { instrument: INSTRUMENT, messages: [], settings: null, mode: LITE_DEFAULTS.mode });
      applyReply(r);
    } catch (e: any) {
      setMessages([{ role: "assistant", content: `I couldn't read the session just now. ${e?.message || ""}`.trim(), chips: ["Try again"] }]);
      openingAsked.current = false;
    } finally { setChatBusy(false); }
  }, [sessionId, applyReply]);
  useEffect(() => { void askOpening(); }, [askOpening]);
  useEffect(() => { const el = listRef.current; if (el) el.scrollTop = el.scrollHeight; }, [messages, chatBusy, chatOpen]);

  // ── running it ───────────────────────────────────────────────────────────
  const run = useCallback(async () => {
    if (running) return;
    const spec = { ...settingsRef.current };
    const missing = inputs.filter((i) => i.required && !String(spec[i.key] ?? "").trim());
    if (missing.length) { setError(`Still to decide: ${missing.map((i) => i.label.toLowerCase()).join(", ")}.`); return; }
    setRunning(true); setError(null);
    try {
      const p = await api.lab.run(sessionId, { instrument: INSTRUMENT, mode: LITE_DEFAULTS.mode, spec });
      setProbe(p);
      setStage("running");
    } catch (e: any) { setError(e?.message || "Could not ask them"); } finally { setRunning(false); }
  }, [running, inputs, sessionId]);

  // The moment every setting is settled, it runs: "when all options are sorted out, it performs its function."
  useEffect(() => {
    if (ready && stage === "compose" && !autoRan.current && !chatBusy) { autoRan.current = true; void run(); }
  }, [ready, stage, chatBusy, run]);

  useEffect(() => {
    if (stage !== "running" || !probe) return;
    let alive = true;
    const tick = async () => {
      try {
        const full = await api.lab.probe(sessionId, probe.id);
        if (!alive) return;
        setProbe(full);
        if (full.status !== "queued" && full.status !== "running") { setStage("results"); loadPast(); }
      } catch { /* try again */ }
    };
    const id = setInterval(tick, 2500);
    void tick();
    return () => { alive = false; clearInterval(id); };
  }, [stage, probe?.id, sessionId, loadPast]); // eslint-disable-line react-hooks/exhaustive-deps

  // The run lands "complete" a few seconds before the answers are coded into shared barriers
  // (the pro Lab waits on the socket for that; the simple view polls): keep refreshing the
  // result until `barriers_coded` is true, for up to two minutes.
  useEffect(() => {
    if (stage !== "results" || !probe || probe.status !== "complete" || probe.aggregates?.barriers_coded) return;
    let alive = true;
    const started = Date.now();
    const tick = async () => {
      if (Date.now() - started > 120_000) return;
      try { const full = await api.lab.probe(sessionId, probe.id); if (alive) setProbe(full); } catch { /* try again */ }
    };
    const id = setInterval(tick, 4000);
    return () => { alive = false; clearInterval(id); };
  }, [stage, probe?.id, probe?.status, probe?.aggregates?.barriers_coded, sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  const openPast = async (p: Probe) => {
    setProbe(p);
    setStage(p.status === "queued" || p.status === "running" ? "running" : "results");
    const full = await api.lab.probe(sessionId, p.id).catch(() => null);
    if (full) setProbe(full);
  };

  // ── the conversation ─────────────────────────────────────────────────────
  const send = async (text: string) => {
    const t = text.trim();
    if (!t || chatBusy) return;
    setInput("");
    const history: ChatItem[] = [...messages, { role: "user", content: t }];
    setMessages(history);
    setChatBusy(true);
    try {
      const r = await api.lab.configureChat(sessionId, { instrument: INSTRUMENT, messages: history.slice(-MAX_HISTORY).map(({ role, content }) => ({ role, content })), settings: settingsRef.current, mode: LITE_DEFAULTS.mode });
      if (r.ready && !ready) autoRan.current = false;      // a fresh "ready" runs once
      applyReply(r);
    } catch (e: any) {
      setMessages((m) => [...m, { role: "assistant", content: `Sorry — that didn't go through. ${e?.message || ""}`.trim() }]);
    } finally { setChatBusy(false); }
  };
  const tapChip = (c: string) => {
    const low = c.toLowerCase();
    if (low === "run it" || low === "find out") { autoRan.current = true; void run(); return; }
    if (low === "try again") { openingAsked.current = false; void askOpening(); return; }
    if (low === "change it") { setInput(""); setTimeout(() => inputRef.current?.focus(), 0); setChatOpen(true); return; }
    void send(c);
  };
  const startOver = () => {
    setMessages([]); setSettings({}); setAsking(""); setRecommended(""); setReady(false); autoRan.current = false; openingAsked.current = false;
    try { sessionStorage.removeItem(stateKey(sessionId)); } catch { /* private mode */ }
    setStage("compose"); setProbe(null);
    void askOpening();
  };

  // ── no people yet ──────────────────────────────────────────────────────────
  if (n === 0) {
    return (
      <div className="max-w-xl mx-auto pt-16 px-6 animate-rise text-center">
        <div className="lite-card p-8">
          <h1 className="text-[24px] font-semibold tracking-tight">Make the people first</h1>
          <p className="lite-lead mt-2">Barriers ask the people in this question what stands in their way. Once they exist, come back here.</p>
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
          <h1 className="text-[24px] font-semibold tracking-tight mt-4">Asking {total} people what stands in the way</h1>
          <p className="lite-lead mt-2">Each one says whether this would happen for them, the one thing in the way, and what would remove it. Then the answers are grouped and ranked.</p>
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
          <button type="button" onClick={() => setStage("compose")} className="lite-pill-quiet"><ChevronLeft className="w-3.5 h-3.5" /> Set it up again</button>
          <div className="min-w-0">
            <h1 className="text-[20px] font-semibold tracking-tight truncate">What stands in the way of: {String((probe.spec as any)?.outcome || "the outcome")}</h1>
            <p className="text-[12.5px] text-muted-foreground">{probe.answer_count} of {probe.agent_count} answered{probe.created_at ? ` · ${ago(probe.created_at)}` : ""}{probe.status !== "complete" ? ` · ${probe.status}` : ""}{probe.status === "complete" && !probe.aggregates?.barriers_coded ? <span className="inline-flex items-center gap-1 ml-2"><Loader2 className="w-3 h-3 animate-spin" /> grouping the answers…</span> : null}</p>
          </div>
          <button type="button" onClick={startOver} className="lite-btn-soft lite-btn-sm ml-auto"><Plus className="w-3.5 h-3.5" /> Another outcome</button>
        </div>
        <Detail href={proLinks.lab(sessionId)} className="flex-1 min-h-0">
          <div className="lite-card p-4 sm:p-6 h-full overflow-y-auto">
            {ok && instrument ? (
              <ErrorBoundary label="The barriers"><BarriersPage instrument={instrument} probe={probe} agentsById={agentsById} /></ErrorBoundary>
            ) : (
              <p className="lite-lead">{probe.error || (probe.status === "stopped" ? "Stopped before anyone answered." : "Nobody could answer this one.")}</p>
            )}
          </div>
        </Detail>
      </div>
    );
  }

  // ── compose: the chat decides everything ──────────────────────────────────
  const chat = (
    <div className="h-full flex flex-col min-h-0">
      <div className="px-5 pt-4 pb-2 flex items-center gap-2 shrink-0">
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-semibold">Set it up together</div>
          <div className="text-[12px] text-muted-foreground mt-0.5">I'll suggest each setting; say yes or change it.</div>
        </div>
        <button type="button" onClick={() => setChatOpen(false)} className="lg:hidden w-9 h-9 rounded-full inline-flex items-center justify-center text-muted-foreground hover:bg-foreground/5"><X className="w-4 h-4" /></button>
      </div>
      <div ref={listRef} className="flex-1 min-h-0 overflow-y-auto px-5 pb-3 space-y-4">
        {messages.length === 0 && <p className="text-[13px] text-muted-foreground inline-flex items-center gap-2 pt-2"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Reading everything in this question…</p>}
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "flex justify-end" : ""}>
            <div className={cn("max-w-[92%] text-[14px] leading-relaxed", m.role === "user" ? "rounded-2xl rounded-br-md bg-foreground text-background px-4 py-2.5" : "text-foreground")}>
              {m.role === "user" ? <span className="whitespace-pre-wrap">{m.content}</span> : <Md text={m.content} />}
            </div>
            {m.role === "assistant" && i === messages.length - 1 && m.chips && m.chips.length > 0 && !chatBusy && (
              <div className="flex flex-wrap gap-1.5 mt-2.5">
                {m.chips.slice(0, 3).map((c) => <button key={c} type="button" onClick={() => tapChip(c)} className="lite-pill-quiet">{c}</button>)}
              </div>
            )}
          </div>
        ))}
        {chatBusy && <p className="text-[13px] text-muted-foreground inline-flex items-center gap-2"><span className="lite-dots flex gap-1"><span /><span /><span /></span> thinking</p>}
      </div>
      <div className="p-4 shrink-0">
        <div className="lite-field flex items-end gap-2 py-2 pr-2">
          <textarea ref={inputRef} value={input} onChange={(e) => setInput(e.target.value)} rows={Math.min(4, Math.max(1, input.split("\n").length))}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(input); } }}
            placeholder={asking ? "Use that, or say what you'd rather…" : "Change something…"} className="lite-input flex-1 text-[15px] leading-relaxed" />
          <button type="button" onClick={() => void send(input)} disabled={!input.trim() || chatBusy} className="w-9 h-9 rounded-full bg-foreground text-background disabled:opacity-30 inline-flex items-center justify-center shrink-0"><ArrowUp className="w-4 h-4" /></button>
        </div>
      </div>
    </div>
  );

  const settingsCard = (
    <div className="animate-rise space-y-8 max-w-xl">
      <div>
        <h1 className="text-[26px] sm:text-[30px] font-semibold tracking-tight">What stands in the way?</h1>
        <p className="lite-lead mt-2">Every one of the {n} people says whether this would happen for them, the one thing in the way, and what would remove it. The answers come back grouped and ranked.</p>
      </div>
      <section className="lite-card p-5 space-y-4">
        <div className="text-[13px] text-muted-foreground">The settings{ready ? " — all set" : asking ? " — being decided on the left" : ""}</div>
        {inputs.map((f) => {
          const v = settings[f.key];
          const isAsking = asking === f.key;
          return (
            <div key={f.key} className={cn("rounded-2xl px-4 py-3 transition-colors", isAsking ? "bg-primary/5 ring-1 ring-primary/30" : "bg-foreground/[0.03]")}>
              <div className="text-[12.5px] text-muted-foreground">{f.label}{f.required ? "" : " (optional)"}</div>
              {v !== undefined && v !== "" ? (
                <div className="mt-1 text-[15px] font-medium inline-flex items-start gap-2"><Check className="w-4 h-4 text-primary mt-0.5 shrink-0" /> <span>{String(v)}</span></div>
              ) : isAsking && recommended ? (
                <div className="mt-1 space-y-2">
                  <div className="text-[15px] inline-flex items-start gap-2"><Sparkles className="w-4 h-4 text-primary mt-0.5 shrink-0" /> <span><span className="text-muted-foreground">Suggested: </span>{recommended}</span></div>
                  <div className="flex gap-1.5">
                    <button type="button" onClick={() => void send("Use that")} disabled={chatBusy} className="lite-btn lite-btn-sm">Use that</button>
                    <button type="button" onClick={() => tapChip("Change it")} className="lite-btn-soft lite-btn-sm">Change it</button>
                  </div>
                </div>
              ) : (
                <div className="mt-1 text-[14px] text-muted-foreground">{isAsking ? "Being decided…" : "Not decided yet"}</div>
              )}
            </div>
          );
        })}
        {inputs.length === 0 && <p className="text-[13px] text-muted-foreground inline-flex items-center gap-2"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading the tool…</p>}
      </section>
      {past.length > 0 && (
        <section>
          <div className="text-[13px] text-muted-foreground">Earlier runs</div>
          <div className="divide-y divide-border">
            {past.slice(0, 6).map((p) => (
              <button key={p.id} type="button" onClick={() => void openPast(p)} className="w-full flex items-baseline gap-3 py-2.5 text-left group">
                <span className="text-[14px] font-medium truncate flex-1 group-hover:text-primary transition-colors">{String((p.spec as any)?.outcome || "An outcome")}</span>
                <span className="text-[12px] text-muted-foreground shrink-0 tabular-nums">{p.answer_count} answered · {ago(p.created_at || null)}</span>
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  );

  return (
    <div className="flex-1 min-h-0 relative">
      <div className="h-full grid grid-cols-1 lg:grid-cols-[minmax(340px,420px)_minmax(0,1fr)]">
        <div className="hidden lg:block border-r border-border min-h-0">{chat}</div>
        <div className="min-h-0 overflow-y-auto">
          <div className="max-w-[880px] mx-auto px-4 sm:px-8 pt-6 pb-28">
            <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-[13px] text-muted-foreground hover:text-foreground mb-6"><ChevronLeft className="w-3.5 h-3.5" /> Back</button>
            {error && (
              <div className="mb-4 flex items-center gap-3 rounded-2xl bg-red-500/10 px-4 py-2.5 text-[13px] text-red-700">
                <span className="flex-1">{error}</span>
                <button type="button" onClick={() => setError(null)}><X className="w-4 h-4" /></button>
              </div>
            )}
            {settingsCard}
          </div>
        </div>
      </div>

      {ready && (
        <div className="fixed bottom-5 left-1/2 -translate-x-1/2 lg:left-[calc(50%+210px)] z-30 max-w-[calc(100vw-2rem)]">
          <div className="lite-float px-2 py-2 flex items-center gap-1.5 animate-rise">
            <button type="button" onClick={startOver} className="lite-btn-soft h-11 px-4">Start over</button>
            <button type="button" onClick={() => { autoRan.current = true; void run(); }} disabled={running} className="lite-btn h-11 px-5">{running ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowRight className="w-4 h-4" />} Ask the {n} people</button>
          </div>
        </div>
      )}

      {chatOpen && (
        <div className="lg:hidden fixed inset-0 z-40">
          <div className="absolute inset-0 bg-black/30" onClick={() => setChatOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-[420px] max-w-[94vw] bg-background shadow-2xl">{chat}</div>
        </div>
      )}
      {!chatOpen && (
        <button type="button" onClick={() => setChatOpen(true)} className="lg:hidden fixed bottom-5 left-4 z-30 lite-btn-soft h-11 px-4 shadow-lg"><MessageCircle className="w-4 h-4" /> Set it up</button>
      )}
    </div>
  );
}
