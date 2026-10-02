"use client";

import { useState, useRef, useEffect, useMemo } from "react";
import PersonaAvatar from "@/components/PersonaAvatar";
import { api, Agent, OutcomeRecord, Post, ReportStructure, SourceFact, SourceItem, ProvenanceClass, EquityBlock, EquityCell, ReportDelta } from "@/lib/api";
import {
  FileText, Send, Loader2, Bot, User,
  ChevronDown, ChevronRight, MessageCircle, Download, RefreshCw, X, Quote, Hash, AlertTriangle, GitCompare, Printer, Beaker } from "lucide-react";
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
  /** Opens the Lab tab — the coverage line offers the tools that were not run. */
  onGoToLab?: () => void;
  /** Earlier Ask-Report questions and answers from the session's history, so a reload keeps the conversation. */
  initialMessages?: Message[];
}

/** Only while no report exists: once there is one, the questions come from its records (`structure.follow_ups`). */
const STARTER_QUESTIONS = [
  "Where do the twins agree, and where do they split?",
  "What are the strongest arguments for this idea?",
  "What are the main risks or concerns the twins raised?",
  "Which twins argued most convincingly, and for what?",
  "Summarise what the debate settled and what it left open",
];

// ── Plain words for the units the records use ─────────────────────────────────
// Every unit a reader meets on the page has a hover explanation; the page never assumes a
// reader knows what n, a 95% interval, a deprivation quintile or movability is.

const GLOSSARY: Record<string, string> = {
  n: "How many twins answered this. A share of 8 twins is far less certain than a share of 80.",
  ci: "The 95% interval: re-run the same twins many times and the share would land inside this range 95 times in 100. Wide means uncertain.",
  pts: "Percentage points: the difference between two shares (30% to 35% is +5 pts).",
  q1: "Q1 is the fifth of the population living in the most deprived areas (Index of Multiple Deprivation); Q5 the least deprived.",
  gap: "The most deprived cell minus the least deprived cell, in percentage points. 'Real' means the two intervals do not overlap; 'not distinguishable' means they do, so the gap may be noise at this size.",
  confidence: "A computed 5–95 score from the record's own numbers: how many answered, how wide the interval is, whether the panel matches published distributions, whether agreement looked too neat. Never typed by the model.",
  movable: "The share of the stuck whose barrier a single partner could remove, from what the twins said would remove it.",
  system: "Stuck behind a barrier only the wider system (council, landlord, NHS) could remove.",
  structural: "Stuck behind a barrier nobody can remove soon (housing stock, geography).",
  weight: "How heavily the twins who raised this barrier said it weighs on them, 0–100.",
  ess: "Effective sample size: after weighting the twins to match the population, how many twins' worth of information is left.",
  match: "How closely the twins match published distributions (age, deprivation, tenure…): good, fair, poor or none.",
  verdict: "The record of the population's answer to the session question: every twin's for / against / mixed.",
  runs: "This tool was run more than once at this step; only the latest run is shown. Earlier runs stay on file and appear in Compare runs.",
  shift: "A shift is the change in the share getting through a step when the twins re-answer under a lever or a message: modelled, not observed.",
  weighted: "The share after weighting the twins to the population's published distributions.",
};

function Term({ k, children, className = "" }: { k: keyof typeof GLOSSARY | string; children: React.ReactNode; className?: string }) {
  return <abbr title={GLOSSARY[k] || undefined} className={`no-underline cursor-help border-b border-dotted border-muted-foreground/40 ${className}`}>{children}</abbr>;
}

/** A plain reading of a record kind for tiles and cards. */
const KIND_LABEL: Record<string, string> = {
  headline: "Population verdict", probe: "Lab result", experiment: "A/B test", lever: "Lever run", targeting: "Behaviour ranking", messaging: "Message test", commitment: "Committed outcome",
};

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
  onGoToLab,
  initialMessages,
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
  // Export and the delta view (brief L6-06).
  const [exporting, setExporting] = useState(false);
  const [showDelta, setShowDelta] = useState(false);
  const [delta, setDelta] = useState<ReportDelta | null>(null);
  const [deltaError, setDeltaError] = useState<string | null>(null);
  async function handleExport() {
    setExporting(true);
    try {
      const blob = await api.report.exportZip(sessionId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `population-${sessionId.slice(0, 8)}.zip`; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch (e: any) {
      alert(e?.message || "Export failed");
    } finally {
      setExporting(false);
    }
  }
  async function loadDelta(a?: string, b?: string) {
    setDeltaError(null);
    try { setDelta(await api.report.delta(sessionId, a, b)); }
    catch (e: any) { setDelta(null); setDeltaError(/404|at least twice/.test(e?.message || "") ? "Generate the report again after new research, then compare the two runs here." : e?.message || "Could not compare"); }
  }
  useEffect(() => { setDelta(null); }, [reportContent]);
  useEffect(() => {
    if (recordsProp && recordsProp.length) return;
    api.records.list(sessionId).then((r) => setLoadedRecords(r.records || [])).catch(() => {});
  }, [sessionId, reportContent, recordsProp]);
  const records = recordsProp && recordsProp.length ? recordsProp : loadedRecords;
  RECORDS_BY_ID = Object.fromEntries(records.map((r) => [r.id, r]));
  // L6-03: the source-figure ledger a `[[fact:…]]` / `[[evidence:…]]` citation resolves to.
  const [ledger, setLedger] = useState<{ facts: SourceFact[]; items: SourceItem[] }>({ facts: [], items: [] });
  useEffect(() => {
    api.figures.list(sessionId).then((l) => setLedger({ facts: l.facts || [], items: l.items || [] })).catch(() => {});
  }, [sessionId, reportContent]);
  FACTS_BY_ID = Object.fromEntries(ledger.facts.map((f) => [f.id, f]));
  ITEMS_BY_ID = Object.fromEntries(ledger.items.map((i) => [i.id, i]));
  // A source chip that was clicked: the statistic or document behind a quoted figure.
  const [openSource, setOpenSource] = useState<{ fact?: SourceFact; item?: SourceItem; x: number; y: number } | null>(null);
  const [reportMessages, setReportMessages] = useState<Message[]>(initialMessages || []);
  const [agentMessages, setAgentMessages] = useState<Message[]>([]);
  // The history arrives after the first render; seed the chat once, never over a conversation in progress.
  useEffect(() => { if (initialMessages?.length) setReportMessages((prev) => (prev.length ? prev : initialMessages)); }, [initialMessages]);
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
    const src = (e.target as HTMLElement).closest?.("[data-fact],[data-evidence]") as HTMLElement | null;
    if (src) {
      const fact = src.dataset.fact ? FACTS_BY_ID[src.dataset.fact] : undefined;
      const item = src.dataset.evidence ? ITEMS_BY_ID[src.dataset.evidence] : undefined;
      if (fact || item) {
        e.preventDefault();
        const rect = src.getBoundingClientRect();
        setOpenSource({ fact, item, x: rect.left, y: rect.bottom + 6 });
      }
      return;
    }
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
                  <a
                    href={`/session/${sessionId}/report/client`} target="_blank" rel="noreferrer"
                    title="The client-facing document: the report, the records, the equity split, what's in the way, the caveats — with the synthetic-population statement at the top and bottom. Print-ready."
                    className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded border border-border/60 text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors"
                  >
                    <FileText className="w-3 h-3" />
                    Client report
                  </a>
                  <button
                    onClick={handleExport} disabled={exporting}
                    title="Download every outcome record (JSON + CSV), the report with its structure, the source ledger, the roster and the run record as one zip. Every file carries the synthetic-population statement."
                    className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded border border-border/60 text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors disabled:opacity-50"
                  >
                    <Download className="w-3 h-3" />
                    {exporting ? "Exporting…" : "Export data"}
                  </button>
                  <button
                    onClick={() => { setShowDelta((v) => !v); if (!delta && !deltaError) loadDelta(); }}
                    title="What changed since the previous run of this report: the headline, the positions, the equity gap, the barriers, the dissent, the evidence base."
                    className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded border transition-colors ${showDelta ? "border-primary/50 text-primary" : "border-border/60 text-muted-foreground hover:text-foreground hover:border-primary/40"}`}
                  >
                    <GitCompare className="w-3 h-3" />
                    Compare runs
                  </button>
                  <button
                    onClick={handleSaveAsPDF}
                    className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded border border-border/60 text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors"
                  >
                    <Printer className="w-3 h-3" />
                    Print
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
                <span className="text-sm">Writing the report from the twins&apos; answers and the source material…</span>
              </div>
            ) : (
              <>
                {showDelta && (
                  <div className="max-w-2xl mb-4 no-print" onClick={handleCiteClick}>
                    <DeltaPanel delta={delta} error={deltaError} agentsById={agentsById} onPick={(a, b) => loadDelta(a, b)} />
                  </div>
                )}
                <div id="report-printable" className="max-w-2xl" onClick={handleCiteClick}>
                  <ReportDocument content={reportContent!} agentsById={agentsById} records={records} structure={structure} onGoToLab={onGoToLab} />
                </div>
              </>
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
            followUps={structure?.follow_ups}
            compact
          />
        </div>

        {openRecord && <RecordCard record={openRecord.record} x={openRecord.x} y={openRecord.y} onClose={() => setOpenRecord(null)} />}
        {openSource && <SourceCard fact={openSource.fact} item={openSource.item} x={openSource.x} y={openSource.y} onClose={() => setOpenSource(null)} />}
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
            A structured briefing from the twins, the debate and the source material — with every figure counted, never typed
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
        {openSource && <SourceCard fact={openSource.fact} item={openSource.item} x={openSource.x} y={openSource.y} onClose={() => setOpenSource(null)} />}
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
          <PersonaAvatar agent={agent} size={28} shape="rounded" />
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
  /** Questions written from the report's records; the generic starters are the fallback. */
  followUps?: string[] | null;
}

function ChatPanel({
  mode, setMode, agents, selectedAgent, setSelectedAgent,
  dropdownOpen, setDropdownOpen, dropdownRef,
  messages, loading, input, setInput, send,
  bottomRef, currentAgentColor, compact = false,
  agentsById, onCiteClick, followUps,
}: ChatPanelProps) {
  const suggestions = followUps && followUps.length ? followUps : STARTER_QUESTIONS;
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
            Talk to a twin
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
                <span className="text-muted-foreground text-xs">Pick a twin…</span>
              )}
              <ChevronDown className="w-3 h-3 text-muted-foreground" />
            </button>

            {dropdownOpen && (
              <div className="absolute top-full left-0 mt-1 w-72 bg-background border border-border rounded-xl shadow-xl z-50 overflow-hidden">
                <div className="max-h-60 overflow-y-auto divide-y divide-border">
                  {agents.length === 0 ? (
                    <p className="text-xs text-muted-foreground px-4 py-3">No twins built yet</p>
                  ) : (
                    agents.map((a) => (
                      <button
                        key={a.id}
                        onClick={() => { setSelectedAgent(a); setDropdownOpen(false); }}
                        className={`w-full flex items-start gap-3 px-4 py-2.5 text-left hover:bg-muted transition-colors ${selectedAgent?.id === a.id ? "bg-primary/5" : ""}`}
                      >
                        <PersonaAvatar agent={a} size={28} shape="rounded" />
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
              <p className="text-sm text-muted-foreground mb-6">Ask anything about the twins, the debate or the source material.</p>
              <div className="flex flex-col gap-2">
                {suggestions.map((q) => (
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
            <div className="pt-1">
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground/55 font-semibold mb-2">
                {mode === "report" ? (followUps?.length ? "Questions this report raises" : "Ask about the report") : "Ask this twin"}
              </p>
              {mode === "report" && (
                <div className="flex flex-col gap-1.5">
                  {suggestions.map((q) => (
                    <button key={q} onClick={() => send(q)}
                      className="text-[11px] text-left rounded-lg px-3 py-2 border border-border/50 hover:border-primary/30 transition-all text-muted-foreground hover:text-foreground leading-snug">
                      {q}
                    </button>
                  ))}
                </div>
              )}
              {mode === "agent" && <p className="text-xs text-muted-foreground/60">Pick a twin above and ask them directly. They answer in character, from what they could see.</p>}
            </div>
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
                ? "Ask about the report…"
                : selectedAgent ? `Ask ${selectedAgent.name.split(" ")[0]}…` : "Pick a twin first…"
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
// L6-03: a figure read from the material cites the typed statistic or the document it came from;
// a number with nothing behind it arrives wrapped as unsourced and is shown as the model's own.
const FACT_RE = /\[\[fact:([A-Za-z0-9-]{1,64}#\d+)\]\]/g;
const EVID_RE = /\[\[evidence:([A-Za-z0-9-]{1,64})\]\]/g;
const UNSOURCED_RE = /\[\[unsourced:([^\]]+)\]\]/g;
let FACTS_BY_ID: Record<string, SourceFact> = {};
let ITEMS_BY_ID: Record<string, SourceItem> = {};

export const CLASS_LABEL: Record<ProvenanceClass, string> = {
  official_statistic: "Official statistic", peer_reviewed: "Peer-reviewed", grey_literature: "Grey literature",
  commissioned_research: "Commissioned research", client_data: "Client data", social_signal: "Social signal", model_inference: "Model-inferred",
};
/** One colour per provenance class, so a reader tells an official statistic from a paper from a social claim from a counted twin figure at a glance. */
export const CLASS_STYLE: Record<ProvenanceClass | "unsourced", string> = {
  official_statistic: "border-sky-500/40 text-sky-300 bg-sky-500/10 hover:bg-sky-500/20",
  peer_reviewed: "border-violet-500/40 text-violet-300 bg-violet-500/10 hover:bg-violet-500/20",
  grey_literature: "border-slate-400/40 text-slate-300 bg-slate-500/10 hover:bg-slate-500/20",
  commissioned_research: "border-indigo-500/40 text-indigo-300 bg-indigo-500/10 hover:bg-indigo-500/20",
  client_data: "border-pink-500/40 text-pink-300 bg-pink-500/10 hover:bg-pink-500/20",
  social_signal: "border-orange-500/40 text-orange-300 bg-orange-500/10 hover:bg-orange-500/20",
  model_inference: "border-teal-500/40 text-teal-300 bg-teal-500/10 hover:bg-teal-500/20",
  unsourced: "border-dashed border-zinc-500/60 text-zinc-400 bg-zinc-500/10 line-through decoration-zinc-500/60",
};
const CLASS_DOT: Record<ProvenanceClass | "unsourced", string> = {
  official_statistic: "bg-sky-400", peer_reviewed: "bg-violet-400", grey_literature: "bg-slate-400", commissioned_research: "bg-indigo-400",
  client_data: "bg-pink-400", social_signal: "bg-orange-400", model_inference: "bg-teal-400", unsourced: "bg-zinc-500",
};
const CHIP = "inline-flex items-center gap-1 align-baseline text-[11px] font-semibold px-1.5 py-px rounded border";

function esc(t: string): string {
  return t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function renderSourceCitations(html: string): string {
  html = html.replace(FACT_RE, (_m, id: string) => {
    const f = FACTS_BY_ID[id];
    if (!f) return "";
    const where = [f.source || f.title, f.year].filter(Boolean).join(" ");
    return (
      `<button type="button" data-fact="${id}" title="${esc(`${f.statistic}${f.group ? ` — ${f.group}` : ""}${f.geography ? `, ${f.geography}` : ""} · ${CLASS_LABEL[f.provenance_class]} · trust ${f.trust_tier}`)}" ` +
      `class="source-cite ${CHIP} ${CLASS_STYLE[f.provenance_class] || CLASS_STYLE.grey_literature}">` +
      `${esc(f.value)}<span class="font-normal opacity-70">· ${esc(CLASS_LABEL[f.provenance_class])}${where ? ` · ${esc(where.length > 26 ? where.slice(0, 24) + "…" : where)}` : ""}</span></button>`
    );
  });
  html = html.replace(EVID_RE, (_m, id: string) => {
    const it = ITEMS_BY_ID[id];
    if (!it) return "";
    return (
      `<button type="button" data-evidence="${id}" title="${esc(`${it.title} — ${it.author || ""} · trust ${it.trust_tier}`)}" ` +
      `class="source-cite ${CHIP} ${CLASS_STYLE[it.provenance_class] || CLASS_STYLE.grey_literature}">` +
      `${esc(CLASS_LABEL[it.provenance_class])}<span class="font-normal opacity-70">· ${esc(it.title.length > 30 ? it.title.slice(0, 28) + "…" : it.title)}</span></button>`
    );
  });
  html = html.replace(UNSOURCED_RE, (_m, tok: string) =>
    `<span title="Typed by the model — no record, statistic or document behind it" class="${CHIP} ${CLASS_STYLE.unsourced}">${esc(tok)}<span class="font-normal no-underline opacity-70">· unsourced</span></span>`);
  return html;
}

function fmtEstimate(r: OutcomeRecord): string {
  const e = r.estimate;
  if (e.value == null) return "not counted";
  if (e.format === "share") return `${Math.round(e.value * 100)}%`;
  if (e.format === "lift") return `${e.value > 0 ? "+" : ""}${Math.round(e.value * 100)} pts`;
  if (typeof e.value === "number") return Number.isInteger(e.value) ? String(e.value) : e.value.toFixed(2);
  return String(e.value);
}
/** A shift record that moved nobody reads "no shift" in a chip, never "0 pts". */
function chipFigure(r: OutcomeRecord): string {
  const e = r.estimate;
  if (e.format === "lift" && !e.significant && e.value != null && Math.round(e.value * 100) === 0) return "no shift";
  return fmtEstimate(r);
}
function fmtInterval(r: OutcomeRecord): string {
  const e = r.estimate;
  if (e.low == null || e.high == null) return "";
  if (e.format === "share") return `95% CI ${Math.round(e.low * 100)}–${Math.round(e.high * 100)}%`;
  if (e.format === "lift") return `95% CI ${Math.round(e.low * 100)} to ${Math.round(e.high * 100)} pts`;
  return `${e.low}–${e.high}`;
}
/** The interval in words, for tiles: "could be 3–20%" rather than "95% CI 3–20%". */
function fmtIntervalText(r: OutcomeRecord): string {
  const e = r.estimate;
  if (e.low == null || e.high == null) return "interval not counted";
  if (e.format === "share") return `could be ${Math.round(e.low * 100)}–${Math.round(e.high * 100)}%`;
  if (e.format === "lift") return `could be ${Math.round(e.low * 100)} to ${Math.round(e.high * 100)} pts`;
  return `${e.low}–${e.high}`;
}
/** The interval as a hoverable term. */
function Interval({ r }: { r: OutcomeRecord }) {
  const t = fmtInterval(r);
  if (!t) return <span className="text-[10px] text-muted-foreground/60">interval not counted</span>;
  return <Term k="ci" className="text-[10px] text-muted-foreground/70">{t}</Term>;
}

function renderRecordCitations(html: string): string {
  return html.replace(RECORD_RE, (_m, id: string) => {
    const r = RECORDS_BY_ID[id];
    if (!r) return "";
    return (
      `<button type="button" data-record="${id}" title="${esc(`${r.label} — ${fmtInterval(r) || "interval not counted"} · ${r.estimate.n} twins answered · confidence ${r.confidence.score ?? "not computed"}/100 · counted from the synthetic twins, never typed`)}" ` +
      `class="record-cite inline-flex items-center gap-1 align-baseline text-[11px] font-semibold px-1.5 py-px rounded border border-teal-500/40 text-teal-300 bg-teal-500/10 hover:bg-teal-500/20">` +
      `${esc(chipFigure(r))}<span class="font-normal text-teal-300/70">· ${esc(r.label.length > 34 ? r.label.slice(0, 32) + "…" : r.label)}</span></button>`
    );
  });
}

/** "34% [[fact:…]]" and "75% [[record:…]]": the chip carries the figure, so the same figure typed
 *  just before it is dropped rather than shown twice. Only an exact match goes; anything else stays. */
function dedupeFigures(html: string): string {
  const norm = (t: string) => t.replace(/[\s,]/g, "").replace(/\.0+(?=%|$)/, "").toLowerCase();
  return html.replace(/([^\s>]+)\s+(\[\[(record|fact):([^\]]+)\]\])/g, (m, before: string, tok: string, kind: string, id: string) => {
    const v = kind === "record" ? (RECORDS_BY_ID[id] ? fmtEstimate(RECORDS_BY_ID[id]) : "") : (FACTS_BY_ID[id]?.value || "");
    return v && norm(before) === norm(v) ? tok : m;
  });
}

/** A twin's initials, for the compact marker a repeat citation renders as. */
function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("") || "·";
}

/**
 * Twin citations in one block of text. The first citation of a twin renders as the full name;
 * every later one in the same block is a small marker — "¶" when it points at a statement,
 * the twin's initials otherwise — so "his [[A7#P12]] claim" reads as prose with a clickable
 * pointer rather than the name a third time. Both open the same card.
 */
function renderCitations(html: string, agentsById: Record<string, Agent>): string {
  html = dedupeFigures(html);
  html = renderRecordCitations(html);
  html = renderSourceCitations(html);
  // Reports stored before collapse_repeats existed can carry "name + handle" as two adjacent
  // tokens of one twin; fold them here too so an old report reads the same as a new one.
  html = html.replace(/(\[\[twin:([0-9a-fA-F-]{36})(?:\|post:[0-9a-fA-F-]{36})?\]\])[ \t]*\[\[twin:\2(\|post:[0-9a-fA-F-]{36})?\]\]/g,
    (_m, first: string, id: string, post2?: string) => (first.includes("|post:") || !post2 ? first : `[[twin:${id}${post2}]]`));
  const seen = new Set<string>();
  return html.replace(CITE_RE, (_m, twinId: string, postId?: string) => {
    const agent = agentsById[twinId];
    if (!agent) return "a twin in the population";
    const post = postId ? ` data-post="${postId}"` : "";
    if (seen.has(twinId)) {
      return (
        `<button type="button" data-twin="${twinId}"${post} title="${agent.name} — ${postId ? "this statement" : agent.role}" ` +
        `class="twin-cite twin-cite-again inline-flex items-center align-baseline h-[15px] px-1 rounded text-[9.5px] font-semibold leading-none tracking-wide text-primary/90 bg-primary/10 hover:bg-primary/20">` +
        `${postId ? "¶" : initials(agent.name)}</button>`
      );
    }
    seen.add(twinId);
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

function ReportDocument({ content, agentsById, records = [], structure = null, onGoToLab }: { content: string; agentsById: Record<string, Agent>; records?: OutcomeRecord[]; structure?: ReportStructure | null; onGoToLab?: () => void }) {
  const blocks = parseReport(content);
  const firstAnswer = blocks.findIndex((b) => b.type === "direct_answer");
  // The confidence beside the direct answer is the headline record's computed band (L6-02);
  // the model's own label is only a fallback for reports written before the structure existed.
  const computed = structure?.direct_answer?.confidence;
  const hasOutcome = blocks.some((b) => b.type === "h2" && /^outcome/i.test(b.text));
  const isError = blocks.some((b) => b.type === "h2" && /^report (unavailable|generation failed)/i.test(b.text));

  // Reading order: the answer, how sure we are and what it rests on, one tile per question the
  // tools answered, then the prose, then the computed blocks, and every record last, folded.
  return (
    <div className="space-y-4 text-sm">
      {blocks.map((block, i) => {
        if (block.type === "direct_answer") {
          const band = computed?.band || block.confidence;
          return (
            <div key={i}>
            <div className="border-l-4 border-primary bg-primary/5 rounded-r-lg px-5 py-4 mb-2">
              <div className="flex items-center gap-2 mb-2.5 flex-wrap">
                <span className="text-[10px] uppercase tracking-widest font-bold text-primary">Direct Answer</span>
                {band && (
                  <button type="button" data-record={computed?.band ? structure?.direct_answer?.record_id || undefined : undefined}
                    title={computed?.band ? `${GLOSSARY.confidence} Drivers: ${computed.drivers.join(" · ")}` : "Stated by the model"}
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
                {computed?.band && computed.drivers.length > 0 && (
                  <span className="text-[10px] text-muted-foreground/70 leading-none">
                    because {computed.drivers.slice(0, 4).join(" · ")}{computed.drivers.length > 4 ? " · …" : ""}
                  </span>
                )}
              </div>
              <p className="text-[15px] font-semibold text-foreground leading-snug"
                dangerouslySetInnerHTML={{ __html: renderInline(block.text, agentsById) }} />
            </div>
            {i === firstAnswer && structure?.coverage && <CoverageLine cov={structure.coverage} onGoToLab={onGoToLab} />}
            {i === firstAnswer && records.length > 0 && <SummaryStrip records={records} />}
            {i === firstAnswer && !isError && <FigureKey structure={structure} records={records} />}
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
      {structure?.outcome?.barriers && hasOutcome && <WhatsInTheWay b={structure.outcome.barriers} agentsById={agentsById} />}
      {structure?.outcome?.candidates && hasOutcome && <WhereTheyDropOff c={structure.outcome.candidates} agentsById={agentsById} />}
      {structure?.outcome?.commitments && hasOutcome && <CommittedOutcomes items={structure.outcome.commitments} />}
      {structure && hasOutcome && <ComputedCaveats caveats={structure.outcome.caveats} />}
      {records.length > 0 && !isError && <AllRecords records={records} />}
    </div>
  );
}

// ── What this report rests on ─────────────────────────────────────────────────
// One line under the answer: the tools that produced records, and the tools that were not run
// — each with what it would add and a way to the Lab. A report no longer looks the same
// whatever was done in the session.

function CoverageLine({ cov, onGoToLab }: { cov: NonNullable<ReportStructure["coverage"]>; onGoToLab?: () => void }) {
  const ran = cov.ran || [];
  const notRun = cov.not_run || [];
  if (!ran.length && !notRun.length) return null;
  return (
    <div className="mt-2 mb-1 text-[11px] leading-relaxed text-muted-foreground/85">
      <span className="text-foreground/80 font-medium">Based on</span>{" "}
      {ran.length ? ran.map((x, i) => (
        <span key={x.key}>{i > 0 ? ", " : ""}
          {x.record_ids?.length ? <button type="button" data-record={x.record_ids[0]} className="underline decoration-dotted underline-offset-2 hover:text-foreground">{x.phrase}</button> : x.phrase}
        </span>
      )) : "the session's material only"}.
      {notRun.length > 0 && (
        <>
          {" "}<span className="text-foreground/80 font-medium">Not run:</span>{" "}
          {notRun.map((x, i) => (
            <span key={x.key} className="inline-flex items-center gap-1">
              {i > 0 ? <span className="mr-1">,</span> : null}
              <span title={`${x.adds}${x.needs ? ` — needs ${x.needs}` : ""}`} className="border-b border-dotted border-muted-foreground/40 cursor-help">{x.label}</span>
              {x.needs && <span className="text-muted-foreground/60">(needs {x.needs})</span>}
            </span>
          ))}
          {onGoToLab && (
            <button type="button" onClick={onGoToLab} className="ml-2 inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded border border-border/60 text-muted-foreground hover:text-foreground hover:border-primary/40 no-print">
              <Beaker className="w-2.5 h-2.5" /> open the Lab
            </button>
          )}
          <span className="block text-[10px] text-muted-foreground/60 mt-0.5">The report says where a tool that was not run would have mattered; it never estimates what it would have shown.</span>
        </>
      )}
    </div>
  );
}

// ── One tile per question the tools answered ──────────────────────────────────
// Not one card per run. The latest verdict, the step where most stall, the top barrier, the
// best lever, the best message, the most responsive behaviour and the widest real equity gap —
// each in words a reader can act on, each opening its record.

type Tile = { key: string; title: string; value: string; reading: string; recordId: string; tone?: "flat" | "good" | "warn"; runs?: number };

function tilesFor(records: OutcomeRecord[]): Tile[] {
  const out: Tile[] = [];
  const head = records.find((r) => r.kind === "headline");
  if (head) {
    out.push({ key: "answer", title: "The answer", value: fmtEstimate(head), reading: `${head.estimate.label || "of the population"} · ${fmtIntervalText(head)} · ${head.estimate.n} twins`, recordId: head.id, runs: head.runs?.count });
  }
  const journey = records.find((r) => r.candidates?.length);
  if (journey) {
    const worst = [...(journey.candidates || [])].sort((a, b) => (b.stuck || 0) - (a.stuck || 0))[0];
    const last = journey.funnel?.[journey.funnel.length - 1];
    if (worst) {
      out.push({ key: "dropoff", title: "Where most drop off", value: `${worst.stuck} of ${worst.n}`, tone: "warn",
        reading: `stall at "${worst.from?.label} → ${worst.to?.label}"${worst.stuck_people != null ? ` · ≈${worst.stuck_people.toLocaleString()} people` : ""}${last ? ` · ${Math.round((last.share || 0) * 100)}% reach "${last.label}"` : ""}`, recordId: journey.id, runs: journey.runs?.count });
    }
  }
  const bars = records.find((r) => r.barriers?.length);
  if (bars) {
    const top = bars.barriers![0];
    out.push({ key: "barrier", title: "Biggest barrier", value: top.theme, reading: `${top.count} twin${top.count === 1 ? "" : "s"} raised it${bars.barriers!.length > 1 ? ` · ${bars.barriers!.length} barriers ranked` : ""}${top.removals?.length ? ` · removed by ${(typeof top.removals[0] === "string" ? top.removals[0] : (top.removals[0] as { value: string }).value)}` : ""}`, recordId: bars.id, runs: bars.runs?.count });
  }
  const pick = (kind: string) => {
    const rs = records.filter((r) => r.kind === kind);
    if (!rs.length) return null;
    const sig = rs.filter((r) => r.estimate.significant && r.estimate.value != null);
    return sig.length ? sig.sort((a, b) => (b.estimate.value || 0) - (a.estimate.value || 0))[0] : rs[0];
  };
  const lever = pick("lever");
  if (lever) {
    const sig = lever.estimate.significant && lever.estimate.value != null;
    out.push({ key: "lever", title: "Best lever", value: sig ? fmtEstimate(lever) : "No shift", tone: sig ? "good" : "flat",
      reading: lever.summary || lever.label.replace(/^(Lever|Assumed effect): /, ""), recordId: lever.id, runs: records.filter((r) => r.kind === "lever").length });
  }
  const msg = pick("messaging");
  if (msg) {
    const sig = msg.estimate.significant && msg.estimate.value != null;
    out.push({ key: "message", title: "Best message", value: sig ? fmtEstimate(msg) : "No shift", tone: sig ? "good" : "flat",
      reading: msg.summary || msg.label, recordId: msg.id, runs: records.filter((r) => r.kind === "messaging").length });
  }
  const tgt = pick("targeting");
  if (tgt) {
    const sig = tgt.estimate.significant && tgt.estimate.value != null;
    out.push({ key: "behaviour", title: "Most responsive behaviour", value: sig ? `${fmtEstimate(tgt)}/pt` : "No shift", tone: sig ? "good" : "flat",
      reading: tgt.summary || tgt.label, recordId: tgt.id, runs: records.filter((r) => r.kind === "targeting").length });
  }
  const gaps = records.filter((r) => r.equity && r.equity.available && r.equity.significant && r.equity.gap != null);
  if (gaps.length) {
    const g = gaps.sort((a, b) => Math.abs((b.equity as { gap: number }).gap) - Math.abs((a.equity as { gap: number }).gap))[0];
    const eq = g.equity as Extract<EquityBlock, { available: true }>;
    out.push({ key: "equity", title: "Widest equity gap", value: `${eq.gap! > 0 ? "+" : ""}${eq.gap} pts`, tone: "warn",
      reading: `${eq.most.label.split(" ")[0]} ${fmtCell(eq.most)} vs ${eq.least.label.split(" ")[0]} ${fmtCell(eq.least)} on "${g.label}" · a real gap`, recordId: g.id });
  }
  const commits = records.filter((r) => r.kind === "commitment" && (r as OutcomeRecord & { commitment?: { status?: string } }).commitment?.status !== "superseded");
  if (commits.length) {
    const c = commits[0];
    out.push({ key: "commit", title: "Committed forecast", value: fmtEstimate(c), reading: c.label.replace(/^Committed: /, "") + " · frozen", recordId: c.id });
  }
  return out;
}

function SummaryStrip({ records }: { records: OutcomeRecord[] }) {
  const tiles = tilesFor(records);
  if (!tiles.length) return null;
  const toneCls = (t?: Tile["tone"]) => t === "good" ? "text-emerald-300" : t === "warn" ? "text-amber-300" : t === "flat" ? "text-muted-foreground/80" : "text-teal-300";
  return (
    <div className="mt-3">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[10px] uppercase tracking-widest text-teal-300 font-bold flex items-center gap-1"><Hash className="w-3 h-3" /> At a glance</span>
        <span className="text-[10px] text-muted-foreground/60">one tile per question the tools answered · counted from the twins · click for the record</span>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-2">
        {tiles.map((t) => (
          <button key={t.key} type="button" data-record={t.recordId} className="text-left border border-teal-500/25 rounded-lg px-3.5 py-3 bg-teal-500/5 hover:bg-teal-500/10 transition-colors">
            <div className="flex items-center gap-1.5 mb-1">
              <span className="text-[9px] uppercase tracking-wide text-teal-300/80 font-semibold">{t.title}</span>
              {t.runs && t.runs > 1 ? <Term k="runs" className="text-[9px] text-muted-foreground/60">{t.runs} runs</Term> : null}
            </div>
            <div className={`text-lg font-bold leading-tight ${toneCls(t.tone)} ${t.value.length > 14 ? "text-[13px] leading-snug" : ""}`}>{t.value}</div>
            <div className="text-[10.5px] text-muted-foreground/80 leading-snug mt-1">{t.reading}</div>
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Every record, folded ──────────────────────────────────────────────────────

function AllRecords({ records }: { records: OutcomeRecord[] }) {
  const [open, setOpen] = useState(false);
  const folded = records.reduce((n, r) => n + Math.max(0, (r.runs?.count || 1) - 1), 0);
  return (
    <div className="mt-5 border-t border-border/40 pt-3">
      <button type="button" onClick={() => setOpen((v) => !v)} className="flex items-center gap-2 text-left w-full group">
        {open ? <ChevronDown className="w-3.5 h-3.5 text-muted-foreground/60" /> : <ChevronRight className="w-3.5 h-3.5 text-muted-foreground/60" />}
        <span className="text-[10px] uppercase tracking-widest text-teal-300 font-bold flex items-center gap-1"><Hash className="w-3 h-3" /> All outcome records</span>
        <span className="text-[10px] text-muted-foreground/60 group-hover:text-muted-foreground">{records.length} counted from the twins&apos; answers · every figure in this report cites one{folded ? ` · ${folded} earlier run${folded === 1 ? "" : "s"} folded` : ""}</span>
      </button>
      {open && (
        <>
          <RecordGrid records={records} />
          <EquityStrip records={records} />
        </>
      )}
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
          <Term k="match" className="font-semibold text-foreground/75">Population match:</Term> {fr.summary}
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
        {d.record_id && <button type="button" data-record={d.record_id} title={GLOSSARY.verdict} className="text-[9px] text-teal-300/80 underline decoration-dotted underline-offset-2">verdict record</button>}
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

// ── The delta view (brief L6-06) ──────────────────────────────────────────────
// What changed between two runs of the same question, as plain then → now lines: the headline
// and whether its change is real, the positions, the equity gap, the barriers that appeared,
// dropped or moved, the dissenters who joined or left, the evidence base, the computed confidence.

function pctOr(v: number | null | undefined): string { return typeof v === "number" ? `${Math.round(v * 100)}%` : "—"; }

function DeltaPanel({ delta, error, agentsById, onPick }: { delta: ReportDelta | null; error: string | null; agentsById: Record<string, Agent>; onPick: (a?: string, b?: string) => void }) {
  if (error) return <div className="rounded-lg border border-border/50 bg-muted/10 px-3.5 py-3 text-[11px] text-muted-foreground">{error}</div>;
  if (!delta) return <div className="rounded-lg border border-border/50 bg-muted/10 px-3.5 py-3 text-[11px] text-muted-foreground">Comparing runs…</div>;
  const when = (t: string | null) => (t ? new Date(t).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "");
  const h = delta.headline;
  const Row = ({ label, then, now, note }: { label: string; then: string; now: string; note?: string }) => (
    <div className="flex items-baseline gap-2 text-[11px]">
      <span className="w-40 shrink-0 text-muted-foreground">{label}</span>
      <span className="text-foreground/70 tabular-nums">{then}</span>
      <span className="text-muted-foreground/50">→</span>
      <span className="text-foreground/95 tabular-nums font-medium">{now}</span>
      {note && <span className="text-muted-foreground/70">· {note}</span>}
    </div>
  );
  return (
    <div className="rounded-lg border border-border/50 bg-muted/10 px-3.5 py-3 space-y-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[10px] uppercase tracking-widest font-bold text-muted-foreground/80">What changed</span>
        <span className="text-[10px] text-muted-foreground/70">{when(delta.a.created_at)} → {when(delta.b.created_at)}</span>
        {delta.available.length > 2 && (
          <span className="ml-auto text-[10px] text-muted-foreground/70">compare with:{" "}
            {delta.available.filter((r) => r.id !== delta.b.report_id).map((r) => (
              <button key={r.id} type="button" onClick={() => onPick(r.id, delta.b.report_id)} className={`ml-1 underline decoration-dotted ${r.id === delta.a.report_id ? "text-primary" : ""}`}>{when(r.created_at)}</button>
            ))}
          </span>
        )}
      </div>
      <p className="text-[11px] text-foreground/85 leading-snug">{delta.summary}</p>
      <div className="space-y-1">
        {h ? <Row label={h.label || "Headline"} then={pctOr(h.then?.value)} now={pctOr(h.now?.value)} note={h.real === true ? "a real change — the intervals do not overlap" : h.real === false ? "not distinguishable — the intervals overlap" : undefined} />
           : <Row label="Headline" then="not polled" now="not polled" note="no verdict record on one or both runs" />}
        {delta.positions.map((p) => <Row key={p.value} label={`position · ${p.value}`} then={pctOr(p.then)} now={pctOr(p.now)} note={p.change_points != null ? `${p.change_points > 0 ? "+" : ""}${p.change_points} pts` : undefined} />)}
        <Row label="equity gap (most vs least deprived)" then={delta.equity.then ? `${delta.equity.then.gap ?? "not computed"} pts${delta.equity.then.significant ? " (real)" : ""}` : "not cut"} now={delta.equity.now ? `${delta.equity.now.gap ?? "not computed"} pts${delta.equity.now.significant ? " (real)" : ""}` : "not cut"} />
        <Row label="computed confidence" then={delta.confidence.then.band ? `${delta.confidence.then.band} ${delta.confidence.then.score}` : "not computed"} now={delta.confidence.now.band ? `${delta.confidence.now.band} ${delta.confidence.now.score}` : "not computed"} />
        <Row label="evidence items" then={String(delta.evidence_total.then)} now={String(delta.evidence_total.now)} note={delta.evidence.filter((e) => e.change).map((e) => `${e.class} ${e.change > 0 ? "+" : ""}${e.change}`).join(", ") || undefined} />
        <Row label="twins answering" then={delta.a.n == null ? "not polled" : String(delta.a.n)} now={delta.b.n == null ? "not polled" : String(delta.b.n)} />
        <Row label="figures typed with no source" then={delta.unsourced.then == null ? "not checked" : String(delta.unsourced.then)} now={delta.unsourced.now == null ? "not checked" : String(delta.unsourced.now)} />
        {delta.coverage && (delta.coverage.added.length > 0 || delta.coverage.dropped.length > 0) && (
          <Row label="tools run" then={delta.coverage.dropped.length ? `had ${delta.coverage.dropped.join(", ")}` : "—"} now={delta.coverage.added.length ? `+ ${delta.coverage.added.join(", ")}` : "—"} />
        )}
      </div>
      {delta.barriers && (delta.barriers.appeared.length + delta.barriers.dropped.length + delta.barriers.moved.length > 0) && (
        <div className="text-[11px] space-y-0.5">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground/60">Barriers</div>
          {delta.barriers.appeared.map((b) => <div key={`a${b.theme}`}>· <span className="text-foreground/90">{b.theme}</span> appeared at #{b.rank} ({b.count} twins)</div>)}
          {delta.barriers.dropped.map((b) => <div key={`d${b.theme}`}>· <span className="text-foreground/90">{b.theme}</span> gone (was #{b.rank}, {b.count} twins)</div>)}
          {delta.barriers.moved.map((b) => <div key={`m${b.theme}`}>· <span className="text-foreground/90">{b.theme}</span> #{b.then} → #{b.now} ({b.count_then} → {b.count_now} twins)</div>)}
        </div>
      )}
      {(delta.dissent.joined.length > 0 || delta.dissent.left.length > 0) && (
        <div className="text-[11px] space-y-0.5">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground/60">Named dissent{delta.dissent.majority_then !== delta.dissent.majority_now ? ` · majority ${delta.dissent.majority_then} → ${delta.dissent.majority_now}` : ""}</div>
          {delta.dissent.joined.length > 0 && <div>· joined: {delta.dissent.joined.map((d, i) => <span key={d.agent_id}>{i > 0 ? ", " : ""}<button type="button" data-twin={d.agent_id} className="twin-cite text-primary underline decoration-dotted underline-offset-2">{agentsById[d.agent_id]?.name || "a twin"}</button></span>)}</div>}
          {delta.dissent.left.length > 0 && <div>· left: {delta.dissent.left.map((d, i) => <span key={d.agent_id}>{i > 0 ? ", " : ""}<button type="button" data-twin={d.agent_id} className="twin-cite text-primary underline decoration-dotted underline-offset-2">{agentsById[d.agent_id]?.name || "a twin"}</button></span>)}</div>}
        </div>
      )}
    </div>
  );
}

// ── Provenance (brief L6-03) ──────────────────────────────────────────────────
// Every figure in the document carries its class in its colour: a counted twin figure is teal
// (model-inferred), an official statistic sky, a paper violet, grey literature slate, a social
// claim orange, client data pink — and a number the model typed with no source is struck through.

/** Only the figure classes this report actually uses; a legend for seven colours when the page
 *  shows two is noise. Reads "what the colour of a figure means", not a taxonomy. */
function FigureKey({ structure, records }: { structure?: ReportStructure | null; records: OutcomeRecord[] }) {
  const n = structure?.figures?.unsourced?.length || 0;
  const present = new Set<ProvenanceClass | "unsourced">();
  if ((structure?.records?.cited?.length || 0) > 0 || records.length) present.add("model_inference");
  for (const id of structure?.figures?.facts_cited || []) { const f = FACTS_BY_ID[id]; if (f) present.add(f.provenance_class); }
  for (const id of structure?.figures?.items_cited || []) { const it = ITEMS_BY_ID[id]; if (it) present.add(it.provenance_class); }
  if (n) present.add("unsourced");
  const order: (ProvenanceClass | "unsourced")[] = ["model_inference", "official_statistic", "peer_reviewed", "grey_literature", "commissioned_research", "social_signal", "client_data", "unsourced"];
  const entries = order.filter((k) => present.has(k));
  if (entries.length <= 1 && !n) return null;
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-muted-foreground/70 border-b border-border/30 pb-2">
      <span className="uppercase tracking-wide text-[9px] font-semibold text-muted-foreground/60">Figures in this report</span>
      {entries.map((k) => (
        <span key={k} className="inline-flex items-center gap-1">
          <span className={`w-1.5 h-1.5 rounded-full ${CLASS_DOT[k]}`} />
          {k === "model_inference" ? "counted from the twins" : k === "unsourced" ? `typed by the model with no source (${n}) — struck through` : `read from ${CLASS_LABEL[k].toLowerCase()}`}
        </span>
      ))}
    </div>
  );
}

function SourceCard({ fact, item, x, y, onClose }: { fact?: SourceFact; item?: SourceItem; x: number; y: number; onClose: () => void }) {
  const left = Math.min(x, (typeof window !== "undefined" ? window.innerWidth : 1200) - 400);
  const top = Math.min(y, (typeof window !== "undefined" ? window.innerHeight : 800) - 360);
  const cls = (fact?.provenance_class || item?.provenance_class || "grey_literature") as ProvenanceClass;
  const trust = fact?.trust_tier || item?.trust_tier || "medium";
  const href = fact?.source_ref || item?.source_ref || "";
  return (
    <>
      <div className="fixed inset-0 z-40 no-print" onClick={onClose} />
      <div className="fixed z-50 w-[380px] max-h-[70vh] overflow-y-auto rounded-xl border border-border/60 bg-background shadow-xl no-print" style={{ left: Math.max(12, left), top: Math.max(12, top) }}>
        <div className="flex items-start gap-2.5 px-4 pt-3.5 pb-3 border-b border-border/50">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <span className={`${CHIP} ${CLASS_STYLE[cls]} text-[10px]`}>{CLASS_LABEL[cls]}</span>
              <span className="text-[10px] text-muted-foreground/70">trust {trust}</span>
            </div>
            <div className="text-sm font-semibold text-foreground leading-tight mt-1.5">{fact ? fact.statistic || fact.title : item?.title}</div>
          </div>
          <button onClick={onClose} className="text-muted-foreground/50 hover:text-foreground shrink-0"><X className="w-3.5 h-3.5" /></button>
        </div>
        <div className="px-4 py-3 space-y-2.5">
          {fact && (
            <>
              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-bold text-foreground leading-none">{fact.value}</span>
                <span className="text-[11px] text-muted-foreground">{[fact.group, fact.geography, fact.year].filter(Boolean).join(" · ")}</span>
              </div>
              {fact.quote && <p className="text-[11px] text-foreground/80 leading-snug italic border-l-2 border-border/60 pl-2">&ldquo;{fact.quote}&rdquo;</p>}
              <div className="text-[10px] text-muted-foreground/80">{fact.source}{fact.title && fact.title !== fact.source ? ` — ${fact.title}` : ""}</div>
            </>
          )}
          {item && !fact && (
            <>
              <div className="text-[10px] text-muted-foreground/80">{[item.author, item.published_at].filter(Boolean).join(" · ")}</div>
              {item.excerpt && <p className="text-[11px] text-foreground/80 leading-snug">{item.excerpt}</p>}
            </>
          )}
          {href && (
            <a href={href} target="_blank" rel="noreferrer" className="block text-[10px] text-primary underline decoration-dotted underline-offset-2 truncate">{href}</a>
          )}
        </div>
      </div>
    </>
  );
}

/** Barriers (brief L6-05): a plain numbered list from the Barriers record — no colour, the twin
 *  names underlined as every citation is, each barrier's count and what would remove it. */
function WhatsInTheWay({ b, agentsById }: { b: NonNullable<ReportStructure["outcome"]["barriers"]>; agentsById: Record<string, Agent> }) {
  if (!b.items?.length) return null;
  return (
    <div className="mt-4 rounded-lg border border-border/50 bg-muted/10 px-3.5 py-3">
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-[9px] uppercase tracking-wide text-muted-foreground/70 font-semibold">What&apos;s in the way · ranked by the twins</span>
        {b.record_id && <button type="button" data-record={b.record_id} className="text-[9px] text-teal-300/80 underline decoration-dotted underline-offset-2">record</button>}
        {b.n > 0 && <Term k="n" className="text-[10px] text-muted-foreground/60">{b.n} twins</Term>}
      </div>
      {b.outcome && <p className="text-[10px] text-muted-foreground/70 mb-1.5">Outcome: {b.outcome}</p>}
      <ol className="space-y-1">
        {b.items.map((it, k) => {
          const names = it.agent_ids.map((id) => agentsById[id]).filter(Boolean);
          return (
            <li key={it.theme} className="text-[11px] text-foreground/85 leading-snug flex gap-2">
              <span className="text-muted-foreground/60 tabular-nums w-4 shrink-0">{k + 1}.</span>
              <span>
                <span className="font-medium first-letter:uppercase">{it.theme}</span>
                <span className="text-muted-foreground"> · {it.count} twin{it.count === 1 ? "" : "s"}{it.weight_mean != null ? <> · <Term k="weight">weight {Math.round(it.weight_mean)}/100</Term></> : null}</span>
                {it.removals?.length > 0 && <span className="text-muted-foreground"> · removed by {it.removals.map((r) => (typeof r === "string" ? r : r.value)).join(", ")}</span>}
                {names.length > 0 && (
                  <span className="text-muted-foreground"> · {names.slice(0, 4).map((ag, i) => (
                    <span key={ag.id}>{i > 0 ? ", " : ""}<button type="button" data-twin={ag.id} className="twin-cite text-primary underline decoration-dotted underline-offset-2">{ag.name}</button></span>
                  ))}{names.length > 4 ? ` and ${names.length - 4} more` : ""}</span>
                )}
                {it.evidence?.length > 0 && <span className="text-muted-foreground/70"> · evidence: {it.evidence.slice(0, 2).map((e) => e.provenance_class.replace(/_/g, " ")).join(", ")}</span>}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** Journey (brief L7-01): the funnel in one line and a plain numbered list of the candidate
 *  outcomes — the step, how many get through, how many are stuck, the top barriers and who raised
 *  them. The model may only quote candidates from this list, in this order. */
/** Committed outcomes (brief L7-08): the frozen forecasts a client chose to pursue, what each
 *  rested on, and the observed result against it where one has been entered. Read from the
 *  commitment records only — never from the live journey figure. */
function CommittedOutcomes({ items }: { items: NonNullable<ReportStructure["outcome"]["commitments"]> }) {
  if (!items?.length) return null;
  const P = (x: number | null | undefined) => (x == null ? "—" : `${Math.round(x * 100)}%`);
  return (
    <div className="mt-4 rounded-lg border border-amber-400/30 bg-amber-500/5 px-3.5 py-3">
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-[9px] uppercase tracking-wide text-muted-foreground/70 font-semibold" title="A copy of the modelled baseline as it stood when the outcome was chosen; later work in the session does not change it.">Committed outcomes · the frozen forecasts</span>
        <span className="text-[10px] text-muted-foreground/60">{items.length}</span>
      </div>
      <ol className="space-y-1.5">
        {items.map((c, k) => (
          <li key={c.record_id} className="text-[11px] text-foreground/85 leading-snug flex gap-2">
            <span className="text-muted-foreground/60 tabular-nums w-4 shrink-0">{k + 1}.</span>
            <span>
              <span className="font-medium">{c.from} → {c.to}</span>
              {c.status !== "open" && <span className="text-muted-foreground/70"> · {c.status}</span>}
              <span className="text-muted-foreground"> · committed by {c.committed_by || "nobody"} on {(c.committed_at || "").slice(0, 10)}</span>
              <button type="button" data-record={c.record_id} className="ml-1 text-[9px] text-teal-300/80 underline decoration-dotted underline-offset-2">record</button>
              <br />
              <span className="text-muted-foreground">forecast </span><span className="tabular-nums">{P(c.conversion)} get through ({P(c.low)}–{P(c.high)}) · {c.stuck} of {c.n} stuck</span>
              {c.stuck_people != null && <span className="tabular-nums"> · ≈{c.stuck_people.toLocaleString()} people stuck</span>}
              <span className="text-muted-foreground"> · population build {(c.build_id || "unknown").slice(0, 8)} ({c.population_n} twins, frame {c.frame_level || "none"}) · {c.evidence_items} evidence items, {c.rules} rules on file</span>
              {c.target?.value != null && <span className="text-foreground/85 tabular-nums"> · target {P(c.target.value)}{c.target.horizon ? ` by ${c.target.horizon}` : ""}</span>}
              <br />
              {c.comparison ? (
                <span className={c.comparison.inside_interval ? "text-emerald-300/85" : "text-red-300/85"}>
                  observed {P(c.comparison.observed)} on {c.comparison.observed_date} ({c.comparison.observed_source}) · {c.comparison.delta != null ? `${c.comparison.delta > 0 ? "+" : ""}${Math.round(c.comparison.delta * 100)} points against the forecast` : ""} · {c.comparison.inside_interval ? "inside" : "outside"} the modelled interval{"target_met" in c.comparison ? ` · target ${c.comparison.target_met ? "met" : "not met"}` : ""}
                </span>
              ) : <span className="text-muted-foreground/70">no observed result yet</span>}
              {c.status === "closed" && c.close_note && <span className="text-muted-foreground"> · closed: {c.close_note}</span>}
            </span>
          </li>
        ))}
      </ol>
      <p className="mt-1.5 text-[10px] text-muted-foreground/60">An observed result is a figure entered by hand with its source; whether it sits inside the modelled interval is counted, not judged.</p>
    </div>
  );
}

function WhereTheyDropOff({ c, agentsById }: { c: NonNullable<ReportStructure["outcome"]["candidates"]>; agentsById: Record<string, Agent> }) {
  if (!c.items?.length && !c.funnel?.length) return null;
  return (
    <div className="mt-4 rounded-lg border border-border/50 bg-muted/10 px-3.5 py-3">
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-[9px] uppercase tracking-wide text-muted-foreground/70 font-semibold" title="Ranked by the movable gap first: the share of the stuck whose barrier a single partner could reach, from what the twins said would remove it.">Where the population drops off · candidate outcomes · ranked by what a partner could move</span>
        {c.record_id && <button type="button" data-record={c.record_id} className="text-[9px] text-teal-300/80 underline decoration-dotted underline-offset-2">record</button>}
        {c.n > 0 && <Term k="n" className="text-[10px] text-muted-foreground/60">{c.n} twins</Term>}
      </div>
      {c.funnel?.length > 0 && (
        <p className="text-[10px] text-muted-foreground/70 mb-1.5">
          {c.funnel.map((f, i) => <span key={f.label}>{i > 0 ? " → " : ""}{f.label} <span className="text-foreground/80 tabular-nums">{Math.round(f.share * 100)}%</span>{f.people != null ? <span className="tabular-nums"> (≈{f.people.toLocaleString()})</span> : null}</span>)}
        </p>
      )}
      {c.headcount && (
        <p className="text-[10px] mb-1.5" title="Headcounts are a published or client-supplied denominator multiplied by the simulated share; they are no more real than the share.">
          {c.headcount.available
            ? <span className="text-muted-foreground/80">Headcounts: {c.headcount.sentence} <span className={c.headcount.basis === "official_statistic" ? "text-sky-300/80" : "text-pink-300/80"}>· {c.headcount.basis === "official_statistic" ? "official statistic" : "client supplied"}</span></span>
            : <span className="text-yellow-300/70">Headcounts not available — {c.headcount.reason || "no sizing figure on file"}</span>}
        </p>
      )}
      {c.items?.length === 0 && <p className="text-[10px] text-muted-foreground/60">Nobody reported being stuck at any step.</p>}
      <ol className="space-y-1">
        {c.items.map((it) => (
          <li key={it.id} className="text-[11px] text-foreground/85 leading-snug flex gap-2">
            <span className="text-muted-foreground/60 tabular-nums w-4 shrink-0">{it.rank}.</span>
            <span>
              <span className="font-medium">{it.from} → {it.to}</span>
              <span className="text-muted-foreground"> · {typeof it.conversion === "number" ? `${Math.round(it.conversion * 100)}% get through` : "share not counted"}{typeof it.low === "number" && typeof it.high === "number" ? <> (<Term k="ci">{Math.round(it.low * 100)}–{Math.round(it.high * 100)}%</Term>)</> : null} · {it.stuck} of {it.n} stuck</span>
              {it.stuck_people != null && <span className="text-foreground/85 tabular-nums"> · ≈{it.stuck_people.toLocaleString()} people{it.stuck_low != null && it.stuck_high != null && it.stuck_low !== it.stuck_high ? ` (${it.stuck_low.toLocaleString()}–${it.stuck_high.toLocaleString()})` : ""}</span>}
              {it.movability?.scored
                ? <span className="text-muted-foreground"> · <Term k="movable" className="text-emerald-300/85">movable {Math.round((it.movability.movable_share || 0) * 100)}%</Term>{it.movability.movable_people != null ? <span className="tabular-nums"> (≈{it.movability.movable_people.toLocaleString()} people)</span> : null}{(it.movability.system_share || 0) > 0 ? <> · <Term k="system">needs the system {Math.round((it.movability.system_share || 0) * 100)}%</Term></> : null}{(it.movability.structural_share || 0) > 0 ? <> · <Term k="structural">structural {Math.round((it.movability.structural_share || 0) * 100)}%</Term></> : null}{it.movability.levers?.length ? ` · lever: ${it.movability.levers.slice(0, 2).map((l) => l.lever + (l.actor ? ` (${l.actor})` : "")).join("; ")}` : ""}</span>
                : <span className="text-muted-foreground/60"> · <Term k="movable">movability not scored</Term></span>}
              {it.equity_gap != null && <span className="text-muted-foreground"> · <Term k="gap">equity gap {it.equity_gap > 0 ? "+" : ""}{it.equity_gap} pts</Term></span>}
              {it.barriers?.length > 0 && (
                <span className="text-muted-foreground"> · barriers: {it.barriers.map((b, k) => {
                  const names = b.agent_ids.map((id) => agentsById[id]).filter(Boolean);
                  return (
                    <span key={b.theme}>{k > 0 ? "; " : ""}<span className="text-foreground/80 first-letter:uppercase">{b.theme}</span> ({b.count})
                      {names.length > 0 && <> — {names.slice(0, 3).map((ag, i) => (
                        <span key={ag.id}>{i > 0 ? ", " : ""}<button type="button" data-twin={ag.id} className="twin-cite text-primary underline decoration-dotted underline-offset-2">{ag.name}</button></span>
                      ))}{names.length > 3 ? ` +${names.length - 3}` : ""}</>}
                    </span>
                  );
                })}</span>
              )}
            </span>
          </li>
        ))}
      </ol>
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

/** A shift record that moved nobody shows its reading in words, never a bare "0 pts". */
function flatShift(r: OutcomeRecord): boolean {
  return r.estimate.format === "lift" && !r.estimate.significant && !!r.summary;
}

function RecordGrid({ records }: { records: OutcomeRecord[] }) {
  return (
    <div className="mt-3">
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-2">
        {records.map((r) => {
          const flagged = r.unanimity?.flagged;
          const refused = r.refusals?.refused || 0;
          const flat = flatShift(r);
          return (
            <button key={r.id} type="button" data-record={r.id} className="text-left border border-teal-500/25 rounded-lg px-3.5 py-3 bg-teal-500/5 hover:bg-teal-500/10 transition-colors">
              <div className="flex items-center gap-1.5 mb-1">
                <span className="text-[9px] uppercase tracking-wide text-teal-300/80 font-semibold">{KIND_LABEL[r.kind] || r.kind}</span>
                {flagged && <AlertTriangle className="w-3 h-3 text-yellow-400" />}
                {r.runs && r.runs.count > 1 ? <Term k="runs" className="text-[9px] text-muted-foreground/60 ml-auto">latest of {r.runs.count}</Term> : null}
              </div>
              <div className="text-[11px] text-foreground/85 leading-snug line-clamp-2">{r.label}</div>
              {flat ? (
                <div className="mt-1.5 text-[12px] font-semibold text-muted-foreground/85 leading-snug">{r.summary}</div>
              ) : (
                <div className="flex items-baseline gap-2 mt-1.5">
                  <span className={`font-bold leading-none ${r.estimate.value == null ? "text-sm text-muted-foreground/70" : "text-xl text-teal-300"}`}>{fmtEstimate(r)}</span>
                  <Interval r={r} />
                </div>
              )}
              <div className="flex items-center gap-2 mt-1.5 text-[10px] text-muted-foreground/70">
                <Term k="n">{r.estimate.n} twins</Term>
                <Term k="confidence">· confidence {r.confidence.score ?? "—"}/100</Term>
                {refused > 0 && <span>· {refused} refused</span>}
              </div>
              <EquityLine eq={r.equity} compact />
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── Equity by default (brief L6-04) ───────────────────────────────────────────
// Every record is read by deprivation level as well as the headline: the most and least
// deprived cells side by side, the gap, and whether it is real (intervals do not overlap).

function fmtCell(c: EquityCell): string {
  if (typeof c.share === "number") return `${Math.round(c.share * 100)}%`;
  if (typeof c.mean === "number") return `${c.mean}`;
  return "—";
}

function EquityLine({ eq, compact = false }: { eq: EquityBlock | null; compact?: boolean }) {
  // null: this kind of record is never cut by deprivation (a message test, a behaviour ranking).
  if (!eq) return <div className={`text-[10px] text-muted-foreground/45 ${compact ? "mt-1.5" : ""}`}>not cut by deprivation</div>;
  if (!eq.available) return <div className={`text-[10px] text-muted-foreground/55 ${compact ? "mt-1.5" : ""}`} title={eq.reason}>equity · no deprivation levels on this population</div>;
  const tone = eq.significant ? "text-fuchsia-300" : "text-muted-foreground/70";
  return (
    <div className={`flex flex-wrap items-center gap-x-2 text-[10px] ${compact ? "mt-1.5" : ""}`}>
      <Term k="gap" className="text-fuchsia-300/80 font-semibold uppercase tracking-wide text-[9px]">equity</Term>
      <Term k="q1" className="text-foreground/80">{eq.most.label.split(" ")[0]} {fmtCell(eq.most)}</Term>
      <span className="text-muted-foreground/50">vs</span>
      <Term k="q1" className="text-foreground/80">{eq.least.label.split(" ")[0]} {fmtCell(eq.least)}</Term>
      {eq.gap != null
        ? <Term k="gap" className={tone}>{eq.gap > 0 ? "+" : ""}{eq.gap} {eq.gap_unit === "points" ? "pts" : ""}{eq.significant ? " · real gap" : eq.significant === false ? " · not distinguishable" : ""}</Term>
        : <span className="text-muted-foreground/55">gap not computed</span>}
    </div>
  );
}

function EquitySplit({ eq }: { eq: EquityBlock }) {
  if (!eq) return null;
  if (!eq.available) {
    return (
      <div className="rounded-lg border border-fuchsia-500/20 bg-fuchsia-500/5 px-2.5 py-2 text-[10px] text-muted-foreground/85">
        <span className="text-fuchsia-300/80 font-semibold uppercase tracking-wide text-[9px]">Equity</span> · {eq.reason}
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-fuchsia-500/20 bg-fuchsia-500/5 px-2.5 py-2 space-y-1">
      <div className="flex items-center gap-2">
        <span className="text-fuchsia-300/80 font-semibold uppercase tracking-wide text-[9px]">Equity · {eq.label}</span>
        {eq.gap != null && (
          <span className={`text-[10px] ${eq.significant ? "text-fuchsia-300" : "text-muted-foreground/70"}`}>
            gap {eq.gap > 0 ? "+" : ""}{eq.gap} {eq.gap_unit === "points" ? "pts" : ""} · {eq.significant ? "real: the intervals do not overlap" : eq.significant === false ? "not distinguishable at this size" : "untested"}
          </span>
        )}
      </div>
      <div className="space-y-0.5">
        {eq.cells.map((c) => (
          <div key={c.rank} className={`flex items-center gap-2 text-[10px] ${c.thin ? "opacity-60" : ""}`}>
            <span className="w-28 truncate text-foreground/80" title={c.value}>{c.label}</span>
            <div className="flex-1 h-1 bg-muted rounded-full overflow-hidden">
              <div className="h-full bg-fuchsia-400/70 rounded-full" style={{ width: `${typeof c.share === "number" ? Math.round(c.share * 100) : 0}%` }} />
            </div>
            <span className="w-16 text-right tabular-nums text-muted-foreground">{fmtCell(c)} <span className="text-muted-foreground/50">n={c.n}{c.thin ? " thin" : ""}</span></span>
          </div>
        ))}
      </div>
    </div>
  );
}

function EquityStrip({ records }: { records: OutcomeRecord[] }) {
  const withEq = records.filter((r) => r.equity);
  if (!withEq.length) return null;
  const none = withEq.every((r) => !r.equity.available);
  return (
    <div className="mt-3 rounded-lg border border-fuchsia-500/20 bg-fuchsia-500/5 px-3.5 py-3">
      <div className="flex items-center gap-2 mb-1.5">
        <Term k="gap" className="text-[10px] uppercase tracking-widest text-fuchsia-300 font-bold">Equity</Term>
        <span className="text-[10px] text-muted-foreground/60">every record by deprivation level, <Term k="q1">most vs least deprived</Term></span>
      </div>
      {none ? (
        <p className="text-[11px] text-muted-foreground/85 leading-snug">{(withEq[0].equity as { reason: string }).reason}</p>
      ) : (
        <div className="space-y-1">
          {withEq.map((r) => (
            <div key={r.id} className="flex items-center gap-2 text-[11px]">
              <button type="button" data-record={r.id} className="truncate max-w-[45%] text-left text-foreground/85 hover:text-foreground underline decoration-dotted underline-offset-2">{r.label}</button>
              <EquityLine eq={r.equity} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function RecordCard({ record: r, x, y, onClose }: { record: OutcomeRecord; x: number; y: number; onClose: () => void }) {
  const left = Math.min(x, (typeof window !== "undefined" ? window.innerWidth : 1200) - 400);
  const top = Math.min(y, (typeof window !== "undefined" ? window.innerHeight : 800) - 460);
  const splitKeys = Object.keys(r.splits || {}).filter((k) => k !== "deprivation" && (r.splits[k] || []).length >= 2).slice(0, 3);
  const mix = Object.entries(r.provenance?.evidence_mix || {}).filter(([, n]) => n > 0);
  return (
    <>
      <div className="fixed inset-0 z-40 no-print" onClick={onClose} />
      <div className="fixed z-50 w-[380px] max-h-[70vh] overflow-y-auto rounded-xl border border-teal-500/30 bg-background shadow-xl no-print" style={{ left: Math.max(12, left), top: Math.max(12, top) }}>
        <div className="flex items-start gap-2.5 px-4 pt-3.5 pb-3 border-b border-border/50">
          <div className="min-w-0 flex-1">
            <div className="text-[9px] uppercase tracking-wide text-teal-300/80 font-semibold">{KIND_LABEL[r.kind] || r.kind} · {r.basis === "simulated" ? "model-inferred · counted from the synthetic twins" : r.basis.replace("_", " ")}</div>
            <div className="text-sm font-semibold text-foreground leading-tight mt-0.5">{r.label}</div>
            {r.question && <div className="text-[11px] text-muted-foreground/70 leading-snug mt-1">{r.question}</div>}
          </div>
          <button onClick={onClose} className="text-muted-foreground/50 hover:text-foreground shrink-0"><X className="w-3.5 h-3.5" /></button>
        </div>
        <div className="px-4 py-3 space-y-3">
          {r.runs && r.runs.count > 1 ? <p className="text-[10px] text-muted-foreground/70"><Term k="runs">Latest of {r.runs.count} runs of this tool at this step</Term>; the earlier runs are on file and open from Compare runs.</p> : null}
          {flatShift(r) ? (
            <div>
              <div className="text-base font-semibold text-foreground/90 leading-snug">{r.summary}</div>
              <div className="text-[11px] text-muted-foreground mt-0.5">{r.estimate.label} · counted as {fmtEstimate(r)}{fmtInterval(r) ? <> · <Interval r={r} /></> : null} · <Term k="n">{r.estimate.n} twins</Term></div>
            </div>
          ) : (
            <div className="flex items-baseline gap-2">
              <span className={`font-bold text-teal-300 leading-none ${r.estimate.value == null ? "text-base" : "text-3xl"}`}>{fmtEstimate(r)}</span>
              <span className="text-[11px] text-muted-foreground">{r.estimate.label} · <Interval r={r} /> · <Term k="n">{r.estimate.n} twins</Term></span>
            </div>
          )}
          {r.sentence && <p className="text-[11px] text-foreground/80 leading-snug">{r.sentence}</p>}
          {r.weighted && r.weighted.weighted != null && (
            <p className="text-[10px] text-muted-foreground/80"><Term k="weighted">Weighted to the population</Term>: {r.weighted.format === "share" ? `${Math.round((r.weighted.weighted || 0) * 100)}%` : r.weighted.weighted} (<Term k="ess">effective sample {r.weighted.ess.toFixed(1)}</Term>)</p>
          )}
          {r.unanimity?.flagged && (
            <div className="flex gap-2 text-[10px] text-yellow-200/90 bg-yellow-500/10 border border-yellow-500/25 rounded-lg px-2.5 py-2"><AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-px text-yellow-400" /><span>{r.unanimity.reason}</span></div>
          )}
          {r.refusals && r.refusals.refused > 0 && (
            <p className="text-[10px] text-muted-foreground/80">{r.refusals.refused} of {r.refusals.n} said it was not theirs to answer — outside every denominator.</p>
          )}
          <EquitySplit eq={r.equity} />
          {(r.sources?.length || 0) > 0 && (
            <div>
              <div className="text-[9px] uppercase tracking-wide text-muted-foreground/50 mb-1">Documents the twins drew on · by their own citation</div>
              <ul className="text-[10px] text-foreground/75 space-y-0.5">
                {r.sources!.slice(0, 6).map((u) => (
                  <li key={u.unit_id} title={u.text}>· {u.provenance_class.replace(/_/g, " ")} · cited by {u.twins} twin{u.twins === 1 ? "" : "s"}{u.source_ref ? <span className="text-muted-foreground/60"> · {u.source_ref.replace(/^https?:\/\//, "").slice(0, 44)}</span> : null}</li>
                ))}
              </ul>
            </div>
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
            <div className="text-[9px] uppercase tracking-wide text-muted-foreground/50 mb-1"><Term k="confidence">Confidence {r.confidence.score ?? "not computed"}/100</Term></div>
            <ul className="text-[10px] text-foreground/75 space-y-0.5">{r.confidence.drivers.map((d, i) => <li key={i}>· {d}</li>)}</ul>
          </div>
          {r.caveats?.length > 0 && (
            <div>
              <div className="text-[9px] uppercase tracking-wide text-muted-foreground/50 mb-1">Caveats</div>
              <ul className="text-[10px] text-muted-foreground/85 space-y-0.5">{r.caveats.map((c, i) => <li key={i}>· {c}</li>)}</ul>
            </div>
          )}
          <div className="text-[10px] text-muted-foreground/60 border-t border-border/40 pt-2">
            {r.provenance.model && <span>model {r.provenance.model} · </span>}<Term k="match">population match {r.provenance.frame_level === "none" || !r.provenance.frame_level ? "none" : r.provenance.frame_level}</Term>
            {mix.length > 0 && <span> · evidence {mix.map(([k, n]) => `${k} ${n}`).join(", ")}</span>}
            <span className="block font-mono text-muted-foreground/45 mt-0.5" title="The record id and the random seed the run used, so it can be reproduced">{r.id.slice(0, 8)} · seed {r.provenance.seed}</span>
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
