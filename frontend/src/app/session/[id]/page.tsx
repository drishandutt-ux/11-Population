"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, Session, Agent, Post, WSEvent, SpawnOptions, SimMode } from "@/lib/api";
import { getSessionWS } from "@/lib/websocket";
import { Brain, MessageSquare, Network, FileText, Users, ArrowLeft } from "lucide-react";
import InputPanel from "@/components/ingestion/InputPanel";
import ThreadView from "@/components/simulation/ThreadView";
import SimulationControls from "@/components/simulation/SimulationControls";
import KGPanel from "@/components/knowledge-graph/KGPanel";
import ReportChat from "@/components/report/ReportChat";
import AgentDirectory from "@/components/simulation/AgentDirectory";

type Tab = "ingest" | "agents" | "simulation" | "kg" | "report";

const REPORT_PROMPT = `You are a senior analyst. Produce a structured executive briefing for this simulation session.

CRITICAL: Your VERY FIRST line must be "## DIRECT ANSWER" — no preamble, no intro. Use exactly these six sections in this order:

## DIRECT ANSWER
One precise sentence directly answering the user's question. End the section with exactly one of these on its own line: Confidence: HIGH  /  Confidence: MEDIUM  /  Confidence: LOW

## QUESTION
Restate the question being investigated and why it matters.

## SOURCE MATERIALS
What was ingested — document types, names, and their direct relevance to the query. Be specific.

## DISCUSSION
Which perspectives were represented (bullish/bearish, for/against, technical/regulatory, etc.), what the majority view concluded, notable dissenting opinions, and any contradictions or risks flagged during the debate.

## KEY METRICS
The most relevant quantitative data points for this query type. Write ONLY as "Label: Value" lines — one per line, no bullets, no prose. For finance: revenue, margins, multiples, growth rates, price targets. For markets: TAM, market share, adoption rates, unit economics. For policy: risk scores, timelines, compliance rates. Extract actual numbers from the discussion wherever possible.

## OUTCOME
Final recommendation and answer. State the 2–3 key caveats that could change the conclusion.

Use **bold** for critical figures and key conclusions. Write densely — every sentence must carry insight, zero filler.`;


export default function SessionPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [session, setSession] = useState<Session | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("ingest");
  const [agents, setAgents] = useState<Agent[]>([]);
  const [posts, setPosts] = useState<Post[]>([]);
  const [agentsMap, setAgentsMap] = useState<Record<string, Agent>>({});
  const [kgEntities, setKgEntities] = useState<string[]>([]);
  const [kgRelations, setKgRelations] = useState<string[][]>([]);
  const [kgActivity, setKgActivity] = useState<{ time: number; source: string; entities: string[]; relations: string[][] }[]>([]);
  const [isSpawning, setIsSpawning] = useState(false);
  const [spawnProgress, setSpawnProgress] = useState<{ current: number; total: number } | null>(null);
  const [spawnError, setSpawnError] = useState<string | null>(null);
  const [spawnStartTime, setSpawnStartTime] = useState<number | null>(null);
  const [spawnCount, setSpawnCount] = useState<number>(0);

  // Simulation config
  const [intensity, setIntensity] = useState(2);
  const [simMode, setSimMode] = useState<SimMode>("fast");
  // If user clicks "Start" while ingestion is still running, queue the start
  const [pendingSim, setPendingSim] = useState<{ intensity: number; mode: SimMode } | null>(null);

  // Report split-screen state
  const [reportContent, setReportContent] = useState<string | null>(null);
  const [isGeneratingReport, setIsGeneratingReport] = useState(false);

  // Agent opinion KPIs — generated once we have enough posts, refreshed on completion
  const [agentOpinions, setAgentOpinions] = useState<Record<string, string>>({});
  const opinionsLoadedRef = useRef(false);

  const postCountRef = useRef(0);

  const refreshSession = useCallback(async () => {
    try {
      const s = await api.sessions.get(id) as Session;
      setSession(s);
      if (s.agent_count > 0 || s.status !== "created") {
        const a = await api.agents.list(id) as Agent[];
        if (a.length > 0) {
          setAgents(a);
          setAgentsMap(Object.fromEntries(a.map((ag: Agent) => [ag.id, ag])));
        }
      }
    } catch {}
  }, [id]);

  useEffect(() => {
    refreshSession();
    const interval = setInterval(refreshSession, 8000);
    return () => clearInterval(interval);
  }, [refreshSession]);

  // Auto-start simulation once ingestion completes (if user queued a start)
  useEffect(() => {
    if (
      session?.status === "ready" &&
      pendingSim !== null &&
      agents.length > 0
    ) {
      const p = pendingSim;
      setPendingSim(null);
      handleStartSimulation(p.intensity, p.mode);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.status, agents.length]);

  // Load historical posts for completed/paused sessions
  useEffect(() => {
    api.sessions.posts(id)
      .then((p) => {
        const posts = p as Post[];
        if (posts.length > 0) {
          setPosts(posts);
          postCountRef.current = posts.length;
        }
      })
      .catch(() => {});
  }, [id]);

  useEffect(() => {
    const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    fetch(`${base}/api/v1/sessions/${id}/kg`)
      .then((r) => r.json())
      .then((data) => {
        if (data.entities?.length) setKgEntities(data.entities);
        if (data.relations?.length) setKgRelations(data.relations);
      })
      .catch(() => {});
  }, [id]);

  useEffect(() => {
    const ws = getSessionWS(id);
    const unsub = ws.subscribe((event: WSEvent) => {
      if (event.type === "agent_spawned") {
        const agent = event.agent as Agent;
        setAgents((prev) => {
          if (prev.find((a) => a.id === agent.id)) return prev;
          return [...prev, agent];
        });
        setAgentsMap((prev) => ({ ...prev, [agent.id]: agent }));
        const idx = (event as any).index ?? 0;
        const total = (event as any).total ?? 1;
        setSpawnProgress({ current: idx + 1, total });

      } else if (event.type === "agents_spawned_batch") {
        const incoming = (event.agents as Agent[]) || [];
        setAgents((prev) => {
          const seen = new Set(prev.map((a) => a.id));
          const merged = prev.slice();
          for (const a of incoming) if (!seen.has(a.id)) merged.push(a);
          return merged;
        });
        setAgentsMap((prev) => {
          const next = { ...prev };
          for (const a of incoming) next[a.id] = a;
          return next;
        });
        setSpawnProgress({ current: event.spawned, total: event.total });

      } else if (event.type === "agents_ready") {
        setIsSpawning(false);
        setSpawnProgress(null);
        refreshSession();

      } else if (event.type === "spawn_error") {
        setIsSpawning(false);
        setSpawnProgress(null);
        setSpawnError((event as any).error || "Failed to spawn agents");

      } else if (event.type === "simulation_started") {
        setActiveTab("simulation");

      } else if (event.type === "post_created") {
        const fullAgent = event.agent as Agent;
        setPosts((prev) => [...prev, event.post]);
        setAgentsMap((prev) => ({ ...prev, [fullAgent.id]: fullAgent }));
        postCountRef.current += 1;
        // Note: we intentionally do NOT switch tabs here. Posts keep streaming into
        // the Thread tab regardless of where the user is, so they can browse freely.

      } else if (event.type === "like_added") {
        setPosts((prev) =>
          prev.map((p) => p.id === event.post_id ? { ...p, likes: event.new_likes } : p)
        );

      } else if (event.type === "kg_updated") {
        const ev = event as any;
        const newEnts: string[] = ev.new_entities || [];
        const newRels: string[][] = ev.new_relations || [];
        if (newEnts.length > 0) setKgEntities((prev) => Array.from(new Set([...prev, ...newEnts])));
        if (newRels.length > 0) setKgRelations((prev) => [...prev, ...newRels]);
        if (newEnts.length > 0 || newRels.length > 0) {
          setKgActivity((prev) => [
            { time: Date.now(), source: ev.source || "system", entities: newEnts, relations: newRels },
            ...prev.slice(0, 49),
          ]);
        }

      } else if (event.type === "ingest_complete") {
        refreshSession();

      } else if (event.type === "simulation_complete") {
        refreshSession();
        // Refresh opinions with final posts
        api.sessions.opinions(id)
          .then((d: any) => { if (d.opinions) setAgentOpinions(d.opinions); })
          .catch(() => {});
      }
    });
    return () => { unsub(); };
  }, [id, refreshSession]);

  // First-time opinion generation: fire once we have at least one post per agent
  useEffect(() => {
    if (opinionsLoadedRef.current) return;
    if (posts.length >= Math.max(agents.length, 3) && agents.length > 0) {
      opinionsLoadedRef.current = true;
      api.sessions.opinions(id)
        .then((d: any) => { if (d.opinions) setAgentOpinions(d.opinions); })
        .catch(() => {});
    }
  }, [posts.length, agents.length, id]);

  async function handleSpawn(count: number, opts?: SpawnOptions) {
    setIsSpawning(true);
    setSpawnProgress(null);
    setSpawnError(null);
    setSpawnStartTime(Date.now());
    setSpawnCount(count);
    setAgents([]);
    setAgentsMap({});
    try {
      await api.simulation.spawnAgents(id, count, opts);
    } catch (e: any) {
      setIsSpawning(false);
      setSpawnError(e.message || "Failed to start spawning");
    }
  }

  async function handleApplyPreset(presetId: string) {
    setIsSpawning(true);
    setSpawnProgress(null);
    setSpawnError(null);
    setSpawnStartTime(Date.now());
    setSpawnCount(0); // unknown until first agent_spawned event reports the total
    setAgents([]);
    setAgentsMap({});
    try {
      await api.presets.apply(id, presetId);
    } catch (e: any) {
      setIsSpawning(false);
      setSpawnError(e.message || "Failed to load lineup");
    }
  }

  async function handleStartSimulation(nextIntensity?: number, nextMode?: SimMode) {
    const it = nextIntensity ?? intensity;
    const md = nextMode ?? simMode;
    setIntensity(it);
    setSimMode(md);
    // If session is still ingesting, queue the start — it will auto-fire when ready
    if (session?.status === "ingesting") {
      setPendingSim({ intensity: it, mode: md });
      setActiveTab("simulation"); // go to thread so user sees the waiting state
      return;
    }
    try {
      await api.simulation.start(id, it, md);
      setActiveTab("simulation");
      refreshSession();
    } catch (e: any) {
      // 409 = backend says still ingesting — queue it
      if (e?.status === 409 || e?.message?.includes("ingesting")) {
        setPendingSim({ intensity: it, mode: md });
        setActiveTab("simulation");
      } else {
        console.error("Start simulation failed:", e);
      }
    }
  }

  async function handleMakeReport() {
    setIsGeneratingReport(true);
    setActiveTab("report"); // switch immediately so user sees the generating state
    try {
      const result = await api.report.query(id, REPORT_PROMPT) as { answer: string };
      setReportContent(result.answer);
    } catch (e: any) {
      // Never fail silently — surface the reason in the report panel so the button
      // is never a no-op. A thrown 404 means the session was wiped (no persistence).
      console.error("Report generation failed:", e);
      const msg = e?.message || "Unknown error";
      const sessionGone = /not found|404/i.test(msg);
      setReportContent(
        sessionGone
          ? "## Report unavailable\n\nThis session no longer exists on the server. This demo has **no persistent storage**, so sessions are wiped whenever the backend restarts or redeploys.\n\nPlease start a **new session** and re-run the simulation."
          : `## Report generation failed\n\n${msg}\n\nPlease try again — the model may be busy or the backend may be restarting.`
      );
    } finally {
      setIsGeneratingReport(false);
    }
  }

  const tabs: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: "ingest", label: "Ingest", icon: <Brain className="w-3.5 h-3.5" /> },
    { key: "agents", label: agents.length > 0 ? `Agents (${agents.length})` : "Agents", icon: <Users className="w-3.5 h-3.5" /> },
    { key: "simulation", label: posts.length > 0 ? `Thread (${posts.length})` : "Thread", icon: <MessageSquare className="w-3.5 h-3.5" /> },
    { key: "kg", label: "Graph", icon: <Network className="w-3.5 h-3.5" /> },
    { key: "report", label: "Report", icon: <FileText className="w-3.5 h-3.5" /> },
  ];

  return (
    <div className="h-screen bg-background flex flex-col overflow-hidden">
      {/* Header */}
      <header className="border-b border-border/60 px-5 py-3 flex items-center gap-3 shrink-0">
        <button
          onClick={() => router.push("/")}
          className="text-muted-foreground hover:text-foreground transition-colors p-1 -ml-1 rounded"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm font-medium text-foreground truncate">{session?.title || "Loading…"}</span>
          {session && <StatusDot status={session.status} />}
        </div>
        <div className="ml-auto">
          {session && (
            <SimulationControls sessionId={id} status={session.status} intensity={intensity} mode={simMode} onUpdate={refreshSession} />
          )}
        </div>
      </header>

      {/* Tabs */}
      <div className="border-b border-border/60 px-5 flex gap-0 shrink-0">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium border-b-2 transition-colors whitespace-nowrap ${
              activeTab === t.key
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-hidden min-h-0">
        {activeTab === "ingest" && session && (
          <InputPanel
            session={session}
            onIngested={refreshSession}
            onGoToAgents={() => setActiveTab("agents")}
          />
        )}
        {activeTab === "agents" && (
          <AgentDirectory
            agents={agents}
            sessionId={id}
            sessionStatus={session?.status || "created"}
            isSpawning={isSpawning}
            spawnProgress={spawnProgress}
            spawnError={spawnError}
            spawnStartTime={spawnStartTime}
            spawnCount={spawnCount}
            isPendingSimulation={pendingSim !== null}
            onSpawn={(count, opts) => handleSpawn(count, opts)}
            onStartSimulation={(it, md) => handleStartSimulation(it, md)}
            onGoToThread={() => setActiveTab("simulation")}
            onGoToReport={() => setActiveTab("report")}
            onApplyPreset={handleApplyPreset}
          />
        )}
        {activeTab === "simulation" && (
          <ThreadView
            posts={posts}
            agentsMap={agentsMap}
            sessionStatus={session?.status || "created"}
            pendingSimulation={pendingSim !== null}
            onMakeReport={handleMakeReport}
            isGeneratingReport={isGeneratingReport}
            agentOpinions={agentOpinions}
          />
        )}
        {activeTab === "kg" && (
          <KGPanel sessionId={id} entities={kgEntities} relations={kgRelations} activity={kgActivity} />
        )}
        {activeTab === "report" && session && (
          <ReportChat
            sessionId={id}
            query={session.query}
            agents={agents}
            reportContent={reportContent}
            isGeneratingReport={isGeneratingReport}
            onMakeReport={handleMakeReport}
            onClearReport={() => setReportContent(null)}
          />
        )}
      </div>
    </div>
  );
}

function StatusDot({ status }: { status: string }) {
  const colors: Record<string, string> = {
    created: "bg-slate-500",
    ingesting: "bg-yellow-400 animate-pulse",
    ready: "bg-emerald-400",
    simulating: "bg-blue-400 animate-pulse",
    paused: "bg-orange-400",
    complete: "bg-primary",
    error: "bg-red-400",
  };
  const labels: Record<string, string> = {
    created: "created", ingesting: "ingesting", ready: "ready",
    simulating: "simulating", paused: "paused", complete: "complete", error: "error",
  };
  return (
    <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${colors[status] || colors.created}`} />
      {labels[status] || status}
    </span>
  );
}
