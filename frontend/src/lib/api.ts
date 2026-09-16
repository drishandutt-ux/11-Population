import { authHeaders, redirectToLogin } from "./supabase";

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** fetch() against the backend with the user's Supabase token attached. Use for multipart
 *  uploads and any call that bypasses `request()`. A 401 sends the user to /login. */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const auth = await authHeaders();
  const res = await fetch(`${BASE}/api/v1${path}`, { ...init, headers: { ...auth, ...(init.headers || {}) } });
  if (res.status === 401) redirectToLogin();
  return res;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 120_000); // 2 min — LLM calls can be slow
  try {
    const auth = await authHeaders();
    const res = await fetch(`${BASE}/api/v1${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...auth, ...options?.headers },
      signal: controller.signal,
    });
    if (res.status === 401) {
      redirectToLogin();
      throw new Error("Please sign in to continue.");
    }
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`Request failed (${res.status})${text ? `: ${text.slice(0, 300)}` : ""}`);
    }
    if (res.status === 204) return undefined as T;
    return res.json();
  } catch (e: any) {
    if (e?.name === "AbortError") {
      throw new Error("The request timed out — the model may be busy. Please try again.");
    }
    if (e instanceof TypeError) {
      // fetch() network-level failure ("Failed to fetch"): server unreachable, CORS, or dropped connection
      throw new Error("Couldn't reach the server. It may be restarting — please try again in a moment.");
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

// Sessions
export const api = {
  me: () => request<Me>("/me"),
  admin: {
    users: () => request<AdminUser[]>("/admin/users"),
    setRole: (userId: string, role: "admin" | "member") =>
      request(`/admin/users/${userId}/role`, { method: "PATCH", body: JSON.stringify({ role }) }),
  },
  research: {
    state: (sessionId: string) => request<ResearchState>(`/sessions/${sessionId}/research`),
    start: (sessionId: string, sources?: string[]) =>
      request<ResearchRun>(`/sessions/${sessionId}/research/start`, { method: "POST", body: JSON.stringify(sources ? { sources } : {}) }),
    stop: (sessionId: string) => request(`/sessions/${sessionId}/research/stop`, { method: "POST" }),
    addSubQuestion: (sessionId: string, text: string) =>
      request<ResearchRun>(`/sessions/${sessionId}/research/subquestion`, { method: "POST", body: JSON.stringify({ text }) }),
    evidence: (sessionId: string) => request<EvidenceItem[]>(`/sessions/${sessionId}/evidence?limit=1000`),
    exclude: (sessionId: string, evidenceId: string, excluded: boolean) =>
      request<EvidenceItem>(`/sessions/${sessionId}/evidence/${evidenceId}/exclude`, { method: "POST", body: JSON.stringify({ excluded }) }),
    recommendations: (sessionId: string) => request<{ recommendations: any[] }>(`/sessions/${sessionId}/recommendations`),
  },
  sessions: {
    create: (title: string, query: string, opts?: { auto_research?: boolean; research_sources?: string[] }) =>
      request("/sessions", { method: "POST", body: JSON.stringify({ title, query, ...(opts || {}) }) }),
    list: (scope: "mine" | "all" = "mine") => request<Session[]>(`/sessions${scope === "all" ? "?scope=all" : ""}`),
    get: (id: string) => request(`/sessions/${id}`),
    delete: (id: string) => request(`/sessions/${id}`, { method: "DELETE" }),
    posts: (id: string) => request(`/sessions/${id}/posts`),
    opinions: (id: string, agentIds?: string[]) =>
      request<OpinionsResponse>(`/sessions/${id}/opinions`, {
        method: "POST",
        body: JSON.stringify(agentIds ? { agent_ids: agentIds } : {}),
      }),
  },
  ingest: {
    text: (sessionId: string, text: string) =>
      request(`/sessions/${sessionId}/ingest/text`, {
        method: "POST",
        body: JSON.stringify({ text }),
      }),
    youtube: (sessionId: string, url: string) =>
      request(`/sessions/${sessionId}/ingest/youtube`, {
        method: "POST",
        body: JSON.stringify({ url }),
      }),
    document: (sessionId: string, file: File) => {
      const form = new FormData();
      form.append("file", file);
      return apiFetch(`/sessions/${sessionId}/ingest/document`, {
        method: "POST",
        body: form,
      }).then((r) => r.json());
    },
    llmGenerate: (sessionId: string, data: { query: string; llm: string; contextFile?: File | null }) => {
      const form = new FormData();
      form.append("query", data.query);
      form.append("llm", data.llm);
      if (data.contextFile) form.append("context_file", data.contextFile);
      return apiFetch(`/sessions/${sessionId}/ingest/llm-search/generate`, {
        method: "POST",
        body: form,
      }).then((r) => r.json());
    },
    llmSearch: (sessionId: string, data: { query: string; llm: string; contextFile?: File | null }) => {
      const form = new FormData();
      form.append("query", data.query);
      form.append("llm", data.llm);
      if (data.contextFile) form.append("context_file", data.contextFile);
      return apiFetch(`/sessions/${sessionId}/ingest/llm-search`, {
        method: "POST",
        body: form,
      }).then((r) => r.json());
    },
  },
  simulation: {
    spawnAgents: (sessionId: string, count: number, opts?: SpawnOptions) =>
      request(`/sessions/${sessionId}/spawn-agents`, {
        method: "POST",
        body: JSON.stringify({ count, ...opts }),
      }),
    start: (sessionId: string, intensity: number, mode: SimMode = "fast") =>
      request(`/sessions/${sessionId}/simulate/start`, {
        method: "POST",
        body: JSON.stringify({ intensity, mode }),
      }),
    pause: (sessionId: string) =>
      request(`/sessions/${sessionId}/simulate/pause`, { method: "POST" }),
    stop: (sessionId: string) =>
      request(`/sessions/${sessionId}/simulate/stop`, { method: "POST" }),
  },
  agents: {
    list: (sessionId: string) => request(`/sessions/${sessionId}/agents`),
    get: (agentId: string) => request(`/agents/${agentId}`),
    chat: (agentId: string, message: string) =>
      request(`/agents/${agentId}/chat`, {
        method: "POST",
        body: JSON.stringify({ message }),
      }),
  },
  report: {
    query: (sessionId: string, question: string) =>
      request(`/sessions/${sessionId}/report/query`, {
        method: "POST",
        body: JSON.stringify({ question }),
      }),
    history: (sessionId: string) => request(`/sessions/${sessionId}/report/history`),
  },
  kg: {
    ontology: (sessionId: string) => request<OntologyState>(`/sessions/${sessionId}/kg/ontology`),
    buildOntology: (sessionId: string) => request<OntologyState>(`/sessions/${sessionId}/kg/ontology/build`, { method: "POST" }),
  },
  scoping: {
    state: (sessionId: string) => request<ScopingState>(`/sessions/${sessionId}/scoping`),
    tag: (sessionId: string) => request<ScopingState>(`/sessions/${sessionId}/scoping/tag`, { method: "POST" }),
    preview: (sessionId: string, agentId: string) => request<ScopingPreview>(`/sessions/${sessionId}/scoping/preview?agent_id=${encodeURIComponent(agentId)}`),
    setPolicy: (sessionId: string, rules: ScopeRule[], note = "") =>
      request<{ version: number; rules: ScopeRule[] }>(`/sessions/${sessionId}/scoping/policy`, { method: "PUT", body: JSON.stringify({ rules, note }) }),
    setExposure: (sessionId: string, agentId: string, exposure: Record<string, unknown> | null) =>
      request<{ agent_id: string; exposure: Record<string, unknown> | null }>(`/sessions/${sessionId}/scoping/agents/${agentId}/exposure`, { method: "PUT", body: JSON.stringify({ exposure }) }),
    retrievals: (sessionId: string, agentId?: string) =>
      request<{ retrievals: RetrievalRow[] }>(`/sessions/${sessionId}/scoping/retrievals${agentId ? `?agent_id=${encodeURIComponent(agentId)}` : ""}`),
  },
  lab: {
    instruments: () => request<{ instruments: Instrument[] }>("/lab/instruments"),
    estimate: (sessionId: string, body: ProbeRequest) =>
      request<ProbeEstimate>(`/sessions/${sessionId}/probes/estimate`, { method: "POST", body: JSON.stringify(body) }),
    run: (sessionId: string, body: ProbeRequest) =>
      request<Probe>(`/sessions/${sessionId}/probes`, { method: "POST", body: JSON.stringify(body) }),
    probes: (sessionId: string) => request<{ probes: Probe[] }>(`/sessions/${sessionId}/probes`),
    probe: (sessionId: string, probeId: string) =>
      request<Probe & { answers: ProbeAnswerRow[] }>(`/sessions/${sessionId}/probes/${probeId}`),
    stop: (sessionId: string, probeId: string) =>
      request<{ status: string }>(`/sessions/${sessionId}/probes/${probeId}/stop`, { method: "POST" }),
    /** Standalone runs only; an arm of an A/B test goes with its experiment. 409 while running. */
    deleteProbe: (sessionId: string, probeId: string) =>
      request(`/sessions/${sessionId}/probes/${probeId}`, { method: "DELETE" }),
    // A/B/n experiments: one instrument, several variants, the same agents (or a seeded split).
    estimateExperiment: (sessionId: string, body: ExperimentRequest) =>
      request<ExperimentEstimate>(`/sessions/${sessionId}/experiments/estimate`, { method: "POST", body: JSON.stringify(body) }),
    runExperiment: (sessionId: string, body: ExperimentRequest) =>
      request<Experiment>(`/sessions/${sessionId}/experiments`, { method: "POST", body: JSON.stringify(body) }),
    experiments: (sessionId: string) => request<{ experiments: Experiment[] }>(`/sessions/${sessionId}/experiments`),
    experiment: (sessionId: string, experimentId: string) =>
      request<Experiment>(`/sessions/${sessionId}/experiments/${experimentId}`),
    stopExperiment: (sessionId: string, experimentId: string) =>
      request<{ status: string }>(`/sessions/${sessionId}/experiments/${experimentId}/stop`, { method: "POST" }),
    /** Removes the test, its arm probes and their answers. 409 while running. */
    deleteExperiment: (sessionId: string, experimentId: string) =>
      request(`/sessions/${sessionId}/experiments/${experimentId}`, { method: "DELETE" }),
    downloadExperimentCsv: async (sessionId: string, experimentId: string, filename: string) => {
      const res = await apiFetch(`/sessions/${sessionId}/experiments/${experimentId}/export.csv`);
      if (!res.ok) throw new Error(`Export failed: ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    },
    /** CSV goes through apiFetch so the auth header is attached, then downloads as a blob. */
    downloadCsv: async (sessionId: string, probeId: string, filename: string) => {
      const res = await apiFetch(`/sessions/${sessionId}/probes/${probeId}/export.csv`);
      if (!res.ok) throw new Error(`Export failed (${res.status})`);
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    },
  },
  population: {
    sources: (geography = "") =>
      request<{ sources: QuantSource[]; default: string[] }>(`/population/sources${geography ? `?geography=${encodeURIComponent(geography)}` : ""}`),
    start: (sessionId: string, body: { mode: SimMode; count: number; constraints: PopulationConstraints; sources: PopulationSources }) =>
      request<PopulationBuild>(`/sessions/${sessionId}/population/builds`, { method: "POST", body: JSON.stringify(body) }),
    latest: (sessionId: string) => request<{ build: PopulationBuild | null }>(`/sessions/${sessionId}/population/builds/latest`),
    get: (sessionId: string, buildId: string) => request<PopulationBuild>(`/sessions/${sessionId}/population/builds/${buildId}`),
    answer: (sessionId: string, buildId: string, answers: Record<string, string>, skip = false) =>
      request<PopulationBuild>(`/sessions/${sessionId}/population/builds/${buildId}/answers`, { method: "POST", body: JSON.stringify({ answers, skip }) }),
    frameAction: (sessionId: string, buildId: string, dimKey: string, body: { action: "estimate" | "upload" | "proxy" | "skip"; categories?: FrameCategory[]; source?: string; proxy_of?: string }) =>
      request<PopulationBuild>(`/sessions/${sessionId}/population/builds/${buildId}/frame/${encodeURIComponent(dimKey)}`, { method: "POST", body: JSON.stringify(body) }),
    frameEstimateAll: (sessionId: string, buildId: string) =>
      request<PopulationBuild>(`/sessions/${sessionId}/population/builds/${buildId}/frame/estimate-all`, { method: "POST" }),
    decide: (sessionId: string, buildId: string, segmentId: string, body: { decision: "accept" | "reject" | "edit"; edits?: Partial<PopulationSegment>; reason?: string }) =>
      request<PopulationBuild>(`/sessions/${sessionId}/population/builds/${buildId}/segments/${segmentId}`, { method: "POST", body: JSON.stringify(body) }),
    replan: (sessionId: string, buildId: string, body: { constraints?: PopulationConstraints; count?: number; keep_accepted?: boolean }) =>
      request<PopulationBuild>(`/sessions/${sessionId}/population/builds/${buildId}/replan`, { method: "POST", body: JSON.stringify(body) }),
    approve: (sessionId: string, buildId: string, body: { count?: number; mode?: SimMode }) =>
      request<PopulationBuild>(`/sessions/${sessionId}/population/builds/${buildId}/approve`, { method: "POST", body: JSON.stringify(body) }),
    stop: (sessionId: string, buildId: string) =>
      request<{ stopped: boolean }>(`/sessions/${sessionId}/population/builds/${buildId}/stop`, { method: "POST" }),
    quantSearch: (sessionId: string, query: string, sources: string[], buildId?: string | null) =>
      request<{ queued: boolean }>(`/sessions/${sessionId}/population/quant-search`, { method: "POST", body: JSON.stringify({ query, sources, build_id: buildId ?? null }) }),
    /** Statistics pages gathered for this session (`quant` evidence). */
    facts: (sessionId: string) => request<EvidenceItem[]>(`/sessions/${sessionId}/evidence?source_class=quant&limit=200`),
  },
  presets: {
    list: () => request<AgentPreset[]>("/presets"),
    save: (sessionId: string, name: string) =>
      request("/presets", { method: "POST", body: JSON.stringify({ session_id: sessionId, name }) }),
    delete: (presetId: string) =>
      request(`/presets/${presetId}`, { method: "DELETE" }),
    apply: (sessionId: string, presetId: string) =>
      request(`/sessions/${sessionId}/apply-preset`, {
        method: "POST",
        body: JSON.stringify({ preset_id: presetId }),
      }),
  },
};

export type Session = {
  id: string;
  title: string;
  query: string;
  status: string;
  agent_count: number;
  created_at: string;
  updated_at: string;
  owner_email?: string | null; // admins listing everyone's sessions
  is_mine?: boolean | null;
};

export type ResearchQuery = {
  id: string; run_id: string; source: "web" | "reddit"; query: string; round: number;
  status: "queued" | "running" | "done" | "error"; engine?: string | null; results: number; read: number; on_topic: number; note?: string | null; created_at?: string;
};

export type ResearchRun = {
  id: string; session_id: string; status: string; question: string; sources: string[];
  frame: any | null; plan: any | null; verdicts: any[]; covered: string[]; budget: Record<string, number>;
  brief: any | null; recommendations: any[] | null; note?: string | null; started_at?: string | null; finished_at?: string | null;
};

export type ResearchState = { run: ResearchRun | null; queries: ResearchQuery[]; counts: Record<string, { read: number; on_topic: number }>; in_graph?: number };

export type EvidenceItem = {
  id: string; run_id?: string | null; source_class: "web" | "social" | "personal" | "synthetic" | "quant"; source_ref: string;
  title?: string | null; author?: string | null; published_at?: string | null; text: string; structured: any;
  trust_tier: string; relevance: number; on_topic: boolean; excluded: boolean; in_graph: boolean; query?: string | null; attempt: number;
  sub_questions: string[]; created_at?: string;
};

export type Me = { id: string; email: string | null; role: "admin" | "member"; is_admin: boolean };

export type AdminUser = {
  id: string;
  email: string | null;
  display_name: string | null;
  role: "admin" | "member";
  created_at: string;
  sessions: number;
  is_you: boolean;
};

export type DialCategory = {
  [key: string]: number;
};

export type AgentDials = {
  sentiment?: DialCategory;
  motivation?: DialCategory;
  habit?: DialCategory;
  trust?: DialCategory;
  friction?: DialCategory;
  identity?: DialCategory;
  commercial?: DialCategory;
  product?: DialCategory;
  composite?: DialCategory;
};

export type Agent = {
  id: string;
  session_id: string;
  name: string;
  age: number;
  role: string;
  background: string;
  stance: "direct" | "indirect" | "neutral";
  correlation: string;
  personality: string[];
  debate_style: string;
  energy: number;
  avatar_color: string;
  dials?: AgentDials;
  humanity?: number; // 0 = expert/analytical, 100 = fully human/emotional
  verdict?: string | null; // persisted one-line verdict (Agent Opinions sidebar), null until generated
  /** Population Studio: the plan segment this agent was built from, and the demographics it fixed. */
  segment?: string | null;
  demographics?: AgentDemographics;
  /** Raking weight to the Studio's sampling frame; 1 when the population was not weighted. */
  weight?: number;
};

export type AgentDemographics = {
  gender?: string;
  region?: string;
  income_band?: string;
  education?: string;
  occupation?: string;
  /** Spawn-written paragraph: the query analysed from the agent's place — injected into their system prompt. */
  geo_behavior?: string;
};

export type OpinionsResponse = {
  opinions: Record<string, string>;
  generated: number;
  total: number;
  error?: string | null;
};

export type SimMode = "fast" | "pro";

export type SpawnOptions = {
  mode?: SimMode;             // "fast" = pre-built bank (instant); "pro" = LLM-curated (Sonnet)
  profile_query?: string;
  direct_pct?: number;
  indirect_pct?: number;
  neutral_pct?: number;
  doc_context?: string;
  humanity?: number;          // 0-100 intensity
  humanity_coverage?: number; // 0-100 % of agents it applies to
  ground_in_evidence?: boolean;
  /** Pro + survey upload: build the population FROM the respondents instead of applying the
   *  stance quota over the top of them. */
  mirror_survey?: boolean;
};

export type Post = {
  id: string;
  agent_id: string;
  type: "comment" | "reply" | "like" | "debate";
  content: string | null;
  parent_id: string | null;
  likes: number;
  round_num: number;
};

export type AgentPreset = {
  id: string;
  name: string;
  agent_count: number;
  created_at: string;
};

export type WSEvent =
  | { type: "agent_spawned"; agent: Partial<Agent>; index?: number; total?: number }
  | { type: "agents_spawned_batch"; agents: Partial<Agent>[]; spawned: number; total: number }
  | { type: "agents_ready"; count: number }
  | { type: "spawn_error"; error: string }
  | { type: "simulation_started"; agent_count: number }
  | { type: "post_created"; post: Post; agent: Partial<Agent> }
  | { type: "like_added"; post_id: string; agent_id: string; new_likes: number }
  | { type: "kg_updated"; new_entities: string[]; new_relations: string[][] }
  | { type: "ingest_complete"; source: string }
  | { type: "simulation_complete"; message: string }
  | { type: "research_started"; run_id: string; question: string; sources: string[] }
  | { type: "research_frame"; run_id: string; frame: any }
  | { type: "research_plan"; run_id: string; plan: any }
  | { type: "research_query"; query: ResearchQuery }
  | { type: "research_item"; item: EvidenceItem }
  | { type: "research_verdict"; run_id: string; source: string; round: number; verdict: any; covered: string[] }
  | { type: "research_budget"; run_id: string; budget: Record<string, number> }
  | { type: "research_brief"; run_id: string; brief: any }
  | { type: "research_complete"; run_id: string; status: string; note: string; budget: Record<string, number>; covered: string[]; recommendations: any[] }
  | { type: "research_error"; run_id: string; error: string }
  | { type: "research_status"; run_id: string; status: string; note?: string }
  | { type: "probe_started"; probe_id: string; instrument: string; agent_count: number }
  | { type: "probe_answer"; probe_id: string; agent_id: string; agent_name: string; avatar_color: string; answer: Record<string, any>; segments: Record<string, string> }
  | { type: "probe_complete"; probe_id: string; status: string; answer_count: number; failed_count: number; sentence: string }
  | { type: "experiment_started"; experiment_id: string; probe_ids: string[]; agent_count: number; design: string }
  | { type: "experiment_complete"; experiment_id: string; status: string; verdict?: string }
  | { type: "population_log"; build_id: string | null; entry: PopulationLogEntry }
  | { type: "population_build"; build: PopulationBuild }
  | { type: "population_quant_done"; build_id: string | null };


// ── Behaviour Lab ────────────────────────────────────────────────────────────

/** One control on an instrument's own input panel. There is no shared form: each tool
 *  declares the inputs it needs, and the UI renders them. */
export type InstrumentInput = {
  key: string;
  type: "text" | "textarea" | "number" | "select" | "money" | "questions";
  label: string;
  required: boolean;
  help: string;
  placeholder: string;
  default: any;
  /** "session_query" prefills from the session so the analyst edits rather than retypes. */
  default_from: string;
  options: string[];
  /** Free-text inputs: ready-made phrasings offered as one-click chips. */
  suggestions: string[];
};

/** A headline number the instrument produces, named so the shell can render it without
 *  knowing what the tool measures. */
export type InstrumentKpi = {
  key: string;
  label: string;
  format: "share" | "mean" | "money" | "count";
  help: string;
};

/** One number an A/B test compares between variants, declared by the instrument. */
export type InstrumentMetric = {
  key: string;
  label: string;
  format: "share" | "mean" | "money";
  primary: boolean;
  help: string;
};

/** A tool: its inputs, its schema, its KPIs and which page renders its results. */
export type Instrument = {
  key: string;
  label: string;
  description: string;
  question: string;
  inputs: InstrumentInput[];
  kpis: InstrumentKpi[];
  /** What an A/B test of this tool compares; empty when it cannot be run as one. */
  metrics: InstrumentMetric[];
  supports_experiments: boolean;
  decision_key: string;
  /** Which input holds what the agent is shown ("stimulus", "material"…). */
  stimulus_key: string;
  /** Set when the ask comes from the spec (the analyst writes the question). */
  question_from: string;
  /** Internal instruments (the choice design's) are not offered in the picker. */
  hidden: boolean;
  /** Key into the frontend form registry (a bespoke input panel); empty = generic form. */
  form: string;
  /** Ready-made forms for a form-building tool (the survey's templates). */
  templates: SurveyTemplate[];
  /** Key into the frontend page registry; empty or unknown falls back to the generic view. */
  page: string;
  schema_id: string;
  answer_schema: { properties: Record<string, any>; required?: string[] };
};

/** Instrument-declared inputs land here by key, alongside the runner's own options. The
 *  shell never assumes a particular instrument's fields. */
export type ProbeSpec = {
  context?: { kg?: boolean; own_posts?: boolean; prior_answers?: boolean };
  agent_filter?: { segments?: Record<string, string | string[]>; sample?: number; agent_ids?: string[] };
  seed?: number;
  [key: string]: any;
};

export type ProbeRequest = {
  instrument: string;
  spec: ProbeSpec;
  mode?: SimMode;
  seed?: number | null;
  agent_filter?: ProbeSpec["agent_filter"];
};

export type ProbeEstimate = { agent_count: number; mode: SimMode; model: string; estimated_cost_usd: number };

export type ProbeStatus = "queued" | "running" | "complete" | "failed" | "stopped";

/** A share with its Wilson interval — every proportion the Lab reports carries one. */
export type Interval = { share: number; low: number; high: number; n: number; successes: number };
export type MeanInterval = { mean: number; low: number; high: number; median: number; p25: number; p75: number; sd: number; n: number };

export type ProbeAggregates = {
  /** The primary metric weighted to the sampling frame, beside the one-agent-one-vote figure. */
  weighted?: { metric: string; label: string; format: string; weighted: number | null; unweighted: number | null; ess: number; n: number };
  n: number;
  sentence: string;
  headline?: Interval & { metric: string; label: string };
  would_buy?: (Interval & { value: string; count: number })[];
  likelihood?: MeanInterval;
  max_price?: MeanInterval & { currency: string };
  demand_curve?: { price: number; share: number; low: number; high: number; revenue_index: number }[];
  optimal_price?: { price: number; share: number; revenue_index: number };
  at_asking_price?: Interval | null;
  consistency?: { contradictions: number; share: number | null; note: string };
  drivers?: (Interval & { value: string; count: number })[];
  sentiment?: MeanInterval;
  segments?: Record<string, (Interval & { segment: string; value: string; n: number; thin: boolean })[]>;
  verbatims?: Record<string, { agent_id: string; name: string; role: string; reasoning: string; max_price?: number }[]>;
};

export type Probe = {
  id: string;
  session_id: string;
  instrument: string;
  schema_id: string;
  spec: ProbeSpec;
  experiment_id: string | null;
  variant_key: string | null;
  seed: number;
  model: string;
  prompt_hash: string;
  status: ProbeStatus;
  agent_count: number;
  answer_count: number;
  failed_count: number;
  aggregates: ProbeAggregates | null;
  error: string | null;
  created_at: string | null;
  completed_at: string | null;
};

export type ProbeAnswerRow = {
  agent_id: string;
  name: string;
  role: string;
  avatar_color: string;
  answer: Record<string, any>;
  reasoning: string;
  segments: Record<string, string>;
  latency_ms: number;
};

// ── Experiments (A/B/n) ───────────────────────────────────────────────────────

export type ExperimentDesign = "within" | "between" | "choice";

export type ExperimentVariant = { key: string; label: string; spec: Record<string, any> };

export type ExperimentRequest = {
  instrument: string;
  design: ExperimentDesign;
  name?: string;
  /** Choice design: the ask; defaults to the base tool's question. */
  question?: string;
  variants: ExperimentVariant[];
  spec?: Record<string, any>;
  mode?: SimMode;
  seed?: number | null;
  agent_filter?: ProbeSpec["agent_filter"];
};

export type ExperimentEstimate = {
  agent_count: number;
  variants: number;
  calls: number;
  mode: SimMode;
  model: string;
  estimated_cost_usd: number;
};

/** A difference between two arms with its bootstrap interval. */
export type Lift = { mean: number; low: number; high: number; n: number; significant: boolean; n_a?: number; n_b?: number };

export type ComparisonMetric = {
  key: string;
  label: string;
  format: "share" | "mean" | "money";
  primary: boolean;
  currency: string;
  control: number;
  variant: number;
  lift: Lift;
};

export type FlipRow = {
  agent_id: string;
  name: string;
  role: string;
  from: string;
  to: string;
  reasoning_control: string;
  reasoning_variant: string;
  driver: string;
  segments: Record<string, string>;
};

export type SegmentLift = {
  segment: string;
  value: string;
  n: number;
  thin: boolean;
  control: number;
  variant: number;
  mean: number;
  low: number;
  high: number;
  significant: boolean;
};

export type Comparison = {
  variant: string;
  label: string;
  control: string;
  control_label: string;
  n: number;
  metrics: ComparisonMetric[];
  /** Within-subjects only: agents whose decision changed, with both reasons. */
  flips: {
    n: number;
    paired: number;
    share: Interval;
    /** Every paired agent's movement on the decision field, stayers included. */
    matrix: { from: string; to: string; count: number }[];
    direction: (Interval & { value: string; count: number })[];
    reasons: (Interval & { value: string; count: number })[];
    rows: FlipRow[];
  } | null;
  /** The primary metric's lift inside every segment bucket — the heat-map. */
  segments: Record<string, SegmentLift[]>;
  sentence: string;
};

export type Preference = Interval & {
  key: string;
  label: string;
  runner_up: number;
  runner_up_share: number;
  themes: (Interval & { value: string; count: number })[];
  confidence: MeanInterval;
  segments: Record<string, (Interval & { segment: string; value: string; n: number; thin: boolean })[]>;
  verbatims: { agent_id: string; name: string; role: string; reasoning: string; key_factor: string; theme: string }[];
};

export type ExperimentResults = {
  design: ExperimentDesign;
  instrument: string;
  control: string;
  primary_metric: string;
  arms: { key: string; label: string; n: number }[];
  comparisons: Comparison[];
  verdict: string;
  /** variant key → probe id ("all" for the choice design's single arm) */
  probes: Record<string, string>;
  /** Choice design only. */
  preference?: Preference[];
  head_to_head?: { first: string; second: string; count: number }[];
  clear_winner?: boolean;
  winner?: string;
  n?: number;
};

export type Experiment = {
  id: string;
  session_id: string;
  name: string;
  design: ExperimentDesign;
  instrument: string;
  variants: ExperimentVariant[];
  spec: Record<string, any>;
  seed: number;
  model: string;
  status: ProbeStatus;
  agent_count: number;
  results: ExperimentResults | null;
  error: string | null;
  created_at: string | null;
  completed_at: string | null;
  /** The arms, when fetched individually or just created. */
  probes?: Probe[];
};

// ── Survey ────────────────────────────────────────────────────────────────────

export type SurveyQuestionType = "single" | "multi" | "scale" | "yesno" | "number" | "text" | "grid";

export type SurveyQuestion = {
  key: string;
  type: SurveyQuestionType;
  text: string;
  options?: string[];
  rows?: string[];
  columns?: string[];
  min?: number;
  max?: number;
  min_label?: string;
  max_label?: string;
  primary?: boolean;
};

export type SurveyTemplate = {
  key: string;
  label: string;
  description: string;
  title: string;
  questions: SurveyQuestion[];
};

export type SurveyBucket = Interval & { value: string; count: number };

export type SurveyQuestionResult = {
  key: string;
  type: SurveyQuestionType;
  text: string;
  n: number;
  primary: boolean;
  sentence: string;
  distribution?: SurveyBucket[];
  headline?: SurveyBucket & { label: string };
  mean?: MeanInterval;
  top_two_box?: Interval;
  bottom_two_box?: Interval;
  mean_selected?: number;
  themes?: SurveyBucket[];
  themes_coded?: boolean;
  responses?: { agent_id: string; name: string; role: string; text: string; theme: string }[];
  columns?: string[];
  rows?: { key: string; label: string; distribution: SurveyBucket[]; n: number }[];
};


// ── Population Studio ─────────────────────────────────────────────────────────

export type QuantSource = {
  key: string; label: string; domain: string; regions: string[]; kind: string; description: string;
  /** Narrower `site:` prefix than the domain, where the publisher mixes statistics with policy pages. */
  site?: string;
  /** Population dimensions the publisher covers (size, age, income, attitude, tech, …). */
  covers?: string[];
  /** How the publisher titles its pages — the planner phrases queries to match. */
  phrasing?: string[];
  /** 1–5: how well an automated search-and-read works against it. */
  fit?: number;
  note?: string;
};

/** `quant_auto`: the analyst never changed the ticked publishers, so the build may re-derive them from the detected geography. */
export type PopulationSources = { quant: boolean; quant_sources: string[]; quant_query?: string; quant_auto?: boolean };

/** The dials. Anything left at its default ("mixed", 5, follow_evidence) is not imposed on the plan. */
export type PopulationConstraints = {
  stance?: { direct: number; indirect: number; neutral: number; follow_plan?: boolean };
  /** Legacy — the Studio ignores these: humanity is set per segment by its register (humanity_hint). */
  humanity?: number;
  humanity_coverage?: number;
  demographics?: {
    age_min?: number;
    age_max?: number;
    age_skew?: "even" | "younger" | "older";
    gender?: { female: number; male: number; other: number };
    regions?: string[];
    urban_rural?: "mixed" | "urban" | "suburban" | "rural";
    income?: "mixed" | "low" | "middle" | "high";
    education?: "mixed" | "secondary" | "degree" | "postgraduate";
    notes?: string;
  };
  sentiment?: {
    follow_evidence?: boolean;
    mood?: { for: number; against: number; mixed: number };
    temperature?: number;
    trust_in_institutions?: number;
    price_sensitivity?: number;
    tech_savviness?: number;
    openness_to_change?: number;
  };
  profile_query?: string;
  doc_context?: string;
  skip_questions?: boolean;
  /** Dials the detect stage set from the research (dial → the evidence it rests on). */
  derived_from_research?: Record<string, string>;
};

export type PopulationSegment = {
  id: string;
  name: string;
  share_pct: number;
  count?: number;
  stance: "direct" | "indirect" | "neutral";
  description: string;
  demographics: {
    age_min?: number;
    age_max?: number;
    gender_female_pct?: number;
    regions?: string[];
    income_band?: string;
    education?: string;
    occupations?: string[];
  };
  sentiment: { mood: "for" | "against" | "mixed" | "uncertain"; temperature: number; top_emotions: string[] };
  arguments: string[];
  evidence: string[];
  rationale: string;
  /** The segment's register (expert | tempered | balanced | defensive | reactive) — sets its agents' humanity band. */
  humanity_hint?: string;
  decision: "proposed" | "accepted" | "rejected" | "edited";
  reason?: string | null;
  /** Set on a segment that replaced a rejected one. */
  replaced?: string;
};

export type PopulationQuestion = { id: string; text: string; why: string; suggested: string[]; default: string; answer: string | null };

export type PopulationLogEntry = {
  ts: string;
  stage: "detect" | "gather" | "clarify" | "plan" | "review" | "spawn" | "error" | string;
  level: "info" | "ok" | "warn" | "error" | "question" | "decision";
  message: string;
  detail?: string | null;
};

export type PopulationDetected = {
  topic: string;
  decision: string;
  geography: string;
  target_population: string;
  population_kind: string;
  segments_hinted: string[];
  demographic_signals: { attribute: string; value: string; source: string }[];
  sentiment_signals: string[];
  gaps: string[];
  confidence: number;
};

// ── The sampling frame (Studio; brief L2-01…L2-05) ───────────────────────────
export type FrameCategory = { label: string; share_pct: number; age_min?: number; age_max?: number };
export type FrameDimension = { key: string; label: string; attribute: string; kind: "demographic" | "behavioural" | "attitudinal"; why: string; matchable: boolean; proxy_attribute: string };
export type FrameTarget = { status: "found" | "proxy" | "uploaded" | "estimated" | "skipped" | "missing"; categories: FrameCategory[]; source: string; year: string; geography: string; proxy_attribute: string; note: string; provenance?: string; confidence?: number };
export type FrameReportCell = { label: string; target_pct: number; planned_pct: number; achieved_pct: number | null; achieved_n: number | null; expected_n: number; thin: boolean };
export type FrameReportDim = { key: string; label: string; attribute: string; status: string; source: string; year: string; geography: string; provenance: string; priority: number; mode: "exact" | "weighted" | "unmatched"; cells?: FrameReportCell[]; max_deviation_planned?: number; max_deviation_achieved?: number | null; unplaced?: number | null };
export type FrameReport = { level: "good" | "fair" | "poor" | "none"; worst_deviation_pts: number; matched_exactly: string[]; weighted_only: string[]; unmatched: string[]; estimated: string[]; dimensions: FrameReportDim[]; thin_cells: string[]; stage: "planned" | "achieved"; n: number | null; ess: number | null };
export type PopulationFrame = { dimensions: FrameDimension[]; targets: Record<string, FrameTarget>; report: FrameReport | null; geography: string };

export type PopulationBuildStatus =
  | "queued" | "detecting" | "gathering" | "clarifying" | "planning" | "awaiting_review" | "spawning" | "complete" | "stopped" | "error";

export type PopulationBuild = {
  id: string;
  session_id: string;
  status: PopulationBuildStatus;
  mode: SimMode;
  target_count: number;
  constraints: PopulationConstraints;
  sources: PopulationSources;
  detected: PopulationDetected | null;
  questions: PopulationQuestion[];
  plan: { segments: PopulationSegment[]; rationale: string; assumptions: string[]; evidence_coverage: string } | null;
  frame?: PopulationFrame | null;
  log: PopulationLogEntry[];
  error: string | null;
  created_at: string | null;
  updated_at: string | null;
};

// ── Ontology (typed layer over the session knowledge graph) ───────────────────
export interface OntologyClass { key: string; label: string; color: string; description: string; levels?: string[] }
export interface OntologyPredicate { key: string; label: string; domain: string[]; range: string[]; description: string }
export interface OntologySchema { classes: OntologyClass[]; predicates: OntologyPredicate[]; geo_levels: string[] }
export interface OntologyNode { id: string; cls: string; level: string | null; mentions: number; inferred: boolean }
export interface OntologyEdge { head: string; predicate: string; tail: string; verb: string; inferred: boolean }
export interface Ontology {
  nodes: OntologyNode[];
  edges: OntologyEdge[];
  counts: Record<string, number>;
  built_at: string;
  model: string;
  entity_count: number;
  relation_count: number;
  classified: number;
  typed: number;
}
export interface OntologyState { schema: OntologySchema; ontology: Ontology | null; stale: boolean; entity_count: number }

// ── Scoped retrieval (typed knowledge units, exposure profiles, policies) ─────
export interface ScopeDimension { key: string; label: string; ontology_class?: string; semantics: string; default: string; values?: string[]; description: string }
export interface KnowledgeUnit { id: string; text: string; source_ref: string; provenance_class: string; trust_tier: string; facets: Record<string, string[] | string>; snapshot_id: string }
export interface ScopeRule { dimension: string; when?: "own" | "unscoped" | "any" | string[]; effect: "deny" | "require" | "allow" | "boost" | "route"; weight?: number; route?: string; override?: string[]; note?: string }
export interface ScopingState {
  dimensions: ScopeDimension[];
  chunk_count: number;
  tagged: boolean;
  units: KnowledgeUnit[];
  unit_count: number;
  counts: Record<string, Record<string, number>>;
  policy: { version: number; rules: ScopeRule[] } | null;
  snapshot_id: string | null;
  stale: boolean;
}
export interface ExposureProfile { values: Record<string, unknown>; basis: Record<string, string>; band: string }
export interface ScopingPreview {
  tagged: boolean;
  profile: ExposureProfile | null;
  visible: { unit: KnowledgeUnit; score: number; route: string; applied: string[] }[];
  visible_total?: number;
  hidden: { unit: KnowledgeUnit; failed: [string, string][] }[];
  hidden_total?: number;
  block: string;
  policy_version?: number;
  snapshot_id?: string;
}
export interface RetrievalRow { id: string; agent_id: string; purpose: string; snapshot_id: string; policy_version: number; unit_ids: string[]; routes: string[]; created_at: string }
