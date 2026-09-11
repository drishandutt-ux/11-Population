"use client";

/** The Lab tab: ask the population a structured question, watch the answers land, read the
 *  result with its error bars. The dial dashboard stays in the Agents tab as priors — what
 *  appears here is measured, not assigned. */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, Agent, Instrument, Probe, ProbeAnswerRow, ProbeRequest, SimMode } from "@/lib/api";
import { Beaker, Download, Loader2, Play, Square, AlertTriangle, RefreshCw } from "lucide-react";
import { CategoryBars, DemandCurve, DotGrid, MeanStat, SegmentTable, ShareBar, money, pct } from "./Charts";

type LiveAnswer = { agent_id: string; agent_name: string; avatar_color: string; answer: Record<string, any> };

interface Props {
  sessionId: string;
  agents: Agent[];
  /** Answers streamed over the session websocket, keyed by probe id. */
  liveAnswers: Record<string, LiveAnswer[]>;
  /** Bumped by the page when a probe_complete event arrives, so the panel refetches. */
  completedAt: number;
  onClearLive: (probeId: string) => void;
}

const SEGMENT_FILTERS: { key: string; label: string; options: string[] }[] = [
  { key: "stance", label: "Stance", options: ["direct", "indirect", "neutral"] },
  { key: "age_band", label: "Age", options: ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"] },
];

const ANSWER_COLORS: Record<string, string> = { yes: "hsl(var(--primary))", no: "#f87171", unsure: "#fbbf24" };

export default function LabPanel({ sessionId, agents, liveAnswers, completedAt, onClearLive }: Props) {
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [instrumentKey, setInstrumentKey] = useState<string>("purchase_intent");
  const [stimulus, setStimulus] = useState("");
  const [price, setPrice] = useState<string>("");
  const [currency, setCurrency] = useState("GBP");
  const [mode, setMode] = useState<SimMode>("fast");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [estimate, setEstimate] = useState<{ agent_count: number; estimated_cost_usd: number } | null>(null);
  const [probes, setProbes] = useState<Probe[]>([]);
  const [selected, setSelected] = useState<(Probe & { answers?: ProbeAnswerRow[] }) | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const instrument = useMemo(() => instruments.find((i) => i.key === instrumentKey), [instruments, instrumentKey]);

  const buildRequest = useCallback((): ProbeRequest => {
    const segments: Record<string, string> = {};
    for (const [k, v] of Object.entries(filters)) if (v) segments[k] = v;
    return {
      instrument: instrumentKey,
      mode,
      spec: {
        stimulus,
        price: price.trim() ? Number(price) : null,
        currency,
        ...(Object.keys(segments).length ? { agent_filter: { segments } } : {}),
      },
    };
  }, [instrumentKey, mode, stimulus, price, currency, filters]);

  useEffect(() => {
    api.lab.instruments().then((r) => setInstruments(r.instruments)).catch((e) => setError(String(e.message || e)));
  }, []);

  const loadProbes = useCallback(async () => {
    try {
      const r = await api.lab.probes(sessionId);
      setProbes(r.probes);
      return r.probes;
    } catch (e: any) {
      setError(e?.message || String(e));
      return [];
    }
  }, [sessionId]);

  useEffect(() => { loadProbes(); }, [loadProbes]);

  // A probe finished: pull the stored aggregates and drop the live stream for it.
  useEffect(() => {
    if (!completedAt) return;
    (async () => {
      const list = await loadProbes();
      const latest = list[0];
      if (latest) {
        const full = await api.lab.probe(sessionId, latest.id).catch(() => null);
        if (full) {
          setSelected(full);
          onClearLive(full.id);
        }
      }
    })();
  }, [completedAt, loadProbes, sessionId, onClearLive]);

  // Cost before you run, refreshed as the filter changes.
  useEffect(() => {
    if (!agents.length) return;
    const t = setTimeout(() => {
      api.lab.estimate(sessionId, buildRequest()).then(setEstimate).catch(() => setEstimate(null));
    }, 250);
    return () => clearTimeout(t);
  }, [agents.length, sessionId, buildRequest]);

  async function run() {
    if (!stimulus.trim()) { setError("Describe what you want the population to react to."); return; }
    setBusy(true); setError(null);
    try {
      const p = await api.lab.run(sessionId, buildRequest());
      setSelected(p);
      setProbes((prev) => [p, ...prev]);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  }

  async function stop(probeId: string) {
    try { await api.lab.stop(sessionId, probeId); } catch (e: any) { setError(e?.message || String(e)); }
  }

  async function select(p: Probe) {
    setSelected(p);
    const full = await api.lab.probe(sessionId, p.id).catch(() => null);
    if (full) setSelected(full);
  }

  const running = selected && (selected.status === "queued" || selected.status === "running");
  const live = selected ? liveAnswers[selected.id] || [] : [];

  return (
    <div className="h-full flex min-h-0">
      {/* ── Ask ───────────────────────────────────────────────────────────── */}
      <div className="w-[340px] shrink-0 border-r border-border/60 overflow-y-auto p-4 space-y-4">
        <div className="flex items-center gap-2">
          <Beaker className="w-4 h-4 text-primary" />
          <span className="text-sm font-medium">Ask the population</span>
        </div>

        <div>
          <label className="text-xs text-muted-foreground block mb-1.5">Instrument</label>
          <select
            value={instrumentKey}
            onChange={(e) => setInstrumentKey(e.target.value)}
            className="w-full bg-input border border-border rounded-lg px-3 py-2 text-sm"
          >
            {instruments.map((i) => (
              <option key={i.key} value={i.key}>{i.label}</option>
            ))}
          </select>
          {instrument && <p className="text-[11px] text-muted-foreground mt-1.5">{instrument.description}</p>}
        </div>

        <div>
          <label className="text-xs text-muted-foreground block mb-1.5">Stimulus</label>
          <textarea
            value={stimulus}
            onChange={(e) => setStimulus(e.target.value)}
            rows={6}
            placeholder={instrument?.stimulus_hint || "What are they reacting to?"}
            className="w-full bg-input border border-border rounded-lg px-3 py-2 text-sm resize-y"
          />
        </div>

        {instrument?.spec_fields.includes("price") && (
          <div className="flex gap-2">
            <div className="flex-1">
              <label className="text-xs text-muted-foreground block mb-1.5">Asking price</label>
              <input
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                inputMode="decimal"
                placeholder="12"
                className="w-full bg-input border border-border rounded-lg px-3 py-2 text-sm tabular-nums"
              />
            </div>
            <div className="w-24">
              <label className="text-xs text-muted-foreground block mb-1.5">Currency</label>
              <select value={currency} onChange={(e) => setCurrency(e.target.value)} className="w-full bg-input border border-border rounded-lg px-3 py-2 text-sm">
                <option>GBP</option><option>USD</option><option>EUR</option>
              </select>
            </div>
          </div>
        )}

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
                {m === "fast" ? "Fast (Haiku)" : "Pro (Sonnet)"}
              </button>
            ))}
          </div>
        </div>

        {estimate && (
          <p className="text-[11px] text-muted-foreground">
            {estimate.agent_count} agent{estimate.agent_count === 1 ? "" : "s"} will answer · about ${estimate.estimated_cost_usd.toFixed(2)}
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
          Run probe
        </button>
        {!agents.length && <p className="text-[11px] text-muted-foreground">Spawn a population first — the Lab measures the agents in this session.</p>}

        {probes.length > 0 && (
          <div className="pt-2 border-t border-border/60">
            <div className="text-xs text-muted-foreground mb-2">Past runs</div>
            <div className="space-y-1">
              {probes.map((p) => (
                <button
                  key={p.id}
                  onClick={() => select(p)}
                  className={`w-full text-left px-2.5 py-2 rounded-lg text-[11px] transition-colors ${selected?.id === p.id ? "bg-primary/10 text-primary" : "hover:bg-muted text-muted-foreground"}`}
                >
                  <div className="flex justify-between gap-2">
                    <span className="truncate">{p.spec?.stimulus?.slice(0, 40) || p.instrument}</span>
                    <span className="tabular-nums shrink-0">{p.answer_count}/{p.agent_count}</span>
                  </div>
                  <span className="opacity-60">{p.status}{p.spec?.price ? ` · ${money(p.spec.price, p.spec.currency)}` : ""}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── Results ───────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto p-5 min-h-0">
        {!selected && (
          <div className="h-full flex flex-col items-center justify-center text-center text-muted-foreground gap-2">
            <Beaker className="w-8 h-8 opacity-30" />
            <p className="text-sm">Ask this population a question and the answer comes back with an interval.</p>
            <p className="text-xs max-w-sm opacity-70">
              Each agent answers in character — from its own background, its dials and what it already argued in the thread.
            </p>
          </div>
        )}

        {selected && (
          <div className="space-y-5 max-w-3xl">
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">{instruments.find((i) => i.key === selected.instrument)?.label || selected.instrument}</div>
                <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{selected.spec?.stimulus}</p>
              </div>
              {running ? (
                <button onClick={() => stop(selected.id)} className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-border text-muted-foreground hover:text-foreground">
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
                  dots={live.map((a) => ({
                    color: ANSWER_COLORS[String(a.answer?.would_buy)] || a.avatar_color,
                    title: `${a.agent_name}: ${a.answer?.would_buy ?? ""} — ${a.answer?.reasoning ?? ""}`,
                  }))}
                />
                {live.slice(-3).reverse().map((a) => (
                  <p key={a.agent_id} className="text-[11px] text-muted-foreground truncate">
                    <span className="text-foreground/80">{a.agent_name}</span> — {a.answer?.reasoning}
                  </p>
                ))}
              </div>
            )}

            {selected.error && (
              <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">{selected.error}</div>
            )}

            {selected.aggregates && selected.aggregates.n > 0 && (
              <Results probe={selected} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Results({ probe }: { probe: Probe & { answers?: ProbeAnswerRow[] } }) {
  const a = probe.aggregates!;
  const currency = a.max_price?.currency || probe.spec?.currency || "GBP";
  return (
    <div className="space-y-5">
      {a.headline && (
        <div className="rounded-xl border border-border/60 bg-card/40 p-4">
          <ShareBar value={a.headline} label={a.headline.label} />
          <p className="text-xs text-foreground/70 mt-3 leading-relaxed">{a.sentence}</p>
        </div>
      )}

      <div className="grid grid-cols-3 gap-2">
        {a.likelihood && <MeanStat label="Mean likelihood" value={a.likelihood} suffix="/100" />}
        {a.max_price && <MeanStat label="Walk-away price" value={a.max_price} currency={currency} />}
        {a.sentiment && <MeanStat label="Feeling (-1…1)" value={a.sentiment} />}
      </div>

      {a.at_asking_price && (
        <div className="rounded-lg border border-border/60 bg-card/40 p-3 text-xs text-muted-foreground">
          <span className="text-foreground/80">{pct(a.at_asking_price.share)}</span> have a walk-away price at or above the asking price
          {a.consistency && a.consistency.contradictions > 0 && (
            <> · <span className="text-amber-400">{a.consistency.contradictions}</span> {a.consistency.note.toLowerCase()}</>
          )}
        </div>
      )}

      <div className="grid grid-cols-2 gap-5">
        {a.would_buy && <CategoryBars rows={a.would_buy} title="Decision" />}
        {a.drivers && <CategoryBars rows={a.drivers} title="What decided it" />}
      </div>

      {a.demand_curve && a.demand_curve.length > 0 && (
        <div className="rounded-xl border border-border/60 bg-card/40 p-4">
          <DemandCurve curve={a.demand_curve} currency={currency} askingPrice={probe.spec?.price ?? null} optimal={a.optimal_price ?? null} />
        </div>
      )}

      {a.segments && Object.keys(a.segments).length > 0 && (
        <div className="grid grid-cols-2 gap-5">
          {Object.entries(a.segments).map(([key, rows]) => (
            <SegmentTable key={key} title={key} rows={rows} />
          ))}
        </div>
      )}

      {a.verbatims && (
        <div className="space-y-3">
          <div className="text-xs text-muted-foreground">In their own words</div>
          {Object.entries(a.verbatims).map(([bucket, rows]) =>
            rows.length ? (
              <div key={bucket}>
                <div className="text-[11px] uppercase tracking-wide text-muted-foreground/70 mb-1 capitalize">{bucket}</div>
                <div className="space-y-1.5">
                  {rows.map((v) => (
                    <p key={v.agent_id} className="text-xs text-foreground/75 leading-relaxed">
                      <span className="text-foreground/95">{v.name}</span>
                      <span className="text-muted-foreground"> · {v.role}</span> — “{v.reasoning}”
                    </p>
                  ))}
                </div>
              </div>
            ) : null
          )}
        </div>
      )}

      <p className="text-[10px] text-muted-foreground/70">
        {probe.answer_count} answered{probe.failed_count ? `, ${probe.failed_count} failed and are excluded from every number above` : ""} ·
        model {probe.model} · seed {probe.seed} · schema {probe.schema_id}
      </p>
    </div>
  );
}
