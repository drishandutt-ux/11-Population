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

async function request<T>(path: string, options?: RequestInit, timeoutMs = 120_000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs); // 2 min by default — LLM calls can be slow
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
      throw new Error(`Request failed (${res.status})${text ? `: ${text.slice(0, 600)}` : ""}`);
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
    /** A web page handed over directly (simple view): read and ingested as it is, never filtered. */
    url: (sessionId: string, url: string) =>
      request(`/sessions/${sessionId}/ingest/url`, {
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
    /** Agent Builder: read the draft and tune every dial the analyst left to the system, relative to the session's query. */
    buildProfile: (sessionId: string, agent: AuthoredAgentDraft) =>
      request<BuiltProfile>(`/sessions/${sessionId}/agent-builder/profile`, { method: "POST", body: JSON.stringify({ agent }) }),
    chat: (agentId: string, message: string) =>
      request(`/agents/${agentId}/chat`, {
        method: "POST",
        body: JSON.stringify({ message }),
      }),
    /** The whole validation battery for one twin (brief L3-05): items, its answers, the judge's evidence. */
    validation: (agentId: string) => request(`/agents/${agentId}/validation`),
  },
  validation: {
    /** How far this population behaved like itself. */
    summary: (sessionId: string) => request<ValidationSummary>(`/sessions/${sessionId}/validation`),
    /** Run (or re-run) the battery; scores land over the websocket as each twin finishes. */
    run: (sessionId: string, agentIds?: string[], mode: SimMode = "fast") =>
      request(`/sessions/${sessionId}/validation`, { method: "POST", body: JSON.stringify({ agent_ids: agentIds ?? null, mode }) }),
  },
  report: {
    query: (sessionId: string, question: string) =>
      request(`/sessions/${sessionId}/report/query`, {
        method: "POST",
        body: JSON.stringify({ question }),
      }),
    /** The report proper (brief L6-01): computes the headline outcome record first, then writes the narrative around every record. Slow — it may run a verdict probe. */
    generate: (sessionId: string) =>
      request<{ id: string; question: string; answer: string; sources: string | null; records: OutcomeRecord[]; structure: ReportStructure | null }>(`/sessions/${sessionId}/report/generate`, {
        method: "POST",
        body: JSON.stringify({}),
      }, 10 * 60_000), // the report proper may run a verdict probe over the whole roster first
    history: (sessionId: string) => request(`/sessions/${sessionId}/report/history`),
    /** The client-facing document (brief L6-06) with the synthetic-population statement (L6-07). */
    client: (sessionId: string) => request<ClientReport>(`/sessions/${sessionId}/report/client`),
    /** What changed between two reports proper (brief L6-06): b (default latest) against a (default the one before). */
    delta: (sessionId: string, a?: string, b?: string) =>
      request<ReportDelta>(`/sessions/${sessionId}/report/delta${a || b ? `?${[a ? `a=${a}` : "", b ? `b=${b}` : ""].filter(Boolean).join("&")}` : ""}`),
    /** The structured export as a zip (brief L6-06): fetched with auth, handed to the browser as a download. */
    exportZip: async (sessionId: string): Promise<Blob> => {
      const res = await apiFetch(`/sessions/${sessionId}/export.zip`);
      if (!res.ok) throw new Error(`Export failed (${res.status})`);
      return res.blob();
    },
  },
  records: {
    /** Every outcome record on file for the session — the headline verdict first, then Lab results. */
    list: (sessionId: string) => request<{ records: OutcomeRecord[] }>(`/sessions/${sessionId}/records`),
  },
  figures: {
    /** The source-figure ledger (brief L6-03): typed statistics and evidence items with their provenance class. */
    list: (sessionId: string) => request<FigureLedger>(`/sessions/${sessionId}/figures`),
  },
  kg: {
    /** What the graph was fed, by material — the simple view's flow diagram reads it. */
    sources: (sessionId: string) => request<KgSources>(`/sessions/${sessionId}/kg/sources`),
    ontology: (sessionId: string) => request<OntologyState>(`/sessions/${sessionId}/kg/ontology`),
    buildOntology: (sessionId: string) => request<OntologyState>(`/sessions/${sessionId}/kg/ontology/build`, { method: "POST" }),
  },
  scoping: {
    state: (sessionId: string) => request<ScopingState>(`/sessions/${sessionId}/scoping`),
    tag: (sessionId: string) => request<ScopingState>(`/sessions/${sessionId}/scoping/tag`, { method: "POST" }),
    /** Tag now if untagged or stale, then annotate every twin (what each can see). */
    ensure: (sessionId: string) => request<ScopingState>(`/sessions/${sessionId}/scoping/ensure`, { method: "POST" }),
    /** Per-twin scoping records for the Agents tab. */
    coverage: (sessionId: string) => request<ScopingCoverage>(`/sessions/${sessionId}/scoping/coverage`),
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
    /** The Journey tool (brief L7-01): propose the steps to the outcome from what the session knows. */
    // Calibration rules (brief L4-02) and lever runs (brief L7-04).
    rules: (sessionId: string) => request<{ rules: CalibrationRule[]; dials: Record<string, string[]>; bound_max: number; bound_default: number }>(`/sessions/${sessionId}/rules`),
    createRule: (sessionId: string, body: RuleRequest) => request<CalibrationRule>(`/sessions/${sessionId}/rules`, { method: "POST", body: JSON.stringify(body) }),
    /** The system drafts a rule for a lever from the candidate's barriers, the facts on file and the documents the twins cited; saved as a draft for a human to read, correct and sign. */
    draftRule: (sessionId: string, body: { lever: string; journey_probe_id?: string; candidate_id?: string; mode?: string }) =>
      request<CalibrationRule>(`/sessions/${sessionId}/rules/draft`, { method: "POST", body: JSON.stringify(body) }),
    updateRule: (sessionId: string, ruleId: string, body: RuleRequest) => request<CalibrationRule>(`/sessions/${sessionId}/rules/${ruleId}`, { method: "PUT", body: JSON.stringify(body) }),
    reviewRule: (sessionId: string, ruleId: string, reviewed_by: string, approve = true) =>
      request<CalibrationRule>(`/sessions/${sessionId}/rules/${ruleId}/review`, { method: "POST", body: JSON.stringify({ reviewed_by, approve }) }),
    deleteRule: (sessionId: string, ruleId: string) => request(`/sessions/${sessionId}/rules/${ruleId}`, { method: "DELETE" }),
    /** 409 with a LeverRefusal in the body when no reviewed rule exists for the lever. */
    runLever: (sessionId: string, body: { journey_probe_id: string; candidate_id: string; lever: string; rule_id?: string; mode?: string }) =>
      request<Experiment & { rule: CalibrationRule }>(`/sessions/${sessionId}/levers/run`, { method: "POST", body: JSON.stringify(body) }),
    leverRuns: (sessionId: string) => request<{ runs: Experiment[] }>(`/sessions/${sessionId}/levers`),
    /** Refresh a journey run with the simulation amendments: the same twins answer again with every signed rule in place; the growth per step is counted against the base run. 409 when nothing is signed. */
    amendJourney: (sessionId: string, probeId: string, body: { rule_ids?: string[]; mode?: string } = {}) =>
      request<Probe>(`/sessions/${sessionId}/journey/${probeId}/amend`, { method: "POST", body: JSON.stringify(body) }),
    journeyAmendments: (sessionId: string, probeId: string) => request<{ runs: Probe[] }>(`/sessions/${sessionId}/journey/${probeId}/amendments`),
    // Behaviour targeting (brief L7-05): rank behaviours by modelled movement per point at a candidate's step.
    targetingBehaviours: (sessionId: string) => request<TargetingMenu>(`/sessions/${sessionId}/targeting/behaviours`),
    runTargeting: (sessionId: string, body: { journey_probe_id: string; candidate_id: string; behaviours?: string[]; points?: number; mode?: string }) =>
      request<Experiment & { behaviours: string[]; points: number; at_risk: number }>(`/sessions/${sessionId}/targeting/run`, { method: "POST", body: JSON.stringify(body) }),
    targetingRuns: (sessionId: string) => request<{ runs: Experiment[] }>(`/sessions/${sessionId}/targeting`),
    // Message testing (brief L7-06): framings read by the twins at risk at a candidate's step; the shift counted per message and by cohort, backfire flagged.
    runMessaging: (sessionId: string, body: { journey_probe_id: string; candidate_id: string; messages: { label?: string; text: string }[]; mode?: string }) =>
      request<Experiment & { messages: MessageSpec[]; at_risk: number }>(`/sessions/${sessionId}/messaging/run`, { method: "POST", body: JSON.stringify(body) }),
    messagingRuns: (sessionId: string) => request<{ runs: Experiment[] }>(`/sessions/${sessionId}/messaging`),
    // Commitments (brief L7-08): freeze the modelled baseline for a chosen candidate outcome; enter observed results against it later.
    commitments: (sessionId: string) => request<{ commitments: Commitment[] }>(`/sessions/${sessionId}/commitments`),
    commit: (sessionId: string, body: { journey_probe_id: string; candidate_id: string; committed_by: string; label?: string; target?: { value?: number | string; horizon?: string; note?: string } }) =>
      request<Commitment>(`/sessions/${sessionId}/commitments`, { method: "POST", body: JSON.stringify(body) }),
    observeCommitment: (sessionId: string, commitmentId: string, body: { value: number; low?: number; high?: number; source: string; date: string; entered_by?: string; note?: string }) =>
      request<Commitment>(`/sessions/${sessionId}/commitments/${commitmentId}/observe`, { method: "POST", body: JSON.stringify(body) }),
    closeCommitment: (sessionId: string, commitmentId: string, body: { closed_by: string; note?: string }) =>
      request<Commitment>(`/sessions/${sessionId}/commitments/${commitmentId}/close`, { method: "POST", body: JSON.stringify(body) }),
    // Forms (2026-10-06): the Lab brief and the three ways to a questionnaire — import, write-for-me, the brainstorm chat.
    /** The stored Lab brief with `stale` (the session has moved on since it was written). */
    brief: (sessionId: string) => request<LabBriefState>(`/sessions/${sessionId}/lab/brief`),
    /** (Re)write the brief from everything on file; a current brief is returned as it is unless `force`. One strong-tier call. */
    buildBrief: (sessionId: string, force = false) =>
      request<LabBriefState>(`/sessions/${sessionId}/lab/brief`, { method: "POST", body: JSON.stringify({ mode: "pro", force }) }, 180_000),
    /** Pasted questionnaire text → typed questions (the model, else a heuristic parse). */
    formsImportText: (sessionId: string, text: string) =>
      request<FormDraft>(`/sessions/${sessionId}/forms/import`, { method: "POST", body: JSON.stringify({ text, mode: "pro" }) }, 180_000),
    /** An uploaded questionnaire (.pdf, .docx, .txt, .md, .csv …) → typed questions. */
    formsImportFile: async (sessionId: string, file: File): Promise<FormDraft> => {
      const fd = new FormData();
      fd.append("file", file);
      const res = await apiFetch(`/sessions/${sessionId}/forms/import/file`, { method: "POST", body: fd });
      if (!res.ok) {
        let detail = `Import failed (${res.status})`;
        try { detail = (await res.json()).detail || detail; } catch { /* keep */ }
        throw new Error(detail);
      }
      return res.json();
    },
    /** Write the form from the brief and a one-line goal; `existing` is extended rather than replaced. */
    formsGenerate: (sessionId: string, body: { goal?: string; length?: "short" | "standard" | "deep"; existing?: FormDraftInput | null }) =>
      request<FormDraft>(`/sessions/${sessionId}/forms/generate`, { method: "POST", body: JSON.stringify({ ...body, mode: "pro" }) }, 180_000),
    /** One turn of the brainstorm: the history and the form on screen go up; the reply may carry a changed form. An empty history returns the opening line. */
    formsChat: (sessionId: string, body: { messages: FormsChatMessage[]; form: FormDraftInput | null }) =>
      request<FormsChatReply>(`/sessions/${sessionId}/forms/chat`, { method: "POST", body: JSON.stringify({ ...body, mode: "pro" }) }, 180_000),
    journeySuggest: (sessionId: string, question?: string) =>
      request<JourneySuggestion>(`/sessions/${sessionId}/journey/suggest`, { method: "POST", body: JSON.stringify({ question: question || null, mode: "pro" }) }),
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
    /** Published segmentations that build a population directly, and the real polls to score against. */
    kits: () => request<{ kits: PopulationKit[]; benchmarks: BenchmarkSummary[] }>(`/kits`),
    fromKit: (sessionId: string, body: { kit_id: string; count: number; mode: SimMode; preset?: string | null; seed?: number; approve?: boolean }) =>
      request<PopulationBuild>(`/sessions/${sessionId}/population/kit`, { method: "POST", body: JSON.stringify(body) }),
    /** A finished Forms run scored against a real poll: per question, per segment, per demographic cut. */
    benchmarkScore: (sessionId: string, probeId: string, benchmarkId: string) =>
      request<BenchmarkScore>(`/sessions/${sessionId}/probes/${probeId}/benchmark/${encodeURIComponent(benchmarkId)}`),
    /** The scorecard against whichever real poll this Forms run reproduces (404 when none). */
    benchmarkScoreAuto: (sessionId: string, probeId: string) =>
      request<BenchmarkScore>(`/sessions/${sessionId}/probes/${probeId}/benchmark`),
  },
  presets: {
    list: () => request<AgentPreset[]>("/presets"),
    get: (presetId: string) => request<AgentPreset & { agents: Record<string, any>[] }>(`/presets/${presetId}`),
    /** A new lineup made only of hand-authored agents. */
    createCustom: (name: string, agents: AuthoredAgentDraft[], asArchetype = false) =>
      request<AgentPreset>("/presets/custom", { method: "POST", body: JSON.stringify({ name, agents, as_archetype: asArchetype }) }),
    /** Append hand-authored agents to an existing lineup (a name already in it is refused). */
    addAgents: (presetId: string, agents: AuthoredAgentDraft[], asArchetype = false) =>
      request<AgentPreset>(`/presets/${presetId}/agents`, { method: "POST", body: JSON.stringify({ agents, as_archetype: asArchetype }) }),
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
  /** Archetypes (brief L3-02): hand-authored twins the Studio casts personas from. */
  archetypes: {
    list: () => request<Archetype[]>("/archetypes"),
    delete: (id: string) => request(`/archetypes/${id}`, { method: "DELETE" }),
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
  /** The question's own dials (brief L3-04) — chosen by the model for this session. */
  dynamic_dials?: DynamicDial[] | null;
};

/** One dynamic dial: a question-specific 0-10 scale every twin in the session carries. */
export type DynamicDial = {
  key: string;
  label: string;
  why: string;
  low: string;
  high: string;
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

/** One material the knowledge graph was fed, with the chunks it left on file. */
export type KgSource = { kind: "file" | "text" | "video" | "page" | "research" | "social" | "statistics" | "synthetic" | "other"; name: string; ref: string; chunks: number };
export type KgSources = { sources: KgSource[]; chunks: number; entities: number; relations: number };

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
  /** This session's dynamic dials (brief L3-04), keyed by dial key. */
  dynamic?: DialCategory;
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
  /** Hand-authored character (Agent Builder), injected verbatim into the persona prompt. */
  character?: AgentCharacter | null;
  /** Behavioural validation (brief L3-05) — null until the background battery has scored this twin. */
  validation?: AgentValidation | null;
  /** Scoping (L1-04, wired end to end): what this twin was written from and can see — null until annotated. */
  knowledge?: AgentKnowledge | null;
};

export type AgentKnowledge = { snapshot_id: string | null; visible: number; total: number; routes: string[]; provenance: Record<string, number>; written_from: string | null; profile: Record<string, unknown>; at: string | null };
export type ScopingCoverage = { tagged: boolean; stale: boolean; unit_count: number; chunk_count: number; snapshot_id: string | null; annotated: number; total: number;
  agents: Record<string, { visible: number; total: number; snapshot_id: string | null; written_from: string | null; routes: string[]; provenance: Record<string, number> }> };

/** The battery's headline for one twin: 0-100 and the four parts behind it (each 0-1). */
export type AgentValidation = {
  score: number;
  band?: "strong" | "fair" | "weak" | null;
  parts?: { stability?: number | null; refusal?: number | null; knowledge?: number | null; register?: number | null };
  at?: string | null;
};

/** How far a whole population behaved like itself (GET /sessions/{id}/validation). */
export type ValidationSummary = {
  session_id: string;
  total: number;
  scored: number;
  mean: number | null;
  bands: Record<string, number>;
  parts: Record<string, number | null>;
  weakest: string | null;
  retest?: { agreement: number; n: number } | null;
};

/** The authored character fields (brief L3-01 / L3-04) — free text, each optional. */
export type AgentCharacter = {
  decision_rules?: string;
  behaviour?: string;
  vocabulary?: string;
  information_diet?: string;
  failure_modes?: string;
  /** Set on a persona the Studio cast from an archetype. */
  archetype?: { id: string; name: string };
};

/** What the Agent Builder sends: the person in words plus `dials` holding only the values the analyst fixed. */
export type AuthoredAgentDraft = {
  name: string;
  age?: number;
  role: string;
  background: string;
  stance?: "direct" | "indirect" | "neutral";
  correlation?: string;
  personality?: string[] | string;
  debate_style?: string;
  humanity?: number;
  /** True when the analyst set Expert↔Reactive by hand; otherwise the profile build places it. */
  humanity_fixed?: boolean;
  demographics?: AgentDemographics;
  character?: AgentCharacter;
  dials?: AgentDials;
};

/** An outcome record (brief L6-01): one computed figure about the population, the backbone every report is rendered from. */
export type OutcomeRecord = {
  id: string;
  kind: "headline" | "probe" | "experiment" | "lever" | "targeting" | "messaging" | "commitment";
  instrument: string;
  /** A reader's one-line reading of a shift record ("No message moved the twins (4 tested)"), so a tile never shows a bare 0 pts. */
  summary?: string | null;
  /** How many runs of this tool at this step exist; only the latest is listed and the earlier ids are superseded. */
  runs?: { count: number; superseded: string[] };
  label: string;
  question: string;
  basis: "simulated" | "evidence_anchored" | "client_reported";
  estimate: { metric: string; label: string; format: "share" | "lift" | "mean" | "text"; value: number | null; low: number | null; high: number | null; n: number; successes?: number; significant?: boolean; control?: number | null; variant?: number | null };
  sentence: string;
  distribution: { value: string; count: number; share: number }[];
  splits: Record<string, { value: string; share: number; low?: number; high?: number; n: number }[]>;
  /** Equity by default (brief L6-04): the record by deprivation level — most vs least deprived cell, the gap, whether it is real. */
  equity: EquityBlock;
  /** Barriers (brief L6-05): the ranked list a Barriers record carries; empty for every other record. */
  barriers?: BarrierItem[];
  /** The documents the answering twins cited for this record, by their own citation (L6-05), most cited first. */
  sources?: UsedUnit[];
  outcome?: string;
  /** Journey (brief L7-01): the steps, the funnel and the ranked candidate outcomes; empty for every other record. */
  journey?: JourneyStage[];
  funnel?: { key: string; label: string; reached: number; at: number; share: number; low: number; high: number;
    people?: number | null; people_low?: number | null; people_high?: number | null; basis?: HeadcountBasis; fixed?: boolean; anchor?: string; share_weighted?: number }[];
  candidates?: JourneyCandidate[];
  headcount?: JourneyHeadcount;
  refusals: { n: number; refused: number; share: number; reasons: { value: string; count: number; share: number }[]; who: { agent_id: string; name: string; why: string }[] } | null;
  unanimity: { flagged: boolean; top_share: number; widest_split: string; widest_spread: number; n: number; reason?: string } | null;
  weighted: { metric: string; label: string; format: string; weighted: number | null; unweighted: number | null; ess: number; n: number } | null;
  provenance: { model: string; seed: number; schema_id?: string; prompt_hash?: string; agents?: number; answered?: number; design?: string; arms?: any[]; evidence_mix: Record<string, number>; frame_level: string; created_at: string | null };
  confidence: { score: number; drivers: string[] };
  caveats: string[];
  tags: { condition?: string; journey_stage?: string };
};

/** The report's wired parts (brief L6-02): what the rendered report reads from data, not prose. */
export type ReportStructure = {
  version: number;
  direct_answer: { record_id: string | null; confidence: { band: "HIGH" | "MEDIUM" | "LOW" | null; score: number | null; drivers: string[] }; claimed_band: string | null };
  question: { session_query: string; instrument: string | null; asked: number | null; answered: number | null };
  /** What was run in the session and what was not (2026-09-30): the line under the direct answer, and the "not run" offers. */
  coverage?: { ran: { key: string; label: string; count: number; phrase: string; record_ids: string[] }[]; not_run: { key: string; label: string; adds: string; instrument: string | null; needs: string | null }[] };
  /** Follow-up questions written from the records, not a fixed list. */
  follow_ups?: string[];
  source_materials: {
    evidence: { class: string; label: string; count: number; on_topic: number; trust: Record<string, number>; top: { id: string | null; title: string; author: string; source_ref: string; trust: string }[] }[];
    frame: { level: string; summary: string; dimensions: { key: string; label: string; status: string; source?: string | null; geography?: string | null; year?: string | number | null }[]; estimated: string[]; thin_cells: string[] };
  };
  discussion: { record_id: string | null; positions: { value: string; count: number; share: number }[]; n: number; majority: string | null; dissent: { agent_id: string; position: string; confidence: number; verdict: string }[] };
  records: { all: string[]; cited: string[] };
  outcome: { caveats: { text: string; record_ids: string[] }[]; barriers?: { record_id: string | null; outcome: string; n: number; items: BarrierItem[] } | null;
    /** Where the population drops off (brief L7-01): the funnel and the ranked candidate outcomes from the newest Journey record. */
    candidates?: { record_id: string | null; n: number;
      headcount?: { available: boolean; sentence: string; reason: string; basis: HeadcountBasis; weighted: boolean };
      funnel: { label: string; share: number; reached: number; people?: number | null; people_low?: number | null; people_high?: number | null }[];
      items: { id: string; rank: number; from: string; to: string; label: string; n: number; stuck: number; conversion: number; low: number; high: number; gap: number | null; equity_gap: number | null;
        stuck_people?: number | null; stuck_low?: number | null; stuck_high?: number | null; at_risk_people?: number | null; basis?: HeadcountBasis;
        movability?: Partial<Movability>;
        barriers: { theme: string; count: number; weight_mean: number | null; removals: string[]; agent_ids: string[]; reach?: Reach; lever?: string; actor?: string }[] }[] } | null;
    /** Committed outcomes (brief L7-08): the frozen forecasts and the observed results against them. */
    commitments?: { record_id: string; label: string; from: string; to: string; status: "open" | "closed" | "superseded"; committed_by: string; committed_at: string | null; frozen_at: string;
      conversion: number; low: number; high: number; n: number; stuck: number; stuck_people?: number | null; stuck_low?: number | null; stuck_high?: number | null; basis?: string;
      build_id: string | null; population_n: number; frame_level: string; evidence_items: number; rules: number; related: { id: string; kind: string; label: string }[];
      target: { value?: number; horizon?: string; note?: string }; comparison: CommitmentComparison | null; observations: number; closed_by?: string; close_note?: string }[] | null };
  /** L6-03: the source figures the prose cites, and every number it typed with no source behind it. */
  figures?: { facts_cited: string[]; items_cited: string[]; unsourced: string[] };
};

/** A knowledge item a twin said it drew on (L6-05). */
export type UsedUnit = { unit_id: string; source_ref: string; provenance_class: string; trust_tier: string; text: string; route?: string; twins?: number; basis?: "used" | "could_see" };

export type BarrierItem = { theme: string; count: number; share: number | null; low?: number | null; high?: number | null; weight_mean: number | null;
  /** Movability (brief L7-03): who could reach it, the lever and who could pull it. Journey barriers only. */
  reach?: Reach; lever?: string; actor?: string; reach_reason?: string;
  removals: ({ value: string; count: number; share: number } | string)[]; agent_ids: string[];
  evidence: { unit_id: string; source_ref: string; provenance_class: string; trust_tier: string; text: string; twins: number; route: string }[] };

/** A candidate outcome (brief L7-01): one step of the journey where the twins drop off. */
export type JourneyStage = { key: string; label: string; definition?: string;
  /** A known headcount for this step (brief L7-02): held fixed, the steps after it scaled from it. Needs a source. */
  people?: number | string | null; people_source?: string };
export type HeadcountBasis = "official_statistic" | "client_supplied" | "client_anchored" | "";
/** Movability (brief L7-03): who could reach each barrier, counted up per candidate. */
export type Reach = "partner" | "system" | "structural" | "none" | "unscored" | "";
export type Movability = { scored: boolean; movable_count: number; movable_share: number; system_count: number; system_share: number; structural_count: number; structural_share: number;
  unscored_count: number; unscored_share: number; movable_people?: number | null; movable_low?: number | null; movable_high?: number | null;
  levers: { theme: string; lever: string; actor: string; count: number }[] };
export type JourneyCandidate = { id: string; rank: number; step: number; from: { key: string; label: string }; to: { key: string; label: string }; label: string;
  n: number; through: number; stuck: number; conversion: number; low: number; high: number; gap: number | null;
  movability?: Movability;
  /** Headcounts (brief L7-02): the gap in individuals, when a denominator exists. */
  at_risk_people?: number | null; through_people?: number | null; stuck_people?: number | null; stuck_low?: number | null; stuck_high?: number | null; basis?: HeadcountBasis;
  barriers: BarrierItem[]; equity: EquityBlock; confidence?: { score: number; drivers: string[] } };
/** The in-scope slice the frame can offer as a denominator (brief L7-02), or one the analyst typed. */
export type JourneyDenominator = { people: number; basis: HeadcountBasis; label: string; source: string; year: string; derived?: string };
export type JourneyHeadcount = { available: boolean; reason?: string; sentence?: string; denominator?: JourneyDenominator | null;
  anchors?: { step: string; people: number; source: string }[]; weighted?: boolean; ess?: number | null; unit?: string };
/** A calibration rule (brief L4-02): what evidence shows a lever does to behaviour. */
/** `basis_class`: evidence_anchored when at least one evidence line names a source; otherwise an assumption — a scenario the reviewer signs, labelled as such wherever its shift travels. */
export type CalibrationRule = { id: string; session_id: string; lever: string; description: string; applies_to: Record<string, string[]>; deltas: Record<string, number>; bound: number;
  evidence: { ref: string; note: string }[]; basis: string; author: string; status: "draft" | "reviewed"; reviewed_by: string; reviewed_at: string | null; created_at: string | null; updated_at: string | null;
  basis_class: "evidence_anchored" | "assumption"; drafted?: boolean; material?: number };
export type RuleRequest = Omit<CalibrationRule, "id" | "session_id" | "status" | "reviewed_by" | "reviewed_at" | "created_at" | "updated_at" | "basis_class" | "drafted" | "material">;
/** The modelled shift of a lever run (brief L7-04), counted from the two arms on the same twins. */
export type LeverShift = { available: boolean; reason?: string; candidate_id: string; step: number; from: { key: string; label: string }; to: { key: string; label: string };
  conversion: { then: number; now: number; lift: number; low: number; high: number; n: number; significant: boolean };
  stuck: { then: number; now: number }; movement: { up: number; down: number; unchanged: number; n: number };
  end: { label: string; then: number; now: number; lift: number; low: number; high: number; n: number; significant: boolean };
  segments: Record<string, { value: string; n: number; thin: boolean; then: number; now: number; lift: number; low: number; high: number }[]>;
  people?: { moved: number; low: number; high: number; stuck_then: number | null; stuck_now: number; basis: string };
  rule: { rule_id: string; lever: string; description: string; applies_to: Record<string, string[]>; deltas: Record<string, number>; bound: number; reviewed_by: string; reviewed_at: string | null;
    basis_class?: "evidence_anchored" | "assumption"; evidence_count?: number };
  assumed?: boolean; covered: number; journey_probe_id: string; sentence: string;
  /** Why it moved, in the twins' own words: the movers coded into reasons with a verbatim quote each, and those still stuck by the barrier they still name. */
  why?: LeverWhy };
export type LeverWhyRow = { reason: string; n: number; twins: string[]; quote: string; who: string };
export type LeverWhy = { n: { through: number; back: number; still_stuck: number; already_through: number }; coded: boolean;
  through: LeverWhyRow[]; back: LeverWhyRow[]; still_stuck: LeverWhyRow[]; sentence: string };
export type LeverRefusal = { refused: true; lever: string; reason: string; drafts: string[]; missing: boolean };
/** The growth of a journey refreshed with the simulation amendments — every signed rule in place — counted step by step against the base run on the same twins. */
export type JourneyGrowth = { available: boolean; reason?: string; n: number; base_probe_id?: string; assumed: boolean; covered: number;
  rules: { rule_id: string; lever: string; description: string; applies_to: Record<string, string[]>; deltas: Record<string, number>; bound: number; reviewed_by: string; reviewed_at: string | null;
    basis_class?: "evidence_anchored" | "assumption"; evidence_count?: number }[];
  funnel: { key: string; label: string; then: number; now: number; reached_then: number; reached_now: number; lift: number; low: number; high: number; n: number; significant: boolean;
    people_then?: number | null; people_now?: number | null; people_moved?: number | null; basis?: string }[];
  transitions: { id: string; step: number; from: { key: string; label: string }; to: { key: string; label: string }; then: number | null; now: number | null; lift: number; low: number; high: number; n: number;
    significant: boolean; stuck_then: number | null; stuck_now: number | null; up: number; down: number }[];
  end: { label: string; then: number; now: number; lift: number; low: number; high: number; n: number; significant: boolean; people_then?: number | null; people_now?: number | null; people_moved?: number | null };
  movement: { up: number; down: number; unchanged: number; n: number }; sentence: string;
  /** Why it moved over the whole journey, in the twins' own words: who gets further and who stops earlier, coded into reasons with a verbatim quote each. */
  why?: LeverWhy };
/** What a behaviour-targeting run can rank (brief L7-05): the question-specific dials (ticked by default) and the fixed dial vocabulary. */
export type TargetingMenu = { behaviours: { key: string; label: string; group: string; why: string; low: string; high: string; question_specific: boolean }[];
  fixed: Record<string, string[]>; points_default: number; points_max: number; max_behaviours: number };
export type TargetingBand = { value: string; n: number; thin: boolean; then: number; now: number; lift: number; low: number; high: number };
export type TargetingRow = { rank?: number; key: string; label: string; group: string; question_specific: boolean; available: boolean; reason?: string;
  points: number; lift: number; low: number; high: number; n: number; significant: boolean; per_point: number; per_point_low: number; per_point_high: number;
  direction: "up" | "down" | "none"; then: number; now: number; movement: { up: number; down: number; unchanged: number; n: number };
  end?: { label: string; then: number; now: number; lift: number }; bands: TargetingBand[]; backfire: { value: string; n: number; lift: number; per_point: number }[]; hurts: boolean;
  people?: { per_point: number; at_points: number; low: number; high: number; basis: string } };
export type TargetingResult = { available: boolean; candidate_id: string; step: number; from: { key: string; label: string }; to: { key: string; label: string }; points: number; n: number;
  behaviours: TargetingRow[]; any_significant: boolean; backfires: { key: string; label: string; direction: string; bands: { value: string; per_point: number }[]; hurts: boolean }[];
  end_label?: string; sentence: string; journey_probe_id?: string };
/** A message run (brief L7-06): the framings ranked by the shift in conversion at the step, backfire beside the winner, labelled a reaction not a forecast. */
export type MessageSpec = { key: string; label: string; text: string };
export type MessagingRow = { rank?: number; key: string; label: string; text: string; available: boolean; reason?: string;
  lift: number; low: number; high: number; n: number; significant: boolean; direction: "helps" | "hurts" | "none"; then: number; now: number;
  movement: { up: number; down: number; unchanged: number; n: number }; end?: { label: string; then: number; now: number; lift: number };
  segments: Record<string, TargetingBand[]>; bands: TargetingBand[]; backfire: { value: string; n: number; lift: number; low: number; high: number }[]; hurts: boolean;
  weighted: { lift: number; low: number; high: number; ess: number; significant: boolean } | null;
  people?: { moved: number; low: number; high: number; basis: string } };
export type MessagingResult = { available: boolean; candidate_id: string; step: number; from: { key: string; label: string }; to: { key: string; label: string }; n: number;
  messages: MessagingRow[]; any_significant: boolean; weighted: boolean; backfires: { key: string; label: string; hurts: boolean; lift: number; bands: { value: string; lift: number }[] }[];
  end_label?: string; label: string; sentence: string; journey_probe_id?: string };
/** A commitment (brief L7-08): the frozen modelled baseline for a candidate outcome a client chose to pursue, signed by name, never edited; observed results entered later against it. */
export type CommitmentObserved = { value: number; low?: number; high?: number; source: string; date: string; entered_by: string; entered_at: string; note: string };
export type CommitmentComparison = { observed: number; observed_date: string; observed_source: string; observations: number; forecast: number | null; forecast_low: number | null; forecast_high: number | null;
  delta?: number; direction?: "above" | "below" | "at"; inside_interval?: boolean; target?: number; target_met?: boolean };
export type Commitment = { id: string; session_id: string; journey_probe_id: string; candidate_id: string; label: string; committed_by: string; committed_at: string | null;
  target: { value?: number; horizon?: string; note?: string }; status: "open" | "closed" | "superseded"; superseded_by: string | null;
  closed_by: string; closed_at: string | null; close_note: string;
  baseline: { frozen_at: string; question: string; title: string; candidate: JourneyCandidate & Record<string, any>;
    journey: { probe_id: string; stages: JourneyStage[]; funnel: any[]; headcount: { available: boolean; sentence: string; reason: string; denominator: any; weighted: boolean }; n: number; seed: number; model: string; prompt_hash: string; created_at: string | null };
    related: { id: string; kind: string; label: string; estimate?: any; sentence?: string }[];
    population: { n: number; build_id: string | null; mode: string | null; weights: { n: number; weighted: boolean; ess: number } };
    frame: { level: string; matched_exactly: string[]; weighted_only: string[]; estimated: string[]; ess: number | null; thin_cells: any[]; geography: any; sizing: any };
    evidence: { counts: Record<string, number>; items: { id: string; title: string; source_ref: string; provenance_class: string; trust_tier: string; published_at: string; on_topic: boolean }[]; facts: any[] };
    scoping_snapshot: string | null; calibration_rules: { id: string; lever: string; status: string; reviewed_by: string; basis_class?: string }[]; statement: string };
  observed: CommitmentObserved[]; comparison: CommitmentComparison | null; sentence: string; created_at: string | null };
export type JourneySuggestion = { outcome: string; stages: JourneyStage[]; basis: string; grounded: boolean; denominator: JourneyDenominator | null };

export type ClientReport = {
  run: { session_id: string; question: string; title: string; generated_at: string; population: { n: number }; frame: { level: string; matched_exactly: string[]; weighted_only: string[]; estimated: string[]; ess: number | null; thin_cells: string[] }; evidence: Record<string, number>; scoping_snapshot: string | null; runs: any[] };
  statement: string;
  report: { id: string; created_at: string | null; answer: string; structure: ReportStructure | null } | null;
  records: OutcomeRecord[];
  ledger: FigureLedger;
  markdown: string;
};
export type ReportDelta = {
  a: { report_id: string; created_at: string | null; n: number | null }; b: { report_id: string; created_at: string | null; n: number | null };
  headline: { label: string; then: any; now: any; change_points: number | null; real: boolean | null } | null;
  positions: { value: string; then: number | null; now: number | null; change_points: number | null }[];
  equity: { then: { gap: number | null; significant: boolean | null } | null; now: { gap: number | null; significant: boolean | null } | null };
  dissent: { joined: { agent_id: string; position: string; verdict?: string }[]; left: { agent_id: string; position: string; verdict?: string }[]; stayed: any[]; majority_then: string | null; majority_now: string | null };
  barriers: { appeared: { theme: string; rank: number; count: number }[]; dropped: { theme: string; rank: number; count: number }[]; moved: { theme: string; then: number; now: number; count_then: number; count_now: number }[]; same: { theme: string; rank: number; count_then: number; count_now: number }[] } | null;
  evidence: { class: string; then: number; now: number; change: number }[]; evidence_total: { then: number; now: number };
  confidence: { then: { band: string | null; score: number | null }; now: { band: string | null; score: number | null } };
  unsourced: { then: number | null; now: number | null }; records: { then: number; now: number }; summary: string;
  coverage?: { added: string[]; dropped: string[] } | null;
  available: { id: string; created_at: string | null }[];
};

export type EquityCell = { rank: number; label: string; value: string; n: number; thin: boolean; share?: number | null; low?: number | null; high?: number | null; mean?: number | null };
export type EquityBlock =
  | { available: true; key: string; level: "quintile" | "decile"; label: string; cells: EquityCell[]; most: EquityCell; least: EquityCell; gap: number | null; gap_unit: string; significant: boolean | null; thin: string[]; spans: boolean }
  | { available: false; key: string; reason: string };

export type ProvenanceClass = "official_statistic" | "peer_reviewed" | "grey_literature" | "commissioned_research" | "client_data" | "social_signal" | "model_inference";
/** A typed statistic read from the material (brief L6-03): what `[[fact:<evidence id>#<k>]]` resolves to. */
export type SourceFact = { id: string; evidence_id: string; k: number; value: string; statistic: string; group: string; geography: string; year: string; quote: string; source: string; source_ref: string; title: string; provenance_class: ProvenanceClass; trust_tier: string };
/** An evidence item with its provenance class: what `[[evidence:<id>]]` resolves to. */
export type SourceItem = { id: string; provenance_class: ProvenanceClass; trust_tier: string; title: string; author: string; source_ref: string; published_at: string; on_topic: boolean; excerpt: string };
export type FigureLedger = { facts: SourceFact[]; items: SourceItem[] };

export type BuiltProfile = { dials: AgentDials; humanity: number; reading: string; dynamic_dials?: DynamicDial[] };

/** A hand-authored twin promoted to a mould the Population Studio casts personas from (§7.10 / L3-02). */
export type Archetype = { id: string; name: string; role: string; summary: string; created_at: string };

export type AgentDemographics = {
  gender?: string;
  region?: string;
  income_band?: string;
  education?: string;
  occupation?: string;
  /** Spawn-written paragraph: the query analysed from the agent's place — injected into their system prompt. */
  geo_behavior?: string;
  /** The persona's cell on each sampling-frame dimension (dimension key → category). */
  frame?: Record<string, string>;
  /** The persona's label on each question-specific population facet (facet key → label). */
  facets?: Record<string, string>;
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
  | { type: "scoping_started"; reason: string; chunks: number; stale: boolean }
  | { type: "scoping_complete"; reason: string; unit_count: number; snapshot_id: string | null; counts: Record<string, Record<string, number>> }
  | { type: "scoping_error"; reason: string; error: string }
  | { type: "scoping_annotated"; reason: string; count: number }
  | { type: "agent_validated"; agent_id: string; score: number; band: string; parts: Record<string, number | null> }
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
  /** Twins who said this was not theirs to answer (brief L3-06) — reported, never in the denominator. */
  dont_know?: {
    n: number;
    refused: number;
    share: number;
    reasons: { value: string; count: number; share: number }[];
    who: { agent_id: string; name: string; why: string }[];
  };
  /** The unanimity check (brief L3-06): agreement this population should not have produced. */
  unanimity?: {
    flagged: boolean;
    top_share: number;
    widest_split: string;
    widest_spread: number;
    n: number;
    reason?: string;
  };
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
  /** A lever run (brief L7-04): the counted shift, once both arms are in. */
  lever?: LeverShift;
  targeting?: TargetingResult;
  /** A message run (brief L7-06): the framings ranked, once counted. */
  messaging?: MessagingResult;
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
  /** "Select up to N" on a multi question. */
  max_choices?: number;
  /** Options that stand alone ("Don't know", "None of the above"). */
  exclusive?: string[];
  /** Routing: asked only of those who gave one of `equals` to question `key`. */
  show_if?: { key: string; equals: string[] } | null;
  /** Answer as likelihoods: the twin gives a chance per option and its answer is drawn from them. */
  likelihood?: boolean;
};

/** A published segmentation the Studio can build from (backend/app/data/kits). */
export type PopulationKit = {
  id: string;
  title: string;
  publisher?: string;
  population?: string;
  description?: string;
  year?: number | string;
  share_presets: Record<string, { label: string; source?: string }>;
  default_preset?: string;
  segments: { id: string; name: string; share_pct?: number; tagline?: string }[];
  benchmarks: string[];
};

export type BenchmarkSummary = { id: string; title?: string; fieldwork?: string; sample?: string; segmentation?: string; kit?: string; questions: number };

export type BenchmarkSummaryStats = {
  items: number; mae_pts: number; median_mae_pts: number; uniform_baseline_mae_pts: number | null;
  top_choice_agreement: number | null; mean_rank_corr: number | null; within_5_pts: number; national_baseline_mae_pts?: number | null;
  respondents?: number;
};

export type BenchmarkScore = {
  benchmark: string; title?: string; respondents: number;
  estimator?: "draws" | "likelihood"; benchmark_title?: string; fieldwork?: string; sample?: string;
  headline: BenchmarkSummaryStats;
  per_question: (BenchmarkSummaryStats & { question: string; number?: string; text: string; type: string })[];
  by_column: Record<string, BenchmarkSummaryStats>;
  segment_gradients: { question: string; option: string; real_spread_pts: number; corr: number | null; real: Record<string, number>; sim: Record<string, number> }[];
  units: { question: string; row?: string; mae_pts: number; options: { option: string; real_pct: number; sim_pct: number; diff_pts: number }[] }[];
  segment_units?: Record<string, { question: string; row?: string; mae_pts: number }[]>;
};

export type SurveyTemplate = {
  key: string;
  label: string;
  description: string;
  title: string;
  questions: SurveyQuestion[];
};

// ── Forms (2026-10-06) ───────────────────────────────────────────────────────

/** One open question the brief says a form should go after. */
export type LabChallenge = { title: string; why: string; measure: string };

/** The Lab brief: one structured read of everything the session holds, written once and
 *  prepended to every form-writing and brainstorm call. */
export type LabBrief = {
  question?: string;
  summary: string;
  population: string;
  what_we_know: string[];
  tensions: string[];
  challenges: LabChallenge[];
  already_measured: string[];
  vocabulary: string[];
  gaps: string[];
  /** Which stores spoke: population · debate · lab · report · evidence · studio · graph. */
  sources?: string[];
};

export type LabBriefState = {
  brief: LabBrief | null;
  status: "none" | "building" | "ready" | "failed";
  /** The session has moved on since the brief was written. */
  stale: boolean;
  built_at: string | null;
  inputs: Record<string, any>;
  fingerprint: string;
  model: string;
  error?: string | null;
};

/** A survey question as the form writer returns it: the instrument's fields plus `why`. */
export type FormQuestion = SurveyQuestion & { why?: string };

/** What the client sends: the form on screen. */
export type FormDraftInput = { title?: string; intro?: string; questions: SurveyQuestion[] };

/** What every forms call returns: a runnable form plus what the writer wants said about it. */
export type FormDraft = {
  title: string;
  intro: string;
  questions: FormQuestion[];
  rationale?: string;
  covers?: string[];
  notes: string[];
  /** The instrument's own validation of the result; empty when it can run. */
  problems: string[];
  grounded?: boolean;
  filename?: string;
};

export type FormsChatMessage = { role: "user" | "assistant"; content: string };

export type FormsChatReply = {
  reply: string;
  chips: string[];
  form_changed: boolean;
  form: FormDraft | null;
  change_note: string;
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
  /** Expert ↔ Reactive: 0 = experts, 50 = exactly as the real population is, 100 = ordinary people reacting from their own lives. `auto` lets the planner choose from the question. */
  voice?: { auto: boolean; value: number };
  profile_query?: string;
  doc_context?: string;
  skip_questions?: boolean;
  /** Simple view: approve the plan as proposed and start the debate as soon as the roster is written. */
  auto_run?: { intensity: number; mode: SimMode };
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
  /** The cell this segment mostly sits in on each sampling-frame dimension (dimension key → category). */
  frame_values?: Record<string, string>;
  /** The archetype this segment is cast from ("" = the model invents its personas); `archetype_manual` once the analyst chose. */
  archetype_id?: string;
  archetype_name?: string;
  archetype_manual?: boolean;
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
export type FrameDimension = { key: string; label: string; attribute: string; kind: "demographic" | "behavioural" | "attitudinal"; why: string; matchable: boolean; proxy_attribute: string; equity?: boolean; level?: "quintile" | "decile" };
export type FrameTarget = { status: "found" | "proxy" | "uploaded" | "estimated" | "skipped" | "missing"; categories: FrameCategory[]; source: string; year: string; geography: string; proxy_attribute: string; note: string; provenance?: string; confidence?: number };
export type FrameReportCell = { label: string; target_pct: number; planned_pct: number; achieved_pct: number | null; achieved_n: number | null; expected_n: number; thin: boolean };
export type FrameReportDim = { key: string; label: string; attribute: string; status: string; source: string; year: string; geography: string; provenance: string; priority: number; mode: "exact" | "weighted" | "unmatched"; cells?: FrameReportCell[]; max_deviation_planned?: number; max_deviation_achieved?: number | null; unplaced?: number | null };
export type FrameReport = { level: "good" | "fair" | "poor" | "none"; worst_deviation_pts: number; matched_exactly: string[]; weighted_only: string[]; unmatched: string[]; estimated: string[]; dimensions: FrameReportDim[]; thin_cells: string[]; stage: "planned" | "achieved"; n: number | null; ess: number | null };
export type FrameSizingCell = { value?: string; label?: string; source?: string; year?: string };
export type FrameSizing = { tam: FrameSizingCell; sam: FrameSizingCell; som: FrameSizingCell; note?: string };
export type PopulationFrame = { dimensions: FrameDimension[]; targets: Record<string, FrameTarget>; report: FrameReport | null; geography: string; sizing?: FrameSizing | null };

/** One cell type of the population map: what personas are counted by (5–15 per plan, ranked). */
export type PopulationFacet = { key: string; label: string; why: string; kind: "attribute" | "persona"; attribute: string; values_hint: string[] };

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
  plan: { segments: PopulationSegment[]; rationale: string; assumptions: string[]; evidence_coverage: string; facets?: PopulationFacet[]; voice?: { auto: boolean; value: number; reason: string } } | null;
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
