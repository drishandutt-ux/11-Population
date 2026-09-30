"use client";

/** The Journey tool's own results page (brief L7-01): the funnel — share reaching each step —
 *  then the candidate outcomes ranked: the step where twins drop off, how many get through, how
 *  many are stuck, the barriers at that step and who raised them. The same "Read by" picker as
 *  the Verdict and Barriers pages: the funnel and the ranking are recounted inside the cut from
 *  the stored answers, so no call is needed. */

import { useEffect, useMemo, useState } from "react";
import { BookOpen, ListOrdered, Lock, MessageSquare, Play, Sparkles } from "lucide-react";
import { DrewOn, pct } from "../Charts";
import { segmentLabel } from "../filters";
import RuleBook from "../RuleBook";
import ConfidenceBadge from "@/components/ConfidenceBadge";
import { api, CalibrationRule, Commitment, Experiment, LeverRefusal, LeverShift, MessagingResult, TargetingMenu, TargetingResult, TargetingRow } from "@/lib/api";
import { InstrumentPageProps } from "./types";

/** The 409 body of a refused lever run, from the API client's error text. */
function refusalOf(e: any): LeverRefusal | null {
  const text = String(e?.message || "");
  if (!/\(409\)/.test(text) || !/"refused"\s*:\s*true/.test(text)) return null;
  const m = text.match(/\{[\s\S]*\}/);
  if (m) {
    try { const j = JSON.parse(m[0]); const d = j.detail || j; if (d?.refused) return d as LeverRefusal; } catch { /* the client trims long bodies; read the fields below */ }
  }
  const field = (k: string) => (text.match(new RegExp(`"${k}"\\s*:\\s*"([^"]*)`)) || [])[1] || "";
  const reason = field("reason");
  return { refused: true, lever: field("lever"), reason: reason + (/"reason"\s*:\s*"[^"]*"/.test(text) ? "" : "…"), drafts: [], missing: !/"drafts"\s*:\s*\["/.test(text) };
}

const SPLIT_ORDER = ["deprivation", "stance", "age_band", "segment", "region", "income_band", "gender", "education", "humanity_band"];
const rankOf = (v: string) => { const m = v.match(/^[QD](\d{1,2})/i); return m ? parseInt(m[1], 10) : 99; };
const STUCK = ["unlikely", "no"];

type Stage = { key: string; label: string; definition?: string };
type Row = { agent_id: string; name: string; role: string; answer: Record<string, any>; reasoning?: string; segments?: Record<string, string> };
type Twin = { agent_id: string; name: string; role: string; answering_for: string; barrier: string; removal: string; weight: number; reasoning: string; deprivation?: string; used_units?: any[] };
type Barrier = { theme: string; count: number; weight_mean: number; removals: string[]; twins: Twin[]; evidence: any[]; reach?: string; lever?: string; actor?: string; reach_reason?: string };
type Mv = { scored: boolean; movable_count: number; movable_share: number; system_count: number; system_share: number; structural_count: number; structural_share: number; unscored_count: number; unscored_share: number; movable_people?: number | null; levers: { theme: string; lever: string; actor: string; count: number }[] };
const REACH_LABEL: Record<string, string> = { partner: "a partner could fix it", system: "needs the whole system", structural: "nobody can fix it soon", none: "no removal named", unscored: "not scored" };
const REACH_COLOR: Record<string, string> = { partner: "bg-emerald-400/70", system: "bg-amber-400/60", structural: "bg-zinc-500/60", none: "bg-zinc-500/60", unscored: "bg-zinc-700/50" };
function movabilityOf(stuck: number, barriers: Barrier[]): Mv {
  const counts: Record<string, number> = { partner: 0, system: 0, structural: 0, none: 0, unscored: 0 };
  const levers: Mv["levers"] = [];
  barriers.forEach((b) => { const r = b.reach && b.reach in counts ? b.reach : "unscored"; counts[r] += b.count; if (r === "partner") levers.push({ theme: b.theme, lever: b.lever || "", actor: b.actor || "", count: b.count }); });
  counts.none += Math.max(0, stuck - Object.values(counts).reduce((a, c) => a + c, 0));
  const sh = (k: string) => (stuck ? counts[k] / stuck : 0);
  return { scored: stuck > 0 && counts.unscored < stuck, movable_count: counts.partner, movable_share: sh("partner"), system_count: counts.system, system_share: sh("system"),
    structural_count: counts.structural + counts.none, structural_share: sh("structural") + sh("none"), unscored_count: counts.unscored, unscored_share: sh("unscored"), levers: levers.sort((a, b) => b.count - a.count) };
}
type Candidate = { id: string; step: number; from: Stage; to: Stage; n: number; through: number; stuck: number; conversion: number; low: number; high: number; barriers: Barrier[]; equity?: any; confidence?: { score: number; drivers: string[] };
  at_risk_people?: number | null; stuck_people?: number | null; stuck_low?: number | null; stuck_high?: number | null; basis?: string; movability?: Mv };
const people = (n: number | null | undefined) => (n == null ? "" : n.toLocaleString());
const BASIS_LABEL: Record<string, string> = { official_statistic: "official statistic", client_supplied: "client supplied", client_anchored: "scaled from a client figure" };

// Wilson interval, the same as the backend's, so a cut reads with its own uncertainty.
function wilson(k: number, n: number) {
  if (!n) return { share: 0, low: 0, high: 0 };
  const z = 1.96, p = k / n, d = 1 + (z * z) / n;
  const c = (p + (z * z) / (2 * n)) / d, h = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / d;
  return { share: p, low: Math.max(0, c - h), high: Math.min(1, c + h) };
}

function compute(rows: Row[], stages: Stage[], stored: Candidate[]) {
  const idx: Record<string, number> = {};
  stages.forEach((s, i) => { idx[s.key] = i; });
  const at = (r: Row) => (r.answer.reached in idx ? idx[r.answer.reached] : -1);
  const placed = rows.filter((r) => at(r) >= 0);
  const n = placed.length;
  const funnel = stages.map((s, k) => {
    const reached = placed.filter((r) => at(r) >= k).length;
    return { ...s, reached, atExactly: placed.filter((r) => at(r) === k).length, ...wilson(reached, n) };
  });
  const storedBarrier = (id: string, theme: string) => stored.find((c) => c.id === id)?.barriers.find((b) => b.theme === theme);
  const evidenceFor = (id: string, theme: string) => storedBarrier(id, theme)?.evidence || [];
  const transitions: Candidate[] = [];
  for (let k = 0; k < stages.length - 1; k++) {
    const atRisk = placed.filter((r) => at(r) >= k);
    const through = atRisk.filter((r) => at(r) > k || (at(r) === k && r.answer.progress === "yes"));
    const stuck = atRisk.filter((r) => at(r) === k && STUCK.includes(r.answer.progress));
    const groups: Record<string, Row[]> = {};
    stuck.forEach((r) => { const key = String(r.answer.barrier__theme || r.answer.barrier || "").trim(); if (key) (groups[key] ||= []).push(r); });
    const id = `${stages[k].key}->${stages[k + 1].key}`;
    const barriers: Barrier[] = Object.entries(groups).map(([theme, rs]) => {
      const twins: Twin[] = rs.map((r) => ({ agent_id: r.agent_id, name: r.name, role: r.role, answering_for: r.answer.answering_for || "", barrier: r.answer.barrier || "",
        removal: r.answer.removal || "", weight: Number(r.answer.weight || 0), reasoning: r.reasoning || r.answer.reasoning || "", deprivation: r.segments?.deprivation, used_units: r.answer.used_units }))
        .sort((x, y) => y.weight - x.weight);
      const removals = [...new Set(rs.map((r) => String(r.answer.removal__theme || r.answer.removal || "").trim()).filter(Boolean))].slice(0, 4);
      const sb = storedBarrier(id, theme);
      return { theme, count: rs.length, weight_mean: twins.reduce((s, t) => s + t.weight, 0) / (twins.length || 1), removals, twins, evidence: evidenceFor(id, theme),
        reach: sb?.reach, lever: sb?.lever, actor: sb?.actor, reach_reason: sb?.reach_reason };
    }).sort((x, y) => y.count - x.count || y.weight_mean - x.weight_mean);
    transitions.push({ id, step: k + 1, from: stages[k], to: stages[k + 1], n: atRisk.length, through: through.length, stuck: stuck.length, ...wilson(through.length, atRisk.length), conversion: atRisk.length ? through.length / atRisk.length : 0, barriers, movability: movabilityOf(stuck.length, barriers) });
  }
  // Ranked by the movable gap first (L7-03), then by who is stuck, then the gap.
  const mv = (t: Candidate) => (t.movability?.scored ? t.movability.movable_count : -1);
  const candidates = transitions.filter((t) => t.stuck > 0).sort((x, y) => mv(y) - mv(x) || y.stuck - x.stuck || x.conversion - y.conversion || x.step - y.step);
  return { n, funnel, transitions, candidates, completed: wilson(placed.filter((r) => at(r) === stages.length - 1).length, n) };
}

export default function JourneyPage({ probe, dynamicDials = [], agentsById = {} }: InstrumentPageProps) {
  const a: any = probe.aggregates;
  const answers = (probe.answers || []) as unknown as Row[];
  const stages: Stage[] = a?.stages || [];
  const [segKey, setSegKey] = useState("");
  const [segValue, setSegValue] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [openBarrier, setOpenBarrier] = useState<string | null>(null);
  // Lever simulation (brief L7-04), gated on the rule book (brief L4-02).
  const sessionId = probe.session_id;
  const [rules, setRules] = useState<CalibrationRule[]>([]);
  const [runs, setRuns] = useState<Experiment[]>([]);
  const [leverText, setLeverText] = useState<Record<string, string>>({});
  const [refusal, setRefusal] = useState<Record<string, LeverRefusal | string>>({});
  const [ruleBook, setRuleBook] = useState<{ lever?: string; candidate_id?: string; draft?: CalibrationRule } | null>(null);
  const [starting, setStarting] = useState<string | null>(null);
  const [drafting, setDrafting] = useState<string | null>(null);
  // The system drafts the rule for this lever (brief L4-02): the human reads and signs it in the rule book.
  const draftRule = async (candidateId: string) => {
    const lever = (leverText[candidateId] || "").trim();
    if (!lever) return;
    setDrafting(candidateId);
    setRefusal((r) => ({ ...r, [candidateId]: "" }));
    try {
      const d = await api.lab.draftRule(sessionId, { lever, journey_probe_id: probe.id, candidate_id: candidateId });
      setRuleBook({ lever, candidate_id: candidateId, draft: d });
    } catch (e: any) {
      setRefusal((r) => ({ ...r, [candidateId]: e?.message || "The draft could not be written" }));
    } finally { setDrafting(null); }
  };
  const loadRuns = () => api.lab.leverRuns(sessionId).then((r) => setRuns(r.runs.filter((x) => x.spec?.lever_run?.journey_probe_id === probe.id))).catch(() => {});
  // Behaviour targeting (brief L7-05): which behaviour to change, as a counted ranking.
  const [menu, setMenu] = useState<TargetingMenu | null>(null);
  const [tgRuns, setTgRuns] = useState<Experiment[]>([]);
  const [tgOpen, setTgOpen] = useState<Record<string, boolean>>({});
  const [tgSel, setTgSel] = useState<Record<string, string[]>>({});
  const [tgPoints, setTgPoints] = useState<Record<string, number>>({});
  const [tgStarting, setTgStarting] = useState<string | null>(null);
  const [tgError, setTgError] = useState<Record<string, string>>({});
  const loadTg = () => api.lab.targetingRuns(sessionId).then((r) => setTgRuns(r.runs.filter((x) => x.spec?.targeting?.journey_probe_id === probe.id))).catch(() => {});
  const selFor = (cid: string) => tgSel[cid] ?? (menu?.behaviours || []).map((b) => b.key);
  const rankBehaviours = async (cid: string) => {
    setTgStarting(cid); setTgError((e) => ({ ...e, [cid]: "" }));
    try {
      await api.lab.runTargeting(sessionId, { journey_probe_id: probe.id, candidate_id: cid, behaviours: selFor(cid), points: tgPoints[cid] ?? menu?.points_default ?? 2 });
      await loadTg();
    } catch (e: any) { setTgError((er) => ({ ...er, [cid]: e?.message || "Could not start the run" })); } finally { setTgStarting(null); }
  };
  // Message testing (brief L7-06): framings read by the twins at risk here; the shift per message and by cohort, backfire beside the winner.
  const [mgRuns, setMgRuns] = useState<Experiment[]>([]);
  const [mgOpen, setMgOpen] = useState<Record<string, boolean>>({});
  const [mgMsgs, setMgMsgs] = useState<Record<string, { label: string; text: string }[]>>({});
  const [mgStarting, setMgStarting] = useState<string | null>(null);
  const [mgError, setMgError] = useState<Record<string, string>>({});
  const MAX_MESSAGES = 6;
  const loadMg = () => api.lab.messagingRuns(sessionId).then((r) => setMgRuns(r.runs.filter((x) => x.spec?.messaging?.journey_probe_id === probe.id))).catch(() => {});
  const msgsFor = (cid: string) => mgMsgs[cid] ?? [{ label: "", text: "" }, { label: "", text: "" }];
  const setMsg = (cid: string, i: number, patch: Partial<{ label: string; text: string }>) =>
    setMgMsgs((m) => ({ ...m, [cid]: msgsFor(cid).map((x, k) => (k === i ? { ...x, ...patch } : x)) }));
  const testMessages = async (cid: string) => {
    const messages = msgsFor(cid).filter((m) => m.text.trim()).map((m) => ({ label: m.label.trim() || undefined, text: m.text.trim() }));
    if (!messages.length) { setMgError((e) => ({ ...e, [cid]: "Write at least one message." })); return; }
    setMgStarting(cid); setMgError((e) => ({ ...e, [cid]: "" }));
    try {
      await api.lab.runMessaging(sessionId, { journey_probe_id: probe.id, candidate_id: cid, messages });
      await loadMg();
    } catch (e: any) { setMgError((er) => ({ ...er, [cid]: e?.message || "Could not start the run" })); } finally { setMgStarting(null); }
  };
  // Commitments (brief L7-08): freeze the modelled baseline for a chosen candidate; observed results entered later against it.
  const [commits, setCommits] = useState<Commitment[]>([]);
  const [cmOpen, setCmOpen] = useState<Record<string, boolean>>({});
  const [cmForm, setCmForm] = useState<Record<string, { who: string; target: string; horizon: string; note: string }>>({});
  const [cmBusy, setCmBusy] = useState<string | null>(null);
  const [cmError, setCmError] = useState<Record<string, string>>({});
  const loadCm = () => api.lab.commitments(sessionId).then((r) => setCommits(r.commitments.filter((c) => c.journey_probe_id === probe.id))).catch(() => {});
  const formFor = (cid: string) => cmForm[cid] ?? { who: "", target: "", horizon: "", note: "" };
  const commitTo = async (cid: string) => {
    const f = formFor(cid);
    if (!f.who.trim()) { setCmError((e) => ({ ...e, [cid]: "A commitment is signed by name: say who is committing." })); return; }
    setCmBusy(cid); setCmError((e) => ({ ...e, [cid]: "" }));
    try {
      await api.lab.commit(sessionId, { journey_probe_id: probe.id, candidate_id: cid, committed_by: f.who.trim(),
        target: f.target.trim() || f.horizon.trim() || f.note.trim() ? { value: f.target.trim() || undefined, horizon: f.horizon.trim() || undefined, note: f.note.trim() || undefined } : undefined });
      await loadCm();
      setCmOpen((o) => ({ ...o, [cid]: false }));
    } catch (e: any) { setCmError((er) => ({ ...er, [cid]: e?.message || "Could not commit" })); } finally { setCmBusy(null); }
  };
  useEffect(() => {
    api.lab.rules(sessionId).then((r) => setRules(r.rules)).catch(() => {});
    api.lab.targetingBehaviours(sessionId).then(setMenu).catch(() => {});
    loadRuns(); loadTg(); loadMg(); loadCm();
    const t = setInterval(() => { loadRuns(); loadTg(); loadMg(); }, 5000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, probe.id]);
  const reviewedFor = (lever: string) => {
    const norm = (x: string) => x.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
    const want = norm(lever);
    return rules.find((r) => r.status === "reviewed" && want && (norm(r.lever) === want || norm(r.lever).includes(want) || want.includes(norm(r.lever)))) || null;
  };
  const simulate = async (candidateId: string) => {
    const lever = (leverText[candidateId] || "").trim();
    if (!lever) return;
    setStarting(candidateId);
    setRefusal((r) => ({ ...r, [candidateId]: "" }));
    try {
      await api.lab.runLever(sessionId, { journey_probe_id: probe.id, candidate_id: candidateId, lever, rule_id: reviewedFor(lever)?.id });
      await loadRuns();
    } catch (e: any) {
      const ref = refusalOf(e);
      setRefusal((r) => ({ ...r, [candidateId]: ref || (e?.message || "Could not start the run") }));
    } finally { setStarting(null); }
  };

  const splitKeys = useMemo(() => {
    const keys = new Set<string>();
    answers.forEach((r) => Object.keys(r.segments || {}).forEach((k) => keys.add(k)));
    return [...SPLIT_ORDER.filter((k) => keys.has(k)), ...[...keys].filter((k) => !SPLIT_ORDER.includes(k)).sort()];
  }, [answers]);
  const valuesFor = (key: string) => {
    const vs = new Set<string>();
    answers.forEach((r) => { const v = r.segments?.[key]; if (v) vs.add(v); });
    return [...vs].sort((x, y) => (key === "deprivation" ? rankOf(x) - rankOf(y) : x.localeCompare(y)));
  };
  const filtered = Boolean(segKey && segValue);
  const rows = useMemo(() => answers.filter((r) => !filtered || r.segments?.[segKey] === segValue), [answers, filtered, segKey, segValue]);
  const view = useMemo(() => compute(rows, stages, (a?.candidates || []) as Candidate[]), [rows, stages, a]);

  if (!a || !a.n || !stages.length) return null;
  const last = stages[stages.length - 1];
  const stored: Candidate[] = a.candidates || [];
  const equityFor = (id: string) => stored.find((c) => c.id === id)?.equity;
  const storedFor = (id: string) => stored.find((c) => c.id === id);
  const hc = a.headcount || null;
  const showPeople = Boolean(hc?.available) && !filtered;
  const funnelPeople = (key: string) => (a.funnel || []).find((f: any) => f.key === key);

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-border/60 bg-card/40 p-3 flex flex-wrap items-center gap-2">
        <span className="text-[11px] text-muted-foreground">Read by</span>
        <select value={segKey} onChange={(e) => { setSegKey(e.target.value); setSegValue(""); }}
          className="bg-input border border-border rounded-lg px-2 py-1 text-xs text-foreground" aria-label="Segment">
          <option value="">everyone</option>
          {splitKeys.map((k) => <option key={k} value={k}>{segmentLabel(k, dynamicDials)}</option>)}
        </select>
        {segKey && (
          <div className="flex flex-wrap gap-1">
            {valuesFor(segKey).map((v) => {
              const n = answers.filter((r) => r.segments?.[segKey] === v).length;
              const on = segValue === v;
              return (
                <button key={v} type="button" onClick={() => setSegValue(on ? "" : v)}
                  className={`px-2 py-0.5 rounded-full text-[11px] border ${on ? "border-primary bg-primary/15 text-foreground" : "border-border/60 text-muted-foreground hover:text-foreground"}`}>
                  {v} <span className="opacity-60">{n}</span>
                </button>
              );
            })}
          </div>
        )}
        <span className="ml-auto text-[11px] text-muted-foreground tabular-nums">{view.n} twin{view.n === 1 ? "" : "s"}{filtered ? " in this cut" : ""}</span>
        <button type="button" onClick={() => setRuleBook({})} title="The calibration rules a lever can be simulated against (brief L4-02)"
          className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground border border-border/60 rounded-lg px-2 py-1">
          <BookOpen className="w-3 h-3" /> Rule book <span className="opacity-60">{rules.length ? `${rules.filter((r) => r.status === "reviewed").length} signed of ${rules.length}` : "empty"}</span>
        </button>
      </div>
      {ruleBook && <RuleBook sessionId={sessionId} initialLever={ruleBook.lever} draft={ruleBook.draft} context={{ journey_probe_id: probe.id, candidate_id: ruleBook.candidate_id }} onClose={() => setRuleBook(null)} onChanged={setRules} />}

      {/* The funnel: share of everyone who reached each step. */}
      <div className="rounded-xl border border-border/60 bg-card/40 p-4">
        <div className="text-xs text-muted-foreground mb-2">
          The journey{filtered ? <> for <span className="text-foreground/85">{segValue}</span></> : null}
          <span className="text-muted-foreground/60"> — share who have reached each step</span>
        </div>
        <div className="space-y-1.5">
          {view.funnel.map((f, k) => {
            const fp = showPeople ? funnelPeople(f.key) : null;
            return (
              <div key={f.key} className="flex items-center gap-3 text-xs">
                <span className="w-5 text-muted-foreground tabular-nums">{k + 1}.</span>
                <span className="w-44 truncate text-foreground/90" title={f.definition}>{f.label}</span>
                <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                  <div className={`h-full rounded-full ${k === stages.length - 1 ? "bg-emerald-400/70" : "bg-primary/70"}`} style={{ width: `${Math.round(f.share * 100)}%` }} />
                </div>
                <span className="w-28 text-right text-muted-foreground tabular-nums">{pct(f.share)} <span className="opacity-60">({f.reached})</span></span>
                {showPeople && (
                  <span className={`w-36 text-right tabular-nums ${fp?.people != null ? "text-foreground/85" : "text-muted-foreground/50"}`}
                    title={fp?.people != null ? `${BASIS_LABEL[fp.basis] || fp.basis}${fp.people_low != null && fp.people_low !== fp.people_high ? ` · ${people(fp.people_low)}–${people(fp.people_high)}` : ""}${fp.anchor ? ` · scaled from '${fp.anchor}'` : ""}` : "no figure for this step"}>
                    {fp?.people != null ? <>≈{people(fp.people)} <span className="opacity-60">{fp.fixed ? "fixed" : "people"}</span></> : "—"}
                  </span>
                )}
              </div>
            );
          })}
        </div>
        {hc && !filtered && (
          <p className="text-[10px] mt-2" title="A headcount is a published or client-supplied denominator multiplied by the simulated share; it is no more real than the share.">
            {hc.available
              ? <span className="text-muted-foreground/80">Headcounts: {hc.sentence}{hc.weighted && hc.ess ? ` Effective n ${hc.ess}.` : ""}</span>
              : <span className="text-yellow-300/70">Headcounts not available — {hc.reason}</span>}
          </p>
        )}
        {hc?.available && filtered && <p className="text-[10px] text-muted-foreground/60 mt-2">Headcounts are for the whole population; a cut shows shares only.</p>}
        <p className="text-[11px] text-foreground/70 mt-3 leading-relaxed">
          {!filtered && a.sentence
            ? a.sentence
            : <>{pct(view.completed.share)} reach &lsquo;{last.label}&rsquo; (±{Math.round(((view.completed.high - view.completed.low) / 2) * 100)} points) in this cut.</>}
        </p>
      </div>

      {/* The candidates: one per step where twins drop off, ranked. */}
      <div>
        <div className="text-xs text-muted-foreground mb-2">
          Candidate outcomes — where the population drops off
          <span className="text-muted-foreground/60"> · ranked by what a partner could move, then by how many are stuck · click one</span>
        </div>
        {view.candidates.length === 0 && <p className="text-xs text-muted-foreground/70">Nobody in this cut reports being stuck at any step.</p>}
        <ol className="space-y-1.5">
          {view.candidates.map((c, k) => {
            const isOpen = open === c.id;
            const eq = !filtered ? equityFor(c.id) : null;
            const conf = stored.find((s) => s.id === c.id)?.confidence;
            return (
              <li key={c.id} className={`rounded-lg border ${isOpen ? "border-primary/40" : "border-border/50"} bg-card/30`}>
                <button type="button" onClick={() => setOpen(isOpen ? null : c.id)} className="w-full text-left px-3 py-2">
                  <div className="flex items-center gap-3 text-xs">
                    <span className="w-5 text-muted-foreground tabular-nums">{k + 1}.</span>
                    <span className="flex-1 text-foreground/95 font-medium">{c.from.label} <span className="text-muted-foreground font-normal">→</span> {c.to.label}
                      {commits.some((x) => x.candidate_id === c.id && x.status === "open") && (
                        <span className="ml-2 inline-flex items-center gap-1 text-[10px] font-normal px-1.5 py-0.5 rounded-full border border-amber-400/50 text-amber-200/90" title="A frozen baseline exists for this outcome (brief L7-08)"><Lock className="w-2.5 h-2.5" /> committed</span>
                      )}
                    </span>
                    <span className="text-muted-foreground tabular-nums">{pct(c.conversion)} get through <span className="opacity-60">({pct(c.low)}–{pct(c.high)})</span></span>
                    <span className="text-muted-foreground/80 tabular-nums w-24 text-right">{c.stuck} of {c.n} stuck</span>
                    {showPeople && (() => { const sc = storedFor(c.id); return sc?.stuck_people != null
                      ? <span className="text-foreground/90 tabular-nums w-40 text-right" title={`${BASIS_LABEL[sc.basis || ""] || sc.basis} · of ≈${people(sc.at_risk_people)} at '${c.from.label}'`}>≈{people(sc.stuck_people)} people <span className="opacity-60">{sc.stuck_low != null && sc.stuck_low !== sc.stuck_high ? `(${people(sc.stuck_low)}–${people(sc.stuck_high)})` : "fixed"}</span></span>
                      : <span className="text-muted-foreground/50 w-40 text-right">—</span>; })()}
                  </div>
                  <div className="flex items-center gap-2 mt-1.5 pl-8">
                    <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden flex">
                      <div className="h-full bg-primary/70" style={{ width: `${Math.round(c.conversion * 100)}%` }} />
                      <div className="h-full bg-red-400/60" style={{ width: `${Math.round((c.stuck / (c.n || 1)) * 100)}%` }} />
                    </div>
                    <span className="text-[10px] text-muted-foreground/70 truncate max-w-[50%]">
                      {c.barriers.length ? <>barriers: {c.barriers.slice(0, 3).map((b) => `${b.theme} (${b.count})`).join(" · ")}</> : "no barrier named"}
                    </span>
                  </div>
                  {c.movability && (
                    <div className="flex items-center gap-2 mt-1.5 pl-8" title={c.movability.scored ? `Of the ${c.stuck} stuck: ${c.movability.movable_count} behind a barrier a partner could fix, ${c.movability.system_count} behind one that needs the whole system, ${c.movability.structural_count} behind one nobody can fix soon or with no removal named${c.movability.unscored_count ? `, ${c.movability.unscored_count} not scored` : ""}` : "Movability not scored for this step"}>
                      <div className="w-40 h-1.5 bg-muted rounded-full overflow-hidden flex shrink-0">
                        {(["partner", "system", "structural", "unscored"] as const).map((k) => {
                          const share = k === "partner" ? c.movability!.movable_share : k === "system" ? c.movability!.system_share : k === "structural" ? c.movability!.structural_share : c.movability!.unscored_share;
                          return <div key={k} className={`h-full ${REACH_COLOR[k]}`} style={{ width: `${Math.round(share * 100)}%` }} />;
                        })}
                      </div>
                      <span className="text-[10px] tabular-nums">
                        {c.movability.scored
                          ? <><span className="text-emerald-300/90">movable {pct(c.movability.movable_share)}</span>{showPeople && storedFor(c.id)?.movability?.movable_people != null ? <span className="text-foreground/80"> · ≈{people(storedFor(c.id)!.movability!.movable_people)} people</span> : null}{c.movability.system_share > 0 ? <span className="text-muted-foreground/70"> · system {pct(c.movability.system_share)}</span> : null}{c.movability.structural_share > 0 ? <span className="text-muted-foreground/70"> · structural {pct(c.movability.structural_share)}</span> : null}</>
                          : <span className="text-muted-foreground/60">movability not scored</span>}
                      </span>
                      {c.movability.levers.length > 0 && <span className="text-[10px] text-muted-foreground/70 truncate">lever: {c.movability.levers.slice(0, 2).map((l) => l.lever + (l.actor ? ` (${l.actor})` : "")).join("; ")}</span>}
                    </div>
                  )}
                  {(eq?.available || conf) && (
                    <div className="pl-8 mt-1 text-[10px] text-muted-foreground/70">
                      {eq?.available && <>Equity: {eq.most.label} {pct(eq.most.share ?? 0)} vs {eq.least.label} {pct(eq.least.share ?? 0)}{eq.gap != null ? ` · gap ${eq.gap > 0 ? "+" : ""}${eq.gap} pts` : ""} · {eq.significant ? "a real gap" : eq.significant === false ? "not distinguishable at this size" : "untested"}</>}
                      {conf && <>{eq?.available ? " · " : ""}confidence {conf.score}/100 · computed</>}
                    </div>
                  )}
                </button>
                {isOpen && (
                  <div className="px-3 pb-3 pl-11 space-y-3">
                    <p className="text-[11px] text-foreground/70">
                      Candidate outcome: <span className="text-foreground/90">share of those at &lsquo;{c.from.label}&rsquo; who reach &lsquo;{c.to.label}&rsquo;</span> — modelled at {pct(c.conversion)} today, so the gap is {pct(1 - c.conversion)} of {c.n}
                      {(() => { const sc = showPeople ? storedFor(c.id) : null; return sc?.stuck_people != null ? <>: about <span className="text-foreground/90 tabular-nums">{people(sc.stuck_people)} people</span> stuck of ≈{people(sc.at_risk_people)} at this step ({BASIS_LABEL[sc.basis || ""] || sc.basis})</> : null; })()}.
                    </p>
                    <div className="text-[10px] uppercase tracking-wide text-muted-foreground/60">What stops the next step — by how many named it, then weight</div>
                    {c.barriers.length === 0 && <p className="text-[11px] text-muted-foreground/70">The stuck twins named no barrier.</p>}
                    <ol className="space-y-1.5">
                      {c.barriers.map((b, j) => {
                        const bid = `${c.id}|${b.theme}`;
                        const bOpen = openBarrier === bid;
                        return (
                          <li key={b.theme} className="rounded-md border border-border/40 bg-card/20">
                            <button type="button" onClick={() => setOpenBarrier(bOpen ? null : bid)} className="w-full text-left px-2.5 py-1.5">
                              <div className="flex items-center gap-2 text-xs">
                                <span className="w-4 text-muted-foreground tabular-nums">{j + 1}.</span>
                                <span className="flex-1 text-foreground/90 first-letter:uppercase">{b.theme}</span>
                                <span className="text-muted-foreground tabular-nums">{b.count} twin{b.count === 1 ? "" : "s"} · weight {Math.round(b.weight_mean)}/100</span>
                              </div>
                              {b.removals.length > 0 && <div className="pl-6 text-[10px] text-muted-foreground/70">removed by: {b.removals.join(" · ")}</div>}
                              <div className="pl-6 text-[10px]" title={b.reach_reason || ""}>
                                <span className={`inline-block w-1.5 h-1.5 rounded-full mr-1 align-middle ${REACH_COLOR[b.reach || "unscored"]}`} />
                                <span className={b.reach === "partner" ? "text-emerald-300/85" : "text-muted-foreground/70"} title={!b.reach || b.reach === "unscored" ? "Who could remove this barrier was not classified for this run (the classification step did not complete). Run the journey again to score it; nothing is guessed in the meantime." : b.reach_reason || undefined}>{REACH_LABEL[b.reach || "unscored"]}</span>
                                {b.lever && <span className="text-foreground/80"> · lever: {b.lever}</span>}
                                {b.actor && <span className="text-muted-foreground/70"> · who: {b.actor}</span>}
                              </div>
                            </button>
                            {bOpen && (
                              <div className="px-2.5 pb-2.5 pl-8 space-y-2">
                                {b.twins.map((t) => (
                                  <div key={t.agent_id} className="text-xs">
                                    <span className="text-foreground/95 font-medium">{t.name}</span>
                                    <span className="text-muted-foreground"> · {t.role}</span>
                                    {t.answering_for === "people I serve" && <span className="text-muted-foreground/70"> · for the people they serve</span>}
                                    {t.deprivation && <span className="text-muted-foreground/70"> · {t.deprivation}</span>}
                                    <span className="text-muted-foreground/70"> · {t.weight}/100</span>
                                    {" "}<ConfidenceBadge validation={agentsById[t.agent_id]?.validation} size="xs" />
                                    <div className="text-foreground/80 mt-0.5">“{t.barrier}”{t.removal ? <span className="text-muted-foreground"> — would be removed by: {t.removal}</span> : null}</div>
                                    {t.reasoning && <div className="text-[11px] text-foreground/60 leading-relaxed">{t.reasoning}</div>}
                                    <DrewOn units={t.used_units} />
                                  </div>
                                ))}
                                {b.evidence?.length > 0 && (
                                  <div className="space-y-1">
                                    <div className="text-[10px] uppercase tracking-wide text-muted-foreground/60">{b.evidence[0]?.basis === "could_see" ? "Evidence these twins could see that speaks to it (none cited)" : "Documents these twins drew on"}</div>
                                    {b.evidence.map((e: any) => (
                                      <div key={e.unit_id} className="text-[11px] text-foreground/75 leading-snug">
                                        <span className="text-muted-foreground">{String(e.provenance_class || "").replace(/_/g, " ")} · trust {e.trust_tier} · {e.basis === "could_see" ? "could see" : "cited by"} {e.twins} of these twins</span>
                                        <div>{e.text}</div>
                                        {e.source_ref && <div className="text-[10px] text-muted-foreground/60 truncate">{e.source_ref}</div>}
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            )}
                          </li>
                        );
                      })}
                    </ol>

                    {/* Lever simulation (brief L7-04): only against a reviewed rule; otherwise a refusal, never a guess. */}
                    <div className="rounded-lg border border-border/50 bg-card/20 p-2.5 space-y-2">
                      <div className="text-[10px] uppercase tracking-wide text-muted-foreground/60">Simulate a lever · name it, let the system draft the rule, sign it, then the same twins answer again with it applied</div>
                      <div className="flex flex-wrap gap-1">
                        {(c.movability?.levers || []).filter((l) => l.lever).map((l) => (
                          <button key={l.lever} type="button" onClick={() => setLeverText((t) => ({ ...t, [c.id]: l.lever }))}
                            className={`px-2 py-0.5 rounded-full text-[10px] border ${leverText[c.id] === l.lever ? "border-primary bg-primary/15 text-foreground" : "border-border/60 text-muted-foreground hover:text-foreground"}`}>
                            {l.lever}{reviewedFor(l.lever) ? " ✓" : ""}
                          </button>
                        ))}
                      </div>
                      <div className="flex items-center gap-1.5">
                        <input value={leverText[c.id] || ""} onChange={(e) => setLeverText((t) => ({ ...t, [c.id]: e.target.value }))} placeholder="the lever, e.g. nurse phone line"
                          className="flex-1 bg-input border border-border rounded-lg px-2.5 py-1.5 text-xs text-foreground" />
                        {!reviewedFor(leverText[c.id] || "") && (
                          <button type="button" disabled={drafting === c.id || !(leverText[c.id] || "").trim()} onClick={() => draftRule(c.id)}
                            title="The system drafts the rule from this candidate's barriers, the facts on file and the documents the twins cited; you read and sign it."
                            className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-primary/50 text-primary text-xs hover:bg-primary/10 disabled:opacity-50">
                            <Sparkles className="w-3 h-3" /> {drafting === c.id ? "Drafting…" : "Draft the rule"}
                          </button>
                        )}
                        <button type="button" disabled={starting === c.id || !(leverText[c.id] || "").trim()} onClick={() => simulate(c.id)}
                          className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-primary text-primary-foreground text-xs disabled:opacity-50">
                          <Play className="w-3 h-3" /> {starting === c.id ? "Starting…" : "Simulate"}
                        </button>
                      </div>
                      {(leverText[c.id] || "").trim() && (
                        reviewedFor(leverText[c.id]) ? (
                          <p className="text-[10px] text-emerald-300/80">Rule on file: <span className="text-foreground/80">{reviewedFor(leverText[c.id])!.lever}</span> · reviewed by {reviewedFor(leverText[c.id])!.reviewed_by} · dials {Object.entries(reviewedFor(leverText[c.id])!.deltas).map(([k, v]) => `${k} ${v > 0 ? "+" : ""}${v}`).join(", ")}
                            {reviewedFor(leverText[c.id])!.basis_class === "assumption" && <> · <span className="text-orange-300/90">assumption, no evidence — the result will say "assumed effect"</span></>}</p>
                        ) : (
                          <p className="text-[10px] text-yellow-300/70">No reviewed rule for this lever yet — press <span className="text-foreground/80">Draft the rule</span> and sign it, or <button type="button" onClick={() => setRuleBook({ lever: leverText[c.id], candidate_id: c.id })} className="underline decoration-dotted">write one yourself</button>. Simulate refuses until a signed rule exists.</p>
                        )
                      )}
                      {refusal[c.id] && (
                        <div className="rounded-md border border-yellow-500/30 bg-yellow-500/5 px-2.5 py-2 text-[11px] text-yellow-200/90">
                          {typeof refusal[c.id] === "string" ? (refusal[c.id] as string) : (
                            <>
                              <span className="font-medium">Refused — no number without a reviewed rule.</span> {(refusal[c.id] as LeverRefusal).reason}{" "}
                              <button type="button" onClick={() => setRuleBook({ lever: (refusal[c.id] as LeverRefusal).lever, candidate_id: c.id })} className="underline decoration-dotted">{(refusal[c.id] as LeverRefusal).missing ? "Open the rule book" : "Open the rule book to sign it"}</button>
                            </>
                          )}
                        </div>
                      )}
                      {runs.filter((r) => r.spec?.lever_run?.candidate_id === c.id).map((r) => <LeverRun key={r.id} run={r} />)}
                    </div>

                    {/* Behaviour targeting (brief L7-05): every behaviour nudged by the same few points over the stuck twins; ranked by movement per point; backfire beside the winner. */}
                    <div className="rounded-lg border border-border/50 bg-card/20 p-2.5 space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-[10px] uppercase tracking-wide text-muted-foreground/60">Rank behaviours · which behaviour to change, counted: each one nudged by the same few points for the twins at risk here</div>
                        <button type="button" onClick={() => setTgOpen((o) => ({ ...o, [c.id]: !o[c.id] }))} className="text-[10px] text-muted-foreground hover:text-foreground underline decoration-dotted shrink-0">{tgOpen[c.id] ? "hide the list" : "choose behaviours"}</button>
                      </div>
                      {tgOpen[c.id] && menu && (
                        <div className="space-y-1.5">
                          <div className="flex flex-wrap gap-1">
                            {menu.behaviours.map((b) => {
                              const on = selFor(c.id).includes(b.key);
                              return (
                                <button key={b.key} type="button" title={`${b.why}\n0 = ${b.low}\n10 = ${b.high}`} onClick={() => setTgSel((t) => ({ ...t, [c.id]: on ? selFor(c.id).filter((k) => k !== b.key) : [...selFor(c.id), b.key] }))}
                                  className={`px-2 py-0.5 rounded-full text-[10px] border ${on ? "border-primary bg-primary/15 text-foreground" : "border-border/60 text-muted-foreground hover:text-foreground"}`}>
                                  {b.label}
                                </button>
                              );
                            })}
                            {selFor(c.id).filter((k) => !menu.behaviours.some((b) => b.key === k)).map((k) => (
                              <button key={k} type="button" onClick={() => setTgSel((t) => ({ ...t, [c.id]: selFor(c.id).filter((x) => x !== k) }))}
                                className="px-2 py-0.5 rounded-full text-[10px] border border-primary bg-primary/15 text-foreground">{k.split(".")[1]?.replace(/_/g, " ")} <span className="opacity-60">· {k.split(".")[0]} ×</span></button>
                            ))}
                          </div>
                          <div className="flex items-center gap-2 flex-wrap text-[10px] text-muted-foreground">
                            <label className="flex items-center gap-1">add a fixed dial
                              <select value="" onChange={(e) => { const k = e.target.value; if (k && !selFor(c.id).includes(k) && selFor(c.id).length < menu.max_behaviours) setTgSel((t) => ({ ...t, [c.id]: [...selFor(c.id), k] })); }}
                                className="bg-input border border-border rounded px-1.5 py-0.5 text-[10px] text-foreground">
                                <option value="">…</option>
                                {Object.entries(menu.fixed).map(([g, ds]) => <optgroup key={g} label={g}>{ds.map((d) => <option key={`${g}.${d}`} value={`${g}.${d}`}>{d.replace(/_/g, " ")}</option>)}</optgroup>)}
                              </select>
                            </label>
                            <label className="flex items-center gap-1">nudge by
                              <input type="number" min={1} max={menu.points_max} value={tgPoints[c.id] ?? menu.points_default} onChange={(e) => setTgPoints((p) => ({ ...p, [c.id]: Math.max(1, Math.min(menu.points_max, Number(e.target.value) || menu.points_default)) }))}
                                className="w-12 bg-input border border-border rounded px-1.5 py-0.5 text-[10px] text-foreground tabular-nums" /> point{(tgPoints[c.id] ?? menu.points_default) === 1 ? "" : "s"}
                            </label>
                            <span>{selFor(c.id).length} behaviour{selFor(c.id).length === 1 ? "" : "s"} · one run of the {c.n} at-risk twins each</span>
                          </div>
                        </div>
                      )}
                      <div className="flex items-center gap-2 flex-wrap">
                        <button type="button" disabled={tgStarting === c.id || !menu || selFor(c.id).length === 0} onClick={() => rankBehaviours(c.id)}
                          title="The twins at risk at this step answer the journey again once per behaviour, with that one dial nudged; the shift per point is counted and ranked."
                          className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-primary text-primary-foreground text-xs disabled:opacity-50">
                          <ListOrdered className="w-3 h-3" /> {tgStarting === c.id ? "Starting…" : "Rank behaviours"}
                        </button>
                        {menu && !tgOpen[c.id] && <span className="text-[10px] text-muted-foreground">{selFor(c.id).length} behaviour{selFor(c.id).length === 1 ? "" : "s"}{menu.behaviours.length ? ", the question's own dials" : ""} · nudge {tgPoints[c.id] ?? menu.points_default} pt{(tgPoints[c.id] ?? menu.points_default) === 1 ? "" : "s"}</span>}
                        {menu && menu.behaviours.length === 0 && <span className="text-[10px] text-yellow-300/70">This session has no question-specific dials; add fixed dials from the list.</span>}
                      </div>
                      {tgError[c.id] && <p className="text-[11px] text-red-400">{tgError[c.id]}</p>}
                      {tgRuns.filter((r) => r.spec?.targeting?.candidate_id === c.id).map((r) => <TargetingRun key={r.id} run={r} />)}
                    </div>

                    {/* Message testing (brief L7-06): the twins at risk here read each framing and answer the journey again; the shift per message and by cohort; backfire beside the winner; a reaction, not a forecast. */}
                    <div className="rounded-lg border border-border/50 bg-card/20 p-2.5 space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-[10px] uppercase tracking-wide text-muted-foreground/60">Test messages · which framing gets the stuck through, counted: the twins at risk here read each one and answer again</div>
                        <button type="button" onClick={() => setMgOpen((o) => ({ ...o, [c.id]: !o[c.id] }))} className="text-[10px] text-muted-foreground hover:text-foreground underline decoration-dotted shrink-0">{mgOpen[c.id] ? "hide the messages" : "write messages"}</button>
                      </div>
                      {mgOpen[c.id] && (
                        <div className="space-y-1.5">
                          {msgsFor(c.id).map((m, i) => (
                            <div key={i} className="grid grid-cols-[8rem_1fr_auto] gap-1.5 items-start">
                              <input value={m.label} placeholder={`name ${i + 1}`} maxLength={60} onChange={(e) => setMsg(c.id, i, { label: e.target.value })}
                                className="bg-input border border-border rounded px-1.5 py-1 text-[11px] text-foreground" />
                              <textarea value={m.text} rows={2} maxLength={1500} placeholder="The message exactly as people would read it — a line of copy, a leaflet paragraph, what a nurse would say"
                                onChange={(e) => setMsg(c.id, i, { text: e.target.value })}
                                className="bg-input border border-border rounded px-1.5 py-1 text-[11px] text-foreground resize-y" />
                              <button type="button" title="remove" onClick={() => setMgMsgs((mm) => ({ ...mm, [c.id]: msgsFor(c.id).filter((_, k) => k !== i) }))}
                                className="text-[11px] text-muted-foreground hover:text-foreground px-1 py-1">×</button>
                            </div>
                          ))}
                          <div className="flex items-center gap-2 flex-wrap text-[10px] text-muted-foreground">
                            <button type="button" disabled={msgsFor(c.id).length >= MAX_MESSAGES} onClick={() => setMgMsgs((mm) => ({ ...mm, [c.id]: [...msgsFor(c.id), { label: "", text: "" }] }))}
                              className="underline decoration-dotted hover:text-foreground disabled:opacity-50">add a message</button>
                            <span>up to {MAX_MESSAGES} · one run of the {c.n} at-risk twins per message, plus a baseline · nothing about the twins is changed; they read it and answer</span>
                          </div>
                        </div>
                      )}
                      <div className="flex items-center gap-2 flex-wrap">
                        <button type="button" disabled={mgStarting === c.id || msgsFor(c.id).every((m) => !m.text.trim())} onClick={() => testMessages(c.id)}
                          title="The twins at risk at this step read each message in its own run and answer the journey again; the shift in conversion is counted per message and by deprivation band."
                          className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-primary text-primary-foreground text-xs disabled:opacity-50">
                          <MessageSquare className="w-3 h-3" /> {mgStarting === c.id ? "Starting…" : "Test messages"}
                        </button>
                        {!mgOpen[c.id] && <span className="text-[10px] text-muted-foreground">{msgsFor(c.id).filter((m) => m.text.trim()).length} message{msgsFor(c.id).filter((m) => m.text.trim()).length === 1 ? "" : "s"} written</span>}
                        <span className="text-[10px] text-muted-foreground/70">a modelled reaction to a framing, not a forecast of uptake</span>
                      </div>
                      {mgError[c.id] && <p className="text-[11px] text-red-400">{mgError[c.id]}</p>}
                      {mgRuns.filter((r) => r.spec?.messaging?.candidate_id === c.id).map((r) => <MessagingRun key={r.id} run={r} />)}
                    </div>

                    {/* Commitment (brief L7-08): freeze this candidate's modelled baseline as a copy, signed by name; enter observed results against it later. */}
                    <div className="rounded-lg border border-amber-400/30 bg-amber-500/5 p-2.5 space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-[10px] uppercase tracking-wide text-muted-foreground/60">Commit to this outcome · freeze the modelled baseline as it stands, signed by name, so a real result can later be compared against it</div>
                        <button type="button" onClick={() => setCmOpen((o) => ({ ...o, [c.id]: !o[c.id] }))} className="text-[10px] text-muted-foreground hover:text-foreground underline decoration-dotted shrink-0">{cmOpen[c.id] ? "cancel" : commits.some((x) => x.candidate_id === c.id && x.status === "open") ? "commit again (supersedes)" : "commit"}</button>
                      </div>
                      {cmOpen[c.id] && (
                        <div className="space-y-1.5">
                          <div className="grid grid-cols-[1fr_6rem_10rem] gap-1.5 text-[11px]">
                            <input value={formFor(c.id).who} placeholder="committed by (your name)" maxLength={120} onChange={(e) => setCmForm((f) => ({ ...f, [c.id]: { ...formFor(c.id), who: e.target.value } }))}
                              className="bg-input border border-border rounded px-1.5 py-1 text-foreground" />
                            <input value={formFor(c.id).target} placeholder="target %" inputMode="decimal" onChange={(e) => setCmForm((f) => ({ ...f, [c.id]: { ...formFor(c.id), target: e.target.value } }))}
                              className="bg-input border border-border rounded px-1.5 py-1 text-foreground tabular-nums" />
                            <input value={formFor(c.id).horizon} placeholder="by when (e.g. March 2027)" maxLength={300} onChange={(e) => setCmForm((f) => ({ ...f, [c.id]: { ...formFor(c.id), horizon: e.target.value } }))}
                              className="bg-input border border-border rounded px-1.5 py-1 text-foreground" />
                          </div>
                          <input value={formFor(c.id).note} placeholder="note (optional): why this outcome, what the partnership will do" maxLength={300} onChange={(e) => setCmForm((f) => ({ ...f, [c.id]: { ...formFor(c.id), note: e.target.value } }))}
                            className="w-full bg-input border border-border rounded px-1.5 py-1 text-[11px] text-foreground" />
                          <div className="flex items-center gap-2 flex-wrap">
                            <button type="button" disabled={cmBusy === c.id || !formFor(c.id).who.trim()} onClick={() => commitTo(c.id)}
                              title="Takes a copy of this candidate, the journey run, every run on it, the population build and frame, the evidence on file, the rules and the statement. Nothing is edited afterwards."
                              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-amber-500/80 text-black text-xs disabled:opacity-50">
                              <Lock className="w-3 h-3" /> {cmBusy === c.id ? "Freezing…" : "Freeze and commit"}
                            </button>
                            <span className="text-[10px] text-muted-foreground">what is frozen: this candidate ({pct(c.conversion)}, {c.stuck} of {c.n} stuck), the funnel and headcounts, every lever run, ranking and message test on it, the population build, frame and weights, the evidence list, every rule, the model and seed, the statement · no model call</span>
                          </div>
                        </div>
                      )}
                      {cmError[c.id] && <p className="text-[11px] text-red-400">{cmError[c.id]}</p>}
                      {commits.filter((x) => x.candidate_id === c.id).map((x) => <CommitmentCard key={x.id} c={x} sessionId={sessionId} onChanged={loadCm} />)}
                    </div>
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      </div>

      <p className="text-[10px] text-muted-foreground/60">
        Every number here is counted from the twins&apos; own placements; barriers are their words coded into shared labels after the run. The report may only name candidate outcomes from this list, in this order. Headcounts multiply a published or client-supplied denominator by the simulated share and are no more real than the share. Movability classes each barrier by who could reach the removal the twins asked for; the report may not judge it on its own. To see what an intervention would shift, click a candidate and simulate a lever against a signed rule.
      </p>
    </div>
  );
}


/** One lever run: the counted shift (brief L7-04) — conversion then → now with its interval, who
 *  moved, the end of the journey, the people moved, and the rule it ran under. */
function LeverRun({ run }: { run: Experiment }) {
  const lv: LeverShift | undefined = run.results?.lever;
  const rule = run.variants?.find((v) => v.key === "lever")?.spec?.lever;
  if (!lv?.available) {
    return (
      <div className="rounded-md border border-border/40 px-2.5 py-2 text-[11px] text-muted-foreground">
        <span className="text-foreground/85">{run.name}</span> · {run.status === "complete" ? "counting the shift…" : run.status === "failed" ? `failed: ${run.error || ""}` : `${run.status}…`}
        {rule && <span className="opacity-70"> · rule reviewed by {rule.reviewed_by}</span>}
      </div>
    );
  }
  const cv = lv.conversion;
  const sign = (x: number) => `${x > 0 ? "+" : ""}${Math.round(x * 100)}`;
  const assumed = lv.assumed || lv.rule?.basis_class === "assumption";
  return (
    <div className={`rounded-md border px-2.5 py-2 space-y-1 text-[11px] ${assumed ? "border-orange-400/40 bg-orange-500/5" : "border-primary/30 bg-primary/5"}`}>
      {assumed && (
        <div className="text-[10px] uppercase tracking-wide text-orange-300/90 font-semibold" title="The rule this ran under rests on no evidence: the reviewer signed its dial changes as a scenario. Read the shift as 'if the change moved people as assumed', not as a forecast.">
          Assumed effect · not a forecast · the rule rests on no evidence
        </div>
      )}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-medium text-foreground/95">{lv.rule.lever}</span>
        <span className={`tabular-nums ${cv.significant ? "text-emerald-300/90" : "text-muted-foreground"}`}>{sign(cv.lift)} points ({sign(cv.low)} to {sign(cv.high)}) · {cv.significant ? "real" : "not distinguishable from zero"}</span>
        <span className="text-muted-foreground tabular-nums">{Math.round(cv.then * 100)}% → {Math.round(cv.now * 100)}% get through · n={cv.n}</span>
        {lv.people && <span className="text-foreground/85 tabular-nums">≈{lv.people.moved.toLocaleString()} people moved ({lv.people.low.toLocaleString()}–{lv.people.high.toLocaleString()})</span>}
      </div>
      <div className="text-muted-foreground">
        {lv.movement.up} moved through · {lv.movement.down} fell back · {lv.movement.unchanged} unchanged · covered {lv.covered} twins
        {" · "}end of journey ‘{lv.end.label}’: {Math.round(lv.end.then * 100)}% → {Math.round(lv.end.now * 100)}% ({sign(lv.end.lift)} pts)
      </div>
      {lv.segments?.deprivation && (
        <div className="text-muted-foreground/80">by deprivation: {lv.segments.deprivation.map((r) => `${r.value} ${sign(r.lift)}${r.thin ? " (thin)" : ""}`).join(" · ")}</div>
      )}
      <div className="text-[10px] text-muted-foreground/70">
        rule: {Object.entries(lv.rule.deltas || {}).map(([k, v]) => `${k} ${v > 0 ? "+" : ""}${v}`).join(", ")} · {Object.keys(lv.rule.applies_to || {}).length ? Object.entries(lv.rule.applies_to).map(([k, v]) => `${k} = ${(v as string[]).join("/")}`).join("; ") : "everyone"} · {assumed ? "no evidence (assumption)" : `${lv.rule.evidence_count ?? ""} evidence line${lv.rule.evidence_count === 1 ? "" : "s"}`} · reviewed by {lv.rule.reviewed_by}
      </div>
    </div>
  );
}


/** One commitment (brief L7-08): the frozen forecast and what it rested on, the target, the observed
 *  results entered against it with the counted comparison, and the close / supersede state. */
function CommitmentCard({ c, sessionId, onChanged }: { c: Commitment; sessionId: string; onChanged: () => void }) {
  const [showBaseline, setShowBaseline] = useState(false);
  const [obsOpen, setObsOpen] = useState(false);
  const [obs, setObs] = useState({ value: "", source: "", date: "", who: "", note: "" });
  const [closeOpen, setCloseOpen] = useState(false);
  const [closeForm, setCloseForm] = useState({ who: "", note: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const b = c.baseline;
  const cand = b?.candidate;
  const cmp = c.comparison;
  const P = (x: number | null | undefined) => (x == null ? "—" : `${Math.round(x * 100)}%`);
  const addObserved = async () => {
    setBusy(true); setErr("");
    try {
      await api.lab.observeCommitment(sessionId, c.id, { value: Number(obs.value), source: obs.source.trim(), date: obs.date.trim(), entered_by: obs.who.trim() || undefined, note: obs.note.trim() || undefined });
      setObs({ value: "", source: "", date: "", who: "", note: "" }); setObsOpen(false); onChanged();
    } catch (e: any) { setErr(e?.message || "Could not record the observation"); } finally { setBusy(false); }
  };
  const closeIt = async () => {
    setBusy(true); setErr("");
    try { await api.lab.closeCommitment(sessionId, c.id, { closed_by: closeForm.who.trim(), note: closeForm.note.trim() || undefined }); setCloseOpen(false); onChanged(); }
    catch (e: any) { setErr(e?.message || "Could not close"); } finally { setBusy(false); }
  };
  const statusCls = c.status === "open" ? "border-amber-400/50 text-amber-200/90" : c.status === "closed" ? "border-border/60 text-muted-foreground" : "border-border/40 text-muted-foreground/60";
  return (
    <div className={`rounded-md border px-2.5 py-2 space-y-1.5 text-[11px] ${c.status === "open" ? "border-amber-400/40 bg-amber-500/5" : "border-border/40 bg-card/20 opacity-90"}`}>
      <div className="flex items-center gap-2 flex-wrap">
        <Lock className="w-3 h-3 text-amber-300/80" />
        <span className="font-medium text-foreground/95">{c.label}</span>
        <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${statusCls}`}>{c.status}</span>
        <span className="text-muted-foreground">committed by <span className="text-foreground/85">{c.committed_by}</span> on {(c.committed_at || "").slice(0, 10)}</span>
        {c.target?.value != null && <span className="text-foreground/85 tabular-nums">target {P(c.target.value)}{c.target.horizon ? ` by ${c.target.horizon}` : ""}</span>}
      </div>
      {cand && (
        <div className="text-muted-foreground">
          <span className="text-foreground/90 tabular-nums">Frozen forecast: {P(cand.conversion)} get through ({P(cand.low)}–{P(cand.high)}) · {cand.stuck} of {cand.n} stuck</span>
          {cand.stuck_people != null && <span className="tabular-nums"> · ≈{Number(cand.stuck_people).toLocaleString()} people stuck</span>}
          <span> · population build <span className="font-mono text-[10px]">{(b.population?.build_id || "unknown").slice(0, 8)}</span> ({b.population?.n} twins, frame {b.frame?.level || "none"}{b.population?.weights?.weighted ? `, effective n ${b.population.weights.ess}` : ""})</span>
          <span> · {b.evidence?.items?.length || 0} evidence items, {b.evidence?.facts?.length || 0} typed facts, {b.calibration_rules?.length || 0} rules on file · {b.related?.length || 0} run{(b.related?.length || 0) === 1 ? "" : "s"} on this candidate</span>
          {c.target?.note && <span> · {c.target.note}</span>}
        </div>
      )}
      {cmp ? (
        <div className={`rounded border px-2 py-1.5 ${cmp.inside_interval ? "border-emerald-400/40 bg-emerald-500/10 text-emerald-100/90" : "border-red-400/40 bg-red-500/10 text-red-100/90"}`}>
          <span className="font-semibold uppercase tracking-wide text-[10px]">Observed</span>{" "}
          <span className="tabular-nums">{P(cmp.observed)}</span> on {cmp.observed_date} ({cmp.observed_source}) · {cmp.delta != null ? `${cmp.delta > 0 ? "+" : ""}${Math.round(cmp.delta * 100)} points against the forecast` : ""} · {cmp.inside_interval ? "inside" : "outside"} the modelled interval
          {"target_met" in cmp && <> · target {cmp.target_met ? "met" : "not met"}</>}
          {cmp.observations > 1 && <span className="opacity-70"> · {cmp.observations} observations, latest shown</span>}
        </div>
      ) : (
        <div className="text-muted-foreground/70">No observed result yet.</div>
      )}
      {c.observed.length > 0 && (
        <ul className="text-muted-foreground/80 space-y-0.5">
          {c.observed.map((o, i) => <li key={i} className="tabular-nums">{P(o.value)}{o.low != null && o.high != null ? ` (${P(o.low)}–${P(o.high)})` : ""} · {o.date} · {o.source}{o.entered_by ? ` · entered by ${o.entered_by}` : ""}{o.note ? ` · ${o.note}` : ""}</li>)}
        </ul>
      )}
      {c.status === "closed" && <div className="text-muted-foreground">Closed by {c.closed_by} on {(c.closed_at || "").slice(0, 10)}{c.close_note ? `: ${c.close_note}` : ""}</div>}
      <div className="flex items-center gap-2 flex-wrap text-[10px]">
        <button type="button" onClick={() => setShowBaseline((s) => !s)} className="text-muted-foreground hover:text-foreground underline decoration-dotted">{showBaseline ? "hide the frozen baseline" : "show the frozen baseline"}</button>
        {c.status !== "superseded" && <button type="button" onClick={() => { setObsOpen((s) => !s); setCloseOpen(false); }} className="text-muted-foreground hover:text-foreground underline decoration-dotted">{obsOpen ? "cancel" : "enter an observed result"}</button>}
        {c.status === "open" && <button type="button" onClick={() => { setCloseOpen((s) => !s); setObsOpen(false); }} className="text-muted-foreground hover:text-foreground underline decoration-dotted">{closeOpen ? "cancel" : "close this commitment"}</button>}
      </div>
      {obsOpen && (
        <div className="space-y-1">
          <div className="grid grid-cols-[5rem_1fr_8rem_9rem] gap-1.5">
            <input value={obs.value} placeholder="value %" inputMode="decimal" onChange={(e) => setObs((o) => ({ ...o, value: e.target.value }))} className="bg-input border border-border rounded px-1.5 py-1 text-foreground tabular-nums" />
            <input value={obs.source} placeholder="source (required): the dataset, audit or report it comes from" maxLength={300} onChange={(e) => setObs((o) => ({ ...o, source: e.target.value }))} className="bg-input border border-border rounded px-1.5 py-1 text-foreground" />
            <input value={obs.date} placeholder="date (required)" maxLength={40} onChange={(e) => setObs((o) => ({ ...o, date: e.target.value }))} className="bg-input border border-border rounded px-1.5 py-1 text-foreground" />
            <input value={obs.who} placeholder="entered by" maxLength={120} onChange={(e) => setObs((o) => ({ ...o, who: e.target.value }))} className="bg-input border border-border rounded px-1.5 py-1 text-foreground" />
          </div>
          <div className="flex items-center gap-2">
            <input value={obs.note} placeholder="note (optional)" maxLength={600} onChange={(e) => setObs((o) => ({ ...o, note: e.target.value }))} className="flex-1 bg-input border border-border rounded px-1.5 py-1 text-foreground" />
            <button type="button" disabled={busy || !obs.value.trim() || !obs.source.trim() || !obs.date.trim()} onClick={addObserved} className="px-2.5 py-1 rounded-lg bg-primary text-primary-foreground text-xs disabled:opacity-50">{busy ? "Saving…" : "Record it"}</button>
          </div>
        </div>
      )}
      {closeOpen && (
        <div className="flex items-center gap-1.5">
          <input value={closeForm.who} placeholder="closed by (your name)" maxLength={120} onChange={(e) => setCloseForm((f) => ({ ...f, who: e.target.value }))} className="bg-input border border-border rounded px-1.5 py-1 text-foreground" />
          <input value={closeForm.note} placeholder="why (optional)" maxLength={600} onChange={(e) => setCloseForm((f) => ({ ...f, note: e.target.value }))} className="flex-1 bg-input border border-border rounded px-1.5 py-1 text-foreground" />
          <button type="button" disabled={busy || !closeForm.who.trim()} onClick={closeIt} className="px-2.5 py-1 rounded-lg border border-border text-xs disabled:opacity-50">{busy ? "Closing…" : "Close"}</button>
        </div>
      )}
      {err && <p className="text-red-400">{err}</p>}
      {showBaseline && b && (
        <div className="rounded border border-border/40 bg-background/40 p-2 space-y-1 text-[10px] text-muted-foreground">
          <div>Frozen {b.frozen_at} · question: <span className="text-foreground/80">{b.question}</span></div>
          <div>Journey run {b.journey?.probe_id?.slice(0, 8)} · {b.journey?.n} answered · model {b.journey?.model} · seed {b.journey?.seed} · prompt {b.journey?.prompt_hash?.slice(0, 10)} · steps: {(b.journey?.stages || []).map((s) => s.label).join(" → ")}</div>
          <div>Headcounts: {b.journey?.headcount?.available ? b.journey.headcount.sentence : `not available — ${b.journey?.headcount?.reason || "no sizing figure"}`}</div>
          <div>Frame: level {b.frame?.level || "none"}{b.frame?.matched_exactly?.length ? ` · matched ${b.frame.matched_exactly.join(", ")}` : ""}{b.frame?.weighted_only?.length ? ` · weighted ${b.frame.weighted_only.join(", ")}` : ""}{b.frame?.estimated?.length ? ` · estimated ${b.frame.estimated.join(", ")}` : ""}{b.scoping_snapshot ? ` · scoping snapshot ${String(b.scoping_snapshot).slice(0, 8)}` : ""}</div>
          {cand?.barriers?.length > 0 && <div>Barriers then: {cand.barriers.map((x: any) => `${x.theme} (${x.count}${x.reach ? `, ${x.reach}` : ""})`).join(" · ")}</div>}
          {cand?.movability?.scored && <div>Movability then: movable {Math.round((cand.movability.movable_share || 0) * 100)}% · system {Math.round((cand.movability.system_share || 0) * 100)}% · structural {Math.round((cand.movability.structural_share || 0) * 100)}%</div>}
          {(b.related || []).length > 0 && <div>Runs on this candidate: {b.related.map((r) => `${r.kind}: ${r.label}`).join(" · ")}</div>}
          {(b.calibration_rules || []).length > 0 && <div>Rules on file: {b.calibration_rules.map((r) => `${r.lever} (${r.status}${r.reviewed_by ? `, ${r.reviewed_by}` : ""})`).join(" · ")}</div>}
          <div>Evidence on file: {Object.entries(b.evidence?.counts || {}).map(([k, v]) => `${v} ${k}`).join(", ") || "none"} · {(b.evidence?.items || []).slice(0, 8).map((it) => it.title).join(" · ")}{(b.evidence?.items || []).length > 8 ? " · …" : ""}</div>
          <details><summary className="cursor-pointer">Synthetic statement as frozen</summary><p className="whitespace-pre-wrap mt-1">{b.statement}</p></details>
        </div>
      )}
      <p className="text-[10px] text-muted-foreground/60">A copy, not a pointer: later runs, documents, rules or population builds do not change it. The report may quote only the frozen forecast for this commitment, and an observed result only where one is recorded here.</p>
    </div>
  );
}


/** One message run (brief L7-06): the framings ranked by the shift in conversion at the step,
 *  the interval, who moved, the people moved, by deprivation band — every backfire above the
 *  winner, and the whole thing labelled a modelled reaction, never a forecast. */
function MessagingRun({ run }: { run: Experiment }) {
  const t: MessagingResult | undefined = run.results?.messaging;
  const info = run.spec?.messaging as { messages?: { key: string; label: string; text: string }[]; at_risk?: number } | undefined;
  if (!t?.available) {
    return (
      <div className="rounded-md border border-border/40 px-2.5 py-2 text-[11px] text-muted-foreground">
        <span className="text-foreground/85">{run.name}</span> · {run.status === "complete" ? "counting the shift…" : run.status === "failed" ? `failed: ${run.error || ""}` : `${run.status}…`}
        {info && <span className="opacity-70"> · {info.messages?.length || 0} message{(info.messages?.length || 0) === 1 ? "" : "s"} × {info.at_risk} twins</span>}
      </div>
    );
  }
  const pp = (x: number) => `${x > 0 ? "+" : ""}${(x * 100).toFixed(1)}`;
  const rows = t.messages.filter((r) => r.available);
  return (
    <div className="rounded-md border border-primary/30 bg-primary/5 px-2.5 py-2 space-y-1.5 text-[11px]">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-medium text-foreground/95">Messages ranked by the shift in conversion</span>
        <span className="text-muted-foreground tabular-nums">{t.n} twins at risk · {rows.length} message{rows.length === 1 ? "" : "s"}{t.weighted ? " · weighted to the frame" : ""}</span>
        {!t.any_significant && <span className="text-yellow-300/80">no shift distinguishable from zero at this size</span>}
        <span className="text-[10px] px-1.5 py-0.5 rounded-full border border-yellow-400/40 text-yellow-200/90">reaction, not a forecast</span>
      </div>
      {t.backfires.length > 0 && (
        <div className="rounded border border-red-400/40 bg-red-500/10 px-2 py-1.5 text-red-200/90">
          <span className="font-semibold uppercase tracking-wide text-[10px]">Backfire</span>{" "}
          {t.backfires.map((b) => [b.hurts ? `‘${b.label}’ lowers conversion overall (${pp(b.lift)})` : "", ...b.bands.map((x) => `‘${b.label}’ lowers it for ${x.value} (${pp(x.lift)})`)].filter(Boolean).join("; ")).join("; ")}
        </div>
      )}
      <ol className="space-y-1">
        {rows.map((r) => (
          <li key={r.key} className={`grid grid-cols-[1.25rem_1fr] gap-x-2 rounded px-1.5 py-1 ${r.hurts || r.backfire.length ? "bg-red-500/5" : r.rank === 1 && r.significant ? "bg-emerald-500/5" : ""}`}>
            <span className="text-muted-foreground tabular-nums">{r.rank}.</span>
            <div className="min-w-0 space-y-0.5">
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${r.direction === "helps" ? "border-emerald-400/40 text-emerald-300/90" : r.direction === "hurts" ? "border-red-400/40 text-red-300/90" : "border-border/60 text-muted-foreground"}`}>{r.direction === "helps" ? "helps" : r.direction === "hurts" ? "hurts" : "no change"}</span>
                <span className="font-medium text-foreground/95">{r.label}</span>
                <span className={`tabular-nums ${r.significant ? "text-foreground/90" : "text-muted-foreground"}`}>{pp(r.lift)} pts <span className="text-muted-foreground">({pp(r.low)} to {pp(r.high)}) · {r.significant ? "real" : "not distinguishable from zero"}</span></span>
                {r.weighted && <span className="text-muted-foreground tabular-nums" title={`each twin at its sampling-frame weight; effective n ${r.weighted.ess}`}>weighted {pp(r.weighted.lift)}</span>}
                {r.people && <span className="text-foreground/85 tabular-nums" title={r.people.basis}>≈{Math.abs(r.people.moved).toLocaleString()} people {r.people.moved < 0 ? "lost" : "moved"}</span>}
                {(r.hurts || r.backfire.length > 0) && <span className="text-[10px] px-1.5 py-0.5 rounded-full border border-red-400/50 text-red-300/90">{r.hurts ? "hurts overall" : "backfires in a band"}</span>}
              </div>
              <div className="text-muted-foreground/80 italic whitespace-pre-wrap">“{r.text}”</div>
              <div className="text-muted-foreground">
                {Math.round(r.then * 100)}% → {Math.round(r.now * 100)}% get through · {r.movement.up} moved through · {r.movement.down} fell back · {r.movement.unchanged} unchanged
                {r.end && <> · end of journey {Math.round((r.end.then || 0) * 100)}% → {Math.round((r.end.now || 0) * 100)}%</>}
                {r.bands.length > 1 && <> · by deprivation: {r.bands.map((b) => `${b.value} ${pp(b.lift)}${b.thin ? " (thin)" : ""}`).join(" · ")}</>}
              </div>
            </div>
          </li>
        ))}
      </ol>
      <p className="text-[10px] text-muted-foreground/70">A modelled reaction to a framing, counted from the twins&apos; own placements after reading it. It says which message the twins respond to, not that the message would reach these people or move them by this much in the world — that is what a reviewed rule and a lever run are for. The report may only quote this list, in this order, with every backfire.</p>
    </div>
  );
}


/** One behaviour-targeting run (brief L7-05): the behaviours ranked by modelled movement per dial
 *  point at the step, the direction to push each, its interval, who moved, the people per point —
 *  and every backfire shown as prominently as the winner. */
function TargetingRun({ run }: { run: Experiment }) {
  const t: TargetingResult | undefined = run.results?.targeting;
  const info = run.spec?.targeting as { behaviours?: string[]; points?: number; at_risk?: number } | undefined;
  if (!t?.available) {
    return (
      <div className="rounded-md border border-border/40 px-2.5 py-2 text-[11px] text-muted-foreground">
        <span className="text-foreground/85">{run.name}</span> · {run.status === "complete" ? "counting the ranking…" : run.status === "failed" ? `failed: ${run.error || ""}` : `${run.status}…`}
        {info && <span className="opacity-70"> · {info.behaviours?.length || 0} behaviours × {info.at_risk} twins, nudge {info.points} pt{info.points === 1 ? "" : "s"}</span>}
      </div>
    );
  }
  const pp = (x: number) => `${x > 0 ? "+" : ""}${(x * 100).toFixed(1)}`;
  const push = (r: TargetingRow) => (r.direction === "up" ? "push up" : r.direction === "down" ? "push down" : "no direction");
  const rows = t.behaviours.filter((r) => r.available);
  return (
    <div className="rounded-md border border-primary/30 bg-primary/5 px-2.5 py-2 space-y-1.5 text-[11px]">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-medium text-foreground/95">Behaviours ranked by movement per point</span>
        <span className="text-muted-foreground tabular-nums">{t.n} twins at risk · nudge {t.points} pt{t.points === 1 ? "" : "s"} · {rows.length} behaviour{rows.length === 1 ? "" : "s"}</span>
        {!t.any_significant && <span className="text-yellow-300/80">no movement distinguishable from zero at this size</span>}
      </div>
      {t.backfires.length > 0 && (
        <div className="rounded border border-red-400/40 bg-red-500/10 px-2 py-1.5 text-red-200/90">
          <span className="font-semibold uppercase tracking-wide text-[10px]">Backfire</span>{" "}
          {t.backfires.map((b) => [b.hurts ? `raising ‘${b.label}’ lowers conversion overall` : "", ...b.bands.map((x) => `pushing ‘${b.label}’ ${b.direction} lowers it for ${x.value} (${pp(x.per_point)} per point)`)].filter(Boolean).join("; ")).join("; ")}
        </div>
      )}
      <ol className="space-y-1">
        {rows.map((r) => (
          <li key={r.key} className={`grid grid-cols-[1.25rem_1fr] gap-x-2 rounded px-1.5 py-1 ${r.hurts || r.backfire.length ? "bg-red-500/5" : r.rank === 1 ? "bg-emerald-500/5" : ""}`}>
            <span className="text-muted-foreground tabular-nums">{r.rank}.</span>
            <div className="min-w-0 space-y-0.5">
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${r.direction === "up" ? "border-emerald-400/40 text-emerald-300/90" : r.direction === "down" ? "border-sky-400/40 text-sky-300/90" : "border-border/60 text-muted-foreground"}`}>{push(r)}</span>
                <span className="font-medium text-foreground/95">{r.label}</span>
                {!r.question_specific && <span className="text-[10px] text-muted-foreground/60">{r.group} dial</span>}
                <span className={`tabular-nums ${r.significant ? "text-foreground/90" : "text-muted-foreground"}`}>{pp(Math.abs(r.per_point))} pts per point <span className="text-muted-foreground">({pp(Math.min(r.per_point_low, r.per_point_high))} to {pp(Math.max(r.per_point_low, r.per_point_high))}) · {r.significant ? "real" : "not distinguishable from zero"}</span></span>
                {r.people && <span className="text-foreground/85 tabular-nums">≈{Math.abs(r.people.per_point).toLocaleString()} people per point</span>}
                {(r.hurts || r.backfire.length > 0) && <span className="text-[10px] px-1.5 py-0.5 rounded-full border border-red-400/50 text-red-300/90">{r.hurts ? "hurts when raised" : "backfires in a band"}</span>}
              </div>
              <div className="text-muted-foreground">
                at {r.points} pt{r.points === 1 ? "" : "s"}: {Math.round(r.then * 100)}% → {Math.round(r.now * 100)}% get through · {r.movement.up} moved through · {r.movement.down} fell back · {r.movement.unchanged} unchanged
                {r.bands.length > 1 && <> · by deprivation: {r.bands.map((b) => `${b.value} ${pp(b.lift / r.points)}${b.thin ? " (thin)" : ""}`).join(" · ")}</>}
              </div>
            </div>
          </li>
        ))}
      </ol>
      <p className="text-[10px] text-muted-foreground/70">The modelled population&apos;s sensitivity to each behaviour, counted from the twins&apos; own placements. It says which behaviour the twins respond to most per point, not that a real intervention moves it that far — that is what a reviewed rule and a lever run are for. The report may only quote this list, in this order, with every backfire.</p>
    </div>
  );
}
