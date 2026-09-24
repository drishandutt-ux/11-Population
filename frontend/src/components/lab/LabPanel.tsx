"use client";

/** The Lab shell.
 *
 *  It owns only what is identical for every tool: picking one, running it, streaming answers
 *  in, stopping, the cost estimate, CSV export, past runs and provenance. Everything a tool
 *  does differently — its inputs, its charts, its KPIs — belongs to the tool: the form comes
 *  from the instrument's own declaration, and the results come from the instrument's own page.
 *
 *  There is no `if (instrument === "purchase_intent")` in this file, and there should never
 *  be one. The Lab has two generic primitives — a probe (one instrument, once) and an
 *  experiment (one instrument, once per variant) — and the shell routes between them; the
 *  A/B tool is itself generic over instruments. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, Agent, Experiment, Instrument, Probe, ProbeAnswerRow, ProbeRequest, SimMode, DynamicDial } from "@/lib/api";
import {
  Beaker, Download, Loader2, Play, Square, AlertTriangle, RefreshCw, ChevronLeft, ChevronDown,
  ChevronRight, History, Trash2, LucideIcon,
} from "lucide-react";
import { DotGrid, dotColor } from "./Charts";
import ExperimentPanel from "./ExperimentPanel";
import { initialValues, toSpec } from "./InstrumentForm";
import { formFor } from "./forms";
import { SEGMENT_FILTERS, dynamicFilters } from "./filters";
import { pageFor } from "./pages";
import ConfidenceBadge from "@/components/ConfidenceBadge";
import { EXPERIMENT_ICON, iconFor } from "./icons";

type LiveAnswer = { agent_id: string; agent_name: string; avatar_color: string; answer: Record<string, any> };

interface Props {
  sessionId: string;
  sessionQuery: string;
  agents: Agent[];
  liveAnswers: Record<string, LiveAnswer[]>;
  completedAt: number;
  experimentCompletedAt: number;
  onClearLive: (probeId: string) => void;
  /** The question's own dials (brief L3-04): extra "who answers" filters and split headings. */
  dynamicDials?: DynamicDial[];
}

type PastRun =
  | { kind: "probe"; at: string; probe: Probe }
  | { kind: "experiment"; at: string; experiment: Experiment };

const PAST_OPEN_KEY = "lab:pastRunsOpen";

/** "3m ago" for the past-runs list. Timestamps come from the API without a zone suffix and
 *  are UTC, so one is added before parsing or the browser would read them as local time. */
function ago(iso: string): string {
  if (!iso) return "";
  const t = Date.parse(/[zZ]$|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 7 * 86400) return `${Math.floor(s / 86400)}d ago`;
  return new Date(t).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export default function LabPanel({ sessionId, sessionQuery, agents, liveAnswers, completedAt, experimentCompletedAt, onClearLive, dynamicDials = [] }: Props) {
  const agentsById = useMemo(() => Object.fromEntries(agents.map((a) => [a.id, a])), [agents]);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [instrumentKey, setInstrumentKey] = useState<string>("");
  // The A/B tool is the shell's second primitive: open it fresh, or on a past experiment.
  const [experimentOpen, setExperimentOpen] = useState(false);
  const [initialExperiment, setInitialExperiment] = useState<Experiment | null>(null);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [values, setValues] = useState<Record<string, any>>({});
  const [mode, setMode] = useState<SimMode>("fast");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [estimate, setEstimate] = useState<{ agent_count: number; estimated_cost_usd: number; model: string } | null>(null);
  const [probes, setProbes] = useState<Probe[]>([]);
  const [selected, setSelected] = useState<(Probe & { answers?: ProbeAnswerRow[] }) | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Past runs fold away under a header; the choice sticks per browser.
  const [pastOpen, setPastOpen] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const selectedId = useRef<string | null>(null);
  selectedId.current = selected?.id || null;
  // Read through a ref so the completion effects below run once per completion tick, never
  // because a parent re-render handed down a new function.
  const clearLive = useRef(onClearLive);
  clearLive.current = onClearLive;

  const instrument = useMemo(() => instruments.find((i) => i.key === instrumentKey), [instruments, instrumentKey]);
  const canExperiment = useMemo(() => instruments.some((i) => i.supports_experiments), [instruments]);

  useEffect(() => {
    api.lab.instruments()
      .then((r) => setInstruments(r.instruments))
      .catch((e) => setError(String(e.message || e)));
  }, []);

  useEffect(() => {
    try { setPastOpen(localStorage.getItem(PAST_OPEN_KEY) === "1"); } catch { /* private mode */ }
  }, []);

  function togglePast() {
    setPastOpen((v) => {
      try { localStorage.setItem(PAST_OPEN_KEY, v ? "0" : "1"); } catch { /* private mode */ }
      return !v;
    });
  }

  // Choosing a tool resets to that tool's own declared inputs, prefilled from the session.
  function chooseInstrument(inst: Instrument) {
    setInstrumentKey(inst.key);
    setValues(initialValues(inst, { session_query: sessionQuery }));
    setSelected(null);
    setError(null);
  }

  const buildRequest = useCallback((): ProbeRequest | null => {
    if (!instrument) return null;
    const segments: Record<string, string> = {};
    for (const [k, v] of Object.entries(filters)) if (v) segments[k] = v;
    return {
      instrument: instrument.key,
      mode,
      spec: {
        ...toSpec(instrument, values),
        ...(Object.keys(segments).length ? { agent_filter: { segments } } : {}),
      },
    };
  }, [instrument, mode, values, filters]);

  const loadProbes = useCallback(async () => {
    try {
      const [p, e] = await Promise.all([api.lab.probes(sessionId), api.lab.experiments(sessionId)]);
      setProbes(p.probes);
      setExperiments(e.experiments);
      return p.probes;
    } catch (e: any) {
      setError(e?.message || String(e));
      return [];
    }
  }, [sessionId]);

  useEffect(() => { loadProbes(); }, [loadProbes]);

  // A probe finished somewhere in this session. Refresh the list, and if it was the one on
  // screen, swap the live dots for its aggregates. An arm of an experiment completing must
  // never hijack the shell — the experiment panel owns those.
  useEffect(() => {
    if (!completedAt) return;
    (async () => {
      await loadProbes();
      const id = selectedId.current;
      if (!id) return;
      const full = await api.lab.probe(sessionId, id).catch(() => null);
      if (full && full.status !== "queued" && full.status !== "running") { setSelected(full); clearLive.current(full.id); }
    })();
  }, [completedAt, loadProbes, sessionId]);

  useEffect(() => {
    if (!experimentCompletedAt) return;
    loadProbes();
  }, [experimentCompletedAt, loadProbes]);

  const pastRuns = useMemo<PastRun[]>(() => {
    const runs: PastRun[] = [
      ...probes.filter((p) => !p.experiment_id).map((p) => ({ kind: "probe" as const, at: p.created_at || "", probe: p })),
      ...experiments.map((e) => ({ kind: "experiment" as const, at: e.created_at || "", experiment: e })),
    ];
    return runs.sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0));
  }, [probes, experiments]);

  /** Delete a past run. The backend refuses while it is still running, and refuses an arm of
   *  an A/B test on its own; the list only offers the delete on rows it will accept. */
  async function remove(r: PastRun) {
    const id = r.kind === "probe" ? r.probe.id : r.experiment.id;
    setDeleting(id); setError(null);
    try {
      if (r.kind === "probe") {
        await api.lab.deleteProbe(sessionId, id);
        setProbes((prev) => prev.filter((p) => p.id !== id));
      } else {
        await api.lab.deleteExperiment(sessionId, id);
        setExperiments((prev) => prev.filter((e) => e.id !== id));
        setProbes((prev) => prev.filter((p) => p.experiment_id !== id));
      }
      if (selectedId.current === id) setSelected(null);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setDeleting(null);
      setConfirming(null);
    }
  }

  function openExperiment(e: Experiment | null) {
    setInstrumentKey("");
    setSelected(null);
    setInitialExperiment(e);
    setExperimentOpen(true);
    setError(null);
  }

  useEffect(() => {
    const req = buildRequest();
    if (!agents.length || !req) return;
    const t = setTimeout(() => {
      api.lab.estimate(sessionId, req).then(setEstimate).catch(() => setEstimate(null));
    }, 250);
    return () => clearTimeout(t);
  }, [agents.length, sessionId, buildRequest]);

  async function run() {
    const req = buildRequest();
    if (!instrument || !req) return;
    const missing = instrument.inputs.filter((f) => f.required && (Array.isArray(values[f.key]) ? values[f.key].length === 0 : !String(values[f.key] ?? "").trim()));
    if (missing.length) { setError(`${missing.map((f) => f.label).join(", ")} required.`); return; }
    setBusy(true); setError(null);
    try {
      const p = await api.lab.run(sessionId, req);
      setSelected(p);
      setProbes((prev) => [p, ...prev]);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  }

  async function select(p: Probe) {
    setInstrumentKey(p.instrument);
    setSelected(p);
    const full = await api.lab.probe(sessionId, p.id).catch(() => null);
    if (full) setSelected(full);
  }

  const running = selected && (selected.status === "queued" || selected.status === "running");
  const live = selected ? liveAnswers[selected.id] || [] : [];

  // ── The A/B tool ──────────────────────────────────────────────────────────
  if (experimentOpen) {
    return (
      <ExperimentPanel
        sessionId={sessionId}
        sessionQuery={sessionQuery}
        agents={agents}
        instruments={instruments}
        liveAnswers={liveAnswers}
        completedAt={experimentCompletedAt}
        onClearLive={onClearLive}
        initial={initialExperiment}
        dynamicDials={dynamicDials}
        onBack={() => { setExperimentOpen(false); setInitialExperiment(null); loadProbes(); }}
      />
    );
  }

  // ── Tool picker ───────────────────────────────────────────────────────────
  if (!instrument) {
    const visible = instruments.filter((i) => !i.hidden);
    const runsFor = (key: string) => probes.filter((p) => !p.experiment_id && p.instrument === key).length;
    return (
      <div className="h-full overflow-y-auto p-6">
        <div className="max-w-4xl">
          <div className="flex items-center gap-2 mb-1">
            <Beaker className="w-4 h-4 text-primary" />
            <h2 className="text-sm font-medium">Behaviour Lab</h2>
          </div>
          <p className="text-xs text-muted-foreground mb-5 max-w-2xl">
            Ask this population a structured question once, and every number that follows is computed
            from their answers. Each tool has its own inputs and its own results.
          </p>

          {error && (
            <div className="flex gap-2 text-[11px] text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2 mb-4">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
            {visible.map((i) => (
              <ToolCard
                key={i.key}
                icon={iconFor(i.key)}
                label={i.label}
                description={i.description}
                tags={i.kpis.slice(0, 3).map((k) => k.label)}
                runs={runsFor(i.key)}
                onClick={() => chooseInstrument(i)}
              />
            ))}
            {canExperiment && (
              <ToolCard
                icon={EXPERIMENT_ICON}
                label="A/B test"
                description="Two or more versions of the offer, answered by the same agents. Which wins, by how much, who flipped and why."
                tags={["Lift with CI", "Who flipped", "By segment"]}
                runs={experiments.length}
                onClick={() => openExperiment(null)}
              />
            )}
          </div>

          {pastRuns.length > 0 && (
            <div className="mt-6">
              <button
                onClick={togglePast}
                aria-expanded={pastOpen}
                className="w-full flex items-center gap-2 py-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                <History className="w-3.5 h-3.5" />
                <span className="font-medium">Past runs</span>
                <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] tabular-nums">{pastRuns.length}</span>
                <ChevronDown className={`ml-auto w-3.5 h-3.5 transition-transform ${pastOpen ? "rotate-180" : ""}`} />
              </button>

              {pastOpen && (
                <div className="rounded-xl border border-border/60 divide-y divide-border/40 overflow-hidden">
                  {pastRuns.map((r) => {
                    const id = r.kind === "probe" ? r.probe.id : r.experiment.id;
                    const status = r.kind === "probe" ? r.probe.status : r.experiment.status;
                    return (
                      <PastRunRow
                        key={id}
                        icon={r.kind === "probe" ? iconFor(r.probe.instrument) : EXPERIMENT_ICON}
                        title={
                          r.kind === "probe"
                            ? instruments.find((i) => i.key === r.probe.instrument)?.label || r.probe.instrument
                            : `A/B test${r.experiment.name ? ` · ${r.experiment.name}` : ""}`
                        }
                        summary={r.kind === "probe" ? r.probe.aggregates?.sentence || "" : r.experiment.results?.verdict || ""}
                        meta={
                          r.kind === "probe"
                            ? `${r.probe.answer_count}/${r.probe.agent_count}`
                            : r.experiment.variants.map((v) => v.label || v.key).join(" vs ")
                        }
                        when={ago(r.at)}
                        status={status}
                        confirming={confirming === id}
                        deleting={deleting === id}
                        onOpen={() => (r.kind === "probe" ? select(r.probe) : openExperiment(r.experiment))}
                        onAskDelete={() => setConfirming(id)}
                        onCancelDelete={() => setConfirming(null)}
                        onDelete={() => remove(r)}
                      />
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    );
  }

  const Page = pageFor(instrument.page || instrument.key);
  const Form = formFor(instrument.form);

  // ── One tool ──────────────────────────────────────────────────────────────
  return (
    <div className="h-full flex min-h-0">
      <div className="w-[340px] shrink-0 border-r border-border/60 overflow-y-auto p-4 space-y-4">
        <button
          onClick={() => { setInstrumentKey(""); setSelected(null); }}
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground -ml-1"
        >
          <ChevronLeft className="w-3.5 h-3.5" /> All tools
        </button>

        <div>
          <div className="text-sm font-medium">{instrument.label}</div>
          <p className="text-[11px] text-muted-foreground mt-0.5">{instrument.description}</p>
        </div>

        {/* The tool's own inputs, from its own declaration (or its own builder). */}
        <Form
          instrument={instrument}
          values={values}
          onChange={(k, v) => setValues((prev) => ({ ...prev, [k]: v }))}
        />

        <div>
          <label className="text-xs text-muted-foreground block mb-1.5">Who answers</label>
          <div className="space-y-2">
            {[...SEGMENT_FILTERS, ...dynamicFilters(dynamicDials)].map((f) => (
              <select
                key={f.key}
                value={filters[f.key] || ""}
                onChange={(e) => setFilters((prev) => ({ ...prev, [f.key]: e.target.value }))}
                title={(f as { title?: string }).title}
                className="w-full bg-input border border-border rounded-lg px-3 py-2 text-xs"
              >
                <option value="">{f.label}: everyone</option>
                {f.options.map((o) => <option key={o} value={o}>{f.label}: {o}</option>)}
              </select>
            ))}
          </div>
        </div>

        <div>
          <label className="text-xs text-muted-foreground block mb-1.5">Model</label>
          <div className="flex gap-2">
            {(["fast", "pro"] as SimMode[]).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`flex-1 text-xs py-1.5 rounded-lg border transition-colors ${mode === m ? "border-primary text-primary bg-primary/10" : "border-border text-muted-foreground hover:text-foreground"}`}
              >
                {m === "fast" ? "Fast" : "Pro"}
              </button>
            ))}
          </div>
        </div>

        {estimate && (
          // The model comes from the backend's resolved config, not the tier label — and the
          // cost follows the real model.
          <p className="text-[11px] text-muted-foreground">
            {estimate.agent_count} agent{estimate.agent_count === 1 ? "" : "s"} will answer · about ${estimate.estimated_cost_usd.toFixed(2)}
            <br />
            <span className="opacity-70">{estimate.model}</span>
          </p>
        )}

        {error && (
          <div className="flex gap-2 text-[11px] text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        <button
          onClick={run}
          disabled={busy || !agents.length || !!running}
          className="w-full flex items-center justify-center gap-2 bg-primary hover:bg-primary/90 disabled:opacity-40 text-primary-foreground text-sm font-medium px-4 py-2.5 rounded-lg transition-all"
        >
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
          Run {instrument.label.toLowerCase()}
        </button>
        {!agents.length && (
          <p className="text-[11px] text-muted-foreground">Spawn a population first — the Lab measures the agents in this session.</p>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-5 min-h-0">
        {!selected && (
          <div className="h-full flex flex-col items-center justify-center text-center text-muted-foreground gap-2">
            <Beaker className="w-8 h-8 opacity-30" />
            <p className="text-sm">{instrument.question}</p>
            <p className="text-xs max-w-sm opacity-70">
              Each agent answers in character — from its own background, its dials and what it already argued in the thread.
            </p>
          </div>
        )}

        {selected && (
          <div className="space-y-5 max-w-3xl">
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">{instrument.label}</div>
                <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
                  {instrument.inputs.map((f) => selected.spec?.[f.key]).filter((v) => typeof v === "string" && v).join(" · ")}
                </p>
              </div>
              {running ? (
                <button
                  onClick={() => api.lab.stop(sessionId, selected.id).catch((e) => setError(e.message))}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-border text-muted-foreground hover:text-foreground"
                >
                  <Square className="w-3 h-3" /> Stop
                </button>
              ) : (
                <div className="flex gap-2">
                  <button onClick={() => select(selected)} className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-border text-muted-foreground hover:text-foreground">
                    <RefreshCw className="w-3 h-3" /> Refresh
                  </button>
                  <button
                    onClick={() => api.lab.downloadCsv(sessionId, selected.id, `${selected.instrument}_${selected.id.slice(0, 8)}.csv`).catch((e) => setError(e.message))}
                    className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-border text-muted-foreground hover:text-foreground"
                  >
                    <Download className="w-3 h-3" /> CSV
                  </button>
                </div>
              )}
            </div>

            {running && (
              <div className="space-y-2">
                <div className="text-xs text-muted-foreground">
                  {live.length} of {selected.agent_count || agents.length} answered
                </div>
                <DotGrid
                  total={selected.agent_count || agents.length}
                  dots={live.map((x) => ({
                    color: dotColor(x.answer, x.avatar_color),
                    title: `${x.agent_name}: ${x.answer?.reasoning ?? ""}`,
                  }))}
                />
                {live.slice(-3).reverse().map((x) => (
                  <p key={x.agent_id} className="text-[11px] text-muted-foreground truncate flex items-center gap-1.5">
                    <span className="text-foreground/80">{x.agent_name}</span>
                    <ConfidenceBadge validation={agentsById[x.agent_id]?.validation} size="xs" />
                    <span className="truncate">— {x.answer?.reasoning}</span>
                  </p>
                ))}
              </div>
            )}

            {selected.error && (
              <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">{selected.error}</div>
            )}

            {/* The tool's own results page. */}
            {selected.aggregates && selected.aggregates.n > 0 && (
              <>
                <Page instrument={instrument} probe={selected} dynamicDials={dynamicDials} agentsById={agentsById} />
                <p className="text-[10px] text-muted-foreground/70">
                  {selected.answer_count} answered
                  {selected.failed_count ? `, ${selected.failed_count} failed and are excluded from every number above` : ""} ·
                  model {selected.model} · seed {selected.seed} · schema {selected.schema_id}
                </p>
                {selected.aggregates.weighted && selected.aggregates.weighted.weighted !== null && (
                  <p className="text-[11px] text-foreground/85 bg-muted/30 border border-border/60 rounded-lg px-3 py-2">
                    <span className="font-medium">Weighted to the sampling frame:</span> {selected.aggregates.weighted.label}{" "}
                    <span className="font-semibold text-primary tabular-nums">
                      {selected.aggregates.weighted.format === "share" ? `${Math.round((selected.aggregates.weighted.weighted || 0) * 100)}%` : selected.aggregates.weighted.weighted}
                    </span>{" "}
                    <span className="text-muted-foreground">
                      (one agent one vote: {selected.aggregates.weighted.format === "share" ? `${Math.round((selected.aggregates.weighted.unweighted || 0) * 100)}%` : selected.aggregates.weighted.unweighted} · effective n {selected.aggregates.weighted.ess} of {selected.aggregates.weighted.n})
                    </span>
                  </p>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Picker pieces ─────────────────────────────────────────────────────────────

function ToolCard({ icon: Icon, label, description, tags, runs, onClick }: {
  icon: LucideIcon; label: string; description: string; tags: string[]; runs: number; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="group text-left flex flex-col rounded-xl border border-border/60 bg-card/40 hover:border-primary/50 hover:bg-card/70 transition-colors p-4"
    >
      <div className="flex items-center gap-2.5">
        <span className="w-8 h-8 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0">
          <Icon className="w-4 h-4" />
        </span>
        <span className="text-sm font-medium text-foreground">{label}</span>
      </div>
      <p className="text-xs text-muted-foreground mt-2.5 leading-relaxed">{description}</p>
      <div className="flex flex-wrap gap-1 mt-2.5">
        {tags.map((t) => (
          <span key={t} className="text-[10px] text-primary/80 bg-primary/10 rounded px-1.5 py-0.5">{t}</span>
        ))}
      </div>
      <div className="mt-auto pt-3 flex items-center justify-between text-[11px] text-muted-foreground">
        <span className="tabular-nums">{runs === 0 ? "No runs yet" : `${runs} run${runs === 1 ? "" : "s"}`}</span>
        <span className="flex items-center gap-0.5 text-primary opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100 transition-opacity">
          Open <ChevronRight className="w-3 h-3" />
        </span>
      </div>
    </button>
  );
}

const STATUS_PILL: Record<string, string> = {
  queued: "text-amber-300 bg-amber-500/10",
  running: "text-amber-300 bg-amber-500/10",
  failed: "text-red-400 bg-red-500/10",
  stopped: "text-muted-foreground bg-muted",
};

function PastRunRow({
  icon: Icon, title, summary, meta, when, status, confirming, deleting,
  onOpen, onAskDelete, onCancelDelete, onDelete,
}: {
  icon: LucideIcon; title: string; summary: string; meta: string; when: string; status: string;
  confirming: boolean; deleting: boolean;
  onOpen: () => void; onAskDelete: () => void; onCancelDelete: () => void; onDelete: () => void;
}) {
  const running = status === "queued" || status === "running";
  return (
    <div className={`group flex items-center gap-3 px-3 py-2 transition-colors ${confirming ? "bg-red-500/5" : "hover:bg-muted/60"}`}>
      <button onClick={onOpen} className="flex-1 min-w-0 flex items-center gap-3 text-left">
        <Icon className="w-3.5 h-3.5 text-primary/70 shrink-0" />
        <span className="min-w-0 flex-1">
          <span className="block text-[11px] text-foreground/90 truncate">
            <span className="font-medium">{title}</span>
            {summary && <span className="text-muted-foreground"> · {summary}</span>}
          </span>
          <span className="block text-[10px] text-muted-foreground tabular-nums truncate">
            {meta}{when ? ` · ${when}` : ""}
          </span>
        </span>
      </button>

      {STATUS_PILL[status] && (
        <span className={`text-[10px] rounded px-1.5 py-0.5 shrink-0 ${STATUS_PILL[status]}`}>{status}</span>
      )}

      {confirming ? (
        <span className="flex items-center gap-1.5 shrink-0 text-[11px]">
          <span className="text-muted-foreground hidden sm:inline">Delete this run?</span>
          <button
            onClick={onDelete}
            disabled={deleting}
            className="flex items-center gap-1 rounded-md bg-red-500/15 text-red-300 hover:bg-red-500/25 px-2 py-1 disabled:opacity-50"
          >
            {deleting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />} Delete
          </button>
          <button onClick={onCancelDelete} disabled={deleting} className="rounded-md border border-border px-2 py-1 text-muted-foreground hover:text-foreground">
            Keep
          </button>
        </span>
      ) : (
        !running && (
          <button
            onClick={onAskDelete}
            title="Delete this run"
            aria-label="Delete this run"
            className="shrink-0 rounded-md p-1.5 text-muted-foreground/50 hover:text-red-400 hover:bg-red-500/10 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        )
      )}
    </div>
  );
}
