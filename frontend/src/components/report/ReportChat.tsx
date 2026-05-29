"use client";

import { useState, useRef, useEffect } from "react";
import { api, Agent } from "@/lib/api";
import {
  FileText, Send, Loader2, Bot, User,
  ChevronDown, MessageCircle, Download, RefreshCw, X,
} from "lucide-react";

interface Message {
  role: "user" | "assistant";
  content: string;
}

interface Props {
  sessionId: string;
  query: string;
  agents: Agent[];
  reportContent?: string | null;
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
  reportContent = null,
  isGeneratingReport = false,
  onMakeReport,
  onClearReport,
}: Props) {
  const [mode, setMode] = useState<Mode>("report");
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);
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

  // ── Layout: report exists → top report panel + bottom chat ─────────────────
  if (reportContent || isGeneratingReport) {
    return (
      <div className="h-full flex flex-col min-h-0">
        {/* Report document panel */}
        <div className="flex flex-col min-h-0" style={{ flex: "0 0 62%" }}>
          {/* Report header */}
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
          <div className="flex-1 overflow-y-auto min-h-0 px-5 py-5">
            {isGeneratingReport && !reportContent ? (
              <div className="flex items-center justify-center h-full gap-3 text-muted-foreground/60">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span className="text-sm">Generating report from all agents and sources…</span>
              </div>
            ) : (
              <div id="report-printable">
                <ReportDocument content={reportContent!} />
              </div>
            )}
          </div>
        </div>

        {/* Divider */}
        <div className="shrink-0 border-t border-border/40 no-print" />

        {/* Q&A chat panel */}
        <div className="flex flex-col min-h-0 no-print" style={{ flex: "0 0 38%" }}>
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
            compact
          />
        </div>
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
      />
    </div>
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
}

function ChatPanel({
  mode, setMode, agents, selectedAgent, setSelectedAgent,
  dropdownOpen, setDropdownOpen, dropdownRef,
  messages, loading, input, setInput, send,
  bottomRef, currentAgentColor, compact = false,
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
                  <p className="text-xs text-foreground/90 leading-relaxed whitespace-pre-wrap">{msg.content}</p>
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

// ── Report document renderer ──────────────────────────────────────────────────

function ReportDocument({ content }: { content: string }) {
  const blocks = parseReport(content);

  return (
    <div className="space-y-4 text-sm">
      {blocks.map((block, i) => {
        if (block.type === "direct_answer") {
          return (
            <div key={i} className="border-l-4 border-primary bg-primary/5 rounded-r-lg px-5 py-4 mb-2">
              <div className="flex items-center gap-2 mb-2.5">
                <span className="text-[10px] uppercase tracking-widest font-bold text-primary">Direct Answer</span>
                {block.confidence && (
                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold leading-none border ${
                    block.confidence === "HIGH"
                      ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/25"
                      : block.confidence === "MEDIUM"
                      ? "bg-yellow-500/10 text-yellow-400 border-yellow-500/25"
                      : "bg-red-500/10 text-red-400 border-red-500/25"
                  }`}>
                    {block.confidence} confidence
                  </span>
                )}
              </div>
              <p className="text-[15px] font-semibold text-foreground leading-snug"
                dangerouslySetInnerHTML={{ __html: renderInline(block.text) }} />
            </div>
          );
        }
        if (block.type === "h2") {
          return (
            <div key={i} className="pt-4">
              <div className="flex items-center gap-3 mb-2">
                <span className="text-[10px] uppercase tracking-widest text-primary font-bold shrink-0">{block.text}</span>
                <div className="flex-1 h-px bg-border/40" />
              </div>
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
              <span dangerouslySetInnerHTML={{ __html: renderInline(block.text) }} />
            </div>
          );
        }
        if (block.type === "kpi") {
          return (
            <div key={i} className="grid grid-cols-2 gap-2 my-1">
              {block.items!.map((item, j) => (
                <div key={j} className="border border-primary/20 rounded-lg px-3.5 py-3 bg-primary/4">
                  <div className="text-[10px] text-muted-foreground/55 uppercase tracking-wide mb-1 leading-none">{item.label}</div>
                  <div className="text-xl font-bold text-primary leading-tight">{item.value}</div>
                </div>
              ))}
            </div>
          );
        }
        return (
          <p key={i} className="text-foreground/75 leading-relaxed"
            dangerouslySetInnerHTML={{ __html: renderInline(block.text) }} />
        );
      })}
    </div>
  );
}

// ── Parser ────────────────────────────────────────────────────────────────────

type Block =
  | { type: "direct_answer"; text: string; confidence?: string }
  | { type: "h2" | "h3" | "paragraph" | "bullet"; text: string }
  | { type: "kpi"; items: { label: string; value: string }[] };

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

    if (inKeyMetrics) {
      const kpiMatch = line.match(/^[*\-•]?\s*(.+?):\s*(.+)$/);
      if (kpiMatch && kpiMatch[2].trim().length < 80) {
        kpiBuffer.push({ label: kpiMatch[1].replace(/\*/g, "").trim(), value: kpiMatch[2].replace(/\*/g, "").trim() });
        continue;
      }
    } else {
      const kpiMatch = line.match(/^\*?\*?([A-Za-z][^:*\n]{2,40})\*?\*?:\s*(.+)$/);
      if (kpiMatch && !line.startsWith("-") && !line.startsWith("•") && kpiMatch[2].length < 60 && /[\d%$€£x+\-]/.test(kpiMatch[2])) {
        kpiBuffer.push({ label: kpiMatch[1].replace(/\*/g, "").trim(), value: kpiMatch[2].trim() });
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

function renderInline(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, "<strong class='text-foreground font-semibold'>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>");
}
