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
import { api, Agent, Experiment, Instrument, Probe, ProbeAnswerRow, ProbeRequest, SimMode } from "@/lib/api";
import { Beaker, Download, Loader2, Play, Square, AlertTriangle, RefreshCw, ChevronLeft, FlaskConical } from "lucide-react";
import { DotGrid, dotColor } from "./Charts";
import ExperimentPanel from "./ExperimentPanel";
import InstrumentForm, { initialValues, toSpec } from "./InstrumentForm";
import { SEGMENT_FILTERS } from "./filters";
import { pageFor } from "./pages";

type LiveAnswer = { agent_id: string; agent_name: string; avatar_color: string; answer: Record<string, any> };

interface Props {
  sessionId: string;
  sessionQuery: string;
  agents: Agent[];
  liveAnswers: Record<string, LiveAnswer[]>;
  completedAt: number;
  experimentCompletedAt: number;
  onClearLive: (probeId: string) => void;
}

type PastRun =
  | { kind: "probe"; at: string; probe: Probe }
  | { kind: "experiment"; at: string; experiment: Experiment };

export default function LabPanel({ sessionId, sessionQuery, agents, liveAnswers, completedAt, experimentCompletedAt, onClearLive }: Props) {
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
  const selectedId = useRef<string | null>(null);
  selectedId.current = selected?.id || null;

  const instrument = useMemo(() => instruments.find((i) => i.key === instrumentKey), [instruments, instrumentKey]);
  const canExperiment = useMemo(() => instruments.some((i) => i.supports_experiments), [instruments]);

  useEffect(() => {
    api.lab.instruments()
      .then((r) => setInstruments(r.instruments))
      .catch((e) => setError(String(e.message || e)));
  }, []);

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
      if (full && full.status !== "queued" && full.status !== "running") { setSelected(full); onClearLive(full.id); }
    })();
  }, [completedAt, loadProbes, sessionId, onClearLive]);

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
    const missing = instrument.inputs.filter((f) => f.required && !String(values[f.key] ?? "").trim());
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
        onBack={() => { setExperimentOpen(false); setInitialExperiment(null); loadProbes(); }}
      />
    );
  }

  // ── Tool picker ───────────────────────────────────────────────────────────
  if (!instrument) {
    return (
      <div className="h-full overflow-y-auto p-6">
        <div className="max-w-3xl">
          <div className="flex items-center gap-2 mb-1">
            <Beaker className="w-4 h-4 text-primary" />
            <h2 className="text-sm font-medium">Behaviour Lab</h2>
          </div>
          <p className="text-xs text-muted-foreground mb-5">
            Ask this population a structured question once, and every number that follows is computed
            from their answers. Each tool has its own inputs and its own results.
          </p>

          {error && (
            <div className="flex gap-2 text-[11px] text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2 mb-4">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            {instruments.filter((i) => !i.hidden).map((i) => (
              <button
                key={i.key}
                onClick={() => chooseInstrument(i)}
                className="text-left rounded-xl border border-border/60 bg-card/40 hover:border-primary/50 hover:bg-card/70 transition-colors p-4"
              >
                <div className="text-sm font-medium text-foreground">{i.label}</div>
                <p className="text-xs text-muted-foreground mt-1 leading-relaxed">{i.description}</p>
                <div className="flex flex-wrap gap-1 mt-2.5">
                  {i.kpis.slice(0, 3).map((k) => (
                    <span key={k.key} className="text-[10px] text-primary/80 bg-primary/10 rounded px-1.5 py-0.5">
                      {k.label}
                    </span>
                  ))}
                </div>
              </button>
            ))}

            {canExperiment && (
              <button
                onClick={() => openExperiment(null)}
                className="text-left rounded-xl border border-border/60 bg-card/40 hover:border-primary/50 hover:bg-card/70 transition-colors p-4"
              >
                <div className="flex items-center gap-1.5 text-sm font-medium text-foreground">
                  <FlaskConical className="w-3.5 h-3.5 text-primary" /> A/B test
                </div>
                <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
                  Two or more versions of the offer, answered by the same agents. Which wins, by how much, who flipped and why.
                </p>
                <div className="flex flex-wrap gap-1 mt-2.5">
                  {["Lift with CI", "Who flipped", "By segment"].map((t) => (
                    <span key={t} className="text-[10px] text-primary/80 bg-primary/10 rounded px-1.5 py-0.5">{t}</span>
                  ))}
                </div>
              </button>
            )}
          </div>

          {pastRuns.length > 0 && (
            <div className="mt-7">
              <div className="text-xs text-muted-foreground mb-2">Past runs</div>
              <div className="space-y-1">
                {pastRuns.map((r) =>
                  r.kind === "probe" ? (
                    <button
                      key={r.probe.id}
                      onClick={() => select(r.probe)}
                      className="w-full text-left px-3 py-2 rounded-lg text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground transition-colors flex justify-between gap-3"
                    >
                      <span className="truncate">
                        <span className="text-foreground/80">{instruments.find((i) => i.key === r.probe.instrument)?.label || r.probe.instrument}</span>
                        {" · "}{r.probe.aggregates?.sentence || r.probe.status}
                      </span>
                      <span className="tabular-nums shrink-0">{r.probe.answer_count}/{r.probe.agent_count}</span>
                    </button>
                  ) : (
                    <button
                      key={r.experiment.id}
                      onClick={() => openExperiment(r.experiment)}
                      className="w-full text-left px-3 py-2 rounded-lg text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground transition-colors flex justify-between gap-3"
                    >
                      <span className="truncate">
                        <span className="text-foreground/80">A/B test{r.experiment.name ? ` · ${r.experiment.name}` : ""}</span>
                        {" · "}{r.experiment.results?.verdict || r.experiment.status}
                      </span>
                      <span className="tabular-nums shrink-0">{r.experiment.variants.map((v) => v.label || v.key).join(" vs ")}</span>
                    </button>
                  )
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  const Page = pageFor(instrument.page || instrument.key);

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

        {/* The tool's own inputs, from its own declaration. */}
        <InstrumentForm
          instrument={instrument}
          values={values}
          onChange={(k, v) => setValues((prev) => ({ ...prev, [k]: v }))}
        />

        <div>
          <label className="text-xs text-muted-foreground block mb-1.5">Who answers</label>
          <div className="space-y-2">
            {SEGMENT_FILTERS.map((f) => (
              <select
                key={f.key}
                value={filters[f.key] || ""}
                onChange={(e) => setFilters((prev) => ({ ...prev, [f.key]: e.target.value }))}
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
                  {instrument.inputs.map((f) => selected.spec?.[f.key]).filter(Boolean).join(" · ")}
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
                  <p key={x.agent_id} className="text-[11px] text-muted-foreground truncate">
                    <span className="text-foreground/80">{x.agent_name}</span> — {x.answer?.reasoning}
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
                <Page instrument={instrument} probe={selected} />
                <p className="text-[10px] text-muted-foreground/70">
                  {selected.answer_count} answered
                  {selected.failed_count ? `, ${selected.failed_count} failed and are excluded from every number above` : ""} ·
                  model {selected.model} · seed {selected.seed} · schema {selected.schema_id}
                </p>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
