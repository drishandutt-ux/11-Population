"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, apiFetch, Agent, AgentPreset, EvidenceItem, FrameCategory, PopulationBuild, PopulationConstraints, PopulationLogEntry, PopulationSegment, QuantSource, ResearchState, Session, SimMode, WSEvent } from "@/lib/api";
import { getSessionWS } from "@/lib/websocket";
import DialsPanel, { DEFAULT_CONSTRAINTS } from "@/components/population/DialsPanel";
import SourcesPanel from "@/components/population/SourcesPanel";
import { BuildLog, QuestionsCard, STATUS_LABEL, Stepper, isActive } from "@/components/population/BuildLog";
import PlanReview from "@/components/population/PlanReview";
import SamplingFrameGraph from "@/components/population/SamplingFrameGraph";
import FrameCard from "@/components/population/FrameCard";
import ErrorBoundary from "@/components/ErrorBoundary";
import { ArrowLeft, Users, Sparkles, Loader2, Square, RefreshCw, Check, AlertCircle, Wand2, Bookmark, Network } from "lucide-react";

interface Props {
  sessionId: string;
  /** Rendered inside the session's Agents tab (no back arrow, fills the tab) rather than as its own page. */
  embedded?: boolean;
  /** Where "View agents" goes when embedded; the standalone page navigates to the Agents tab. */
  onViewAgents?: () => void;
  /** Saved lineups, offered before a build exists as the quick alternative to planning one. */
  presets?: AgentPreset[];
  onApplyPreset?: (presetId: string) => void;
  onDeletePreset?: (presetId: string) => void;
}

/** The Population Studio: detect → gather → clarify → plan → review → build, with the analyst in the loop. */
export default function PopulationStudio({ sessionId: id, embedded = false, onViewAgents, presets = [], onApplyPreset, onDeletePreset }: Props) {
  const router = useRouter();

  const [session, setSession] = useState<Session | null>(null);
  const [build, setBuild] = useState<PopulationBuild | null>(null);
  const [looseLog, setLooseLog] = useState<PopulationLogEntry[]>([]);   // log lines that arrive before a build exists (standalone searches)
  const [constraints, setConstraints] = useState<PopulationConstraints>(DEFAULT_CONSTRAINTS);
  const [count, setCount] = useState(50);
  const [mode, setMode] = useState<SimMode>("fast");
  const [catalogue, setCatalogue] = useState<QuantSource[]>([]);
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [quantOnBuild, setQuantOnBuild] = useState(true);
  const [quantQuery, setQuantQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [facts, setFacts] = useState<EvidenceItem[]>([]);
  const [research, setResearch] = useState<ResearchState | null>(null);
  const [kgCounts, setKgCounts] = useState<{ entities: number; relations: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [busySegs, setBusySegs] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [spawn, setSpawn] = useState<{ current: number; total: number } | null>(null);
  const [agentCount, setAgentCount] = useState(0);
  // The sampling-frame graph inflates its cells with personas: the roster on file, then every
  // batch that streams in during a build.
  const [liveAgents, setLiveAgents] = useState<Partial<Agent>[]>([]);
  const [frameOpen, setFrameOpen] = useState(false);
  const loadAgents = useCallback(async () => {
    try { setLiveAgents((await api.agents.list(id)) as Agent[]); } catch {}
  }, [id]);
  const seededRef = useRef(false);
  /** True once the analyst ticks or unticks a publisher; until then the selection follows the geography. */
  const sourcesTouchedRef = useRef(false);

  const viewAgents = () => (onViewAgents ? onViewAgents() : router.push(`/session/${id}?tab=agents`));

  // ── load ──
  const loadBuild = useCallback(async () => {
    try {
      const { build: b } = await api.population.latest(id);
      setBuild(b);
      if (b && !seededRef.current) {
        // A reload restores the dials the build was started with, so re-plan edits them rather than resets them.
        seededRef.current = true;
        setConstraints({ ...DEFAULT_CONSTRAINTS, ...(b.constraints || {}) });
        setCount(b.target_count);
        setMode(b.mode);
        if (b.sources?.quant_sources?.length) setSelectedSources(b.sources.quant_sources);
        if (typeof b.sources?.quant === "boolean") setQuantOnBuild(b.sources.quant);
      }
    } catch {}
  }, [id]);

  const loadFacts = useCallback(async () => {
    try { setFacts(await api.population.facts(id)); } catch {}
  }, [id]);

  useEffect(() => {
    // The lookup box is left empty on purpose: the build gathers statistics on its own, and a
    // prefilled question made the optional lookup read like a required step.
    api.sessions.get(id).then((s) => { setSession(s as Session); setAgentCount((s as Session).agent_count || 0); }).catch(() => {});
    api.research.state(id).then(setResearch).catch(() => {});
    apiFetch(`/sessions/${id}/kg`).then((r) => r.json()).then((d) => setKgCounts({ entities: (d.entities || []).length, relations: (d.relations || []).length })).catch(() => {});
    loadBuild();
    loadFacts();
    loadAgents();
  }, [id, loadBuild, loadFacts, loadAgents]);

  // Default source ticks follow the geography: what detect found, else the research frame's region,
  // else the question itself (UK regions and cities count as UK). An untouched selection keeps
  // following it; once the analyst ticks a publisher the choice is theirs. A build that re-derived
  // its publishers (quant_auto) reports them back in its sources.
  const buildSources = build?.sources?.quant_sources?.join("|") || "";
  useEffect(() => {
    const geo = build?.detected?.geography || (research?.run?.plan?.web_region as string | undefined) || session?.query || "";
    api.population.sources(geo).then(({ sources, default: def }) => {
      setCatalogue(sources);
      if (sourcesTouchedRef.current) return;
      setSelectedSources(buildSources ? buildSources.split("|") : def);
    }).catch(() => {});
  }, [build?.detected?.geography, research?.run?.plan?.web_region, session?.query, buildSources]);

  // ── live events ──
  useEffect(() => {
    const ws = getSessionWS(id);
    const unsub = ws.subscribe((ev: WSEvent) => {
      if (ev.type === "population_log") {
        if (!ev.build_id) { setLooseLog((l) => [...l, ev.entry].slice(-200)); return; }
        setBuild((b) => (b && b.id === ev.build_id ? { ...b, log: [...(b.log || []), ev.entry] } : b));
      } else if (ev.type === "population_build") {
        setBuild((b) => {
          // The full build replaces our copy; keep any log lines that raced ahead of it.
          const incoming = ev.build;
          if (b && b.id === incoming.id && (b.log?.length || 0) > (incoming.log?.length || 0)) return { ...incoming, log: b.log };
          return incoming;
        });
      } else if (ev.type === "population_quant_done") {
        setSearching(false);
        loadFacts();
      } else if (ev.type === "research_item" && ev.item.source_class === "quant") {
        setFacts((prev) => { const k = prev.findIndex((x) => x.id === ev.item.id); return k >= 0 ? prev.map((x) => (x.id === ev.item.id ? ev.item : x)) : [...prev, ev.item]; });
      } else if (ev.type === "research_brief" || ev.type === "research_complete" || ev.type === "research_status" || ev.type === "research_error" || ev.type === "research_started") {
        api.research.state(id).then(setResearch).catch(() => {});
      } else if (ev.type === "agents_spawned_batch") {
        setSpawn({ current: ev.spawned, total: ev.total });
        setLiveAgents((prev) => {
          // A build wipes the roster first; the first batch of a new build starts the frame afresh.
          const fresh = ev.spawned <= ev.agents.length ? [] : prev;
          return [...fresh, ...ev.agents];
        });
      } else if (ev.type === "agents_ready") {
        setSpawn(null);
        setAgentCount(ev.count);
        loadAgents();
      } else if (ev.type === "spawn_error") {
        setSpawn(null);
        setError(ev.error || "Build failed");
      } else if (ev.type === "kg_updated") {
        setKgCounts((k) => ({ entities: (k?.entities || 0) + ((ev as any).new_entities?.length || 0), relations: (k?.relations || 0) + ((ev as any).new_relations?.length || 0) }));
      }
    });
    return () => { unsub(); };
  }, [id, loadFacts, loadAgents]);

  // Backstop poll while something runs (the socket can drop a burst). Clarifying counts: the
  // answers call returns before the plan stage starts, so the move to awaiting_review arrives
  // over the socket — or, if that dropped, from this poll.
  useEffect(() => {
    if (!build || !(isActive(build.status) || build.status === "clarifying")) return;
    const t = setInterval(loadBuild, 6000);
    return () => clearInterval(t);
  }, [build?.status, build?.id, loadBuild]);

  // The research panel on the Ingest tab may be stopped or finish while this page is open.
  const researchRunning = !!research?.run && ["queued", "running", "stopping", "finalising"].includes(research.run.status);
  useEffect(() => {
    if (!researchRunning) return;
    const t = setInterval(() => { api.research.state(id).then(setResearch).catch(() => {}); }, 8000);
    return () => clearInterval(t);
  }, [researchRunning, id]);

  // Dials the detect stage set from the research land on the build; mirror them into the
  // panel (the analyst could not have moved a dial meanwhile — the panel is locked while a
  // stage runs), so what the plan will honour is what the panel shows.
  const derivedRef = useRef<string>("");
  useEffect(() => {
    const derived = build?.constraints?.derived_from_research;
    if (!derived || !Object.keys(derived).length) return;
    const sig = `${build?.id}:${JSON.stringify(derived)}`;
    if (derivedRef.current === sig) return;
    derivedRef.current = sig;
    setConstraints((c) => ({ ...c, demographics: { ...c.demographics, ...(build!.constraints.demographics || {}) }, sentiment: { ...c.sentiment, ...(build!.constraints.sentiment || {}) }, derived_from_research: derived }));
  }, [build?.id, build?.constraints?.derived_from_research]);

  const fullConstraints = useMemo<PopulationConstraints>(() => ({ ...constraints, profile_query: constraints.profile_query || "", doc_context: constraints.doc_context || "" }), [constraints]);
  const active = isActive(build?.status);
  const status = build?.status;
  const entries = build ? build.log : looseLog;
  const keptCount = build?.plan ? build.plan.segments.filter((s) => s.decision !== "rejected").reduce((n, s) => n + (s.count || 0), 0) : 0;
  const regenerating = new Set((build?.plan?.segments || []).filter((s) => s.decision === "rejected" && !s.replaced).map((s) => s.id));

  // ── actions ──
  async function guard<T>(fn: () => Promise<T>) {
    setBusy(true); setError(null);
    try { return await fn(); }
    catch (e: any) { setError(e?.message || "Something went wrong"); }
    finally { setBusy(false); }
  }

  const startBuild = () => guard(async () => {
    setLooseLog([]);
    const b = await api.population.start(id, { mode, count, constraints: fullConstraints, sources: { quant: quantOnBuild, quant_sources: selectedSources, quant_query: "", quant_auto: !sourcesTouchedRef.current } });
    seededRef.current = true;
    setBuild(b);
  });
  const answer = (answers: Record<string, string>, skip: boolean) => guard(async () => { if (build) setBuild(await api.population.answer(id, build.id, answers, skip)); });
  const decide = async (segmentId: string, body: { decision: "accept" | "reject" | "edit"; edits?: Partial<PopulationSegment>; reason?: string }) => {
    if (!build) return;
    setBusySegs((s) => new Set(s).add(segmentId));
    setError(null);
    try { setBuild(await api.population.decide(id, build.id, segmentId, body)); }
    catch (e: any) { setError(e?.message || "Could not record that decision"); }
    finally { setBusySegs((s) => { const n = new Set(s); n.delete(segmentId); return n; }); }
  };
  const replan = () => guard(async () => { if (build) setBuild(await api.population.replan(id, build.id, { constraints: fullConstraints, count, keep_accepted: true })); });
  const approve = () => guard(async () => { if (build) { setSpawn({ current: 0, total: keptCount }); setLiveAgents([]); setBuild(await api.population.approve(id, build.id, { count, mode })); } });
  const stop = () => guard(async () => { if (build) await api.population.stop(id, build.id); });
  const frameAction = async (dimKey: string, body: { action: "estimate" | "upload" | "proxy" | "skip"; categories?: FrameCategory[]; source?: string; proxy_of?: string }) => {
    await guard(async () => { if (build) setBuild(await api.population.frameAction(id, build.id, dimKey, body)); });
  };
  const estimateAll = () => guard(async () => { if (build) setBuild(await api.population.frameEstimateAll(id, build.id)); });
  const search = async () => {
    setSearching(true); setError(null);
    try { await api.population.quantSearch(id, quantQuery, selectedSources, build?.id ?? null); }
    catch (e: any) { setSearching(false); setError(e?.message || "Search failed"); }
  };
  const toggleFact = async (item: EvidenceItem) => {
    try { const u = await api.research.exclude(id, item.id, !item.excluded); setFacts((prev) => prev.map((x) => (x.id === u.id ? u : x))); } catch {}
  };

  const dialsLocked = active;

  return (
    <div className={`${embedded ? "h-full" : "h-screen"} bg-background flex flex-col overflow-hidden`}>
      <header className="border-b border-border/60 px-5 py-3 flex items-center gap-3 shrink-0">
        {!embedded && (
          <button onClick={viewAgents} className="text-muted-foreground hover:text-foreground transition-colors p-1 -ml-1 rounded" title="Back to Agents"><ArrowLeft className="w-4 h-4" /></button>
        )}
        <Wand2 className="w-4 h-4 text-primary" />
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-foreground">Population Studio</span>
            {status && <span className={`text-[10px] px-1.5 py-0.5 rounded border ${status === "error" ? "border-red-500/30 text-red-300" : status === "complete" ? "border-emerald-500/30 text-emerald-300" : status === "awaiting_review" || status === "clarifying" || status === "stopped" ? "border-amber-500/30 text-amber-300" : "border-primary/30 text-primary"}`}>{status === "stopped" && build?.plan ? "stopped — plan ready to build" : STATUS_LABEL[status] || status}</span>}
          </div>
          <p className="text-[11px] text-muted-foreground truncate">{embedded ? "Build the population from evidence and statistics, with you in the loop" : session?.title || "Loading…"}</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {build && (
            <button onClick={() => setFrameOpen(true)} className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border border-primary/30 text-primary hover:bg-primary/10" title="The cells the population is drawn from, inflating with personas as they are written">
              <Network className="w-3.5 h-3.5" /> Sampling frame
              {(active || spawn) && <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />}
            </button>
          )}
          {spawn && <span className="flex items-center gap-1.5 text-[11px] text-primary"><Loader2 className="w-3.5 h-3.5 animate-spin" /> {spawn.current}/{spawn.total} agents</span>}
          {agentCount > 0 && !spawn && (
            <button onClick={viewAgents} className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border border-border/60 text-muted-foreground hover:text-foreground"><Users className="w-3.5 h-3.5" /> {agentCount} agents</button>
          )}
        </div>
      </header>

      <div className="flex-1 min-h-0 overflow-y-auto xl:overflow-hidden grid grid-cols-1 xl:grid-cols-[320px_minmax(0,1fr)_340px] xl:grid-rows-[minmax(0,1fr)]">
        {/* Sources */}
        <aside className="xl:min-h-0 xl:overflow-y-auto border-b xl:border-b-0 xl:border-r border-border/40 p-4 order-2 xl:order-1">
          <ErrorBoundary label="The sources panel">
            <SourcesPanel
              sessionQuery={session?.query || ""}
              research={research}
              kgCounts={kgCounts}
              catalogue={catalogue}
              selected={selectedSources}
              onSelected={(keys) => { sourcesTouchedRef.current = true; setSelectedSources(keys); }}
              quantQuery={quantQuery}
              onQuantQuery={setQuantQuery}
              quantOnBuild={quantOnBuild}
              onQuantOnBuild={setQuantOnBuild}
              onSearch={search}
              searching={searching}
              buildStatus={build?.status ?? null}
              facts={facts}
              onToggleFact={toggleFact}
              profileQuery={constraints.profile_query || ""}
              onProfileQuery={(v) => setConstraints((c) => ({ ...c, profile_query: v }))}
              docContext={constraints.doc_context || ""}
              onDocContext={(t) => setConstraints((c) => ({ ...c, doc_context: t }))}
              disabled={dialsLocked}
            />
          </ErrorBoundary>
        </aside>

        {/* Build */}
        <main className="xl:min-h-0 xl:overflow-y-auto p-4 space-y-4 order-1 xl:order-2">
          <div className="flex items-center gap-3 flex-wrap">
            <Stepper status={status} />
            {active && build && (
              <button disabled={busy} onClick={stop} className="ml-auto flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-lg border border-red-500/30 text-red-300 hover:bg-red-500/10 disabled:opacity-40" title={status === "spawning" ? "Stop generating; the personas already written are kept" : "Skip the rest of the gathering and compose the plan from what is on file"}><Square className="w-3 h-3" /> {status === "spawning" ? "Stop & keep" : "Stop & plan now"}</button>
            )}
          </div>

          {error && (
            <div className="flex items-center gap-2 text-xs text-red-300 bg-red-500/10 border border-red-500/25 rounded-xl px-3 py-2"><AlertCircle className="w-4 h-4 shrink-0" /> {error}</div>
          )}

          {!build && (
            <div className="glass rounded-2xl p-6 text-center space-y-2">
              <div className="w-12 h-12 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center mx-auto"><Sparkles className="w-6 h-6 text-primary" /></div>
              <h2 className="text-base font-semibold text-foreground">Build a population you can vouch for</h2>
              <p className="text-xs text-muted-foreground max-w-lg mx-auto leading-relaxed">
                The Studio reads your evidence, gathers base rates from statistics publishers, asks you what it can&apos;t infer, and proposes the population as
                segments — each with its share, demographics, mood and the logic behind it. You accept, edit or reject every segment before a single agent is written.
              </p>
              <div className="pt-2">
                <button disabled={busy || !session} onClick={startBuild} className="inline-flex items-center gap-2 bg-primary hover:bg-primary/90 text-primary-foreground font-semibold px-5 py-2.5 rounded-xl text-sm disabled:opacity-50">
                  {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />} Detect &amp; plan for {count} agents
                </button>
              </div>
            </div>
          )}

          {!build && presets.length > 0 && onApplyPreset && (
            <div className="glass rounded-2xl p-4">
              <div className="flex items-center gap-2 mb-3">
                <Bookmark className="w-3.5 h-3.5 text-primary" />
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Or load a saved lineup</span>
              </div>
              <div className="space-y-2">
                {presets.map((preset) => (
                  <div key={preset.id} className="flex items-center gap-3 px-3 py-2 rounded-xl border border-border/40 bg-muted/30">
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-foreground truncate">{preset.name}</div>
                      <div className="text-[11px] text-muted-foreground">{preset.agent_count} agents · {new Date(preset.created_at).toLocaleDateString()}</div>
                    </div>
                    <button onClick={() => onApplyPreset(preset.id)} className="shrink-0 text-xs font-medium px-3 py-1.5 rounded-lg bg-primary/10 border border-primary/20 text-primary hover:bg-primary/20 transition-colors">Load</button>
                    {onDeletePreset && (
                      <button onClick={() => onDeletePreset(preset.id)} className="shrink-0 text-xs text-muted-foreground/50 hover:text-red-400 transition-colors px-1" title="Delete this lineup">×</button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          <ErrorBoundary label="The build log">
            <BuildLog entries={entries} active={active || searching} />
          </ErrorBoundary>

          {build?.detected && (
            <div className="glass rounded-2xl p-4 space-y-1.5">
              <div className="flex items-center gap-2"><span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Detected</span><span className={`text-[10px] px-1.5 py-0.5 rounded border ${build.detected.confidence >= 60 ? "border-emerald-500/30 text-emerald-300" : "border-yellow-500/30 text-yellow-300"}`}>{build.detected.confidence}% confident</span></div>
              <p className="text-xs text-foreground/90"><span className="text-muted-foreground">Population:</span> {build.detected.target_population}</p>
              <p className="text-[11px] text-muted-foreground"><span className="text-foreground/70">{build.detected.population_kind}</span> · {build.detected.geography} · {build.detected.decision}</p>
              {build.detected.segments_hinted?.length ? <p className="text-[11px] text-muted-foreground/80">Groups implied: {build.detected.segments_hinted.join(" · ")}</p> : null}
            </div>
          )}

          {build?.frame && (
            <ErrorBoundary label="The sampling frame">
              <FrameCard build={build} busy={busy} readOnly={active} onAction={frameAction} onEstimateAll={estimateAll} />
            </ErrorBoundary>
          )}

          {build && status === "clarifying" && (
            <ErrorBoundary label="The questions">
              <QuestionsCard build={build} onAnswer={answer} busy={busy} />
            </ErrorBoundary>
          )}

          {build?.plan && (
            <ErrorBoundary label="The plan">
              <PlanReview build={build} onDecide={decide} busyIds={new Set([...busySegs, ...regenerating])} readOnly={status === "spawning"} />
            </ErrorBoundary>
          )}

          {status === "complete" && (
            <div className="glass rounded-2xl p-4 flex items-center gap-3 border border-emerald-500/25">
              <Check className="w-5 h-5 text-emerald-400" />
              <div className="flex-1">
                <p className="text-sm font-semibold text-foreground">Population built</p>
                <p className="text-[11px] text-muted-foreground">{agentCount} agents carry their segment, demographics and dials. Adjust the dials and re-plan, or go and run them.</p>
              </div>
              <button onClick={viewAgents} className="flex items-center gap-1.5 text-xs font-semibold px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90"><Users className="w-3.5 h-3.5" /> View agents</button>
            </div>
          )}
        </main>

        {/* Dials */}
        <aside className="xl:min-h-0 flex flex-col border-t xl:border-t-0 xl:border-l border-border/40 order-3">
          <div className="flex-1 min-h-0 xl:overflow-y-auto p-4">
            <ErrorBoundary label="The dials">
              <DialsPanel constraints={constraints} onChange={setConstraints} count={count} onCount={setCount} mode={mode} onMode={setMode} disabled={active} />
              {build?.plan?.voice && (
                <p className="text-[10px] text-pink-300/80 mt-3 leading-relaxed"><span className="font-semibold">Expert ↔ Reactive in this plan: {build.plan.voice.value}/100</span>{build.plan.voice.auto ? " (chosen by the system)" : " (set by you)"}{build.plan.voice.reason ? ` — ${build.plan.voice.reason}` : ""}</p>
              )}
              {constraints.derived_from_research && Object.keys(constraints.derived_from_research).length > 0 && (
                <p className="text-[10px] text-emerald-300/80 mt-3 leading-relaxed"><span className="font-semibold">Set from the research:</span> {Object.keys(constraints.derived_from_research).map((k) => k.replace(/_/g, " ")).join(", ")}. Move any dial to override it; Re-plan applies your change.</p>
              )}
            </ErrorBoundary>
            <label className="flex items-start gap-2 mt-3 cursor-pointer">
              <input type="checkbox" checked={!!constraints.skip_questions} disabled={active} onChange={(e) => setConstraints((c) => ({ ...c, skip_questions: e.target.checked }))} className="mt-0.5 accent-[hsl(var(--primary))]" />
              <span className="text-[10px] text-muted-foreground leading-relaxed">Don&apos;t ask me clarifying questions — plan on the defaults.</span>
            </label>
          </div>
          <div className="p-4 border-t border-border/40 space-y-2 shrink-0 sticky bottom-0 bg-background xl:static">
            {/* A plan on file can always be built — after review, after a stop, or again after a build. */}
            {build?.plan && !active && (
              <>
                <button disabled={busy || regenerating.size > 0} onClick={approve} className="w-full flex items-center justify-center gap-2 bg-primary hover:bg-primary/90 text-primary-foreground font-semibold py-2.5 rounded-xl text-sm disabled:opacity-50">
                  {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />} {status === "complete" ? "Rebuild" : "Approve & build"} {keptCount} agents · {mode === "pro" ? "Pro" : "Fast"}
                </button>
                <button disabled={busy} onClick={replan} className="w-full flex items-center justify-center gap-2 border border-border/60 text-muted-foreground hover:text-foreground font-medium py-2 rounded-xl text-xs disabled:opacity-50">
                  <RefreshCw className="w-3.5 h-3.5" /> Re-plan with these dials (keeps accepted)
                </button>
                {regenerating.size > 0 && <p className="text-[10px] text-muted-foreground/70 text-center">Waiting for {regenerating.size} replacement segment{regenerating.size === 1 ? "" : "s"}…</p>}
                {mode === "pro" && keptCount > 150 && <p className="text-[10px] text-amber-300/90 text-center">Pro writes {keptCount} personas on Sonnet — several minutes and real API spend.</p>}
              </>
            )}
            {(!build || (!active && status !== "clarifying")) && (
              <button disabled={busy || !session} onClick={startBuild} className={`w-full flex items-center justify-center gap-2 font-semibold rounded-xl disabled:opacity-50 ${build?.plan ? "border border-border/60 text-muted-foreground hover:text-foreground py-2 text-xs" : "bg-primary hover:bg-primary/90 text-primary-foreground py-2.5 text-sm"}`}>
                {busy && !build?.plan ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className={build?.plan ? "w-3.5 h-3.5" : "w-4 h-4"} />} {build ? "Start a new plan from scratch" : "Detect & plan"} · {count} agents
              </button>
            )}
            {build && status === "clarifying" && (
              <>
                <p className="text-[11px] text-muted-foreground text-center">Answer the questions in the middle, or</p>
                <button disabled={busy} onClick={() => answer({}, true)} className="w-full flex items-center justify-center gap-2 border border-border/60 text-muted-foreground hover:text-foreground font-medium py-2 rounded-xl text-xs disabled:opacity-50">
                  <Check className="w-3.5 h-3.5" /> Skip the questions &amp; plan now
                </button>
              </>
            )}
            {active && build && (
              <>
                <p className="text-[11px] text-muted-foreground text-center flex items-center justify-center gap-1.5"><Loader2 className="w-3 h-3 animate-spin" /> {STATUS_LABEL[status || ""]}</p>
                <button disabled={busy} onClick={stop} className="w-full flex items-center justify-center gap-2 border border-red-500/30 text-red-300 hover:bg-red-500/10 font-medium py-2 rounded-xl text-xs disabled:opacity-50">
                  <Square className="w-3.5 h-3.5" /> {status === "spawning" ? "Stop — keep the agents written so far" : "Stop — plan now with what we have"}
                </button>
              </>
            )}
          </div>
        </aside>
      </div>
      {frameOpen && (
        <SamplingFrameGraph build={build} frame={build?.frame || null} agents={liveAgents} targetCount={count} spawning={status === "spawning" || !!spawn} onClose={() => setFrameOpen(false)} />
      )}
    </div>
  );
}
