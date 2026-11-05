"use client";

/** 11 Minds City in the simple view (2026-11-05). The colleague reads the session and plans a
 *  city with the reader: which places, what outcome to watch, which levers are worth trying.
 *  "Build it" asks every twin once about their ordinary week and how far each lever would move
 *  them (the `city` instrument, an ordinary probe), then opens the living 3D town built from
 *  those answers. Drishan: *the system will create a whole new world … suggest what would be the
 *  action points best to influence and then see the influence by themselves.* */

import dynamic from "next/dynamic";
import { useSessionTier } from "@/components/sessions/TierSwitch";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, Agent, CityPlan, Probe, ProbeAnswerRow } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ArrowUp, Building2, ChevronLeft, Loader2, MessageCircle, X } from "lucide-react";
import ErrorBoundary from "@/components/ErrorBoundary";
import { Md, ago } from "@/components/lab/forms/formUtils";

const CityWorld = dynamic(() => import("@/components/city/CityWorld"), { ssr: false, loading: () => <div className="fixed inset-0 z-50 grid place-items-center bg-[#E9E2D6] text-[#2B2522]"><Loader2 className="w-6 h-6 animate-spin" /></div> });

type ChatItem = { role: "user" | "assistant"; content: string; chips?: string[] };
type Stage = "plan" | "building" | "city";
const MAX_HISTORY = 24;
const INSTRUMENT = "city";
const stateKey = (sid: string) => `lite:city:state:${sid}`;
const LEVER_ICON: Record<string, string> = { poster: "📣", tv: "📺", social: "📱", radio: "📻", leaflet: "✉️", advice: "🩺", event: "🎪", price: "🏷️", hours: "🕘", word_of_mouth: "🗣️" };

type Props = { sessionId: string; agents: Agent[]; onBack: () => void };

export default function LiteCity({ sessionId, agents, onBack }: Props) {
  const [tier] = useSessionTier(sessionId);
  const [messages, setMessages] = useState<ChatItem[]>([]);
  const [plan, setPlan] = useState<CityPlan | null>(null);
  const [ready, setReady] = useState(false);
  const [missing, setMissing] = useState<string[]>([]);
  const [chatBusy, setChatBusy] = useState(false);
  const [input, setInput] = useState("");
  const [chatOpen, setChatOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stage, setStage] = useState<Stage>("plan");
  const [probe, setProbe] = useState<(Probe & { answers?: ProbeAnswerRow[] }) | null>(null);
  const [past, setPast] = useState<Probe[]>([]);
  const [building, setBuilding] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const openingAsked = useRef(false);
  const autoBuilt = useRef(false);
  const planRef = useRef(plan); planRef.current = plan;
  const n = agents.length;

  const loadPast = useCallback(() => {
    api.lab.probes(sessionId).then((r) => setPast(r.probes.filter((p) => p.instrument === INSTRUMENT && !p.experiment_id))).catch(() => null);
  }, [sessionId]);
  useEffect(() => { loadPast(); }, [loadPast]);

  // Keep the conversation and the plan across a reload.
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(stateKey(sessionId));
      if (raw) {
        const s = JSON.parse(raw);
        if (Array.isArray(s.messages) && s.messages.length) { setMessages(s.messages); openingAsked.current = true; }
        if (s.plan) setPlan(s.plan);
      }
    } catch { /* private mode */ }
  }, [sessionId]);
  useEffect(() => {
    if (!messages.length) return;
    try { sessionStorage.setItem(stateKey(sessionId), JSON.stringify({ messages: messages.slice(-60), plan })); } catch { /* private mode */ }
  }, [messages, plan, sessionId]);

  const apply = useCallback((r: { reply: string; chips: string[]; plan: CityPlan | null; ready: boolean; missing: string[] }) => {
    if (r.plan) setPlan(r.plan);
    setReady(Boolean(r.ready));
    setMissing(r.missing || []);
    setMessages((m) => [...m, { role: "assistant", content: r.reply, chips: r.chips }]);
  }, []);

  const askOpening = useCallback(async () => {
    if (openingAsked.current) return;
    openingAsked.current = true;
    setChatBusy(true);
    try {
      apply(await api.lab.cityChat(sessionId, { messages: [], plan: planRef.current, mode: tier }));
    } catch (e: any) {
      setMessages([{ role: "assistant", content: `I couldn't read the session just now. ${e?.message || ""}`.trim(), chips: ["Try again"] }]);
      openingAsked.current = false;
    } finally { setChatBusy(false); }
  }, [sessionId, apply, tier]);
  useEffect(() => { if (n > 0) void askOpening(); }, [askOpening, n]);
  useEffect(() => { const el = listRef.current; if (el) el.scrollTop = el.scrollHeight; }, [messages, chatBusy, chatOpen]);

  // ── building it ──────────────────────────────────────────────────────────
  const build = useCallback(async () => {
    const p = planRef.current;
    if (building || !p) return;
    if (!p.cities.length || !p.levers.length) { setError("The plan needs at least one place and one lever."); return; }
    setBuilding(true); setError(null);
    try {
      const pr = await api.lab.run(sessionId, { instrument: INSTRUMENT, mode: tier, spec: { ...p } as any });
      setProbe(pr);
      setStage("building");
    } catch (e: any) { setError(e?.message || "Could not build the city"); } finally { setBuilding(false); }
  }, [building, sessionId, tier]);

  useEffect(() => {
    if (ready && stage === "plan" && !autoBuilt.current && !chatBusy) { autoBuilt.current = true; void build(); }
  }, [ready, stage, chatBusy, build]);

  useEffect(() => {
    if (stage !== "building" || !probe) return;
    let alive = true;
    const tick = async () => {
      try {
        const full = await api.lab.probe(sessionId, probe.id);
        if (!alive) return;
        setProbe(full);
        if (full.status !== "queued" && full.status !== "running") { loadPast(); setStage(full.answers?.length ? "city" : "plan"); if (!full.answers?.length) setError(full.error || "Nobody could answer, so there is no city to show."); }
      } catch { /* try again */ }
    };
    const id = setInterval(tick, 2500);
    void tick();
    return () => { alive = false; clearInterval(id); };
  }, [stage, probe?.id, sessionId, loadPast]); // eslint-disable-line react-hooks/exhaustive-deps

  const openPast = async (p: Probe) => {
    setError(null);
    const full = await api.lab.probe(sessionId, p.id).catch(() => null);
    if (!full) { setError("Could not open that city."); return; }
    setProbe(full);
    setStage(full.status === "queued" || full.status === "running" ? "building" : full.answers?.length ? "city" : "plan");
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
      const r = await api.lab.cityChat(sessionId, { messages: history.slice(-MAX_HISTORY).map(({ role, content }) => ({ role, content })), plan: planRef.current, mode: tier });
      if (r.ready) autoBuilt.current = false;
      apply(r);
    } catch (e: any) {
      setMessages((m) => [...m, { role: "assistant", content: `Sorry — that didn't go through. ${e?.message || ""}`.trim() }]);
    } finally { setChatBusy(false); }
  };
  const tapChip = (c: string) => {
    const low = c.toLowerCase();
    if (low === "build it" || low === "build the city") { autoBuilt.current = true; void build(); return; }
    if (low === "try again") { openingAsked.current = false; void askOpening(); return; }
    void send(c);
  };
  const startOver = () => {
    setMessages([]); setPlan(null); setReady(false); setMissing([]); autoBuilt.current = false; openingAsked.current = false; setError(null);
    try { sessionStorage.removeItem(stateKey(sessionId)); } catch { /* private mode */ }
    void askOpening();
  };
  const removeLever = (id: string) => setPlan((p) => (p ? { ...p, levers: p.levers.filter((l) => l.id !== id) } : p));
  const removeTown = (id: string) => setPlan((p) => (p ? { ...p, cities: p.cities.filter((c) => c.id !== id) } : p));

  // ── screens ──────────────────────────────────────────────────────────────
  if (n === 0) {
    return (
      <div className="max-w-xl mx-auto pt-16 px-6 animate-rise text-center">
        <div className="lite-card p-8">
          <h1 className="text-[24px] font-semibold tracking-tight">Make the people first</h1>
          <p className="lite-lead mt-2">The city is built around the people in this question. Once they exist, come back here.</p>
          <button type="button" onClick={onBack} className="lite-btn mt-6">Back</button>
        </div>
      </div>
    );
  }

  if (stage === "city" && probe?.answers?.length) {
    const spec = probe.spec as any as CityPlan & { seed?: number };
    return (
      <ErrorBoundary label="The city">
        <CityWorld plan={spec} answers={probe.answers} seed={Number((probe.spec as any)?.seed) || 1} onBack={() => setStage("plan")} />
      </ErrorBoundary>
    );
  }

  if (stage === "building" && probe) {
    const answered = probe.answer_count || 0;
    const total = probe.agent_count || n;
    return (
      <div className="max-w-xl mx-auto pt-16 px-6 animate-rise text-center">
        <div className="lite-card p-8">
          <Building2 className="w-8 h-8 mx-auto text-primary" />
          <h1 className="text-[22px] font-semibold tracking-tight mt-3">Moving people in</h1>
          <p className="lite-lead mt-2">Each person is telling us about their ordinary week and how each lever would land with them. {answered} of {total} so far.</p>
          <div className="h-2 rounded-full bg-foreground/10 overflow-hidden mt-5"><div className="h-full bg-primary transition-all" style={{ width: `${total ? (answered / total) * 100 : 0}%` }} /></div>
          <button type="button" onClick={() => api.lab.stop(sessionId, probe.id).catch(() => null)} className="lite-btn-soft lite-btn-sm mt-6">Stop and open with who's in</button>
        </div>
      </div>
    );
  }

  const chat = (
    <div className="h-full flex flex-col min-h-0">
      <div className="px-5 pt-4 pb-2 flex items-center gap-2 shrink-0">
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-semibold">Plan the city</div>
          <button type="button" onClick={startOver} className="text-[12px] text-muted-foreground hover:text-foreground">Start over</button>
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
          <textarea value={input} onChange={(e) => setInput(e.target.value)} rows={Math.min(4, Math.max(1, input.split("\n").length))}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(input); } }}
            placeholder="Which places? What do you want to see happen?" className="lite-input flex-1 text-[15px] leading-relaxed" />
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
            <div className="animate-rise space-y-8">
              <div>
                <h1 className="text-[26px] sm:text-[30px] font-semibold tracking-tight">11 Minds City</h1>
                <p className="lite-lead mt-2">A living town built around this question. The {n} people live in it, go to work, get hungry, spend, meet each other — and you launch the things that might move them and watch who acts, when and why.</p>
              </div>
              {!plan || !plan.cities.length ? (
                <div className="lite-card p-6 text-[14px] text-muted-foreground inline-flex items-center gap-2">{chatBusy ? <><Loader2 className="w-4 h-4 animate-spin" /> Drafting a plan from the session…</> : "The plan appears here as you talk it through."}</div>
              ) : (
                <div className="lite-card p-6 space-y-6">
                  <div>
                    <div className="text-[12px] uppercase tracking-wide text-muted-foreground">The plan</div>
                    <div className="text-[20px] font-semibold tracking-tight mt-1">{plan.title}</div>
                    {plan.goal && <p className="text-[14px] text-muted-foreground mt-1">{plan.goal}</p>}
                  </div>
                  <div>
                    <div className="text-[13px] font-medium">What we watch</div>
                    <p className="text-[14px] mt-1"><b>{plan.outcome_label}</b> at the {plan.outcome_building} · {plan.outcome_price ? `£${plan.outcome_price}` : "free"} · open {plan.open_from}:00–{plan.open_to}:00 · {plan.days} days</p>
                    {plan.outcome_detail && <p className="text-[13px] text-muted-foreground mt-0.5">{plan.outcome_detail}</p>}
                  </div>
                  <div>
                    <div className="text-[13px] font-medium">{plan.cities.length > 1 ? "The places" : "The place"}</div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-2">
                      {plan.cities.map((c) => (
                        <div key={c.id} className="rounded-2xl border border-border p-4 relative">
                          {plan.cities.length > 1 && <button type="button" onClick={() => removeTown(c.id)} className="absolute top-3 right-3 text-muted-foreground hover:text-foreground" title="Remove"><X className="w-3.5 h-3.5" /></button>}
                          <div className="text-[15px] font-semibold">{c.name}</div>
                          <div className="text-[12px] text-muted-foreground">{c.character.replace(/_/g, " ")} · {c.size}</div>
                          {c.blurb && <p className="text-[13px] mt-1.5">{c.blurb}</p>}
                          <div className="flex flex-wrap gap-1 mt-2">{c.places.map((p, i) => <span key={i} className="text-[11.5px] rounded-full bg-foreground/[0.06] px-2 py-0.5">{p.name}</span>)}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div>
                    <div className="text-[13px] font-medium">Levers to try</div>
                    <div className="divide-y divide-border mt-1">
                      {plan.levers.map((lv) => (
                        <div key={lv.id} className="py-2.5 flex gap-3">
                          <div className="text-[18px] leading-none pt-0.5">{LEVER_ICON[lv.kind] || "•"}</div>
                          <div className="min-w-0 flex-1">
                            <div className="text-[14px] font-medium">{lv.label}</div>
                            {lv.detail && <p className="text-[13px] mt-0.5">{lv.detail}</p>}
                            {lv.why && <p className="text-[12.5px] text-muted-foreground mt-0.5">Why: {lv.why}</p>}
                          </div>
                          <button type="button" onClick={() => removeLever(lv.id)} className="text-muted-foreground hover:text-foreground self-start" title="Remove"><X className="w-3.5 h-3.5" /></button>
                        </div>
                      ))}
                    </div>
                  </div>
                  {missing.length > 0 && <p className="text-[13px] text-muted-foreground">Still to settle: {missing.join(" ")}</p>}
                  <div className="flex flex-wrap items-center gap-3">
                    <button type="button" onClick={() => { autoBuilt.current = true; void build(); }} disabled={building || chatBusy || !plan.cities.length || !plan.levers.length} className="lite-btn">
                      {building ? <Loader2 className="w-4 h-4 animate-spin" /> : <Building2 className="w-4 h-4" />} Build the city
                    </button>
                    <span className="text-[12.5px] text-muted-foreground">Asks each of the {n} people once about their week and each lever, then opens the town.</span>
                  </div>
                </div>
              )}
              {error && <p className="text-[13px] text-destructive">{error}</p>}
              {past.length > 0 && (
                <section>
                  <div className="text-[13px] text-muted-foreground">Cities built before</div>
                  <div className="divide-y divide-border">
                    {past.slice(0, 8).map((p) => (
                      <button key={p.id} type="button" onClick={() => void openPast(p)} className="w-full flex items-baseline gap-3 py-2.5 text-left group">
                        <span className="text-[14px] font-medium truncate flex-1 group-hover:text-primary transition-colors">{String((p.spec as any)?.title || "A city")}</span>
                        <span className="text-[12px] text-muted-foreground shrink-0 tabular-nums">{p.answer_count} people · {ago(p.created_at || null)}</span>
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
        <button type="button" onClick={() => setChatOpen(true)} className="lg:hidden fixed bottom-5 left-4 z-30 lite-btn-soft h-11 px-4 shadow-lg"><MessageCircle className="w-4 h-4" /> Plan the city</button>
      )}
    </div>
  );
}
