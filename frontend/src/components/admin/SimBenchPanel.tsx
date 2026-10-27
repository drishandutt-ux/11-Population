"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Download, Loader2, Play, RefreshCw, Square } from "lucide-react";
import { api, SimBenchBlock, SimBenchEstimate, SimBenchOverview, SimBenchRun } from "@/lib/api";
import { fmtUsd } from "@/components/admin/UsageAnalyser";

const CASE_CHOICES = [
  { n: 100, label: "100 · pilot" },
  { n: 250, label: "250" },
  { n: 1000, label: "1,000 · full subset" },
];
const TWIN_CHOICES = [40, 60, 100];
const LIVE = ["queued", "running", "stopping"];

function score(v: number | null | undefined) {
  return v === null || v === undefined ? "—" : v.toFixed(1);
}

function signed(v: number | null | undefined) {
  if (v === null || v === undefined) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(1)}`;
}

function statusChip(s: SimBenchRun["status"]) {
  const tone =
    s === "complete" ? "border-emerald-500/40 text-emerald-400 bg-emerald-500/10"
    : LIVE.includes(s) ? "border-primary/40 text-primary bg-primary/10"
    : s === "failed" ? "border-red-500/40 text-red-400 bg-red-500/10"
    : "border-border text-muted-foreground";
  return <span className={`text-[10px] px-1.5 py-0.5 rounded border ${tone}`}>{s}</span>;
}

function ScoreRow({ label, b, bare, strong }: { label: string; b: SimBenchBlock; bare: boolean; strong?: boolean }) {
  const d = b.twins_minus_bare;
  return (
    <tr className={`border-t border-border/40 ${strong ? "bg-muted/20" : ""}`}>
      <td className={`px-3 py-2 text-xs ${strong ? "font-medium text-foreground" : "text-muted-foreground"}`}>{label}</td>
      <td className="px-3 py-2 text-xs text-right tabular-nums text-muted-foreground">{b.cases}</td>
      <td className="px-3 py-2 text-xs text-right tabular-nums text-foreground">{score(b.likelihood.mean)}</td>
      <td className="px-3 py-2 text-xs text-right tabular-nums text-muted-foreground">{score(b.draws.mean)}</td>
      {bare && <td className="px-3 py-2 text-xs text-right tabular-nums text-foreground">{score(b.bare?.mean)}</td>}
      {bare && (
        <td className={`px-3 py-2 text-xs text-right tabular-nums ${d && d.mean !== null ? (d.mean > 0 ? "text-emerald-400" : "text-red-400") : "text-muted-foreground"}`}>
          {d ? `${signed(d.mean)}${d.sem !== null ? ` ± ${d.sem.toFixed(1)}` : ""}` : "—"}
        </td>
      )}
      {bare && <td className="px-3 py-2 text-xs text-right tabular-nums text-muted-foreground">{d ? `${Math.round(d.twins_ahead_share * 100)}%` : "—"}</td>}
    </tr>
  );
}

function RunResult({ run }: { run: SimBenchRun }) {
  const [showGroupings, setShowGroupings] = useState(false);
  const s = run.summary;
  if (!s || !s.overall.cases) {
    return <p className="text-xs text-muted-foreground">No case has been scored yet.</p>;
  }
  const bare = run.config.bare;
  const datasets = Object.entries(s.by_dataset);
  const groupings = Object.entries(s.by_grouping || {});
  return (
    <div className="space-y-3">
      <div className="border border-border/60 rounded-lg overflow-hidden">
        <table className="w-full">
          <thead className="bg-muted/30 text-[10px] uppercase tracking-wider text-muted-foreground">
            <tr>
              <th className="text-left px-3 py-2 font-semibold">Scored on</th>
              <th className="text-right px-3 py-2 font-semibold">Cases</th>
              <th className="text-right px-3 py-2 font-semibold" title="The mean of every twin's chances per option">Twins</th>
              <th className="text-right px-3 py-2 font-semibold" title="The share of the twins' single picks">Twins, picks only</th>
              {bare && <th className="text-right px-3 py-2 font-semibold" title="The same model, the benchmark's own prompt, no twins">Model alone</th>}
              {bare && <th className="text-right px-3 py-2 font-semibold">Twins minus model alone</th>}
              {bare && <th className="text-right px-3 py-2 font-semibold">Cases twins win</th>}
            </tr>
          </thead>
          <tbody>
            <ScoreRow label="All scored cases" b={s.overall} bare={bare} strong />
            {datasets.map(([k, b]) => <ScoreRow key={k} label={k} b={b} bare={bare} />)}
            {groupings.length > 0 && (
              <tr className="border-t border-border/40">
                <td colSpan={bare ? 7 : 4} className="px-3 py-1.5">
                  <button onClick={() => setShowGroupings((v) => !v)} className="text-[11px] text-muted-foreground hover:text-foreground flex items-center gap-1">
                    {showGroupings ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />} By the trait that defines the subgroup
                  </button>
                </td>
              </tr>
            )}
            {showGroupings && groupings.map(([k, b]) => <ScoreRow key={k} label={k} b={b} bare={bare} />)}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-muted-foreground leading-relaxed">
        Scores run from 0, which is no better than an even guess, to 100, which is the real answer exactly. The published best is{" "}
        {Object.entries(s.published).map(([k, v], i) => <Fragment key={k}>{i ? ", " : ""}{k} {v}</Fragment>)}. Those use other models and both splits together, so the fair
        test is the model-alone column: the same model on the same cases with the benchmark&apos;s own prompt.
        {s.refusal_share ? ` ${Math.round(s.refusal_share * 1000) / 10}% of twin answers said the question was not theirs to answer and were left out.` : ""}
        {s.failed_cases ? ` ${s.failed_cases} case${s.failed_cases === 1 ? "" : "s"} could not be scored.` : ""}
      </p>
    </div>
  );
}

export default function SimBenchPanel() {
  const [data, setData] = useState<SimBenchOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [cases, setCases] = useState(100);
  const [twins, setTwins] = useState(60);
  const [mode, setMode] = useState<"fast" | "pro">("fast");
  const [bare, setBare] = useState(true);
  const [est, setEst] = useState<SimBenchEstimate | null>(null);
  const [openRun, setOpenRun] = useState<string | null>(null);

  async function load() {
    try {
      setData(await api.admin.simbench());
      setError(null);
    } catch (e: any) {
      setError(e?.message || "Couldn't load the benchmark");
    }
  }

  useEffect(() => { load(); }, []);

  const live = useMemo(() => (data?.runs || []).some((r) => LIVE.includes(r.status)), [data]);
  useEffect(() => {
    if (!live) return;
    const t = setInterval(load, 10_000);
    return () => clearInterval(t);
  }, [live]);

  useEffect(() => {
    let gone = false;
    api.admin.simbenchEstimate(cases, twins, mode).then((e) => { if (!gone) setEst(e); }).catch(() => {});
    return () => { gone = true; };
  }, [cases, twins, mode]);

  async function start() {
    if (!est) return;
    const ok = window.confirm(
      `Start SimBench on ${est.cases} cases?\n\n${est.groups} subgroup lineups of ${twins} twins on ${mode === "pro" ? "Sonnet" : "Haiku"}, ` +
      `${est.twin_calls.toLocaleString()} twin answers${bare ? " plus the model alone on every case" : ""}.\n\nEstimated cost: ${fmtUsd(est.total_usd)}.`
    );
    if (!ok) return;
    setBusy("start");
    try {
      const run = await api.admin.simbenchStart({ cases, twins, mode, bare });
      setOpenRun(run.id);
      await load();
    } catch (e: any) {
      setError(e?.message || "Couldn't start the run");
    } finally {
      setBusy(null);
    }
  }

  async function act(run: SimBenchRun, what: "stop" | "resume" | "csv") {
    setBusy(`${what}:${run.id}`);
    try {
      if (what === "stop") await api.admin.simbenchStop(run.id);
      else if (what === "resume") await api.admin.simbenchResume(run.id);
      else await api.admin.simbenchCsv(run.id);
      await load();
    } catch (e: any) {
      setError(e?.message || "That didn't work");
    } finally {
      setBusy(null);
    }
  }

  if (!data) {
    return error ? <p className="text-xs text-red-400">{error}</p> : <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />;
  }
  const sub = data.subset;
  const runs = data.runs;
  const shown = openRun || runs[0]?.id || null;

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-medium text-foreground">SimBench, grouped split</h2>
          <span className="text-[11px] text-muted-foreground">{sub.paper}</span>
          <button onClick={load} className="ml-auto text-muted-foreground hover:text-foreground p-1 rounded" title="Refresh"><RefreshCw className="w-3.5 h-3.5" /></button>
        </div>
        <p className="text-xs text-muted-foreground leading-relaxed max-w-3xl">
          A public test of whether a simulated group answers a survey question the way the real group did. Each case is one subgroup of a national survey, such as
          women in Poland in 2016, and one question. We write a lineup of twins for each subgroup, ask them the question, and score how close their answers come to the
          real ones. The same model answering on its own, with the benchmark&apos;s prompt, is scored beside them.
        </p>
        {sub.ready ? (
          <p className="text-[11px] text-muted-foreground">
            Subset on file: {sub.n?.toLocaleString()} cases from {sub.groups} subgroups across {new Set((sub.strata || []).map((x) => x.dataset)).size} surveys, cut on {sub.created} from{" "}
            {sub.source?.rows.toLocaleString()} cases. {sub.cached ? (sub.stale ? "The cached data no longer matches the subset." : "Data cached on the server.") : "The data is fetched from Hugging Face when a run starts."}
          </p>
        ) : (
          <p className="text-xs text-red-400">{sub.reason}</p>
        )}
      </section>

      {error && <p className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">{error}</p>}

      <section className="border border-border/60 rounded-lg p-4 space-y-3">
        <div className="flex flex-wrap items-end gap-4">
          <label className="text-[11px] text-muted-foreground space-y-1">
            <div>Cases</div>
            <select value={cases} onChange={(e) => setCases(Number(e.target.value))} className="bg-background border border-border/60 rounded px-2 py-1 text-xs text-foreground">
              {CASE_CHOICES.map((c) => <option key={c.n} value={c.n}>{c.label}</option>)}
            </select>
          </label>
          <label className="text-[11px] text-muted-foreground space-y-1">
            <div>Twins per subgroup</div>
            <select value={twins} onChange={(e) => setTwins(Number(e.target.value))} className="bg-background border border-border/60 rounded px-2 py-1 text-xs text-foreground">
              {TWIN_CHOICES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </label>
          <label className="text-[11px] text-muted-foreground space-y-1">
            <div>Model</div>
            <select value={mode} onChange={(e) => setMode(e.target.value as "fast" | "pro")} className="bg-background border border-border/60 rounded px-2 py-1 text-xs text-foreground">
              <option value="fast">Standard (Haiku)</option>
              <option value="pro">Advanced (Sonnet)</option>
            </select>
          </label>
          <label className="text-[11px] text-muted-foreground flex items-center gap-1.5 pb-1">
            <input type="checkbox" checked={bare} onChange={(e) => setBare(e.target.checked)} /> Score the model alone too
          </label>
          <button
            onClick={start}
            disabled={!sub.ready || live || busy === "start" || !est}
            className="ml-auto text-xs text-primary hover:bg-primary/10 border border-primary/40 rounded px-3 py-1.5 flex items-center gap-1.5 disabled:opacity-40"
            title={live ? "A run is already in progress" : undefined}
          >
            {busy === "start" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />} Start run
          </button>
        </div>
        {est && (
          <p className="text-[11px] text-muted-foreground">
            {est.cases.toLocaleString()} cases in {est.groups} subgroups: {(est.groups * twins).toLocaleString()} twins to write and {est.twin_calls.toLocaleString()} answers to collect.
            Estimated {fmtUsd(est.total_usd)}, of which writing the twins is {fmtUsd(est.lineups_usd)}. The pilot is the cheap way to see whether the full subset is worth paying for.
          </p>
        )}
      </section>

      <section className="space-y-3">
        <h3 className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Runs</h3>
        {runs.length === 0 && <p className="text-xs text-muted-foreground">No runs yet.</p>}
        {runs.map((r) => {
          const p = r.progress;
          const pct = p.cases_total ? Math.round((p.cases_done / p.cases_total) * 100) : 0;
          const open = shown === r.id;
          return (
            <div key={r.id} className="border border-border/60 rounded-lg">
              <div className="px-4 py-3 flex flex-wrap items-center gap-3">
                <button onClick={() => setOpenRun(open ? "" : r.id)} className="text-muted-foreground hover:text-foreground">
                  {open ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                </button>
                {statusChip(r.status)}
                <span className="text-xs text-foreground">
                  {r.config.case_count.toLocaleString()} cases · {r.config.twins} twins · {r.config.mode === "pro" ? "Sonnet" : "Haiku"}
                </span>
                <span className="text-[11px] text-muted-foreground">{r.created_at ? new Date(r.created_at + "Z").toLocaleString() : ""}</span>
                <div className="flex items-center gap-2 ml-auto">
                  <div className="w-32 h-1.5 bg-muted rounded overflow-hidden"><div className="h-full bg-primary" style={{ width: `${pct}%` }} /></div>
                  <span className="text-[11px] tabular-nums text-muted-foreground">{p.cases_done}/{p.cases_total} cases · {p.groups_built}/{p.groups_total} lineups</span>
                  <span className="text-[11px] tabular-nums text-muted-foreground">{fmtUsd(r.cost_usd)} of ~{fmtUsd(r.config.estimate?.total_usd || 0)}</span>
                  {LIVE.includes(r.status) && r.status !== "stopping" && (
                    <button onClick={() => act(r, "stop")} disabled={!!busy} className="text-[11px] border border-border/60 rounded px-2 py-1 text-muted-foreground hover:text-foreground flex items-center gap-1">
                      <Square className="w-3 h-3" /> Stop
                    </button>
                  )}
                  {["stopped", "interrupted", "failed"].includes(r.status) && (
                    <button onClick={() => act(r, "resume")} disabled={!!busy || live} className="text-[11px] border border-primary/40 rounded px-2 py-1 text-primary hover:bg-primary/10 flex items-center gap-1 disabled:opacity-40">
                      <Play className="w-3 h-3" /> Resume
                    </button>
                  )}
                  <button onClick={() => act(r, "csv")} disabled={!!busy || !p.cases_done} className="text-[11px] border border-border/60 rounded px-2 py-1 text-muted-foreground hover:text-foreground flex items-center gap-1 disabled:opacity-40">
                    <Download className="w-3 h-3" /> Cases
                  </button>
                </div>
              </div>
              {r.error && <p className="px-4 pb-2 text-[11px] text-red-400">{r.error}</p>}
              {open && <div className="px-4 pb-4"><RunResult run={r} /></div>}
            </div>
          );
        })}
      </section>
    </div>
  );
}
