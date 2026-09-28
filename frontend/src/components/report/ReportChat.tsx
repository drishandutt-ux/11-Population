"use client";

import { useState, useRef, useEffect, useMemo } from "react";
import { api, Agent, OutcomeRecord, Post, ReportStructure } from "@/lib/api";
import {
  FileText, Send, Loader2, Bot, User,
  ChevronDown, MessageCircle, Download, RefreshCw, X, Quote, Hash, AlertTriangle,
} from "lucide-react";
import ConfidenceBadge from "@/components/ConfidenceBadge";

interface Message {
  role: "user" | "assistant";
  content: string;
}

interface Props {
  sessionId: string;
  query: string;
  agents: Agent[];
  /** The transcript, so a citation can show the line it is quoting. */
  posts?: Post[];
  reportContent?: string | null;
  /** The outcome records the report is rendered from (brief L6-01); loaded here when not given. */
  records?: OutcomeRecord[];
  /** The report's wired parts (brief L6-02): computed confidence, evidence by class, positions + dissent, caveats. */
  structure?: ReportStructure | null;
  isGeneratingReport?: boolean;
  onMakeReport?: () => void;
  onClearReport?: () => void;
}

const STARTER_QUESTIONS = [
  "What is the overall consensus among the agents?",
  "What are the strongest arguments for this idea?",
  "What are the main risks or concerns raised?",
  "Which agents were most insightful?",
  "Summarize the key insights from the simulation",
];

type Mode = "report" | "agent";

export default function ReportChat({
  sessionId,
  query,
  agents,
  posts = [],
  reportContent = null,
  records: recordsProp,
  structure = null,
  isGeneratingReport = false,
  onMakeReport,
  onClearReport,
}: Props) {
  const [mode, setMode] = useState<Mode>("report");
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  // The twin a citation in the report (or a chat reply) was clicked on: who they are, and
  // the line being quoted. Backtracking is the point — a claim you cannot trace is a claim.
  const [cited, setCited] = useState<{ agent: Agent; post?: Post; x: number; y: number } | null>(null);
  // A record citation ([[record:…]]) or record card that was clicked: the computed figure behind the claim.
  const [openRecord, setOpenRecord] = useState<{ record: OutcomeRecord; x: number; y: number } | null>(null);
  const [loadedRecords, setLoadedRecords] = useState<OutcomeRecord[]>([]);
  useEffect(() => {
    if (recordsProp && recordsProp.length) return;
    api.records.list(sessionId).then((r) => setLoadedRecords(r.records || [])).catch(() => {});
  }, [sessionId, reportContent, recordsProp]);
  const records = recordsProp && recordsProp.length ? recordsProp : loadedRecords;
  RECORDS_BY_ID = Object.fromEntries(records.map((r) => [r.id, r]));
  const [reportMessages, setReportMessages] = useState<Message[]>([]);
  const [agentMessages, setAgentMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [reportMessages.length, agentMessages.length]);

  useEffect(() => { setAgentMessages([]); }, [selectedAgent?.id]);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const messages = mode === "report" ? reportMessages : agentMessages;
  const setMessages = mode === "report" ? setReportMessages : setAgentMessages;

  const agentsById = useMemo(() => Object.fromEntries(agents.map((a) => [a.id, a])), [agents]);
  const postsById = useMemo(() => Object.fromEntries(posts.map((p) => [p.id, p])), [posts]);

  /** Delegated click for every `[[twin:…]]` citation rendered inside this panel. */
  function handleCiteClick(e: React.MouseEvent) {
    const rel = (e.target as HTMLElement).closest?.("[data-record]") as HTMLElement | null;
    if (rel) {
      const record = RECORDS_BY_ID[rel.dataset.record || ""];
      if (record) {
        e.preventDefault();
        const rect = rel.getBoundingClientRect();
        setOpenRecord({ record, x: rect.left, y: rect.bottom + 6 });
      }
      return;
    }
    const el = (e.target as HTMLElement).closest?.("[data-twin]") as HTMLElement | null;
    if (!el) return;
    e.preventDefault();
    const agent = agentsById[el.dataset.twin || ""];
    if (!agent) return;
    const rect = el.getBoundingClientRect();
    setCited({
      agent,
      post: el.dataset.post ? postsById[el.dataset.post] : undefined,
      x: rect.left,
      y: rect.bottom + 6,
    });
  }

  async function send(question: string) {
    if (!question.trim() || loading) return;
    if (mode === "agent" && !selectedAgent) return;
    const q = question.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: q }]);
    setLoading(true);
    try {
      if (mode === "report") {
        const result = await api.report.query(sessionId, q) as { answer: string };
        setMessages((prev) => [...prev, { role: "assistant", content: result.answer }]);
      } else {
        const result = await api.agents.chat(selectedAgent!.id, q) as { reply: string };
        setMessages((prev) => [...prev, { role: "assistant", content: result.reply }]);
      }
    } catch (e: any) {
      setMessages((prev) => [...prev, { role: "assistant", content: `Error: ${e.message}` }]);
    } finally {
      setLoading(false);
    }
  }

  // ── PDF export ─────────────────────────────────────────────────────────────
  function handleSaveAsPDF() {
    window.print();
  }

  const currentAgentColor = selectedAgent?.avatar_color ?? "#6366f1";

  // ── Layout: report exists → report left + chat right ──────────────────────
  if (reportContent || isGeneratingReport) {
    return (
      <div className="h-full flex flex-row min-h-0 overflow-hidden">
        {/* LEFT: Report document */}
        <div className="flex flex-col min-h-0 flex-1 min-w-0">
          {/* Report toolbar */}
          <div className="px-5 py-2.5 border-b border-border/40 flex items-center justify-between shrink-0 no-print">
            <div className="flex items-center gap-2">
              <FileText className="w-3.5 h-3.5 text-primary" />
              <span className="text-xs font-medium text-foreground">Report</span>
            </div>
            <div className="flex items-center gap-2">
              {!isGeneratingReport && reportContent && (
                <>
                  <button
                    onClick={handleSaveAsPDF}
                    className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded border border-border/60 text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors"
                  >
                    <Download className="w-3 h-3" />
                    Save as PDF
                  </button>
                  {onMakeReport && (
                    <button
                      onClick={onMakeReport}
                      className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded border border-border/60 text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors"
                    >
                      <RefreshCw className="w-3 h-3" />
                      Regenerate
                    </button>
                  )}
                </>
              )}
              {onClearReport && !isGeneratingReport && (
                <button
                  onClick={onClearReport}
                  className="text-muted-foreground/50 hover:text-foreground transition-colors"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          </div>

          {/* Report body */}
          <div className="flex-1 overflow-y-auto min-h-0 px-6 py-6">
            {isGeneratingReport && !reportContent ? (
              <div className="flex items-center justify-center h-full gap-3 text-muted-foreground/60">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span className="text-sm">Generating report from all agents and sources…</span>
              </div>
            ) : (
              <div id="report-printable" className="max-w-2xl" onClick={handleCiteClick}>
                <ReportDocument content={reportContent!} agentsById={agentsById} records={records} structure={structure} />
              </div>
            )}
          </div>
        </div>

        {/* Vertical divider */}
        <div className="shrink-0 border-l border-border/40 no-print" />

        {/* RIGHT: Chat panel */}
        <div className="w-96 shrink-0 flex flex-col min-h-0 no-print">
          <ChatPanel
            mode={mode}
            setMode={setMode}
            agents={agents}
            selectedAgent={selectedAgent}
            setSelectedAgent={setSelectedAgent}
            dropdownOpen={dropdownOpen}
            setDropdownOpen={setDropdownOpen}
            dropdownRef={dropdownRef}
            messages={messages}
            loading={loading}
            input={input}
            setInput={setInput}
            send={send}
            bottomRef={bottomRef}
            currentAgentColor={currentAgentColor}
            agentsById={agentsById}
            onCiteClick={handleCiteClick}
            compact
          />
        </div>

        {openRecord && <RecordCard record={openRecord.record} x={openRecord.x} y={openRecord.y} onClose={() => setOpenRecord(null)} />}
        {cited && (
          <TwinTrace
            agent={cited.agent}
            post={cited.post}
            x={cited.x}
            y={cited.y}
            onClose={() => setCited(null)}
            onTalk={() => { setMode("agent"); setSelectedAgent(cited.agent); setCited(null); }}
          />
        )}
      </div>
    );
  }

  // ── Layout: no report yet → full Q&A interface ─────────────────────────────
  return (
    <div className="h-full flex flex-col min-h-0">
      {/* Generate Report CTA */}
      {onMakeReport && (
        <div className="px-6 py-4 border-b border-border/40 shrink-0 flex items-center gap-3">
          <button
            onClick={onMakeReport}
            disabled={isGeneratingReport}
            className="flex items-center gap-2 text-sm px-4 py-2 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium"
          >
            {isGeneratingReport ? (
              <><Loader2 className="w-3.5 h-3.5 animate-spin" />Generating…</>
            ) : (
              <><FileText className="w-3.5 h-3.5" />Generate Report</>
            )}
          </button>
          <span className="text-xs text-muted-foreground/60">
            Produces a structured briefing from all agents and source materials
          </span>
        </div>
      )}

      <ChatPanel
        mode={mode}
        setMode={setMode}
        agents={agents}
        selectedAgent={selectedAgent}
        setSelectedAgent={setSelectedAgent}
        dropdownOpen={dropdownOpen}
        setDropdownOpen={setDropdownOpen}
        dropdownRef={dropdownRef}
        messages={messages}
        loading={loading}
        input={input}
        setInput={setInput}
        send={send}
        bottomRef={bottomRef}
        currentAgentColor={currentAgentColor}
        agentsById={agentsById}
        onCiteClick={handleCiteClick}
      />

      {openRecord && <RecordCard record={openRecord.record} x={openRecord.x} y={openRecord.y} onClose={() => setOpenRecord(null)} />}
      {cited && (
        <TwinTrace
          agent={cited.agent}
          post={cited.post}
          x={cited.x}
          y={cited.y}
          onClose={() => setCited(null)}
          onTalk={() => { setMode("agent"); setSelectedAgent(cited.agent); setCited(null); }}
        />
      )}
    </div>
  );
}

// ── The trace card: who said it, and who they were ────────────────────────────

/** Where this twin came from — the mould, the segment, or the model. Answers "who was he?". */
function origin(agent: Agent): string {
  const arch = agent.character?.archetype;
  if (arch?.name) return `Cast from the “${arch.name}” archetype`;
  if (agent.character) return "Hand-authored in the Agent Builder";
  if (agent.segment) return `Written for the segment “${agent.segment}”`;
  return "Written for this session";
}

function TwinTrace({
  agent, post, x, y, onClose, onTalk,
}: {
  agent: Agent; post?: Post; x: number; y: number;
  onClose: () => void; onTalk: () => void;
}) {
  const demo = agent.demographics || {};
  const facts: [string, string | undefined][] = [
    ["Role", agent.role],
    ["Age", String(agent.age)],
    ["Place", demo.region],
    ["Segment", agent.segment || undefined],
    ["Stance", agent.stance],
    ["Expert ↔ Reactive", agent.humanity != null ? String(agent.humanity) : undefined],
    ["Weight", agent.weight != null && agent.weight !== 1 ? agent.weight.toFixed(2) : undefined],
  ];
  // Clamped so a citation near the right edge or the fold still opens a readable card.
  const left = Math.min(x, (typeof window !== "undefined" ? window.innerWidth : 1200) - 360);
  const top = Math.min(y, (typeof window !== "undefined" ? window.innerHeight : 800) - 320);

  return (
    <>
      <div className="fixed inset-0 z-40 no-print" onClick={onClose} />
      <div
        className="fixed z-50 w-[340px] rounded-xl border border-border bg-background shadow-xl no-print"
        style={{ left: Math.max(12, left), top: Math.max(12, top) }}
      >
        <div className="flex items-start gap-2.5 px-4 pt-3.5 pb-3 border-b border-border/50">
          <span
            className="w-7 h-7 rounded-lg flex items-center justify-center text-[11px] font-bold text-white shrink-0"
            style={{ backgroundColor: agent.avatar_color }}
          >
            {agent.name.charAt(0)}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-foreground leading-tight">{agent.name}</span>
              <ConfidenceBadge validation={agent.validation} size="xs" />
            </div>
            <div className="text-[11px] text-muted-foreground/70 leading-tight mt-0.5">{origin(agent)}</div>
          </div>
          <button onClick={onClose} className="text-muted-foreground/50 hover:text-foreground shrink-0">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>

        <div className="px-4 py-3 grid grid-cols-2 gap-x-3 gap-y-2">
          {facts.filter(([, v]) => v).map(([k, v]) => (
            <div key={k}>
              <div className="text-[9px] uppercase tracking-wide text-muted-foreground/50">{k}</div>
              <div className="text-[11px] text-foreground/85 leading-snug">{v}</div>
            </div>
          ))}
        </div>

        {post?.content && (
          <div className="px-4 pb-3">
            <div className="text-[9px] uppercase tracking-wide text-muted-foreground/50 mb-1 flex items-center gap-1">
              <Quote className="w-2.5 h-2.5" /> What they said {post.round_num ? `· round ${post.round_num}` : ""}
            </div>
            <p className="text-[11px] text-foreground/80 leading-relaxed border-l-2 border-primary/40 pl-2.5 max-h-40 overflow-y-auto">
              {post.content}
            </p>
          </div>
        )}

        <div className="px-4 py-2.5 border-t border-border/50 flex items-center justify-between">
          <span className="text-[10px] text-muted-foreground/45 font-mono">{agent.id.slice(0, 8)}</span>
          <button
            onClick={onTalk}
            className="flex items-center gap-1.5 text-[11px] px-2.5 py-1.5 rounded border border-border/60 text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors"
          >
            <MessageCircle className="w-3 h-3" />
            Talk to this twin
          </button>
        </div>
      </div>
    </>
  );
}

// ── Shared chat panel ─────────────────────────────────────────────────────────

interface ChatPanelProps {
  mode: Mode;
  setMode: (m: Mode) => void;
  agents: Agent[];
  selectedAgent: Agent | null;
  setSelectedAgent: (a: Agent | null) => void;
  dropdownOpen: boolean;
  setDropdownOpen: (o: boolean) => void;
  dropdownRef: React.RefObject<HTMLDivElement>;
  messages: Message[];
  loading: boolean;
  input: string;
  setInput: (v: string) => void;
  send: (q: string) => void;
  bottomRef: React.RefObject<HTMLDivElement>;
  currentAgentColor: string;
  compact?: boolean;
  /** Resolves `[[twin:…]]` citations in an assistant reply to the twin's real name. */
  agentsById: Record<string, Agent>;
  onCiteClick: (e: React.MouseEvent) => void;
}

function ChatPanel({
  mode, setMode, agents, selectedAgent, setSelectedAgent,
  dropdownOpen, setDropdownOpen, dropdownRef,
  messages, loading, input, setInput, send,
  bottomRef, currentAgentColor, compact = false,
  agentsById, onCiteClick,
}: ChatPanelProps) {
  return (
    <div className={`flex flex-col min-h-0 ${compact ? "h-full" : "flex-1"}`}>
      {/* Mode toggle */}
      <div className="border-b border-border px-4 py-2 flex items-center gap-3 shrink-0">
        <div className="flex bg-muted rounded-lg p-0.5 gap-0.5">
          <button
            onClick={() => setMode("report")}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-all ${
              mode === "report" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <FileText className="w-3 h-3" />
            Ask Report
          </button>
          <button
            onClick={() => setMode("agent")}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-all ${
              mode === "agent" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <MessageCircle className="w-3 h-3" />
            Talk to Agent
          </button>
        </div>

        {mode === "agent" && (
          <div className="relative" ref={dropdownRef}>
            <button
              onClick={() => setDropdownOpen(!dropdownOpen)}
              className="flex items-center gap-2 bg-muted border border-border rounded-lg px-2.5 py-1 text-sm hover:border-border/80 transition-colors"
            >
              {selectedAgent ? (
                <>
                  <span
                    className="w-4 h-4 rounded flex items-center justify-center text-[10px] font-bold text-white shrink-0"
                    style={{ backgroundColor: currentAgentColor }}
                  >
                    {selectedAgent.name.charAt(0)}
                  </span>
                  <span className="text-foreground text-xs font-medium">{selectedAgent.name}</span>
                </>
              ) : (
                <span className="text-muted-foreground text-xs">Select agent…</span>
              )}
              <ChevronDown className="w-3 h-3 text-muted-foreground" />
            </button>

            {dropdownOpen && (
              <div className="absolute top-full left-0 mt-1 w-72 bg-background border border-border rounded-xl shadow-xl z-50 overflow-hidden">
                <div className="max-h-60 overflow-y-auto divide-y divide-border">
                  {agents.length === 0 ? (
                    <p className="text-xs text-muted-foreground px-4 py-3">No agents spawned yet</p>
                  ) : (
                    agents.map((a) => (
                      <button
                        key={a.id}
                        onClick={() => { setSelectedAgent(a); setDropdownOpen(false); }}
                        className={`w-full flex items-start gap-3 px-4 py-2.5 text-left hover:bg-muted transition-colors ${selectedAgent?.id === a.id ? "bg-primary/5" : ""}`}
                      >
                        <span
                          className="w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold text-white shrink-0"
                          style={{ backgroundColor: a.avatar_color }}
                        >
                          {a.name.charAt(0)}
                        </span>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-foreground text-xs">{a.name}</span>
                            <span className={`text-[10px] px-1 py-0.5 rounded border ${
                              a.stance === "direct" ? "border-blue-500/30 text-blue-400" :
                              a.stance === "indirect" ? "border-purple-500/30 text-purple-400" :
                              "border-slate-500/30 text-slate-400"
                            }`}>{a.stance}</span>
                          </div>
                          <p className="text-[10px] text-muted-foreground truncate">{a.role}</p>
                        </div>
                      </button>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto min-h-0 px-4 py-4">
        <div className="max-w-3xl mx-auto space-y-3">
          {messages.length === 0 && mode === "report" && !compact && (
            <div className="text-center pt-4">
              <p className="text-sm text-muted-foreground mb-6">Ask anything about the simulation, knowledge graph, or uploaded content.</p>
              <div className="flex flex-col gap-2">
                {STARTER_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    onClick={() => send(q)}
                    className="text-sm text-left rounded-xl px-4 py-2.5 border border-border/60 hover:border-primary/30 transition-all text-muted-foreground hover:text-foreground"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.length === 0 && compact && (
            <p className="text-xs text-muted-foreground/60 text-center py-2">
              Ask follow-up questions about the report…
            </p>
          )}

          {messages.map((msg, i) => {
            const isUser = msg.role === "user";
            return (
              <div key={i} className={`flex gap-2 ${isUser ? "flex-row-reverse" : ""}`}>
                <div
                  className={`w-6 h-6 rounded-lg flex items-center justify-center shrink-0 text-[10px] font-bold text-white ${isUser ? "bg-primary/20" : ""}`}
                  style={!isUser && mode === "agent" && selectedAgent ? { backgroundColor: currentAgentColor } : undefined}
                >
                  {isUser
                    ? <User className="w-3 h-3 text-primary" />
                    : mode === "agent" && selectedAgent
                      ? selectedAgent.name.charAt(0)
                      : <Bot className="w-3 h-3 text-muted-foreground" />
                  }
                </div>
                <div className={`rounded-xl px-3 py-2 max-w-2xl border border-border/40 bg-muted/20 ${isUser ? "rounded-tr-sm" : "rounded-tl-sm"}`}>
                  {isUser
                    ? <p className="text-xs text-foreground/90 leading-relaxed whitespace-pre-wrap">{msg.content}</p>
                    : (
                      <>
                        {mode === "agent" && selectedAgent?.validation && (
                          <div className="flex items-center gap-1.5 mb-1">
                            <span className="text-[10px] text-muted-foreground/60">{selectedAgent.name}</span>
                            <ConfidenceBadge validation={selectedAgent.validation} size="xs" />
                          </div>
                        )}
                        <div onClick={onCiteClick}><MessageContent text={msg.content} agentsById={agentsById} /></div>
                      </>
                    )}
                </div>
              </div>
            );
          })}

          {loading && (
            <div className="flex gap-2">
              <div
                className="w-6 h-6 rounded-lg flex items-center justify-center text-[10px] font-bold text-white"
                style={mode === "agent" && selectedAgent ? { backgroundColor: currentAgentColor } : undefined}
              >
                {mode === "agent" && selectedAgent ? selectedAgent.name.charAt(0) : <Bot className="w-3 h-3 text-muted-foreground" />}
              </div>
              <div className="rounded-xl rounded-tl-sm px-3 py-2 border border-border/40 bg-muted/20">
                <Loader2 className="w-3 h-3 text-muted-foreground animate-spin" />
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-border/40 px-4 py-3 shrink-0">
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send(input)}
            placeholder={
              mode === "report"
                ? "Ask about the simulation…"
                : selectedAgent ? `Ask ${selectedAgent.name.split(" ")[0]}…` : "Select an agent first…"
            }
            disabled={loading || (mode === "agent" && !selectedAgent)}
            className="flex-1 bg-muted border border-border/60 rounded-lg px-3 py-2 text-foreground placeholder-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50 text-xs disabled:opacity-50"
          />
          <button
            onClick={() => send(input)}
            disabled={loading || !input.trim() || (mode === "agent" && !selectedAgent)}
            className="bg-primary hover:bg-primary/90 disabled:opacity-50 text-primary-foreground px-3 py-2 rounded-lg transition-all shrink-0"
          >
            <Send className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Citations ─────────────────────────────────────────────────────────────────
// The report model never types a name: it cites `[[twin:<id>]]`, optionally `|post:<id>`
// for the exact line. The name below is read from the agent record, so it cannot drift.

const CITE_RE = /\[\[twin:([0-9a-fA-F-]{36})(?:\|post:([0-9a-fA-F-]{36}))?\]\]/g;
// A figure about the population is never typed by the model: it cites `[[record:<id>]]` and the
// number a reader sees is read from the outcome record (brief L6-01).
const RECORD_RE = /\[\[record:([0-9a-fA-F-]{36})\]\]/g;
let RECORDS_BY_ID: Record<string, OutcomeRecord> = {};

function fmtEstimate(r: OutcomeRecord): string {
  const e = r.estimate;
  if (e.value == null) return "—";
  if (e.format === "share") return `${Math.round(e.value * 100)}%`;
  if (e.format === "lift") return `${e.value > 0 ? "+" : ""}${Math.round(e.value * 100)} pts`;
  return String(e.value);
}
function fmtInterval(r: OutcomeRecord): string {
  const e = r.estimate;
  if (e.low == null || e.high == null) return "";
  if (e.format === "share") return `95% CI ${Math.round(e.low * 100)}–${Math.round(e.high * 100)}%`;
  if (e.format === "lift") return `95% CI ${Math.round(e.low * 100)} to ${Math.round(e.high * 100)} pts`;
  return `${e.low}–${e.high}`;
}

function renderRecordCitations(html: string): string {
  return html.replace(RECORD_RE, (_m, id: string) => {
    const r = RECORDS_BY_ID[id];
    if (!r) return "";
    return (
      `<button type="button" data-record="${id}" title="${r.label} — ${fmtInterval(r)} · n=${r.estimate.n} · confidence ${r.confidence.score}/100" ` +
      `class="record-cite inline-flex items-center gap-1 align-baseline text-[11px] font-semibold px-1.5 py-px rounded border border-teal-500/40 text-teal-300 bg-teal-500/10 hover:bg-teal-500/20">` +
      `${fmtEstimate(r)}<span class="font-normal text-teal-300/70">· ${r.label.length > 34 ? r.label.slice(0, 32) + "…" : r.label}</span></button>`
    );
  });
}

function renderCitations(html: string, agentsById: Record<string, Agent>): string {
  html = renderRecordCitations(html);
  return html.replace(CITE_RE, (_m, twinId: string, postId?: string) => {
    const agent = agentsById[twinId];
    if (!agent) return "a twin in the population";
    const post = postId ? ` data-post="${postId}"` : "";
    return (
      `<button type="button" data-twin="${twinId}"${post} title="${agent.name} — ${agent.role}" ` +
      `class="twin-cite font-medium text-primary underline decoration-dotted underline-offset-2 hover:decoration-solid">` +
      `${agent.name}</button>`
    );
  });
}

// ── Chat message renderer (markdown-lite for assistant replies) ────────────────

function renderInlineChat(text: string, agentsById: Record<string, Agent> = {}): string {
  const esc = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return renderCitations(
    esc
      .replace(/\*\*(.+?)\*\*/g, "<strong class='font-semibold text-foreground'>$1</strong>")
      .replace(/`([^`]+?)`/g, "<code class='px-1 py-0.5 rounded bg-muted text-[11px] font-mono'>$1</code>")
      .replace(/(^|[^*])\*([^*\s][^*]*?)\*(?!\*)/g, "$1<em>$2</em>"),
    agentsById,
  );
}

function MessageContent({ text, agentsById = {} }: { text: string; agentsById?: Record<string, Agent> }) {
  const lines = text.split("\n");
  const out: React.ReactNode[] = [];
  let bullets: string[] = [];

  const flushBullets = () => {
    if (bullets.length) {
      out.push(
        <ul key={`u${out.length}`} className="list-disc pl-4 space-y-0.5">
          {bullets.map((b, j) => (
            <li key={j} dangerouslySetInnerHTML={{ __html: renderInlineChat(b, agentsById) }} />
          ))}
        </ul>
      );
      bullets = [];
    }
  };

  lines.forEach((raw) => {
    const line = raw.trim();
    if (!line || /^-{3,}$/.test(line)) { flushBullets(); return; }
    const heading = line.match(/^#{1,6}\s+(.*)$/);
    if (heading) {
      flushBullets();
      out.push(<p key={`h${out.length}`} className="font-semibold text-foreground">{heading[1].replace(/[*#]/g, "").trim()}</p>);
      return;
    }
    const bullet = line.match(/^[-*•]\s+(.*)$/) || line.match(/^\d+[.)]\s+(.*)$/);
    if (bullet) { bullets.push(bullet[1]); return; }
    flushBullets();
    out.push(<p key={`p${out.length}`} dangerouslySetInnerHTML={{ __html: renderInlineChat(line, agentsById) }} />);
  });
  flushBullets();

  return <div className="text-xs text-foreground/90 leading-relaxed space-y-1.5">{out}</div>;
}

// ── Report document renderer ──────────────────────────────────────────────────

function ReportDocument({ content, agentsById, records = [], structure = null }: { content: string; agentsById: Record<string, Agent>; records?: OutcomeRecord[]; structure?: ReportStructure | null }) {
  const blocks = parseReport(content);
  const firstAnswer = blocks.findIndex((b) => b.type === "direct_answer");
  // The confidence beside the direct answer is the headline record's computed band (L6-02);
  // the model's own label is only a fallback for reports written before the structure existed.
  const computed = structure?.direct_answer?.confidence;
  const hasOutcome = blocks.some((b) => b.type === "h2" && /^outcome/i.test(b.text));

  return (
    <div className="space-y-4 text-sm">
      {blocks.map((block, i) => {
        if (block.type === "direct_answer") {
          const band = computed?.band || block.confidence;
          return (
            <div key={i}>
            <div className="border-l-4 border-primary bg-primary/5 rounded-r-lg px-5 py-4 mb-2">
              <div className="flex items-center gap-2 mb-2.5">
                <span className="text-[10px] uppercase tracking-widest font-bold text-primary">Direct Answer</span>
                {band && (
                  <button type="button" data-record={computed?.band ? structure?.direct_answer?.record_id || undefined : undefined}
                    title={computed?.band ? `Computed from the headline record: ${computed.drivers.join(" · ")}` : "Stated by the model"}
                    className={`text-[10px] px-1.5 py-0.5 rounded font-semibold leading-none border ${
                    band === "HIGH"
                      ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/25"
                      : band === "MEDIUM"
                      ? "bg-yellow-500/10 text-yellow-400 border-yellow-500/25"
                      : "bg-red-500/10 text-red-400 border-red-500/25"
                  }`}>
                    {band} confidence{computed?.band && computed.score != null ? ` · ${computed.score}/100` : ""}
                  </button>
                )}
                {computed?.band && <span className="text-[9px] text-muted-foreground/55">computed</span>}
              </div>
              <p className="text-[15px] font-semibold text-foreground leading-snug"
                dangerouslySetInnerHTML={{ __html: renderInline(block.text, agentsById) }} />
            </div>
            {i === firstAnswer && records.length > 0 && <RecordGrid records={records} />}
            </div>
          );
        }
        if (block.type === "h2") {
          // The section's computed part sits under its heading, before the model's prose (L6-02).
          const wired = !structure ? null
            : /^source materials?/i.test(block.text) ? <SourceMaterials sm={structure.source_materials} />
            : /^discussion/i.test(block.text) ? <Positions d={structure.discussion} agentsById={agentsById} />
            : null;
          return (
            <div key={i} className="pt-4">
              <div className="flex items-center gap-3 mb-2">
                <span className="text-[10px] uppercase tracking-widest text-primary font-bold shrink-0">{block.text}</span>
                <div className="flex-1 h-px bg-border/40" />
              </div>
              {wired}
            </div>
          );
        }
        if (block.type === "h3") {
          return <p key={i} className="text-xs font-semibold text-foreground/90 mt-2">{block.text}</p>;
        }
        if (block.type === "bullet") {
          return (
            <div key={i} className="flex gap-2.5 text-foreground/75 leading-relaxed">
              <span className="text-primary/50 shrink-0 mt-0.5 text-xs">·</span>
              <span dangerouslySetInnerHTML={{ __html: renderInline(block.text, agentsById) }} />
            </div>
          );
        }
        if (block.type === "kpi") {
          return (
            <div key={i} className="grid grid-cols-2 gap-2 my-1">
              {block.items!.map((item, j) => (
                <div key={j} className="border border-primary/20 rounded-lg px-3.5 py-3 bg-primary/4">
                  <div className="text-[10px] text-muted-foreground/55 uppercase tracking-wide mb-1 leading-none"
                    dangerouslySetInnerHTML={{ __html: renderInline(item.label, agentsById) }} />
                  <div className="text-xl font-bold text-primary leading-tight"
                    dangerouslySetInnerHTML={{ __html: renderInline(item.value, agentsById) }} />
                </div>
              ))}
            </div>
          );
        }
        return (
          <p key={i} className="text-foreground/75 leading-relaxed"
            dangerouslySetInnerHTML={{ __html: renderInline(block.text, agentsById) }} />
        );
      })}
      {structure && hasOutcome && <ComputedCaveats caveats={structure.outcome.caveats} />}
    </div>
  );
}

// ── The wired sections (brief L6-02) ──────────────────────────────────────────
// Source materials by role, the positions with named dissent, and the conclusion-changing
// caveats are read from the report structure — computed on the backend from the evidence
// store, the verdict probe and the records — so the model's prose describes them, never
// decides them.

function SourceMaterials({ sm }: { sm: ReportStructure["source_materials"] }) {
  const ev = sm?.evidence || [];
  const fr = sm?.frame;
  const sourced = (fr?.dimensions || []).filter((d) => d.source);
  if (!ev.length && (!fr || fr.level === "none")) return null;
  return (
    <div className="mb-3 rounded-lg border border-border/40 bg-muted/10 px-3.5 py-3 space-y-2">
      <div className="text-[9px] uppercase tracking-wide text-muted-foreground/60 font-semibold">By role · from the evidence store</div>
      {ev.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {ev.map((e) => (
            <span key={e.class} className="text-[10px] px-2 py-0.5 rounded-full border border-border/50 bg-background/60"
              title={Object.entries(e.trust || {}).map(([k, n]) => `${k} trust ${n}`).join(" · ") || undefined}>
              <span className="font-semibold text-foreground/85">{e.label}</span>
              <span className="text-muted-foreground"> {e.count}{e.on_topic && e.on_topic !== e.count ? ` · ${e.on_topic} on topic` : ""}</span>
            </span>
          ))}
        </div>
      )}
      {ev.some((e) => e.top?.length) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-0.5">
          {ev.flatMap((e) => (e.top || []).slice(0, 3).map((t) => (
            <div key={`${e.class}-${t.id || t.source_ref}`} className="text-[10px] text-foreground/70 truncate">
              <span className="text-muted-foreground/60">{e.label.split(" ")[0]}</span> · {t.title}{t.author ? <span className="text-muted-foreground/60"> — {t.author}</span> : null}
            </div>
          )))}
        </div>
      )}
      {fr && (
        <div className="text-[10px] text-muted-foreground/85 leading-snug">
          <span className="font-semibold text-foreground/75">Frame:</span> {fr.summary}
          {sourced.length > 0 && (
            <span className="block mt-0.5">{sourced.map((d) => `${d.label} — ${d.source}${d.geography || d.year ? ` (${[d.geography, d.year].filter(Boolean).join(" ")})` : ""}`).join(" · ")}</span>
          )}
        </div>
      )}
    </div>
  );
}

const POSITION_COLOR: Record<string, string> = { for: "bg-emerald-400/80", mixed: "bg-yellow-400/70", against: "bg-red-400/80" };
const POSITION_DOT: Record<string, string> = { for: "bg-emerald-400", mixed: "bg-yellow-400", against: "bg-red-400" };

function Positions({ d, agentsById }: { d: ReportStructure["discussion"]; agentsById: Record<string, Agent> }) {
  if (!d || !d.n) return null;
  return (
    <div className="mb-3 rounded-lg border border-border/40 bg-muted/10 px-3.5 py-3 space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-[9px] uppercase tracking-wide text-muted-foreground/60 font-semibold">Positions · {d.n} twins answered</span>
        {d.record_id && <button type="button" data-record={d.record_id} className="text-[9px] text-teal-300/80 underline decoration-dotted underline-offset-2">headline record</button>}
      </div>
      <div className="flex h-2 rounded-full overflow-hidden bg-muted">
        {d.positions.filter((p) => p.count > 0).map((p) => (
          <div key={p.value} className={POSITION_COLOR[p.value] || "bg-muted-foreground/50"} style={{ width: `${Math.round(p.share * 100)}%` }} title={`${p.value}: ${p.count} (${Math.round(p.share * 100)}%)`} />
        ))}
      </div>
      <div className="flex flex-wrap gap-3 text-[10px] text-foreground/80">
        {d.positions.map((p) => (
          <span key={p.value} className="inline-flex items-center gap-1">
            <span className={`w-1.5 h-1.5 rounded-full ${POSITION_DOT[p.value] || "bg-muted-foreground"}`} />
            {p.value} {Math.round(p.share * 100)}% <span className="text-muted-foreground/60">({p.count})</span>
            {p.value === d.majority && <span className="text-muted-foreground/60">· majority</span>}
          </span>
        ))}
      </div>
      {d.dissent.length > 0 ? (
        <div>
          <div className="text-[9px] uppercase tracking-wide text-muted-foreground/60 font-semibold mb-1">Named dissent · did not hold the majority position</div>
          <ul className="space-y-1">
            {d.dissent.map((x) => {
              const a = agentsById[x.agent_id];
              return (
                <li key={x.agent_id} className="text-[11px] leading-snug">
                  <button type="button" data-twin={x.agent_id} title={a ? `${a.name} — ${a.role}` : undefined}
                    className="twin-cite font-medium text-primary underline decoration-dotted underline-offset-2 hover:decoration-solid">
                    {a?.name || "a twin in the population"}
                  </button>
                  <span className="text-muted-foreground/70"> · {x.position} · {x.confidence}/100</span>
                  {x.verdict && <span className="text-foreground/80"> — &ldquo;{x.verdict}&rdquo;</span>}
                </li>
              );
            })}
          </ul>
        </div>
      ) : (
        <div className="text-[10px] text-muted-foreground/70">No dissent: every twin who answered held the majority position.</div>
      )}
    </div>
  );
}

function ComputedCaveats({ caveats }: { caveats: ReportStructure["outcome"]["caveats"] }) {
  if (!caveats?.length) return null;
  return (
    <div className="mt-4 rounded-lg border border-yellow-500/20 bg-yellow-500/5 px-3.5 py-3">
      <div className="text-[9px] uppercase tracking-wide text-yellow-300/80 font-semibold mb-1.5">What would change this · computed from the records</div>
      <ul className="space-y-1">
        {caveats.map((c, i) => (
          <li key={i} className="flex gap-2 text-[11px] text-foreground/80 leading-snug">
            <span className="text-yellow-400/60 shrink-0">·</span>
            <span>
              {c.text}
              {c.record_ids?.length > 0 && (
                <button type="button" data-record={c.record_ids[0]} className="ml-1.5 text-[9px] text-teal-300/80 underline decoration-dotted underline-offset-2">
                  {c.record_ids.length > 1 ? `${c.record_ids.length} records` : "record"}
                </button>
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── Outcome records (brief L6-01) ─────────────────────────────────────────────
// The report's backbone: every card is a computed figure with its interval, its n and its
// confidence — read from the record, never from the prose. Click one for the splits, the
// refusals, the unanimity verdict, the provenance and the caveats.

const KIND_LABEL: Record<string, string> = { headline: "Population verdict", probe: "Lab result", experiment: "A/B lift" };

function RecordGrid({ records }: { records: OutcomeRecord[] }) {
  return (
    <div className="mt-3">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[10px] uppercase tracking-widest text-teal-300 font-bold flex items-center gap-1"><Hash className="w-3 h-3" /> Outcome records</span>
        <span className="text-[10px] text-muted-foreground/60">{records.length} computed from the twins&apos; answers · every figure in this report cites one</span>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-2">
        {records.map((r) => {
          const flagged = r.unanimity?.flagged;
          const refused = r.refusals?.refused || 0;
          return (
            <button key={r.id} type="button" data-record={r.id} className="text-left border border-teal-500/25 rounded-lg px-3.5 py-3 bg-teal-500/5 hover:bg-teal-500/10 transition-colors">
              <div className="flex items-center gap-1.5 mb-1">
                <span className="text-[9px] uppercase tracking-wide text-teal-300/80 font-semibold">{KIND_LABEL[r.kind] || r.kind}</span>
                {flagged && <AlertTriangle className="w-3 h-3 text-yellow-400" />}
              </div>
              <div className="text-[11px] text-foreground/85 leading-snug line-clamp-2">{r.label}</div>
              <div className="flex items-baseline gap-2 mt-1.5">
                <span className="text-xl font-bold text-teal-300 leading-none">{fmtEstimate(r)}</span>
                <span className="text-[10px] text-muted-foreground/70">{fmtInterval(r)}</span>
              </div>
              <div className="flex items-center gap-2 mt-1.5 text-[10px] text-muted-foreground/70">
                <span>n={r.estimate.n}</span>
                <span>· confidence {r.confidence.score}/100</span>
                {refused > 0 && <span>· {refused} refused</span>}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function RecordCard({ record: r, x, y, onClose }: { record: OutcomeRecord; x: number; y: number; onClose: () => void }) {
  const left = Math.min(x, (typeof window !== "undefined" ? window.innerWidth : 1200) - 400);
  const top = Math.min(y, (typeof window !== "undefined" ? window.innerHeight : 800) - 460);
  const splitKeys = Object.keys(r.splits || {}).filter((k) => (r.splits[k] || []).length >= 2).slice(0, 3);
  const mix = Object.entries(r.provenance?.evidence_mix || {}).filter(([, n]) => n > 0);
  return (
    <>
      <div className="fixed inset-0 z-40 no-print" onClick={onClose} />
      <div className="fixed z-50 w-[380px] max-h-[70vh] overflow-y-auto rounded-xl border border-teal-500/30 bg-background shadow-xl no-print" style={{ left: Math.max(12, left), top: Math.max(12, top) }}>
        <div className="flex items-start gap-2.5 px-4 pt-3.5 pb-3 border-b border-border/50">
          <div className="min-w-0 flex-1">
            <div className="text-[9px] uppercase tracking-wide text-teal-300/80 font-semibold">{KIND_LABEL[r.kind] || r.kind} · {r.basis.replace("_", " ")}</div>
            <div className="text-sm font-semibold text-foreground leading-tight mt-0.5">{r.label}</div>
            {r.question && <div className="text-[11px] text-muted-foreground/70 leading-snug mt-1">{r.question}</div>}
          </div>
          <button onClick={onClose} className="text-muted-foreground/50 hover:text-foreground shrink-0"><X className="w-3.5 h-3.5" /></button>
        </div>
        <div className="px-4 py-3 space-y-3">
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-bold text-teal-300 leading-none">{fmtEstimate(r)}</span>
            <span className="text-[11px] text-muted-foreground">{r.estimate.label} · {fmtInterval(r)} · n={r.estimate.n}</span>
          </div>
          {r.sentence && <p className="text-[11px] text-foreground/80 leading-snug">{r.sentence}</p>}
          {r.weighted && r.weighted.weighted != null && (
            <p className="text-[10px] text-muted-foreground/80">Weighted to the frame: {r.weighted.format === "share" ? `${Math.round((r.weighted.weighted || 0) * 100)}%` : r.weighted.weighted} (effective n {r.weighted.ess.toFixed(1)})</p>
          )}
          {r.unanimity?.flagged && (
            <div className="flex gap-2 text-[10px] text-yellow-200/90 bg-yellow-500/10 border border-yellow-500/25 rounded-lg px-2.5 py-2"><AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-px text-yellow-400" /><span>{r.unanimity.reason}</span></div>
          )}
          {r.refusals && r.refusals.refused > 0 && (
            <p className="text-[10px] text-muted-foreground/80">{r.refusals.refused} of {r.refusals.n} said it was not theirs to answer — outside every denominator.</p>
          )}
          {splitKeys.length > 0 && (
            <div className="space-y-2">
              {splitKeys.map((k) => (
                <div key={k}>
                  <div className="text-[9px] uppercase tracking-wide text-muted-foreground/50 mb-1">{k.replace(/^dyn:/, "").replace(/_/g, " ")}</div>
                  <div className="space-y-0.5">
                    {(r.splits[k] || []).slice(0, 5).map((b) => (
                      <div key={b.value} className="flex items-center gap-2 text-[10px]">
                        <span className="w-24 truncate text-foreground/80">{b.value}</span>
                        <div className="flex-1 h-1 bg-muted rounded-full overflow-hidden"><div className="h-full bg-teal-400/70 rounded-full" style={{ width: `${Math.round((b.share || 0) * 100)}%` }} /></div>
                        <span className="w-14 text-right tabular-nums text-muted-foreground">{Math.round((b.share || 0) * 100)}% <span className="text-muted-foreground/50">n={b.n}</span></span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
          <div>
            <div className="text-[9px] uppercase tracking-wide text-muted-foreground/50 mb-1">Confidence {r.confidence.score}/100</div>
            <ul className="text-[10px] text-foreground/75 space-y-0.5">{r.confidence.drivers.map((d, i) => <li key={i}>· {d}</li>)}</ul>
          </div>
          {r.caveats?.length > 0 && (
            <div>
              <div className="text-[9px] uppercase tracking-wide text-muted-foreground/50 mb-1">Caveats</div>
              <ul className="text-[10px] text-muted-foreground/85 space-y-0.5">{r.caveats.map((c, i) => <li key={i}>· {c}</li>)}</ul>
            </div>
          )}
          <div className="text-[10px] text-muted-foreground/60 border-t border-border/40 pt-2">
            {r.provenance.model && <span>model {r.provenance.model} · </span>}seed {r.provenance.seed} · frame {r.provenance.frame_level}
            {mix.length > 0 && <span> · evidence {mix.map(([k, n]) => `${k} ${n}`).join(", ")}</span>}
            <span className="block font-mono text-muted-foreground/45 mt-0.5">{r.id.slice(0, 8)}</span>
          </div>
        </div>
      </div>
    </>
  );
}

// ── Parser ────────────────────────────────────────────────────────────────────

type Block =
  | { type: "direct_answer"; text: string; confidence?: string }
  | { type: "h2" | "h3" | "paragraph" | "bullet"; text: string }
  | { type: "kpi"; items: { label: string; value: string }[] };

/** Same length, no colons: lets the KPI regexes run without tripping over `[[twin:…]]`. */
function maskCitations(line: string): string {
  return line.replace(CITE_RE, (t) => "·".repeat(t.length));
}

/** `(.+)$` anchors the value to the end of the line, so its length locates the split exactly. */
function splitKpi(line: string, valueLen: number): { label: string; value: string } {
  const value = line.slice(line.length - valueLen).trim();
  const label = line
    .slice(0, line.length - valueLen)
    .replace(/^[*\-•]\s*/, "")
    .replace(/[:\s]+$/, "")
    .replace(/\*/g, "")
    .trim();
  return { label, value };
}

function parseReport(raw: string): Block[] {
  const lines = raw.split("\n");
  const blocks: Block[] = [];
  let kpiBuffer: { label: string; value: string }[] = [];
  let inDirectAnswer = false;
  let inKeyMetrics = false;
  let directAnswerLines: string[] = [];

  const flushKpi = () => {
    if (kpiBuffer.length > 0) { blocks.push({ type: "kpi", items: [...kpiBuffer] }); kpiBuffer = []; }
  };

  const flushDirectAnswer = () => {
    if (directAnswerLines.length > 0) {
      const text = directAnswerLines.join(" ").trim();
      const confMatch = text.match(/\*?\*?Confidence:\s*(HIGH|MEDIUM|LOW)\*?\*?/i);
      const confidence = confMatch ? confMatch[1].toUpperCase() : undefined;
      const cleanText = text
        .replace(/\*?\*?Confidence:\s*(HIGH|MEDIUM|LOW)[.,]?\*?\*?/gi, "")
        .replace(/\s*---+\s*/g, " ")
        .replace(/\s{2,}/g, " ")
        .trim();
      blocks.push({ type: "direct_answer", text: cleanText, confidence });
      directAnswerLines = []; inDirectAnswer = false;
    }
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();

    if (/^#{2,3}\s+/.test(line)) {
      flushKpi(); flushDirectAnswer();
      const isH3 = /^###\s+/.test(line);
      const heading = line.replace(/^#{2,3}\s+/, "").trim();
      if (!isH3 && /^direct answer$/i.test(heading)) { inDirectAnswer = true; inKeyMetrics = false; }
      else if (!isH3 && /^key metrics?$/i.test(heading)) { inKeyMetrics = true; blocks.push({ type: "h2", text: heading }); }
      else { inKeyMetrics = false; blocks.push({ type: isH3 ? "h3" : "h2", text: heading }); }
      continue;
    }

    if (!line || /^-{3,}$/.test(line)) continue;

    if (inDirectAnswer) { directAnswerLines.push(line); continue; }

    // A citation token carries a colon, so the label/value split is decided on a masked
    // copy and the text is then sliced out of the real line (same length, same indices).
    const masked = maskCitations(line);
    if (inKeyMetrics) {
      const kpiMatch = masked.match(/^[*\-•]?\s*(.+?):\s*(.+)$/);
      if (kpiMatch && kpiMatch[2].trim().length < 80) {
        kpiBuffer.push(splitKpi(line, kpiMatch[2].length));
        continue;
      }
    } else {
      const kpiMatch = masked.match(/^\*?\*?([A-Za-z][^:*\n]{2,40})\*?\*?:\s*(.+)$/);
      if (kpiMatch && !line.startsWith("-") && !line.startsWith("•") && kpiMatch[2].length < 60 && /[\d%$€£x+\-]/.test(kpiMatch[2])) {
        kpiBuffer.push(splitKpi(line, kpiMatch[2].length));
        continue;
      }
    }

    flushKpi();

    if (/^[-•*]\s+/.test(line)) { blocks.push({ type: "bullet", text: line.replace(/^[-•*]\s+/, "") }); continue; }
    blocks.push({ type: "paragraph", text: line });
  }

  flushKpi(); flushDirectAnswer();
  return blocks;
}

function renderInline(text: string, agentsById: Record<string, Agent> = {}): string {
  return renderCitations(
    text
      .replace(/\*\*(.+?)\*\*/g, "<strong class='text-foreground font-semibold'>$1</strong>")
      .replace(/\*(.+?)\*/g, "<em>$1</em>"),
    agentsById,
  );
}
