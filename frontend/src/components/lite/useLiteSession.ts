"use client";

/** The simple view's slice of a session: the same API, socket and events the pro page uses,
 *  reduced to what the wrapper needs to decide which screen to show. Every analysis still
 *  happens in the backend exactly as it does for the pro portal. */

import { useCallback, useEffect, useRef, useState } from "react";
import { api, Agent, OutcomeRecord, PopulationBuild, Post, ReportStructure, ResearchState, Session, WSEvent } from "@/lib/api";
import { getSessionWS } from "@/lib/websocket";
import { LITE_DEFAULTS } from "@/lib/lite";

export type OpinionsStatus = "idle" | "loading" | "done" | "error";
export type ChatMsg = { role: "user" | "assistant"; content: string };

const BUILD_ACTIVE = new Set(["queued", "detecting", "gathering", "clarifying", "planning", "spawning"]);
/** A build is "getting ready" while a stage runs — and, for a simple-view build, while the plan
 *  waits for the automatic approval. A plan waiting for a person (the pro Studio) is not. */
function buildInFlight(b: PopulationBuild | null): boolean {
  if (!b) return false;
  if (BUILD_ACTIVE.has(b.status)) return true;
  return b.status === "awaiting_review" && !!(b.constraints as any)?.auto_run;
}

export function useLiteSession(id: string) {
  const [session, setSession] = useState<Session | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentsMap, setAgentsMap] = useState<Record<string, Agent>>({});
  const [posts, setPosts] = useState<Post[]>([]);
  const [build, setBuild] = useState<PopulationBuild | null>(null);
  const [research, setResearch] = useState<ResearchState | null>(null);
  const [spawnProgress, setSpawnProgress] = useState<{ current: number; total: number } | null>(null);
  const [spawnError, setSpawnError] = useState<string | null>(null);

  const [opinions, setOpinions] = useState<Record<string, string>>({});
  const [opinionsStatus, setOpinionsStatus] = useState<OpinionsStatus>("idle");
  const [opinionsError, setOpinionsError] = useState<string | null>(null);
  const opinionsAttempted = useRef(false);
  const opinionsInFlight = useRef(false);

  const [reportContent, setReportContent] = useState<string | null>(null);
  const [reportRecords, setReportRecords] = useState<OutcomeRecord[]>([]);
  const [reportStructure, setReportStructure] = useState<ReportStructure | null>(null);
  const [reportChat, setReportChat] = useState<ChatMsg[]>([]);
  const [isGeneratingReport, setIsGeneratingReport] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);

  const applyAgents = useCallback((list: Agent[]) => {
    setAgents(list);
    setAgentsMap(Object.fromEntries(list.map((a) => [a.id, a])));
    const persisted: Record<string, string> = {};
    for (const a of list) if (a.verdict) persisted[a.id] = a.verdict;
    if (Object.keys(persisted).length) {
      setOpinions((prev) => ({ ...persisted, ...prev }));
      setOpinionsStatus((st) => (st === "idle" ? "done" : st));
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const s = (await api.sessions.get(id)) as Session;
      setSession(s);
      if (s.agent_count > 0 || s.status !== "created") {
        const a = (await api.agents.list(id)) as Agent[];
        if (a.length) applyAgents(a);
        else if (s.agent_count === 0) { setAgents([]); setAgentsMap({}); }
      }
    } catch (e: any) {
      if (/not found|404/i.test(e?.message || "")) setNotFound(true);
    }
  }, [id, applyAgents]);

  const refreshBuild = useCallback(async () => {
    try { const r = await api.population.latest(id); setBuild(r.build); } catch {}
  }, [id]);

  const loadResearch = useCallback(async () => {
    try { setResearch(await api.research.state(id)); } catch {}
  }, [id]);

  useEffect(() => {
    refresh();
    refreshBuild();
    loadResearch();
    api.sessions.posts(id).then((p) => { const list = p as Post[]; if (list.length) setPosts(list); }).catch(() => {});
    api.report.history(id).then((rows: any) => {
      const list: any[] = Array.isArray(rows) ? rows : [];
      const proper = [...list].reverse().find((r) => r.structure);
      if (proper) {
        setReportContent(proper.answer);
        setReportStructure(proper.structure || null);
        api.records.list(id).then((r) => setReportRecords(r.records || [])).catch(() => {});
      }
      const asks = list.filter((r) => !r.structure && r.question && r.question !== "report");
      if (asks.length) setReportChat(asks.flatMap((r) => [{ role: "user" as const, content: r.question }, { role: "assistant" as const, content: r.answer }]));
    }).catch(() => {});
    const t = setInterval(() => { refresh(); }, 8000);
    return () => clearInterval(t);
  }, [id, refresh, refreshBuild, loadResearch]);

  // A build in flight is polled too: the socket carries its log, but the status is what we show.
  useEffect(() => {
    if (!buildInFlight(build)) return;
    const t = setInterval(refreshBuild, 4000);
    return () => clearInterval(t);
  }, [build, refreshBuild]);

  async function loadOpinions(attempt = 0): Promise<void> {
    if (opinionsInFlight.current) return;
    opinionsInFlight.current = true;
    setOpinionsStatus("loading");
    setOpinionsError(null);
    try {
      const d = await api.sessions.opinions(id);
      const got = d?.opinions && typeof d.opinions === "object" ? d.opinions : {};
      if (Object.keys(got).length) setOpinions((prev) => ({ ...prev, ...got }));
      if (d?.error && d.generated === 0) throw new Error(d.error);
      setOpinionsStatus("done");
      if (d?.error) setOpinionsError(`Some verdicts couldn't be generated: ${d.error}`);
    } catch (e: any) {
      if (attempt < 2) {
        opinionsInFlight.current = false;
        await new Promise((r) => setTimeout(r, 2500 * (attempt + 1)));
        return loadOpinions(attempt + 1);
      }
      setOpinionsStatus("error");
      setOpinionsError(e?.message || "Couldn't summarise what each person thinks.");
    } finally {
      opinionsInFlight.current = false;
    }
  }

  useEffect(() => {
    if (opinionsAttempted.current) return;
    if (agents.length > 0 && posts.length >= Math.max(agents.length, 3)) {
      opinionsAttempted.current = true;
      const posted = new Set(posts.filter((p) => p.content && p.type !== "like").map((p) => p.agent_id));
      if ([...posted].some((aid) => !opinions[aid])) loadOpinions();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [posts.length, agents.length]);

  useEffect(() => {
    const ws = getSessionWS(id);
    const unsub = ws.subscribe((event: WSEvent) => {
      switch (event.type) {
        case "agent_spawned": {
          const agent = event.agent as Agent;
          setAgents((prev) => (prev.find((a) => a.id === agent.id) ? prev : [...prev, agent]));
          setAgentsMap((prev) => ({ ...prev, [agent.id]: agent }));
          setSpawnProgress({ current: ((event as any).index ?? 0) + 1, total: (event as any).total ?? 1 });
          break;
        }
        case "agents_spawned_batch": {
          const incoming = (event.agents as Agent[]) || [];
          setAgents((prev) => { const seen = new Set(prev.map((a) => a.id)); const next = prev.slice(); for (const a of incoming) if (!seen.has(a.id)) next.push(a); return next; });
          setAgentsMap((prev) => { const next = { ...prev }; for (const a of incoming) next[a.id] = a; return next; });
          setSpawnProgress({ current: event.spawned, total: event.total });
          break;
        }
        case "agents_ready":
          setSpawnProgress(null);
          refresh();
          refreshBuild();
          break;
        case "spawn_error":
          setSpawnProgress(null);
          setSpawnError((event as any).error || "The people could not be created.");
          refreshBuild();
          break;
        case "population_build":
          setBuild(event.build);
          break;
        case "simulation_started":
          refresh();
          break;
        case "post_created": {
          const fullAgent = event.agent as Agent;
          setPosts((prev) => [...prev, event.post]);
          setAgentsMap((prev) => ({ ...prev, [fullAgent.id]: fullAgent }));
          break;
        }
        case "like_added":
          setPosts((prev) => prev.map((p) => (p.id === event.post_id ? { ...p, likes: event.new_likes } : p)));
          break;
        case "ingest_complete":
          refresh();
          break;
        case "simulation_complete":
          refresh();
          loadOpinions();
          break;
        case "research_complete":
        case "research_started":
          loadResearch();
          break;
        default:
          break;
      }
    });
    return () => { unsub(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  /** The whole hands-off chain: build the people from the profile and the survey, approve the
   *  plan as proposed, start the debate. The backend carries it through even if this tab closes. */
  async function runSimulation(profile: string, docContext: string) {
    setSpawnError(null);
    const b = await api.population.start(id, {
      mode: LITE_DEFAULTS.mode,
      count: LITE_DEFAULTS.count,
      constraints: {
        profile_query: profile.trim(),
        doc_context: docContext || "",
        skip_questions: true,
        auto_run: { intensity: LITE_DEFAULTS.intensity, mode: LITE_DEFAULTS.mode },
      },
      sources: { quant: true, quant_sources: [], quant_auto: true },
    });
    setBuild(b);
  }

  /** People already exist (built in the pro portal, say) but nobody started the conversation. */
  async function startDebate() {
    await api.simulation.start(id, LITE_DEFAULTS.intensity, LITE_DEFAULTS.mode);
    refresh();
  }

  async function stopDebate() {
    await api.simulation.stop(id);
    refresh();
  }

  async function makeReport() {
    setIsGeneratingReport(true);
    setReportError(null);
    try {
      const result = await api.report.generate(id);
      setReportRecords(result.records || []);
      setReportStructure(result.structure || null);
      setReportContent(result.answer);
    } catch (e: any) {
      setReportError(e?.message || "The report could not be written. Please try again.");
    } finally {
      setIsGeneratingReport(false);
    }
  }

  const buildActive = buildInFlight(build);

  return {
    session, notFound, agents, agentsMap, posts, build, buildActive, research, spawnProgress, spawnError,
    opinions, opinionsStatus, opinionsError, loadOpinions,
    reportContent, reportRecords, reportStructure, reportChat, isGeneratingReport, reportError,
    runSimulation, startDebate, stopDebate, makeReport, refresh,
    clearReport: () => setReportContent(null),
  };
}
