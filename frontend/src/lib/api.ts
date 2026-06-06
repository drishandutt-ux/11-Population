const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}/api/v1${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json();
}

// Sessions
export const api = {
  sessions: {
    create: (title: string, query: string) =>
      request("/sessions", { method: "POST", body: JSON.stringify({ title, query }) }),
    list: () => request("/sessions"),
    get: (id: string) => request(`/sessions/${id}`),
    delete: (id: string) => request(`/sessions/${id}`, { method: "DELETE" }),
    posts: (id: string) => request(`/sessions/${id}/posts`),
    opinions: (id: string) => request(`/sessions/${id}/opinions`, { method: "POST" }),
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
      return fetch(`${BASE}/api/v1/sessions/${sessionId}/ingest/document`, {
        method: "POST",
        body: form,
      }).then((r) => r.json());
    },
    llmGenerate: (sessionId: string, data: { query: string; llm: string; contextFile?: File | null }) => {
      const form = new FormData();
      form.append("query", data.query);
      form.append("llm", data.llm);
      if (data.contextFile) form.append("context_file", data.contextFile);
      return fetch(`${BASE}/api/v1/sessions/${sessionId}/ingest/llm-search/generate`, {
        method: "POST",
        body: form,
      }).then((r) => r.json());
    },
    llmSearch: (sessionId: string, data: { query: string; llm: string; contextFile?: File | null }) => {
      const form = new FormData();
      form.append("query", data.query);
      form.append("llm", data.llm);
      if (data.contextFile) form.append("context_file", data.contextFile);
      return fetch(`${BASE}/api/v1/sessions/${sessionId}/ingest/llm-search`, {
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
    start: (sessionId: string, maxRounds: number) =>
      request(`/sessions/${sessionId}/simulate/start`, {
        method: "POST",
        body: JSON.stringify({ max_rounds: maxRounds }),
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
};

export type Session = {
  id: string;
  title: string;
  query: string;
  status: string;
  agent_count: number;
  created_at: string;
  updated_at: string;
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
};

export type SpawnOptions = {
  profile_query?: string;
  direct_pct?: number;
  indirect_pct?: number;
  neutral_pct?: number;
  doc_context?: string;
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

export type WSEvent =
  | { type: "agent_spawned"; agent: Partial<Agent>; index?: number; total?: number }
  | { type: "agents_ready"; count: number }
  | { type: "spawn_error"; error: string }
  | { type: "simulation_started"; agent_count: number }
  | { type: "post_created"; post: Post; agent: Partial<Agent> }
  | { type: "like_added"; post_id: string; agent_id: string; new_likes: number }
  | { type: "kg_updated"; new_entities: string[]; new_relations: string[][] }
  | { type: "ingest_complete"; source: string }
  | { type: "simulation_complete"; message: string };
