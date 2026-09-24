"use client";

/** The A/B test tool.
 *
 *  An experiment is one instrument run once per variant. This panel lets the analyst pick
 *  the base tool, write each variant with that tool's own input form, choose the design,
 *  price the run, watch every arm fill in, and read the comparison. It is generic over
 *  instruments: the form comes from the instrument's declaration and the results page reads
 *  the comparison the backend computed — nothing here knows about purchase intent. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api, Agent, Experiment, ExperimentDesign, ExperimentEstimate, ExperimentRequest, Instrument, SimMode, DynamicDial } from "@/lib/api";
import { AlertTriangle, ChevronLeft, Download, FlaskConical, Loader2, Play, Plus, RefreshCw, Square, X } from "lucide-react";
import { PairedDots, DotGrid, optionColor } from "./Charts";
import InstrumentForm, { initialValues, toSpec } from "./InstrumentForm";
import { SEGMENT_FILTERS, dynamicFilters } from "./filters";
import ExperimentPage from "./pages/ExperimentPage";

type LiveAnswer = { agent_id: string; agent_name: string; avatar_color: string; answer: Record<string, any> };
type VariantDraft = { key: string; label: string; values: Record<string, any> };

interface Props {
  sessionId: string;
  sessionQuery: string;
  agents: Agent[];
  instruments: Instrument[];
  liveAnswers: Record<string, LiveAnswer[]>;
  completedAt: number;
  onClearLive: (probeId: string) => void;
  initial: Experiment | null;
  onBack: () => void;
  /** The question's own dials (brief L3-04): extra "who answers" filters and split headings. */
  dynamicDials?: DynamicDial[];
}

const KEYS = ["A", "B", "C", "D", "E", "F"];
const MAX_VARIANTS = 6;

const DESIGNS: { key: ExperimentDesign; label: string; help: string }[] = [
  { key: "within", label: "Rate each", help: "Every agent answers every variant separately, with no memory of the other. Paired lift, who flipped and why. Best for 'does B land better than A'." },
  { key: "choice", label: "Choose between", help: "Every agent sees all the options at once and picks a winner and a runner-up. One call per agent. Best for 'which is best'." },
  { key: "between", label: "Split population", help: "The population is split by seed; each agent sees one variant. Use when the variants would contaminate each other." },
];

export default function ExperimentPanel({
  sessionId, sessionQuery, agents, instruments, liveAnswers, completedAt, onClearLive, initial, onBack,
  dynamicDials = [],
}: Props) {
  // Any tool that declares metrics, hidden or not: Ask left the picker when the survey arrived
  // but is still the right base for a text-material A/B ("Reaction").
  const testable = useMemo(() => instruments.filter((i) => i.supports_experiments), [instruments]);
  const [baseKey, setBaseKey] = useState<string>(initial?.instrument || testable[0]?.key || "");
  const base = useMemo(() => testable.find((i) => i.key === baseKey), [testable, baseKey]);
  const [design, setDesign] = useState<ExperimentDesign>(initial?.design || "within");
  const [name, setName] = useState(initial?.name || "");
  const [question, setQuestion] = useState(initial?.probes?.[0]?.spec?.question || "");
  const [variants, setVariants] = useState<VariantDraft[]>([]);
  const [mode, setMode] = useState<SimMode>("fast");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [estimate, setEstimate] = useState<ExperimentEstimate | null>(null);
  const [selected, setSelected] = useState<Experiment | null>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selectedId = useRef<string | null>(initial?.id || null);
  selectedId.current = selected?.id || null;
  const clearLive = useRef(onClearLive);
  clearLive.current = onClearLive;

  // Two variants to start, both prefilled from the session so the analyst edits the difference.
  useEffect(() => {
    if (!base) return;
    if (initial && initial.instrument === base.key && initial.variants.length) {
      setVariants(initial.variants.map((v) => ({ key: v.key, label: v.label, values: { ...initialValues(base, { session_query: sessionQuery }), ...v.spec } })));
      return;
    }
    const seed = initialValues(base, { session_query: sessionQuery });
    setVariants([
      { key: "A", label: "A", values: { ...seed } },
      { key: "B", label: "B", values: { ...seed } },
    ]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base?.key]);

  // A past run opened from the picker: show it, and load its arms.
  useEffect(() => {
    if (!initial) return;
    api.lab.experiment(sessionId, initial.id).then(setSelected).catch(() => undefined);
  }, [initial, sessionId]);

  const buildRequest = useCallback((): ExperimentRequest | null => {
    if (!base) return null;
    const segments: Record<string, string> = {};
    for (const [k, v] of Object.entries(filters)) if (v) segments[k] = v;
    return {
      instrument: base.key,
      design,
      name: name.trim() || undefined,
      ...(design === "choice" && question.trim() ? { question: question.trim() } : {}),
      mode,
      variants: variants.map((v) => ({ key: v.key, label: v.label.trim() || v.key, spec: toSpec(base, v.values) })),
      ...(Object.keys(segments).length ? { agent_filter: { segments } } : {}),
    };
  }, [base, design, name, question, mode, variants, filters]);

  useEffect(() => {
    const req = buildRequest();
    if (!agents.length || !req || req.variants.length < 2) return;
    const t = setTimeout(() => {
      api.lab.estimateExperiment(sessionId, req).then(setEstimate).catch(() => setEstimate(null));
    }, 250);
    return () => clearTimeout(t);
  }, [agents.length, sessionId, buildRequest]);

  // The backend says the comparison is stored: fetch the finished experiment and stop streaming.
  useEffect(() => {
    if (!completedAt || !selectedId.current) return;
    const id = selectedId.current;
    api.lab.experiment(sessionId, id).then((full) => {
      setSelected(full);
      for (const p of full.probes || []) clearLive.current(p.id);
    }).catch(() => undefined);
  }, [completedAt, sessionId]);

  function updateVariant(i: number, patch: Partial<VariantDraft>) {
    setVariants((prev) => prev.map((v, j) => (j === i ? { ...v, ...patch } : v)));
  }

  function addVariant() {
    setVariants((prev) => {
      if (prev.length >= MAX_VARIANTS) return prev;
      const key = KEYS.find((k) => !prev.some((v) => v.key === k)) || `V${prev.length + 1}`;
      const last = prev[prev.length - 1];
      return [...prev, { key, label: key, values: { ...(last?.values || {}) } }];
    });
  }

  function removeVariant(i: number) {
    setVariants((prev) => (prev.length <= 2 ? prev : prev.filter((_, j) => j !== i)));
  }

  async function run() {
    const req = buildRequest();
    if (!base || !req) return;
    for (const v of variants) {
      const missing = base.inputs.filter((f) => f.required && !(design === "choice" && f.key === base.question_from) && !String(v.values[f.key] ?? "").trim());
      if (missing.length) { setError(`Variant ${v.label || v.key}: ${missing.map((f) => f.label).join(", ")} required.`); return; }
    }
    setBusy(true); setError(null);
    try {
      const e = await api.lab.runExperiment(sessionId, req);
      setSelected(e);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  }

  async function refresh() {
    if (!selected) return;
    const full = await api.lab.experiment(sessionId, selected.id).catch(() => null);
    if (full) setSelected(full);
  }

  const running = selected && (selected.status === "queued" || selected.status === "running");
  const selectedInstrument = selected ? instruments.find((i) => i.key === selected.instrument) : undefined;

  return (
    <div className="h-full flex min-h-0">
      <div className="w-[380px] shrink-0 border-r border-border/60 overflow-y-auto p-4 space-y-4">
        <button onClick={onBack} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground -ml-1">
          <ChevronLeft className="w-3.5 h-3.5" /> All tools
        </button>

        <div>
          <div className="flex items-center gap-1.5 text-sm font-medium"><FlaskConical className="w-3.5 h-3.5 text-primary" /> A/B test</div>
          <p className="text-[11px] text-muted-foreground mt-0.5">
            The same question, two or more versions of the offer. Lift with an interval, who flipped and why, and where the effect holds.
          </p>
        </div>

        {testable.length === 0 && (
          <p className="text-[11px] text-muted-foreground">No instrument declares metrics to compare yet.</p>
        )}

        {testable.length > 1 && (
          <div>
            <label className="text-xs text-muted-foreground block mb-1.5">Measure with</label>
            <select value={baseKey} onChange={(e) => setBaseKey(e.target.value)} className="w-full bg-input border border-border rounded-lg px-3 py-2 text-xs">
              {testable.map((i) => <option key={i.key} value={i.key}>{i.label}</option>)}
            </select>
          </div>
        )}

        <div>
          <label className="text-xs text-muted-foreground block mb-1.5">Name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Price test: £12 vs £8"
            className="w-full bg-input border border-border rounded-lg px-3 py-2 text-xs" />
        </div>

        <div>
          <label className="text-xs text-muted-foreground block mb-1.5">Design</label>
          <div className="flex gap-2">
            {DESIGNS.map((d) => (
              <button key={d.key} onClick={() => setDesign(d.key)} title={d.help}
                className={`flex-1 text-xs py-1.5 rounded-lg border transition-colors ${design === d.key ? "border-primary text-primary bg-primary/10" : "border-border text-muted-foreground hover:text-foreground"}`}>
                {d.label}
              </button>
            ))}
          </div>
          <p className="text-[10px] text-muted-foreground/70 mt-1">{DESIGNS.find((d) => d.key === design)?.help}</p>
        </div>

        {base && variants.map((v, i) => (
          <div key={v.key} className="rounded-xl border border-border/60 bg-card/30 p-3 space-y-3">
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-medium rounded px-1.5 py-0.5 bg-primary/10 text-primary">{v.key}</span>
              <input value={v.label} onChange={(e) => updateVariant(i, { label: e.target.value })}
                placeholder={i === 0 ? "Control" : `Variant ${v.key}`}
                className="flex-1 bg-transparent border-b border-border/60 focus:border-primary/60 focus:outline-none text-xs py-1" />
              <span className="text-[10px] text-muted-foreground">{i === 0 ? "control" : ""}</span>
              {variants.length > 2 && (
                <button onClick={() => removeVariant(i)} className="text-muted-foreground hover:text-foreground" title="Remove variant">
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
            <InstrumentForm
              instrument={design === "choice" && base.question_from ? { ...base, inputs: base.inputs.filter((f) => f.key !== base.question_from) } : base}
              values={v.values}
              onChange={(k, val) => updateVariant(i, { values: { ...v.values, [k]: val } })}
            />
          </div>
        ))}

        {base && variants.length < MAX_VARIANTS && (
          <button onClick={addVariant} className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground">
            <Plus className="w-3.5 h-3.5" /> Add {design === "choice" ? "an option" : "a variant"}
          </button>
        )}

        {base && design === "choice" && (
          <div>
            <label className="text-xs text-muted-foreground block mb-1.5">The question, asked once with all options shown</label>
            <textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={2}
              placeholder={base.question}
              className="w-full bg-input border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary/50 resize-y" />
            {(base.inputs.find((f) => f.key === base.question_from)?.suggestions || []).length > 0 && (
              <div className="flex flex-wrap gap-1 mt-1.5">
                {["Which of these would you go for, and which is your second choice?", ...(base.inputs.find((f) => f.key === base.question_from)?.suggestions || [])].map((sug) => (
                  <button key={sug} type="button" onClick={() => setQuestion(sug)}
                    className={`text-[10px] rounded px-1.5 py-0.5 border transition-colors ${question === sug ? "border-primary/60 text-primary bg-primary/10" : "border-border/60 text-muted-foreground hover:text-foreground"}`}>
                    {sug}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        <div>
          <label className="text-xs text-muted-foreground block mb-1.5">Who answers</label>
          <div className="space-y-2">
            {[...SEGMENT_FILTERS, ...dynamicFilters(dynamicDials)].map((f) => (
              <select key={f.key} value={filters[f.key] || ""} onChange={(e) => setFilters((prev) => ({ ...prev, [f.key]: e.target.value }))}
                title={(f as { title?: string }).title}
                className="w-full bg-input border border-border rounded-lg px-3 py-2 text-xs">
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
              <button key={m} onClick={() => setMode(m)}
                className={`flex-1 text-xs py-1.5 rounded-lg border transition-colors ${mode === m ? "border-primary text-primary bg-primary/10" : "border-border text-muted-foreground hover:text-foreground"}`}>
                {m === "fast" ? "Fast" : "Pro"}
              </button>
            ))}
          </div>
        </div>

        {estimate && (
          <p className="text-[11px] text-muted-foreground">
            {estimate.agent_count} agent{estimate.agent_count === 1 ? "" : "s"} × {design === "within" ? `${estimate.variants} variants` : design === "choice" ? "1 choice each" : "1 variant each"} = {estimate.calls} answers · about ${estimate.estimated_cost_usd.toFixed(2)}
            <br /><span className="opacity-70">{estimate.model}</span>
          </p>
        )}

        {error && (
          <div className="flex gap-2 text-[11px] text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" /><span>{error}</span>
          </div>
        )}

        <button onClick={run} disabled={busy || !agents.length || !!running || !base}
          className="w-full flex items-center justify-center gap-2 bg-primary hover:bg-primary/90 disabled:opacity-40 text-primary-foreground text-sm font-medium px-4 py-2.5 rounded-lg transition-all">
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
          {design === "choice" ? "Ask them to choose" : "Run A/B test"}
        </button>
        {!agents.length && (
          <p className="text-[11px] text-muted-foreground">Spawn a population first — the Lab measures the agents in this session.</p>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-5 min-h-0">
        {!selected && (
          <div className="h-full flex flex-col items-center justify-center text-center text-muted-foreground gap-2">
            <FlaskConical className="w-8 h-8 opacity-30" />
            <p className="text-sm">{base?.question}</p>
            <p className="text-xs max-w-sm opacity-70">
              Each agent answers every variant separately, with no memory of what it said to the other — the lift is what changed.
            </p>
          </div>
        )}

        {selected && (
          <div className="space-y-5 max-w-3xl">
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">{selected.name || "A/B test"}</div>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {selectedInstrument?.label || selected.instrument} · {selected.variants.map((v) => v.label || v.key).join(" vs ")} · {selected.design === "within" ? "same agents" : selected.design === "choice" ? "chose between" : "split population"}
                </p>
              </div>
              {running ? (
                <button onClick={() => api.lab.stopExperiment(sessionId, selected.id).catch((e) => setError(e.message))}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-border text-muted-foreground hover:text-foreground">
                  <Square className="w-3 h-3" /> Stop
                </button>
              ) : (
                <div className="flex gap-2">
                  <button onClick={refresh} className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-border text-muted-foreground hover:text-foreground">
                    <RefreshCw className="w-3 h-3" /> Refresh
                  </button>
                  <button onClick={() => api.lab.downloadExperimentCsv(sessionId, selected.id, `experiment_${selected.instrument}_${selected.id.slice(0, 8)}.csv`).catch((e) => setError(e.message))}
                    className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-border text-muted-foreground hover:text-foreground">
                    <Download className="w-3 h-3" /> CSV
                  </button>
                </div>
              )}
            </div>

            {running && (
              <LiveComparison
                experiment={selected}
                instrument={selectedInstrument}
                liveAnswers={liveAnswers}
                fallbackTotal={agents.length}
              />
            )}

            {selected.error && (
              <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">{selected.error}</div>
            )}

            {selected.results && selectedInstrument && (
              <>
                <ExperimentPage instrument={selectedInstrument} experiment={selected} />
                <p className="text-[10px] text-muted-foreground/70">
                  {selected.results.arms.map((a) => `${a.label}: ${a.n} answered`).join(" · ")} · model {selected.model} · seed {selected.seed} · {selected.design === "choice" ? "choose between" : `${selected.design}-subjects`}
                  {selected.status === "stopped" ? " · stopped early — only the answers collected are compared" : ""}
                </p>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}


/** The live view of an experiment. Not two dot grids side by side — one pill per agent, split
 *  per arm, so what fills in is each person's pair of answers, and a ring marks the ones who
 *  have already changed their mind. The counters are the comparison forming in real time. */
function LiveComparison({
  experiment, instrument, liveAnswers, fallbackTotal,
}: {
  experiment: Experiment;
  instrument: Instrument | undefined;
  liveAnswers: Record<string, LiveAnswer[]>;
  fallbackTotal: number;
}) {
  const arms = experiment.variants.map((v) => v.key);
  const decision = instrument?.decision_key || "";
  const probeFor: Record<string, string> = {};
  for (const p of experiment.probes || []) if (p.variant_key) probeFor[p.variant_key] = p.id;

  if (experiment.design === "choice") {
    const probe = (experiment.probes || [])[0];
    const rows = probe ? liveAnswers[probe.id] || [] : [];
    const total = probe?.agent_count || experiment.agent_count || fallbackTotal;
    const counts: Record<string, number> = {};
    for (const r of rows) counts[String(r.answer?.choice)] = (counts[String(r.answer?.choice)] || 0) + 1;
    return (
      <div className="rounded-xl border border-border/60 bg-card/40 p-4 space-y-4">
        <div className="flex items-baseline justify-between">
          <span className="text-xs text-muted-foreground">{total} agents, each choosing between {arms.length} options</span>
          <span className="text-[10px] text-muted-foreground/70">one dot per agent, coloured by the option it chose</span>
        </div>
        <div className="grid gap-2 grid-cols-[repeat(auto-fit,minmax(7rem,1fr))]">
          {experiment.variants.map((v) => (
            <div key={v.key} className="rounded-lg bg-muted/40 px-3 py-2">
              <div className="text-[10px] truncate" style={{ color: optionColor(arms, v.key) }}>{v.key} · {v.label || v.key}</div>
              <div className="text-lg font-semibold tabular-nums">{counts[v.key] || 0}<span className="text-xs text-muted-foreground font-normal"> chose it</span></div>
            </div>
          ))}
          <div className="rounded-lg bg-muted/40 px-3 py-2">
            <div className="text-[10px] text-muted-foreground">Answered</div>
            <div className="text-lg font-semibold tabular-nums">{rows.length}<span className="text-xs text-muted-foreground font-normal"> / {total}</span></div>
          </div>
        </div>
        <DotGrid total={total} dots={rows.map((r) => ({ color: optionColor(arms, String(r.answer?.choice)), title: `${r.agent_name}: ${r.answer?.reasoning ?? ""}` }))} />
        {rows.slice(-2).reverse().map((r) => (
          <p key={r.agent_id} className="text-[11px] text-muted-foreground truncate">
            <span className="text-foreground/80">{r.agent_name}</span> chose {r.answer?.choice} — {r.answer?.reasoning}
          </p>
        ))}
      </div>
    );
  }

  const byAgent = new Map<string, { agent_id: string; name: string; fallback: string; answers: Record<string, Record<string, any> | undefined> }>();
  const answered: Record<string, number> = {};
  for (const k of arms) {
    const rows = liveAnswers[probeFor[k]] || [];
    answered[k] = rows.length;
    for (const r of rows) {
      const e = byAgent.get(r.agent_id) || { agent_id: r.agent_id, name: r.agent_name, fallback: r.avatar_color, answers: {} };
      e.answers[k] = r.answer;
      byAgent.set(r.agent_id, e);
    }
  }
  const within = experiment.design === "within";
  const total = within
    ? (experiment.probes?.[0]?.agent_count || experiment.agent_count || fallbackTotal)
    : (experiment.agent_count || fallbackTotal);

  const pills = Array.from(byAgent.values())
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((a) => {
      const complete = arms.every((k) => a.answers[k]);
      const decisions = decision ? arms.map((k) => a.answers[k]?.[decision]).filter((v) => v !== undefined) : [];
      const flipped = complete && decisions.length === arms.length && new Set(decisions.map(String)).size > 1;
      const title = [a.name, ...arms.map((k) => a.answers[k] ? `${experiment.variants.find((v) => v.key === k)?.label || k}: ${a.answers[k]?.reasoning ?? ""}` : "")].filter(Boolean).join("\n");
      return { ...a, flipped, title };
    });
  const paired = pills.filter((p) => arms.every((k) => p.answers[k])).length;
  const flipped = pills.filter((p) => p.flipped).length;
  // Room for the agents that have not answered any arm yet.
  const pending = Math.max(0, total - pills.length);
  const placeholders = Array.from({ length: within ? pending : 0 }, (_, i) => ({
    agent_id: `pending-${i}`, name: "", fallback: "", answers: {} as Record<string, Record<string, any> | undefined>, flipped: false, title: "waiting",
  }));

  return (
    <div className="rounded-xl border border-border/60 bg-card/40 p-4 space-y-4">
      <div className="flex items-baseline justify-between">
        <span className="text-xs text-muted-foreground">
          {within ? `The same ${total} agents, ${arms.length} offers` : `${total} agents split across ${arms.length} offers`}
        </span>
        <span className="text-[10px] text-muted-foreground/70">
          {within ? "one pill per agent · one segment per offer · ring = changed their answer" : "one segment per agent, coloured by its answer"}
        </span>
      </div>

      <div className={`grid gap-2 ${within ? "grid-cols-[repeat(auto-fit,minmax(7rem,1fr))]" : "grid-cols-[repeat(auto-fit,minmax(7rem,1fr))]"}`}>
        {arms.map((k) => (
          <div key={k} className="rounded-lg bg-muted/40 px-3 py-2">
            <div className="text-[10px] text-muted-foreground truncate">{experiment.variants.find((v) => v.key === k)?.label || k}</div>
            <div className="text-lg font-semibold tabular-nums">{answered[k] || 0}<span className="text-xs text-muted-foreground font-normal"> / {within ? total : "…"}</span></div>
          </div>
        ))}
        {within && (
          <>
            <div className="rounded-lg bg-muted/40 px-3 py-2">
              <div className="text-[10px] text-muted-foreground">Answered both</div>
              <div className="text-lg font-semibold tabular-nums">{paired}</div>
            </div>
            <div className="rounded-lg bg-amber-400/10 px-3 py-2">
              <div className="text-[10px] text-amber-200/80">Changed their answer</div>
              <div className="text-lg font-semibold tabular-nums text-amber-300">{flipped}<span className="text-xs text-muted-foreground font-normal"> of {paired}</span></div>
            </div>
          </>
        )}
      </div>

      <PairedDots agents={[...pills, ...placeholders]} arms={arms} />

      {pills.filter((p) => p.flipped).slice(-2).reverse().map((p) => (
        <p key={p.agent_id} className="text-[11px] text-muted-foreground truncate">
          <span className="text-amber-300">{p.name}</span> changed: {arms.map((k) => `${experiment.variants.find((v) => v.key === k)?.label || k} → ${p.answers[k]?.[decision]}`).join(" · ")}
        </p>
      ))}
    </div>
  );
}
