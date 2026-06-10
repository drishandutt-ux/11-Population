"use client";

import { useState, useRef, useEffect } from "react";
import { Agent, AgentDials, AgentPreset, SpawnOptions, SimMode, api } from "@/lib/api";
import { stanceColor } from "@/lib/utils";
import {
  Zap, Users, Sparkles, Play, Loader2, AlertCircle,
  MessageCircle, Upload, X, ChevronDown, ChevronUp, BarChart2, FileText,
  Bookmark, Trash2, Clock, Heart, Rocket, Brain, AlertTriangle, MessageSquare, ThumbsUp, Swords, Reply,
} from "lucide-react";

// ── Activity ladder (mirrors backend orchestrator._build_phases) ──────────────
const LADDER = ["comment", "like", "debate", "reply"] as const;
function buildPhases(intensity: number): string[] {
  const phases: string[] = [];
  for (let k = 0; k < intensity; k++) {
    phases.push(k < 4 ? LADDER[k] : (k - 4) % 2 === 0 ? "debate" : "reply");
  }
  return phases;
}
const INTENSITY_STEPS: { level: number; label: string; adds: string }[] = [
  { level: 1, label: "1 post each", adds: "Every agent posts once" },
  { level: 2, label: "+ 1 reaction", adds: "Each agent also likes a post" },
  { level: 3, label: "+ 1 debate", adds: "Each agent also rebuts someone" },
  { level: 4, label: "+ 1 reply", adds: "Each agent also replies to someone" },
  { level: 5, label: "+ more debate", adds: "Another debate round per agent" },
  { level: 6, label: "+ more replies", adds: "Another reply round per agent" },
];
const MAX_INTENSITY = 6;

interface Props {
  agents: Agent[];
  sessionId: string;
  sessionStatus: string;
  isSpawning: boolean;
  spawnProgress: { current: number; total: number } | null;
  spawnError: string | null;
  spawnStartTime?: number | null;
  spawnCount?: number;
  isPendingSimulation?: boolean;
  onSpawn: (count: number, opts?: SpawnOptions) => void;
  onStartSimulation: (intensity: number, mode: SimMode) => void;
  onGoToThread: () => void;
  onGoToReport: () => void;
  onApplyPreset: (presetId: string) => void;
}

const STANCE_ORDER = ["direct", "indirect", "neutral"] as const;

// ── Spawn ETA model ──────────────────────────────────────────────────────────
// FAST samples the pre-built bank (near-instant). PRO curates each persona with the
// LLM in concurrent batches, so its cost scales with agent count.
function spawnEtaSec(mode: SimMode, count: number) {
  if (mode === "fast") return Math.max(2, Math.round(count * 0.004)); // bulk insert + batched stream
  return Math.round(10 + count * 0.55); // Sonnet curation in bounded-concurrency batches
}

function fmtDuration(totalSec: number) {
  const s = Math.max(0, Math.round(totalSec));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m > 0 ? `${m}:${r.toString().padStart(2, "0")}` : `${r}s`;
}

// ── Dial category config ─────────────────────────────────────────────────────
const DIAL_CATEGORIES: { key: keyof AgentDials; label: string; color: string; bar: string }[] = [
  { key: "sentiment",   label: "Sentiment",         color: "text-rose-400",    bar: "bg-rose-500"    },
  { key: "motivation",  label: "Motivation",        color: "text-amber-400",   bar: "bg-amber-500"   },
  { key: "habit",       label: "Habit",             color: "text-emerald-400", bar: "bg-emerald-500" },
  { key: "trust",       label: "Trust",             color: "text-blue-400",    bar: "bg-blue-500"    },
  { key: "friction",    label: "Friction",          color: "text-red-400",     bar: "bg-red-500"     },
  { key: "identity",    label: "Identity",          color: "text-purple-400",  bar: "bg-purple-500"  },
  { key: "commercial",  label: "Commercial",        color: "text-teal-400",    bar: "bg-teal-500"    },
  { key: "product",     label: "Product Exp",       color: "text-cyan-400",    bar: "bg-cyan-500"    },
  { key: "composite",   label: "Composite",         color: "text-indigo-400",  bar: "bg-indigo-500"  },
];

function toLabel(key: string) {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// ── Dial bar ─────────────────────────────────────────────────────────────────
function DialBar({ value, barClass }: { value: number; barClass: string }) {
  const pct = Math.min(100, Math.max(0, (value / 10) * 100));
  const color =
    value >= 7 ? barClass : value >= 4 ? "bg-yellow-500" : "bg-muted-foreground/25";
  return (
    <div className="flex items-center gap-1.5">
      <div className="flex-1 h-1 bg-muted rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] text-muted-foreground w-3 text-right shrink-0">{value}</span>
    </div>
  );
}

// ── Dial viewer ───────────────────────────────────────────────────────────────
function DialViewer({ dials }: { dials: AgentDials }) {
  const [openCat, setOpenCat] = useState<string | null>(null);

  return (
    <div className="mt-3 border-t border-border/40 pt-3 space-y-1.5">
      {DIAL_CATEGORIES.map(({ key, label, color, bar }) => {
        const cat = dials[key];
        if (!cat || Object.keys(cat).length === 0) return null;
        const isOpen = openCat === key;
        const keys = Object.keys(cat);
        const avg = Math.round(keys.reduce((s, k) => s + (cat[k] ?? 0), 0) / keys.length);

        return (
          <div key={key}>
            <button
              onClick={() => setOpenCat(isOpen ? null : key)}
              className="w-full flex items-center gap-2 py-1 text-left hover:bg-muted/40 rounded px-1 transition-colors"
            >
              <span className={`text-[10px] font-semibold uppercase tracking-wider ${color} w-20 shrink-0`}>
                {label}
              </span>
              <div className="flex-1 h-1 bg-muted rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${bar} opacity-60`}
                  style={{ width: `${avg * 10}%` }}
                />
              </div>
              <span className="text-[10px] text-muted-foreground w-5 text-right shrink-0">{avg}</span>
              {isOpen ? (
                <ChevronUp className="w-2.5 h-2.5 text-muted-foreground shrink-0" />
              ) : (
                <ChevronDown className="w-2.5 h-2.5 text-muted-foreground shrink-0" />
              )}
            </button>

            {isOpen && (
              <div className="ml-1 pl-3 border-l border-border/30 mt-1 mb-1.5 space-y-1.5">
                {keys.map((k) => (
                  <div key={k} className="grid grid-cols-[1fr_3fr] gap-2 items-center">
                    <span className="text-[9px] text-muted-foreground/70 truncate">{toLabel(k)}</span>
                    <DialBar value={cat[k] ?? 0} barClass={bar} />
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Agent card ────────────────────────────────────────────────────────────────
function AgentCard({ agent, animate = false }: { agent: Agent; animate?: boolean }) {
  const [showDials, setShowDials] = useState(false);
  const hasDials = agent.dials && Object.keys(agent.dials).length > 0;
  const humanity = agent.humanity ?? 0;
  const topSentiments = agent.dials?.sentiment
    ? (Object.entries(agent.dials.sentiment) as [string, number][])
        .filter(([, v]) => v >= 6)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3)
    : [];

  return (
    <div
      className={`glass rounded-xl p-4 transition-all duration-500 ${
        animate ? "ring-1 ring-primary/40 shadow-lg shadow-primary/10" : ""
      }`}
    >
      <div className="flex items-start gap-3 mb-3">
        <div
          className="w-10 h-10 rounded-xl flex items-center justify-center text-sm font-bold text-white shrink-0"
          style={{ backgroundColor: agent.avatar_color }}
        >
          {agent.name.charAt(0)}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-0.5">
            <span className="font-semibold text-foreground text-sm">{agent.name}</span>
            <span className="text-xs text-muted-foreground">{agent.age}y</span>
          </div>
          <p className="text-xs text-muted-foreground truncate">{agent.role}</p>
        </div>
        <div className="flex items-center gap-1 text-xs text-muted-foreground shrink-0">
          <Zap className="w-3 h-3" />
          {Math.round(agent.energy * 100)}%
        </div>
      </div>

      <div className="flex items-center gap-1.5 flex-wrap mb-2">
        <span className={`inline-flex text-xs px-1.5 py-0.5 rounded border ${stanceColor(agent.stance)}`}>
          {agent.stance}
        </span>
        {humanity > 0 && (
          <span className="inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded border border-pink-500/30 text-pink-300 bg-pink-500/10">
            <Heart className="w-2.5 h-2.5" /> {humanity}% human
          </span>
        )}
      </div>

      <p className="text-xs text-muted-foreground line-clamp-2 mb-2.5">{agent.background}</p>

      {topSentiments.length > 0 && (
        <div className="flex gap-1 flex-wrap mb-3">
          {topSentiments.map(([k, v]) => (
            <span
              key={k}
              className="text-[10px] px-1.5 py-0.5 rounded bg-rose-500/10 text-rose-300 border border-rose-500/20"
              title="Dominant sentiment dial"
            >
              {toLabel(k)} {v}
            </span>
          ))}
        </div>
      )}

      {agent.personality && agent.personality.length > 0 && (
        <div className="flex gap-1 flex-wrap mb-3">
          {agent.personality.slice(0, 3).map((t: string) => (
            <span key={t} className="text-xs bg-muted text-muted-foreground px-2 py-0.5 rounded-full">
              {t}
            </span>
          ))}
        </div>
      )}

      {hasDials && (
        <button
          onClick={() => setShowDials(!showDials)}
          className={`flex items-center gap-1.5 text-[10px] font-medium px-2 py-1 rounded border transition-colors ${
            showDials
              ? "border-primary/40 text-primary bg-primary/5"
              : "border-border/50 text-muted-foreground hover:text-foreground"
          }`}
        >
          <BarChart2 className="w-3 h-3" />
          {showDials ? "Hide Dials" : "View Dials"}
        </button>
      )}

      {showDials && agent.dials && <DialViewer dials={agent.dials} />}
    </div>
  );
}

// ── Profile doc upload ────────────────────────────────────────────────────────
function ProfileDocUpload({
  docContext,
  onDocContext,
}: {
  docContext: string;
  onDocContext: (text: string, name: string) => void;
}) {
  const [fileName, setFileName] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function handleFile(file: File) {
    if (file.type === "application/pdf") {
      setWarning("PDF not supported for profile docs. Please convert to .txt or .csv.");
      return;
    }
    setWarning(null);
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = (e.target?.result as string) || "";
      const truncated = text.length > 12000 ? text.slice(0, 12000) : text;
      setFileName(file.name);
      onDocContext(truncated, file.name);
    };
    reader.readAsText(file);
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs text-muted-foreground">Profile / Survey Doc</span>
        <span className="text-[10px] text-muted-foreground/50">.txt, .csv only</span>
      </div>

      {docContext ? (
        <div className="flex items-center gap-2 text-xs bg-muted/50 border border-border rounded-lg px-3 py-2">
          <FileText className="w-3.5 h-3.5 text-primary shrink-0" />
          <span className="text-foreground truncate flex-1">{fileName}</span>
          <button
            onClick={() => { setFileName(null); onDocContext("", ""); }}
            className="text-muted-foreground hover:text-foreground shrink-0"
          >
            <X className="w-3 h-3" />
          </button>
        </div>
      ) : (
        <button
          onClick={() => inputRef.current?.click()}
          className="w-full flex items-center gap-2 text-xs border border-dashed border-border/60 rounded-lg px-3 py-2.5 text-muted-foreground hover:text-foreground hover:border-border transition-colors"
        >
          <Upload className="w-3.5 h-3.5 shrink-0" />
          Upload survey or profile data (optional)
        </button>
      )}

      {warning && (
        <p className="text-[10px] text-yellow-400 mt-1">{warning}</p>
      )}

      <p className="text-[10px] text-muted-foreground/50 mt-1">
        CSV/text with survey responses — Claude will translate to dial values
      </p>

      <input
        ref={inputRef}
        type="file"
        accept=".txt,.csv,text/plain,text/csv"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) handleFile(f);
          e.target.value = "";
        }}
      />
    </div>
  );
}

// ── Mode toggle (Fast / Pro) ──────────────────────────────────────────────────
function ModeToggle({
  mode, onChange, compact = false,
}: { mode: SimMode; onChange: (m: SimMode) => void; compact?: boolean }) {
  const opts: { key: SimMode; label: string; desc: string; icon: React.ReactNode }[] = [
    { key: "fast", label: "Fast", desc: "Instant spawn · pre-built agents · quick posts", icon: <Rocket className="w-4 h-4" /> },
    { key: "pro", label: "Pro", desc: "Deeply curated agents · smarter posts · Sonnet", icon: <Brain className="w-4 h-4" /> },
  ];
  return (
    <div className={`grid grid-cols-2 ${compact ? "gap-1.5" : "gap-2"}`}>
      {opts.map((o) => {
        const active = mode === o.key;
        return (
          <button
            key={o.key}
            onClick={() => onChange(o.key)}
            className={`text-left rounded-xl border transition-all ${compact ? "px-3 py-2" : "px-4 py-3"} ${
              active
                ? "border-primary/60 bg-primary/10 ring-1 ring-primary/30"
                : "border-border/50 bg-muted/30 hover:border-border"
            }`}
          >
            <div className="flex items-center gap-2">
              <span className={active ? "text-primary" : "text-muted-foreground"}>{o.icon}</span>
              <span className={`font-semibold text-sm ${active ? "text-foreground" : "text-muted-foreground"}`}>{o.label}</span>
            </div>
            {!compact && <p className="text-[11px] text-muted-foreground/70 mt-1 leading-snug">{o.desc}</p>}
          </button>
        );
      })}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────
export default function AgentDirectory({
  agents,
  sessionId,
  sessionStatus,
  isSpawning,
  spawnProgress,
  spawnError,
  spawnStartTime,
  spawnCount,
  isPendingSimulation = false,
  onSpawn,
  onStartSimulation,
  onGoToThread,
  onGoToReport,
  onApplyPreset,
}: Props) {
  const [agentCount, setAgentCount] = useState(50);
  const [intensity, setIntensity] = useState(2);
  const [mode, setMode] = useState<SimMode>("fast");
  const [profileQuery, setProfileQuery] = useState("");
  const [directPct, setDirectPct] = useState(33);
  const [indirectPct, setIndirectPct] = useState(33);
  const [docContext, setDocContext] = useState("");
  const [humanity, setHumanity] = useState(50);          // 0 = expert, 100 = fully human
  const [humanityCoverage, setHumanityCoverage] = useState(60); // % of agents it applies to
  const [search, setSearch] = useState("");

  // Preset state
  const [presets, setPresets] = useState<AgentPreset[]>([]);
  const [isSaveForm, setIsSaveForm] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Live clock that drives the spawn elapsed / ETA timer
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!isSpawning) return;
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [isSpawning]);

  useEffect(() => {
    api.presets.list()
      .then((p) => setPresets(p as AgentPreset[]))
      .catch(() => {});
  }, []);

  async function handleSavePreset() {
    if (!saveName.trim() || isSaving) return;
    setIsSaving(true);
    try {
      const preset = await api.presets.save(sessionId, saveName.trim()) as AgentPreset;
      setPresets((prev) => [preset, ...prev]);
      setSaveSuccess(true);
      setTimeout(() => {
        setSaveSuccess(false);
        setIsSaveForm(false);
        setSaveName("");
      }, 1800);
    } catch {
      // silently fail — user can retry
    } finally {
      setIsSaving(false);
    }
  }

  async function handleDeletePreset(presetId: string) {
    setPresets((prev) => prev.filter((p) => p.id !== presetId));
    try {
      await api.presets.delete(presetId);
    } catch {
      // re-fetch on failure
      api.presets.list().then((p) => setPresets(p as AgentPreset[])).catch(() => {});
    }
  }

  const neutralPct = Math.max(0, 100 - directPct - indirectPct);
  const overflowPct = directPct + indirectPct > 100;

  const isSimulating = sessionStatus === "simulating";
  const isComplete = sessionStatus === "complete";
  const isIngesting = sessionStatus === "ingesting";
  const hasAgents = agents.length > 0;

  const filtered = agents.filter(
    (a) =>
      a.name.toLowerCase().includes(search.toLowerCase()) ||
      a.role.toLowerCase().includes(search.toLowerCase())
  );

  function handleSpawnClick() {
    onSpawn(agentCount, {
      mode,
      profile_query: profileQuery.trim(),
      direct_pct: directPct,
      indirect_pct: indirectPct,
      neutral_pct: neutralPct,
      doc_context: docContext,
      humanity,
      humanity_coverage: humanityCoverage,
    });
  }

  const phases = buildPhases(intensity);
  const postPhases = phases.filter((p) => p !== "like").length;
  const likePhases = phases.length - postPhases;
  const estPosts = agentCount * postPhases;
  const estReactions = agentCount * likePhases;
  const proHeavy = mode === "pro" && agentCount > 150;

  // ── Phase 1: No agents yet ────────────────────────────────────────────────
  if (!hasAgents && !isSpawning) {
    const dCnt = Math.max(1, Math.round(agentCount * directPct / 100));
    const iCnt = Math.max(1, Math.round(agentCount * indirectPct / 100));
    const nCnt = Math.max(0, agentCount - dCnt - iCnt);
    const humanizedCount = humanity > 0 ? Math.round(agentCount * humanityCoverage / 100) : 0;

    return (
      <div className="h-full overflow-y-auto px-6 py-8">
        <div className="max-w-xl mx-auto space-y-6">

          {/* Header */}
          <div className="text-center">
            <div className="w-16 h-16 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center mx-auto mb-4">
              <Users className="w-8 h-8 text-primary" />
            </div>
            <h2 className="text-xl font-bold text-foreground mb-1.5">Spawn Your Army</h2>
            <p className="text-sm text-muted-foreground">
              Define your audience, tune the stance mix, and optionally upload survey data to seed psychological profiles.
            </p>
          </div>

          {/* Mode */}
          <div className="glass rounded-2xl p-5 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-muted-foreground">Mode</span>
              <span className="text-[10px] text-muted-foreground/50">
                {mode === "fast" ? "speed first" : "quality first"}
              </span>
            </div>
            <ModeToggle mode={mode} onChange={setMode} />
            {mode === "pro" && (
              <div className="flex items-start gap-2 text-[11px] text-amber-300/90 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
                <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-px" />
                <span>
                  Pro curates every agent with Sonnet and runs the debate on Sonnet too — far richer, but
                  <strong className="text-amber-200"> noticeably slower and more costly</strong>
                  {agentCount > 150 ? ` at ${agentCount} agents (several minutes + significant API spend).` : "."}
                </span>
              </div>
            )}
          </div>

          {/* Saved lineups */}
          {presets.length > 0 && (
            <div className="glass rounded-2xl p-5">
              <div className="flex items-center gap-2 mb-3">
                <Bookmark className="w-3.5 h-3.5 text-primary" />
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                  Saved Lineups
                </span>
              </div>
              <div className="space-y-2">
                {presets.map((preset) => (
                  <div
                    key={preset.id}
                    className="flex items-center gap-3 px-3 py-2.5 rounded-xl border border-border/40 bg-muted/30"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-foreground truncate">{preset.name}</div>
                      <div className="text-[11px] text-muted-foreground">
                        {preset.agent_count} agents · {new Date(preset.created_at).toLocaleDateString()}
                      </div>
                    </div>
                    <button
                      onClick={() => onApplyPreset(preset.id)}
                      className="shrink-0 text-xs font-medium px-3 py-1.5 rounded-lg bg-primary/10 border border-primary/20 text-primary hover:bg-primary/20 transition-colors"
                    >
                      Load
                    </button>
                    <button
                      onClick={() => handleDeletePreset(preset.id)}
                      className="shrink-0 text-muted-foreground/50 hover:text-red-400 transition-colors p-1"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Profile query */}
          <div className="glass rounded-2xl p-5 space-y-4">
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                Audience Profile <span className="text-muted-foreground/50">(optional)</span>
              </label>
              <textarea
                value={profileQuery}
                onChange={(e) => setProfileQuery(e.target.value)}
                rows={3}
                placeholder={`e.g. "30% Aspirational early adopters, 20% Paranoid skeptics, rest neutral"\nor "Teenagers aged 15–19 living in the UK, moderate income"`}
                className="w-full bg-muted/50 border border-border rounded-xl px-3 py-2.5 text-sm text-foreground placeholder-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50 resize-none"
              />
            </div>

            <ProfileDocUpload
              docContext={docContext}
              onDocContext={(text) => setDocContext(text)}
            />
          </div>

          {/* Stance distribution */}
          <div className="glass rounded-2xl p-5 space-y-4">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-medium text-muted-foreground">Stance Distribution</span>
              {overflowPct && (
                <span className="text-[10px] text-yellow-400">Direct + Indirect exceed 100%</span>
              )}
            </div>

            {/* Direct */}
            <div>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-blue-400 font-medium">Direct</span>
                <span className="text-blue-400 font-bold">{directPct}%</span>
              </div>
              <input
                type="range" min={0} max={100} step={5}
                value={directPct}
                onChange={(e) => {
                  const v = +e.target.value;
                  setDirectPct(v);
                  if (v + indirectPct > 100) setIndirectPct(Math.max(0, 100 - v));
                }}
                className="w-full accent-blue-500 cursor-pointer h-1.5"
              />
            </div>

            {/* Indirect */}
            <div>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-purple-400 font-medium">Indirect</span>
                <span className="text-purple-400 font-bold">{indirectPct}%</span>
              </div>
              <input
                type="range" min={0} max={100} step={5}
                value={indirectPct}
                onChange={(e) => {
                  const v = +e.target.value;
                  setIndirectPct(v);
                  if (directPct + v > 100) setDirectPct(Math.max(0, 100 - v));
                }}
                className="w-full accent-purple-500 cursor-pointer h-1.5"
              />
            </div>

            {/* Neutral (derived) */}
            <div className="flex justify-between items-center text-xs">
              <span className="text-slate-400 font-medium">Neutral</span>
              <span className="text-slate-400 font-bold">{neutralPct}% (auto)</span>
            </div>

            {/* Preview counts */}
            <div className="grid grid-cols-3 gap-2 text-xs text-center pt-1">
              {[
                { label: "Direct",   count: dCnt, color: "text-blue-400",   desc: "Domain experts" },
                { label: "Indirect", count: iCnt, color: "text-purple-400", desc: "Adjacent fields" },
                { label: "Neutral",  count: nCnt, color: "text-slate-400",  desc: "Skeptics & press" },
              ].map((g) => (
                <div key={g.label} className="bg-muted/60 rounded-lg p-2">
                  <div className={`font-bold text-lg ${g.color}`}>{g.count}</div>
                  <div className="font-medium text-foreground text-[11px]">{g.label}</div>
                  <div className="text-muted-foreground text-[10px]">{g.desc}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Humanity + Coverage */}
          <div className="glass rounded-2xl p-5 space-y-5">
            <div className="flex items-center gap-2">
              <Heart className="w-3.5 h-3.5 text-pink-400" />
              <span className="text-xs font-medium text-muted-foreground">Humanity</span>
              <span className="text-[10px] text-muted-foreground/50 ml-auto">feeling over logic</span>
            </div>

            {/* Humanity intensity */}
            <div className="space-y-2">
              <div className="flex justify-between text-xs">
                <span className="text-pink-400 font-medium">Intensity</span>
                <span className="text-pink-400 font-bold">{humanity === 0 ? "Off" : `${humanity}%`}</span>
              </div>
              <input
                type="range" min={0} max={100} step={5}
                value={humanity}
                onChange={(e) => setHumanity(+e.target.value)}
                className="w-full accent-pink-500 cursor-pointer h-1.5"
              />
              <div className="flex justify-between text-[10px] text-muted-foreground">
                <span>0 · expert &amp; logical</span>
                <span>100 · human &amp; emotional</span>
              </div>
            </div>

            {/* Coverage */}
            <div className={`space-y-2 transition-opacity ${humanity === 0 ? "opacity-40 pointer-events-none" : ""}`}>
              <div className="flex justify-between text-xs">
                <span className="text-pink-300 font-medium">Coverage</span>
                <span className="text-pink-300 font-bold">{humanityCoverage}%</span>
              </div>
              <input
                type="range" min={0} max={100} step={5}
                value={humanityCoverage}
                onChange={(e) => setHumanityCoverage(+e.target.value)}
                className="w-full accent-pink-400 cursor-pointer h-1.5"
              />
            </div>

            <p className="text-[10px] text-muted-foreground/60 leading-relaxed">
              {humanity === 0
                ? "All agents stay analytical experts — citations, frameworks, measured tone."
                : `≈ ${humanizedCount} of ${agentCount} agents will be emotion-led: more human, gut-driven, less expert, leaning on their sentiment dials over logic. The rest stay analytical.`}
            </p>
          </div>

          {/* Agent count + Intensity */}
          <div className="glass rounded-2xl p-5 space-y-5">
            {/* Agent count */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">Number of agents</span>
                <input
                  type="number" min={1} max={1000}
                  value={agentCount}
                  onChange={(e) => setAgentCount(Math.max(1, Math.min(1000, +e.target.value || 0)))}
                  className="w-24 text-right text-3xl font-bold text-primary bg-transparent focus:outline-none tabular-nums"
                />
              </div>
              <input
                type="range" min={5} max={1000} step={5}
                value={Math.min(agentCount, 1000)}
                onChange={(e) => setAgentCount(+e.target.value)}
                className="w-full accent-purple-500 cursor-pointer"
              />
              <div className="flex gap-1.5 flex-wrap">
                {[10, 50, 100, 250, 500, 1000].map((n) => (
                  <button
                    key={n}
                    onClick={() => setAgentCount(n)}
                    className={`text-[11px] px-2.5 py-1 rounded-lg border transition-colors ${
                      agentCount === n
                        ? "border-primary/50 bg-primary/10 text-primary"
                        : "border-border/50 text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>

            <div className="border-t border-border/40" />

            {/* Activity intensity */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-xs text-muted-foreground">Activity intensity</span>
                  <p className="text-[10px] text-muted-foreground/50 mt-0.5">
                    ≈ {estPosts.toLocaleString()} posts{estReactions > 0 ? ` + ${estReactions.toLocaleString()} reactions` : ""}
                  </p>
                </div>
                <span className="text-3xl font-bold text-primary tabular-nums">L{intensity}</span>
              </div>
              <input
                type="range" min={1} max={MAX_INTENSITY} step={1}
                value={intensity}
                onChange={(e) => setIntensity(+e.target.value)}
                className="w-full accent-teal-500 cursor-pointer"
              />
              <div className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 text-[11px]">
                {INTENSITY_STEPS.slice(0, intensity).map((s) => {
                  const icon =
                    s.level === 1 ? <MessageSquare className="w-3 h-3 text-blue-400" />
                    : s.level === 2 ? <ThumbsUp className="w-3 h-3 text-pink-400" />
                    : s.level % 2 === 1 ? <Swords className="w-3 h-3 text-orange-400" />
                    : <Reply className="w-3 h-3 text-emerald-400" />;
                  return (
                    <div key={s.level} className="contents">
                      <span className="flex items-center gap-1.5 text-muted-foreground">{icon}<span className="text-foreground/80 font-medium">{s.label}</span></span>
                      <span className="text-muted-foreground/60 self-center">{s.adds}</span>
                    </div>
                  );
                })}
              </div>
              <p className="text-[10px] text-muted-foreground/50">
                Every agent is guaranteed to act at each level — higher = more posts, debates and replies per agent.
              </p>
            </div>
          </div>

          {spawnError && (
            <div className="flex items-center gap-2 text-sm text-red-400 bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-3">
              <AlertCircle className="w-4 h-4 shrink-0" />
              {spawnError}
            </div>
          )}

          <button
            onClick={handleSpawnClick}
            className="w-full bg-primary hover:bg-primary/90 text-primary-foreground font-semibold py-4 rounded-xl flex items-center justify-center gap-3 transition-all text-base"
          >
            {mode === "fast" ? <Rocket className="w-5 h-5" /> : <Brain className="w-5 h-5" />}
            Spawn {agentCount.toLocaleString()} Agents · {mode === "fast" ? "Fast" : "Pro"}
          </button>
        </div>
      </div>
    );
  }

  // ── Phase 2: Spawning in progress ─────────────────────────────────────────
  if (isSpawning) {
    const plannedCount =
      spawnProgress?.total ?? (spawnCount && spawnCount > 0 ? spawnCount : 15);
    const estTotalSec = spawnEtaSec(mode, plannedCount);
    const elapsedSec = spawnStartTime ? Math.max(0, (now - spawnStartTime) / 1000) : 0;
    const remainingSec = Math.max(0, estTotalSec - elapsedSec);
    const overdue = elapsedSec > estTotalSec + 1;

    const realPct = spawnProgress
      ? Math.round((spawnProgress.current / spawnProgress.total) * 100)
      : 0;
    // Before the first agent_spawned event we're inside the single long Claude
    // call — show time-based progress capped below 100% so the bar is visibly
    // alive without ever falsely signalling completion.
    const timePct =
      estTotalSec > 0 ? Math.min(92, Math.round((elapsedSec / estTotalSec) * 100)) : 0;
    const pct = spawnProgress ? realPct : timePct;

    return (
      <div className="h-full overflow-y-auto px-6 py-6">
        <div className="max-w-4xl mx-auto mb-6">
          <div className="glass rounded-2xl p-5">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-3">
                <Loader2 className="w-5 h-5 text-primary animate-spin" />
                <span className="font-semibold text-foreground">Spawning agents with psychological profiles…</span>
              </div>
              <span className="text-sm text-muted-foreground">
                {spawnProgress?.current ?? 0} / {spawnProgress?.total ?? plannedCount} agents
              </span>
            </div>
            <div className="w-full bg-muted rounded-full h-2">
              <div
                className="bg-primary rounded-full h-2 transition-all duration-500"
                style={{ width: `${pct}%` }}
              />
            </div>

            {/* Timer KPIs */}
            <div className="grid grid-cols-3 gap-2 mt-4">
              <div className="bg-muted/50 rounded-lg px-3 py-2">
                <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground/70 mb-0.5">
                  <Clock className="w-3 h-3" /> Elapsed
                </div>
                <div className="text-lg font-bold text-foreground tabular-nums">{fmtDuration(elapsedSec)}</div>
              </div>
              <div className="bg-muted/50 rounded-lg px-3 py-2">
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground/70 mb-0.5">Est. total</div>
                <div className="text-lg font-bold text-foreground tabular-nums">~{fmtDuration(estTotalSec)}</div>
              </div>
              <div className="bg-muted/50 rounded-lg px-3 py-2">
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground/70 mb-0.5">
                  {overdue ? "Status" : "Remaining"}
                </div>
                <div className={`text-lg font-bold tabular-nums ${overdue ? "text-yellow-400" : "text-primary"}`}>
                  {overdue ? "Finishing…" : `~${fmtDuration(remainingSec)}`}
                </div>
              </div>
            </div>

            <p className="text-[10px] text-muted-foreground/60 mt-3">
              {overdue
                ? "Taking a little longer than usual — generating 112 psychological dials per agent…"
                : "Generating 112 psychological dials per agent — this takes a moment…"}
            </p>
          </div>
        </div>

        {agents.length > 60 && (
          <div className="max-w-4xl mx-auto mb-3 text-[11px] text-muted-foreground/60 text-center">
            Showing the latest 60 of {agents.length.toLocaleString()} agents as they stream in…
          </div>
        )}
        <div className="max-w-4xl mx-auto grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {agents.slice(-60).map((agent, i, arr) => (
            <AgentCard key={agent.id} agent={agent} animate={i === arr.length - 1} />
          ))}
        </div>
      </div>
    );
  }

  // ── Phase 3: Agents ready / simulation running ─────────────────────────────
  return (
    <div className="h-full overflow-y-auto px-6 py-6">
      <div className="max-w-4xl mx-auto space-y-6">

        {/* Simulation settings (mode + intensity) */}
        {!isSimulating && !isComplete && (
          <div className="glass rounded-2xl p-5 space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-muted-foreground">Run settings</span>
              <span className="text-[10px] text-muted-foreground/50">
                {agents.length.toLocaleString()} agents · ≈ {estPosts.toLocaleString()} posts{estReactions > 0 ? ` + ${estReactions.toLocaleString()} reactions` : ""}
              </span>
            </div>
            <ModeToggle mode={mode} onChange={setMode} compact />
            {mode === "pro" && agents.length > 150 && (
              <div className="flex items-start gap-2 text-[11px] text-amber-300/90 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
                <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-px" />
                <span>Pro runs the debate on Sonnet — expect several minutes and significant API cost at {agents.length.toLocaleString()} agents.</span>
              </div>
            )}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">Activity intensity</span>
                <span className="text-sm font-bold text-primary tabular-nums">L{intensity} · {INTENSITY_STEPS[Math.min(intensity, MAX_INTENSITY) - 1]?.label}</span>
              </div>
              <input
                type="range" min={1} max={MAX_INTENSITY} step={1}
                value={intensity}
                onChange={(e) => setIntensity(+e.target.value)}
                className="w-full accent-teal-500 cursor-pointer h-1.5"
              />
              <div className="flex justify-between text-[10px] text-muted-foreground/60">
                <span>L1 · one post each</span>
                <span>L{MAX_INTENSITY} · post + react + debates + replies</span>
              </div>
            </div>
          </div>
        )}

        {!isSimulating && !isComplete && (
          <div className={`glass rounded-2xl p-5 flex flex-col sm:flex-row items-start sm:items-center gap-4 ${
            isIngesting || isPendingSimulation ? "border border-yellow-500/25 bg-yellow-500/5" : ""
          }`}>
            <div className="flex-1">
              {isIngesting || isPendingSimulation ? (
                <>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse shrink-0" />
                    <h3 className="font-semibold text-foreground">
                      {isPendingSimulation ? "Simulation queued — waiting for ingestion" : "Ingestion in progress"}
                    </h3>
                  </div>
                  <p className="text-sm text-muted-foreground/70">
                    {isPendingSimulation
                      ? "The simulation will start automatically once all content is processed."
                      : `${agents.length} agents ready. Simulation will start automatically when content finishes ingesting.`}
                  </p>
                </>
              ) : (
                <>
                  <h3 className="font-semibold text-foreground">{agents.length} agents ready to debate</h3>
                  <p className="text-sm text-muted-foreground mt-0.5">
                    Start the simulation to watch them discuss your query in a live thread.
                  </p>
                </>
              )}
            </div>
            <div className="flex gap-3 shrink-0">
              {!isPendingSimulation && (
                <button
                  onClick={handleSpawnClick}
                  className="text-sm border border-border text-muted-foreground hover:text-foreground px-4 py-2 rounded-lg transition-all"
                >
                  Re-spawn
                </button>
              )}
              <button
                onClick={() => onStartSimulation(intensity, mode)}
                disabled={isPendingSimulation}
                className={`flex items-center gap-2 text-sm font-semibold px-5 py-2.5 rounded-xl transition-all ${
                  isPendingSimulation
                    ? "bg-yellow-500/20 border border-yellow-500/30 text-yellow-400 cursor-not-allowed"
                    : "bg-primary hover:bg-primary/90 text-primary-foreground"
                }`}
              >
                {isPendingSimulation ? (
                  <><Loader2 className="w-4 h-4 animate-spin" />Waiting…</>
                ) : isIngesting ? (
                  <><Play className="w-4 h-4" />Start when ready</>
                ) : (
                  <><Play className="w-4 h-4" />Start Simulation</>
                )}
              </button>
            </div>
          </div>
        )}

        {isSimulating && (
          <div className="glass rounded-2xl p-5 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
              <span className="font-semibold text-foreground">Simulation running</span>
              <span className="text-sm text-muted-foreground">— agents are debating in the Thread tab</span>
            </div>
            <button
              onClick={onGoToThread}
              className="flex items-center gap-2 bg-blue-500/20 border border-blue-500/30 text-blue-400 text-sm font-medium px-4 py-2 rounded-lg hover:bg-blue-500/30 transition-all"
            >
              <MessageCircle className="w-4 h-4" />
              Watch Thread →
            </button>
          </div>
        )}

        {isComplete && (
          <div className="glass rounded-2xl p-5 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-green-400">✓</span>
              <span className="font-semibold text-foreground">Simulation complete</span>
            </div>
            <div className="flex gap-2">
              <button onClick={onGoToThread} className="text-sm border border-border text-muted-foreground hover:text-foreground px-4 py-2 rounded-lg transition-all">
                View Thread
              </button>
              <button onClick={onGoToReport} className="flex items-center gap-2 text-sm bg-primary/10 border border-primary/20 text-primary hover:bg-primary/20 px-4 py-2 rounded-lg transition-all">
                <MessageCircle className="w-3.5 h-3.5" />
                Chat with Agents
              </button>
            </div>
          </div>
        )}

        {/* Save lineup row */}
        <div className="flex items-center gap-2">
          {!isSaveForm ? (
            <>
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search agents by name or role…"
                className="flex-1 bg-muted border border-border rounded-xl px-4 py-2.5 text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 text-sm"
              />
              <button
                onClick={() => { setIsSaveForm(true); setSaveName(""); }}
                className="shrink-0 flex items-center gap-1.5 text-xs font-medium px-3 py-2.5 rounded-xl border border-border/60 text-muted-foreground hover:text-foreground hover:border-border transition-colors"
              >
                <Bookmark className="w-3.5 h-3.5" />
                Save Lineup
              </button>
            </>
          ) : (
            <div className="flex-1 flex items-center gap-2 glass rounded-xl px-3 py-2">
              <Bookmark className="w-3.5 h-3.5 text-primary shrink-0" />
              <input
                value={saveName}
                onChange={(e) => setSaveName(e.target.value)}
                placeholder="Name this lineup…"
                className="flex-1 bg-transparent text-sm text-foreground placeholder-muted-foreground focus:outline-none"
                autoFocus
                onKeyDown={(e) => { if (e.key === "Enter") handleSavePreset(); if (e.key === "Escape") setIsSaveForm(false); }}
              />
              {saveSuccess ? (
                <span className="text-xs text-green-400 shrink-0">Saved!</span>
              ) : (
                <>
                  <button
                    onClick={handleSavePreset}
                    disabled={!saveName.trim() || isSaving}
                    className="shrink-0 text-xs font-medium text-primary hover:text-primary/80 disabled:opacity-40 transition-colors px-1"
                  >
                    {isSaving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : "Save"}
                  </button>
                  <button
                    onClick={() => setIsSaveForm(false)}
                    className="shrink-0 text-muted-foreground/60 hover:text-muted-foreground transition-colors"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </>
              )}
            </div>
          )}
        </div>

        {STANCE_ORDER.map((stance) => {
          const group = filtered.filter((a) => a.stance === stance);
          if (group.length === 0) return null;
          const CAP = 60;
          const shown = group.slice(0, CAP);
          return (
            <div key={stance}>
              <h3 className="text-xs text-muted-foreground uppercase tracking-wider mb-3 flex items-center gap-2">
                <span className={`inline-flex px-2 py-0.5 rounded border text-xs ${stanceColor(stance)}`}>
                  {stance}
                </span>
                {group.length} agent{group.length !== 1 ? "s" : ""}
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {shown.map((agent) => (
                  <AgentCard key={agent.id} agent={agent} />
                ))}
              </div>
              {group.length > CAP && (
                <p className="text-[11px] text-muted-foreground/60 mt-3">
                  +{(group.length - CAP).toLocaleString()} more {stance} agents{search ? " (refine your search to see specific agents)" : ""}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
