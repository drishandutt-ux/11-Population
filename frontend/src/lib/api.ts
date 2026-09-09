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
  id: string; run_id?: string | null; source_class: "web" | "social" | "personal" | "synthetic"; source_ref: string;
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
  | { type: "research_status"; run_id: string; status: string; note?: string };
