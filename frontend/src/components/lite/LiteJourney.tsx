"use client";

/** The Journey in the simple view (2026-10-19): where people drop off on the way to the
 *  outcome, with the complex configuration kept away from the reader.
 *
 *  - The journey is proposed by the system from the question, the evidence and the frame, then
 *    edited one step at a time: tap a step to rename it or change what it means; add, remove,
 *    move. "People in scope" comes from what the session knows, never typed.
 *  - The result is the same path, read one step at a time: how many reach each step, where most
 *    get stuck, and for the open step what stops them and what would move them.
 *  - Rules are a chat box: the reader types a change in plain English (or taps a recommended
 *    one), the system drafts the rule — who it applies to, what it moves, how far, on what
 *    evidence — reads it back in plain words, and "Add it" signs it in the reader's name. "See
 *    what changes" re-asks the same people with the rules in place and shows the growth per step.
 *  Everything else (levers one at a time, behaviour ranking, message tests, commitments) stays
 *  in the pro Lab, one "See in detail" away. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, Agent, CalibrationRule, JourneyCandidate, JourneyGrowth, JourneyStage, Probe, ProbeAnswerRow } from "@/lib/api";
import { LITE_DEFAULTS, proLinks } from "@/lib/lite";
import { cn } from "@/lib/utils";
import { ArrowDown, ArrowRight, ArrowUp, Check, ChevronLeft, Loader2, MessageCircle, Plus, RefreshCw, Sparkles, Trash2, X } from "lucide-react";
import Detail from "./Detail";
import { ago } from "@/components/lab/forms/formUtils";

type Stage = "compose" | "running" | "results";
type Draft = { rule: CalibrationRule; text: string };
const INSTRUMENT = "journey";
const stateKey = (sid: string) => `lite:journey:state:${sid}`;
const pct = (v: number | null | undefined) => (typeof v === "number" ? `${Math.round(v * 100)}%` : "—");
const people = (v: number | null | undefined) => (typeof v === "number" ? `≈${Math.round(v).toLocaleString()} people` : "");
const isAmended = (p: Probe) => Boolean((p.spec as any)?.amendments);

type Props = { sessionId: string; agents: Agent[]; onBack: () => void };

export default function LiteJourney({ sessionId, agents, onBack }: Props) {
  const n = agents.length;
  // ── the journey, proposed then edited ──
  const [stages, setStagesState] = useState<JourneyStage[]>([]);
  const [basis, setBasis] = useState<{ outcome: string; basis: string; grounded: boolean; denominator: string } | null>(null);
  const [proposing, setProposing] = useState(false);
  const [openIdx, setOpenIdx] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const proposed = useRef(false);
  const setStages = (s: JourneyStage[]) => setStagesState(s.map((x, i) => ({ ...x, key: `step${i + 1}` })));

  // ── the run ──
  const [stage, setStage] = useState<Stage>("compose");
  const [probe, setProbe] = useState<(Probe & { answers?: ProbeAnswerRow[] }) | null>(null);
  const [past, setPast] = useState<Probe[]>([]);
  const [running, setRunning] = useState(false);
  const [openStep, setOpenStep] = useState<string | null>(null);

  // ── the rules ──
  const [me, setMe] = useState<string>("");
  const [rules, setRules] = useState<CalibrationRule[]>([]);
  const [ruleInput, setRuleInput] = useState("");
  const [drafting, setDrafting] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [ruleError, setRuleError] = useState<string | null>(null);
  const [amends, setAmends] = useState<Probe[]>([]);
  const [amending, setAmending] = useState<Probe | null>(null);
  const [amendError, setAmendError] = useState<string | null>(null);

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(stateKey(sessionId));
      if (raw) { const st = JSON.parse(raw); if (Array.isArray(st.stages) && st.stages.length) { setStagesState(st.stages); proposed.current = true; } if (st.basis) setBasis(st.basis); }
    } catch { /* private mode */ }
    api.me().then((m) => setMe(m.email || "")).catch(() => null);
  }, [sessionId]);
  useEffect(() => { if (stages.length) { try { sessionStorage.setItem(stateKey(sessionId), JSON.stringify({ stages, basis })); } catch { /* private mode */ } } }, [stages, basis, sessionId]);

  const loadPast = useCallback(() => {
    api.lab.probes(sessionId).then((r) => setPast(r.probes.filter((p) => p.instrument === INSTRUMENT && !p.experiment_id && !isAmended(p)))).catch(() => null);
  }, [sessionId]);
  useEffect(() => { loadPast(); }, [loadPast]);

  const propose = useCallback(async () => {
    setProposing(true); setError(null);
    try {
      const r = await api.lab.journeySuggest(sessionId);
      setStages(r.stages);
      setBasis({ outcome: r.outcome, basis: r.basis, grounded: r.grounded, denominator: r.denominator ? `${r.denominator.people.toLocaleString()} people (${r.denominator.label || r.denominator.source})` : "" });
      setOpenIdx(null);
    } catch (e: any) { setError(e?.message || "Could not propose the journey"); } finally { setProposing(false); }
  }, [sessionId]);
  useEffect(() => { if (!proposed.current && n > 0) { proposed.current = true; void propose(); } }, [propose, n]);

  // ── editing one step at a time ──
  const update = (i: number, patch: Partial<JourneyStage>) => setStages(stages.map((s, k) => (k === i ? { ...s, ...patch } : s)));
  const move = (i: number, d: -1 | 1) => { const j = i + d; if (j < 0 || j >= stages.length) return; const next = [...stages]; [next[i], next[j]] = [next[j], next[i]]; setStages(next); setOpenIdx(j); };
  const remove = (i: number) => { setStages(stages.filter((_, k) => k !== i)); setOpenIdx(null); };
  const addAfter = (i: number) => { const next = [...stages]; next.splice(i + 1, 0, { key: "", label: "", definition: "" }); setStages(next); setOpenIdx(i + 1); };
  const problems = stages.length < 3 ? "A journey needs at least 3 steps." : stages.length > 8 ? "A journey can have at most 8 steps." : stages.some((s) => !s.label.trim()) ? "Every step needs a name." : null;

  // ── running it ──
  const run = async () => {
    if (running || problems) { if (problems) setError(problems); return; }
    setRunning(true); setError(null);
    try {
      const p = await api.lab.run(sessionId, { instrument: INSTRUMENT, mode: LITE_DEFAULTS.mode, spec: { stages: stages.map((s) => ({ key: s.key, label: s.label.trim(), definition: (s.definition || "").trim() })) } });
      setProbe(p); setStage("running"); setOpenStep(null); setAmends([]); setAmending(null); setDraft(null);
    } catch (e: any) { setError(e?.message || "Could not ask them"); } finally { setRunning(false); }
  };
  useEffect(() => {
    if (stage !== "running" || !probe) return;
    let alive = true;
    const tick = async () => {
      try { const full = await api.lab.probe(sessionId, probe.id); if (!alive) return; setProbe(full); if (full.status !== "queued" && full.status !== "running") { setStage("results"); loadPast(); } } catch { /* try again */ }
    };
    const id = setInterval(tick, 2500); void tick();
    return () => { alive = false; clearInterval(id); };
  }, [stage, probe?.id, sessionId, loadPast]); // eslint-disable-line react-hooks/exhaustive-deps
  // The barriers are coded, then movability (who could move them) is scored, in the seconds after
  // the run lands: keep refreshing until both are on the record (or two and a half minutes pass).
  const settled = (p: Probe | null) => {
    const ag: any = p?.aggregates || {};
    if (!ag.barriers_coded) return false;
    const top = [...(ag.candidates || [])].sort((x: any, y: any) => (y.stuck || 0) - (x.stuck || 0))[0];
    return !top || Boolean(top.movability);
  };
  useEffect(() => {
    if (stage !== "results" || !probe || probe.status !== "complete" || settled(probe)) return;
    let alive = true; const started = Date.now();
    const tick = async () => { if (Date.now() - started > 150_000) return; try { const full = await api.lab.probe(sessionId, probe.id); if (alive) setProbe(full); } catch { /* try again */ } };
    const id = setInterval(tick, 4000);
    return () => { alive = false; clearInterval(id); };
  }, [stage, probe?.id, probe?.status, settled(probe), sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  const openPast = async (p: Probe) => {
    setProbe(p); setDraft(null); setAmends([]); setAmending(null); setOpenStep(null);
    setStage(p.status === "queued" || p.status === "running" ? "running" : "results");
    const full = await api.lab.probe(sessionId, p.id).catch(() => null);
    if (full) setProbe(full);
  };

  // ── the rules and the amended run ──
  const loadRules = useCallback(() => api.lab.rules(sessionId).then((r) => setRules(r.rules)).catch(() => null), [sessionId]);
  const loadAmends = useCallback(() => { if (!probe) return Promise.resolve(); return api.lab.journeyAmendments(sessionId, probe.id).then((r) => setAmends(r.runs)).catch(() => null); }, [sessionId, probe?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (stage === "results" && probe) { void loadRules(); void loadAmends(); } }, [stage, probe?.id, loadRules, loadAmends]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!amending) return;
    let alive = true;
    const tick = async () => {
      try {
        const full = await api.lab.probe(sessionId, amending.id); if (!alive) return;
        if (full.status !== "queued" && full.status !== "running") {
          if (full.status === "complete" && !(full.aggregates as any)?.amended?.available) return;   // the growth is counted just after
          setAmending(null); await loadAmends();
          if (full.status !== "complete") setAmendError(full.error || `The run ${full.status === "stopped" ? "was stopped" : "did not finish"}.`);
        } else setAmending(full);
      } catch { /* try again */ }
    };
    const id = setInterval(tick, 3000); void tick();
    return () => { alive = false; clearInterval(id); };
  }, [amending?.id, sessionId, loadAmends]); // eslint-disable-line react-hooks/exhaustive-deps

  const a: any = probe?.aggregates || {};
  const candidates: JourneyCandidate[] = a.candidates || [];
  const funnel: { key: string; label: string; share: number; reached: number; people?: number | null }[] = a.funnel || [];
  const stepsOut: JourneyStage[] = a.stages || [];
  const signed = rules.filter((r) => r.status === "reviewed");
  const latestAmend = amends.find((p) => p.status === "complete" && (p.aggregates as any)?.amended?.available) || null;
  const growth: JourneyGrowth | null = ((latestAmend?.aggregates as any)?.amended as JourneyGrowth) || null;
  const growthFor = (key: string) => growth?.funnel.find((f) => f.key === key);
  const candidateFor = (key: string) => candidates.find((c) => c.from.key === key);
  const mostStuck = useMemo(() => [...candidates].sort((x, y) => y.stuck - x.stuck)[0] || null, [candidates]);
  useEffect(() => { if (stage === "results" && !openStep && mostStuck) setOpenStep(mostStuck.from.key); }, [stage, mostStuck, openStep]);
  const recommended = useMemo(() => {
    const out: string[] = [];
    const seen = new Set(signed.map((r) => r.lever.toLowerCase()));
    const add = (t?: string) => { const v = String(t || "").trim(); if (v && v.length >= 6 && !seen.has(v.toLowerCase())) { seen.add(v.toLowerCase()); out.push(v); } };
    const ranked = [...candidates].sort((x, y) => y.stuck - x.stuck);
    for (const c of ranked) { for (const lv of c.movability?.levers || []) add(lv.lever); for (const b of c.barriers || []) add(b.lever); }
    // Before movability is scored (or when it could not be), the stuck people's own removals are the recommendations.
    for (const c of ranked) for (const b of (c.barriers || []).slice(0, 3)) { const rem = b.removals?.[0]; add(typeof rem === "string" ? rem : rem?.value); }
    return out.slice(0, 4);
  }, [candidates, signed]);

  const draftRule = async (lever: string) => {
    const t = lever.trim();
    if (!t || drafting || !probe) return;
    setDrafting(true); setRuleError(null); setRuleInput("");
    try {
      const r = await api.lab.draftRule(sessionId, { lever: t, journey_probe_id: probe.id, candidate_id: mostStuck?.id, mode: "pro" });
      setDraft({ rule: r, text: t });
    } catch (e: any) { setRuleError(e?.message || "Could not write that as a rule"); } finally { setDrafting(false); }
  };
  const addRule = async () => {
    if (!draft) return;
    try { await api.lab.reviewRule(sessionId, draft.rule.id, me || "the reader", true); setDraft(null); await loadRules(); }
    catch (e: any) { setRuleError(e?.message || "Could not add the rule"); }
  };
  const dropDraft = async () => { if (!draft) return; const id = draft.rule.id; setDraft(null); api.lab.deleteRule(sessionId, id).catch(() => null); };
  const removeRule = async (r: CalibrationRule) => { await api.lab.deleteRule(sessionId, r.id).catch(() => null); await loadRules(); };
  const seeWhatChanges = async () => {
    if (!probe || amending || !signed.length) return;
    setAmendError(null);
    try { const p = await api.lab.amendJourney(sessionId, probe.id, {}); setAmending(p); }
    catch (e: any) { setAmendError(e?.message || "Could not start the run"); }
  };
  const appliesWords = (r: { applies_to: Record<string, string[]> }) => {
    const parts = Object.entries(r.applies_to || {}).filter(([, v]) => Array.isArray(v) && v.length).map(([k, v]) => `${k.replace(/_/g, " ")}: ${v.join(", ")}`);
    return parts.length ? parts.join("; ") : "everyone";
  };
  const movesWords = (r: { deltas: Record<string, number> }) => Object.entries(r.deltas || {}).map(([k, v]) => `${k.split(".").pop()?.replace(/_/g, " ")} ${v >= 0 ? "+" : ""}${v}`).join(", ");

  // ── no people yet ──
  if (n === 0) {
    return (
      <div className="max-w-xl mx-auto pt-16 px-6 animate-rise text-center">
        <div className="lite-card p-8">
          <h1 className="text-[24px] font-semibold tracking-tight">Make the people first</h1>
          <p className="lite-lead mt-2">The journey asks the people in this question how far they get. Once they exist, come back here.</p>
          <button type="button" onClick={onBack} className="lite-btn mt-6">Back</button>
        </div>
      </div>
    );
  }

  // ── running ──
  if (stage === "running" && probe) {
    const answered = probe.answer_count || 0; const total = probe.agent_count || n;
    return (
      <div className="max-w-xl mx-auto pt-16 px-6 animate-rise">
        <div className="lite-card p-8 text-center">
          <div className="lite-dots inline-flex gap-1.5"><span /><span /><span /></div>
          <h1 className="text-[24px] font-semibold tracking-tight mt-4">Asking {total} people how far they get</h1>
          <p className="lite-lead mt-2">Each one says the furthest step they have reached, whether the next one will happen, what stops it and what would move them.</p>
          <div className="mt-6 h-2 rounded-full bg-foreground/[0.06] overflow-hidden"><div className="h-full bg-primary transition-all duration-500" style={{ width: `${Math.max(3, Math.round((answered / Math.max(1, total)) * 100))}%` }} /></div>
          <p className="text-[13px] text-muted-foreground mt-2 tabular-nums">{answered} of {total} answered</p>
          <button type="button" onClick={() => api.lab.stop(sessionId, probe.id).catch(() => null)} className="lite-btn-soft lite-btn-sm mt-6">Stop here</button>
        </div>
      </div>
    );
  }

  // ── the rules chat (left column after a run) ──
  const rulesChat = (
    <div className="h-full flex flex-col min-h-0">
      <div className="px-5 pt-4 pb-2 flex items-center gap-2 shrink-0">
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-semibold">What would you change?</div>
          <div className="text-[12px] text-muted-foreground mt-0.5">Say it in plain words. I'll turn it into a rule and ask the people again with it in place.</div>
        </div>
        <button type="button" onClick={() => setChatOpen(false)} className="lg:hidden w-9 h-9 rounded-full inline-flex items-center justify-center text-muted-foreground hover:bg-foreground/5"><X className="w-4 h-4" /></button>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto px-5 pb-3 space-y-4">
        {signed.length > 0 && (
          <div className="space-y-2">
            <div className="text-[12px] text-muted-foreground">Rules in place</div>
            {signed.map((r) => (
              <div key={r.id} className="rounded-2xl bg-foreground/[0.04] px-4 py-3 text-[13.5px]">
                <div className="flex items-start gap-2">
                  <Check className="w-4 h-4 text-primary mt-0.5 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <div className="font-medium">{r.lever}</div>
                    <div className="text-[12px] text-muted-foreground mt-0.5">{r.basis_class === "assumption" ? "An assumption — no evidence behind it" : `Backed by ${r.evidence.length} piece${r.evidence.length === 1 ? "" : "s"} of evidence`} · applies to {appliesWords(r)}</div>
                  </div>
                  <button type="button" onClick={() => void removeRule(r)} title="Remove" className="text-muted-foreground/50 hover:text-red-600"><Trash2 className="w-3.5 h-3.5" /></button>
                </div>
              </div>
            ))}
          </div>
        )}
        {draft && (
          <div className="rounded-2xl bg-primary/5 ring-1 ring-primary/30 px-4 py-3 text-[13.5px] space-y-2">
            <div className="inline-flex items-center gap-1.5 text-[12px] text-primary"><Sparkles className="w-3.5 h-3.5" /> Here is that as a rule</div>
            <div className="font-medium">{draft.rule.lever}</div>
            {draft.rule.description && <p className="text-muted-foreground">{draft.rule.description}</p>}
            <p className="text-[12px] text-muted-foreground">Applies to {appliesWords(draft.rule)}{movesWords(draft.rule) ? <> · moves {movesWords(draft.rule)}</> : null}. {draft.rule.basis_class === "assumption" ? "Nothing on file backs it, so it counts as an assumption." : `Backed by ${draft.rule.evidence.length} piece${draft.rule.evidence.length === 1 ? "" : "s"} of evidence on file.`}</p>
            <div className="flex gap-1.5">
              <button type="button" onClick={() => void addRule()} className="lite-btn lite-btn-sm">Add it</button>
              <button type="button" onClick={() => void dropDraft()} className="lite-btn-soft lite-btn-sm">Not this</button>
            </div>
          </div>
        )}
        {!draft && recommended.length > 0 && (
          <div className="space-y-2">
            <div className="text-[12px] text-muted-foreground">Recommended, from what the people said would move them</div>
            <div className="flex flex-wrap gap-1.5">{recommended.map((lv) => <button key={lv} type="button" onClick={() => void draftRule(lv)} disabled={drafting} className="lite-pill-quiet text-left">{lv}</button>)}</div>
          </div>
        )}
        {drafting && <p className="text-[13px] text-muted-foreground inline-flex items-center gap-2"><span className="lite-dots flex gap-1"><span /><span /><span /></span> writing the rule</p>}
        {ruleError && <p className="text-[12.5px] text-red-700">{ruleError}</p>}
        {signed.length > 0 && (
          <div className="pt-1">
            <button type="button" onClick={() => void seeWhatChanges()} disabled={Boolean(amending)} className="lite-btn lite-btn-sm w-full justify-center">
              {amending ? <><Loader2 className="w-4 h-4 animate-spin" /> Asking again · {amending.answer_count || 0} of {amending.agent_count || n}</> : <><RefreshCw className="w-4 h-4" /> See what changes with {signed.length === 1 ? "this rule" : `these ${signed.length} rules`}</>}
            </button>
            {amendError && <p className="text-[12.5px] text-red-700 mt-2">{amendError}</p>}
          </div>
        )}
      </div>
      <div className="p-4 shrink-0">
        <div className="lite-field flex items-end gap-2 py-2 pr-2">
          <textarea value={ruleInput} onChange={(e) => setRuleInput(e.target.value)} rows={Math.min(4, Math.max(1, ruleInput.split("\n").length))}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void draftRule(ruleInput); } }}
            placeholder="e.g. A dock within two minutes of every station" className="lite-input flex-1 text-[15px] leading-relaxed" />
          <button type="button" onClick={() => void draftRule(ruleInput)} disabled={!ruleInput.trim() || drafting} className="w-9 h-9 rounded-full bg-foreground text-background disabled:opacity-30 inline-flex items-center justify-center shrink-0"><ArrowUp className="w-4 h-4" /></button>
        </div>
      </div>
    </div>
  );

  // ── the explainer (left column before a run) ──
  const setupChat = (
    <div className="h-full flex flex-col min-h-0">
      <div className="px-5 pt-4 pb-2 flex items-center gap-2 shrink-0">
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-semibold">The journey</div>
          <div className="text-[12px] text-muted-foreground mt-0.5">Proposed from what this session knows. Tap a step to change it.</div>
        </div>
        <button type="button" onClick={() => setChatOpen(false)} className="lg:hidden w-9 h-9 rounded-full inline-flex items-center justify-center text-muted-foreground hover:bg-foreground/5"><X className="w-4 h-4" /></button>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto px-5 pb-4 space-y-4 text-[14px] leading-relaxed">
        {proposing && <p className="text-[13px] text-muted-foreground inline-flex items-center gap-2"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Reading the question, the evidence and the people to propose the steps…</p>}
        {basis && !proposing && (
          <>
            <p>I've laid out the steps a person goes through on the way to <span className="font-medium">{basis.outcome || "the outcome"}</span>.{basis.basis ? ` ${basis.basis}` : ""}</p>
            {!basis.grounded && <p className="text-muted-foreground text-[13px]">Nothing has been gathered for this question yet, so this comes from the question alone.</p>}
            <p className="text-[13px] text-muted-foreground">{basis.denominator ? `People in scope: ${basis.denominator}, read from the published figures on file.` : "No published figure for the people in scope is on file, so the result will be in shares, not headcounts."}</p>
            <p className="text-[13px] text-muted-foreground">Each of the {n} people will say the furthest step they have reached, whether the next will happen, and what stops it.</p>
            <div className="flex flex-wrap gap-1.5">
              <button type="button" onClick={() => void propose()} disabled={proposing} className="lite-pill-quiet"><RefreshCw className="w-3 h-3" /> Propose again</button>
              <button type="button" onClick={() => void run()} disabled={running || Boolean(problems)} className="lite-pill-quiet">Looks right — ask them</button>
            </div>
          </>
        )}
        {past.length > 0 && (
          <section>
            <div className="text-[12px] text-muted-foreground">Earlier journeys</div>
            <div className="divide-y divide-border">
              {past.slice(0, 5).map((p) => (
                <button key={p.id} type="button" onClick={() => void openPast(p)} className="w-full flex items-baseline gap-3 py-2 text-left group">
                  <span className="text-[13px] font-medium truncate flex-1 group-hover:text-primary transition-colors">{String(((p.spec as any)?.stages || []).slice(-1)[0]?.label || "A journey")}</span>
                  <span className="text-[11px] text-muted-foreground shrink-0 tabular-nums">{p.answer_count} answered · {ago(p.created_at || null)}</span>
                </button>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );

  // ── results: the path, one step at a time ──
  const results = probe && stage === "results" ? (
    <div className="animate-rise space-y-6 pb-28">
      <div className="flex items-center gap-3 flex-wrap">
        <button type="button" onClick={() => setStage("compose")} className="lite-pill-quiet"><ChevronLeft className="w-3.5 h-3.5" /> Change the steps</button>
        <div className="min-w-0 flex-1">
          <h1 className="text-[22px] font-semibold tracking-tight">Where people drop off</h1>
          <p className="text-[12.5px] text-muted-foreground">{probe.answer_count} of {probe.agent_count} answered{probe.created_at ? ` · ${ago(probe.created_at)}` : ""}{probe.status === "complete" && !settled(probe) ? <span className="inline-flex items-center gap-1 ml-2"><Loader2 className="w-3 h-3 animate-spin" /> {a.barriers_coded ? "working out what could move them…" : "grouping what stops them…"}</span> : null}{growth ? <span className="ml-2 text-emerald-700">· with {growth.rules.length} rule{growth.rules.length === 1 ? "" : "s"} in place: {pct(growth.end.then)} → {pct(growth.end.now)} reach the end</span> : null}</p>
        </div>
      </div>
      {probe.status !== "complete" || !funnel.length ? (
        <div className="lite-card p-6"><p className="lite-lead">{probe.error || (probe.status === "stopped" ? "Stopped before enough people answered." : "Nobody could answer this one.")}</p></div>
      ) : (
        <Detail href={proLinks.lab(sessionId)}>
          <ol className="space-y-2">
            {stepsOut.map((st, k) => {
              const f = funnel.find((x) => x.key === st.key); const c = candidateFor(st.key); const g = growthFor(st.key);
              const isOpen = openStep === st.key; const last = k === stepsOut.length - 1;
              return (
                <li key={st.key}>
                  <button type="button" onClick={() => setOpenStep(isOpen ? null : st.key)} className={cn("w-full text-left lite-card shadow-none px-4 sm:px-5 py-3.5 transition-shadow", isOpen && "ring-2 ring-primary/40")}>
                    <div className="flex items-center gap-3">
                      <span className={cn("w-7 h-7 rounded-full inline-flex items-center justify-center text-[12px] font-semibold shrink-0", c && c.stuck > 0 ? "bg-amber-500/15 text-amber-700" : "bg-primary/10 text-primary")}>{k + 1}</span>
                      <div className="min-w-0 flex-1">
                        <div className="text-[15px] font-medium truncate">{st.label}</div>
                        <div className="text-[12px] text-muted-foreground">{f ? <>{pct(f.share)} get here{f.people != null ? ` · ${people(f.people)}` : ""}</> : "—"}{g ? <span className={cn("ml-2", g.lift > 0 ? "text-emerald-700" : g.lift < 0 ? "text-red-700" : "")}>→ {pct(g.now)} with the rules</span> : null}</div>
                      </div>
                      <div className="w-28 sm:w-40 h-2 rounded-full bg-foreground/[0.06] overflow-hidden relative shrink-0">
                        <div className="h-full bg-primary/70 rounded-full" style={{ width: `${Math.round((f?.share || 0) * 100)}%` }} />
                        {g && g.now > (f?.share || 0) && <div className="absolute inset-y-0 bg-emerald-500/70 rounded-r-full" style={{ left: `${Math.round((f?.share || 0) * 100)}%`, width: `${Math.round((g.now - (f?.share || 0)) * 100)}%` }} />}
                      </div>
                    </div>
                    {!last && c && c.stuck > 0 && (
                      <div className="mt-2 ml-10 text-[12.5px] text-amber-700">{c.stuck} of {c.n} get stuck here{c.stuck_people != null ? ` · ${people(c.stuck_people)}` : ""} · {pct(c.conversion)} go on to “{c.to.label}”</div>
                    )}
                  </button>
                  {isOpen && (
                    <div className="mx-2 sm:mx-4 mt-1 rounded-2xl bg-foreground/[0.03] px-4 sm:px-5 py-4 text-[13.5px] space-y-3 animate-rise">
                      {st.definition && <p className="text-muted-foreground">{st.definition}</p>}
                      {!last && c && c.stuck > 0 ? (
                        <>
                          <div>
                            <div className="text-[12px] text-muted-foreground mb-1.5">What stops them{!a.barriers_coded ? " (still grouping…)" : ""}</div>
                            <ol className="space-y-1.5">
                              {(c.barriers || []).slice(0, 3).map((b, i) => {
                                const rem = b.removals?.[0]; const remText = typeof rem === "string" ? rem : rem?.value;
                                return (
                                  <li key={i} className="flex items-start gap-2">
                                    <span className="text-[12px] text-muted-foreground tabular-nums w-4 pt-0.5">{i + 1}.</span>
                                    <div className="min-w-0 flex-1">
                                      <div className="font-medium">{b.theme} <span className="text-[12px] text-muted-foreground font-normal">· {b.count} of them</span></div>
                                      {remText && <div className="text-[12.5px] text-muted-foreground">Would move them: {remText}</div>}
                                    </div>
                                  </li>
                                );
                              })}
                              {(c.barriers || []).length === 0 && <li className="text-muted-foreground">Nothing named yet.</li>}
                            </ol>
                          </div>
                        </>
                      ) : last ? (
                        <p className="text-muted-foreground">{pct(f?.share)} of the people reach the end of the journey{growth ? `; with the rules in place, ${pct(growth.end.now)}.` : "."}</p>
                      ) : (
                        <p className="text-muted-foreground">Nobody gets stuck here.</p>
                      )}
                    </div>
                  )}
                  {!last && <div className="flex justify-center py-0.5"><ArrowDown className="w-3.5 h-3.5 text-muted-foreground/40" /></div>}
                </li>
              );
            })}
          </ol>
        </Detail>
      )}
      {growth && (
        <div className="lite-card p-5 space-y-2">
          <div className="text-[13px] text-muted-foreground">With the rules in place</div>
          <div className="flex flex-wrap gap-1.5">{growth.rules.map((r) => <span key={r.rule_id} className="lite-pill-quiet cursor-default">{r.lever}{r.basis_class === "assumption" ? " · assumed" : ""}</span>)}</div>
          <p className="text-[14px] leading-relaxed">{growth.sentence}</p>
          {growth.why && growth.why.through?.length > 0 && <p className="text-[13px] text-muted-foreground">In their words: “{growth.why.through[0].quote}” — {growth.why.through[0].who || "one of them"}</p>}
        </div>
      )}
    </div>
  ) : null;

  // ── compose: the steps, one at a time ──
  const compose = (
    <div className="animate-rise space-y-6 pb-28">
      <div>
        <h1 className="text-[26px] sm:text-[30px] font-semibold tracking-tight">The steps to {basis?.outcome ? <span className="text-primary">{basis.outcome}</span> : "the outcome"}</h1>
        <p className="lite-lead mt-2">Tap a step to change it. The last step is the outcome itself.</p>
      </div>
      {proposing && stages.length === 0 && <div className="lite-card p-6 text-[14px] text-muted-foreground inline-flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Proposing the journey…</div>}
      <ol className="space-y-2">
        {stages.map((s, i) => {
          const isOpen = openIdx === i;
          return (
            <li key={`${s.key}-${i}`}>
              {!isOpen ? (
                <button type="button" onClick={() => setOpenIdx(i)} className="w-full text-left lite-card shadow-none px-4 sm:px-5 py-3.5 flex items-center gap-3">
                  <span className="w-7 h-7 rounded-full bg-primary/10 text-primary inline-flex items-center justify-center text-[12px] font-semibold shrink-0">{i + 1}</span>
                  <div className="min-w-0 flex-1"><div className="text-[15px] font-medium truncate">{s.label || <span className="text-muted-foreground">Name this step</span>}</div>{s.definition && <div className="text-[12px] text-muted-foreground truncate">{s.definition}</div>}</div>
                </button>
              ) : (
                <div className="lite-card px-4 sm:px-5 py-4 ring-2 ring-primary/40 space-y-3 animate-rise">
                  <div className="flex items-center gap-3">
                    <span className="w-7 h-7 rounded-full bg-primary text-background inline-flex items-center justify-center text-[12px] font-semibold shrink-0">{i + 1}</span>
                    <input autoFocus value={s.label} onChange={(e) => update(i, { label: e.target.value })} placeholder="The step, as they would say it" className="lite-input text-[16px] font-medium flex-1" />
                  </div>
                  <input value={s.definition || ""} onChange={(e) => update(i, { definition: e.target.value })} placeholder="What it means, in one line (optional)" className="lite-field text-[14px] py-2 rounded-xl ml-10 w-[calc(100%-2.5rem)]" />
                  <div className="flex items-center gap-1.5 flex-wrap ml-10">
                    <button type="button" onClick={() => move(i, -1)} disabled={i === 0} className="lite-pill-quiet disabled:opacity-40"><ArrowUp className="w-3 h-3" /> Earlier</button>
                    <button type="button" onClick={() => move(i, 1)} disabled={i === stages.length - 1} className="lite-pill-quiet disabled:opacity-40"><ArrowDown className="w-3 h-3" /> Later</button>
                    <button type="button" onClick={() => addAfter(i)} className="lite-pill-quiet"><Plus className="w-3 h-3" /> Add a step after</button>
                    <button type="button" onClick={() => remove(i)} className="lite-pill-quiet text-red-700"><Trash2 className="w-3 h-3" /> Remove</button>
                    <button type="button" onClick={() => setOpenIdx(null)} className="lite-pill-quiet ml-auto"><Check className="w-3 h-3" /> Done</button>
                  </div>
                </div>
              )}
              {i < stages.length - 1 && <div className="flex justify-center py-0.5"><ArrowDown className="w-3.5 h-3.5 text-muted-foreground/40" /></div>}
            </li>
          );
        })}
      </ol>
      {stages.length > 0 && stages.length < 8 && openIdx === null && (
        <button type="button" onClick={() => addAfter(stages.length - 1)} className="lite-btn-soft lite-btn-sm"><Plus className="w-4 h-4" /> Add a step at the end</button>
      )}
    </div>
  );

  const left = stage === "results" ? rulesChat : setupChat;
  return (
    <div className="flex-1 min-h-0 relative">
      <div className="h-full grid grid-cols-1 lg:grid-cols-[minmax(340px,420px)_minmax(0,1fr)]">
        <div className="hidden lg:block border-r border-border min-h-0">{left}</div>
        <div className="min-h-0 overflow-y-auto">
          <div className="max-w-[880px] mx-auto px-4 sm:px-8 pt-6">
            <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-[13px] text-muted-foreground hover:text-foreground mb-6"><ChevronLeft className="w-3.5 h-3.5" /> Back</button>
            {error && (
              <div className="mb-4 flex items-center gap-3 rounded-2xl bg-red-500/10 px-4 py-2.5 text-[13px] text-red-700"><span className="flex-1">{error}</span><button type="button" onClick={() => setError(null)}><X className="w-4 h-4" /></button></div>
            )}
            {stage === "results" ? results : compose}
          </div>
        </div>
      </div>
      {stage === "compose" && stages.length >= 3 && (
        <div className="fixed bottom-5 left-1/2 -translate-x-1/2 lg:left-[calc(50%+210px)] z-30 max-w-[calc(100vw-2rem)]">
          <div className="lite-float px-2 py-2 flex items-center gap-1.5 animate-rise">
            <span className="hidden sm:inline text-[13px] text-muted-foreground pl-3">{stages.length} steps</span>
            <button type="button" onClick={() => void propose()} disabled={proposing} className="lite-btn-soft h-11 px-4">{proposing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />} Propose again</button>
            <button type="button" onClick={() => void run()} disabled={running || Boolean(problems)} className="lite-btn h-11 px-5">{running ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowRight className="w-4 h-4" />} Ask the {n} people</button>
          </div>
        </div>
      )}
      {chatOpen && (
        <div className="lg:hidden fixed inset-0 z-40">
          <div className="absolute inset-0 bg-black/30" onClick={() => setChatOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-[420px] max-w-[94vw] bg-background shadow-2xl">{left}</div>
        </div>
      )}
      {!chatOpen && (
        <button type="button" onClick={() => setChatOpen(true)} className="lg:hidden fixed bottom-5 left-4 z-30 lite-btn-soft h-11 px-4 shadow-lg"><MessageCircle className="w-4 h-4" /> {stage === "results" ? "Change something" : "About the journey"}</button>
      )}
    </div>
  );
}
