"use client";

/** "Compared with the real poll": a Forms run scored against the real survey it reproduces
 *  (backend/app/data/kits/benchmarks). Plain words first — how far off our population is, on
 *  average, per question and per group — then the answers we got most wrong. */

import { useEffect, useState } from "react";
import { api, BenchmarkScore } from "@/lib/api";

const fmt = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? "—" : v.toFixed(d));

/** Fetches the scorecard for a Forms run; null until known, false when the run reproduces no real poll. */
export function useRealPollScore(sessionId: string, probeId: string, complete: boolean): BenchmarkScore | null | false {
  const [score, setScore] = useState<BenchmarkScore | null | false>(null);
  useEffect(() => {
    if (!complete) return;
    let live = true;
    api.population.benchmarkScoreAuto(sessionId, probeId).then((s) => { if (live) setScore(s); }).catch(() => { if (live) setScore(false); });
    return () => { live = false; };
  }, [sessionId, probeId, complete]);
  return score;
}

export default function RealPollScore({ score }: { score: BenchmarkScore }) {
  const h = score.headline;
  const segments = Object.entries(score.by_column).filter(([k]) => k.startsWith("Segment: "));
  const misses = score.units
    .flatMap((u) => u.options.map((o) => ({ ...o, question: u.question, row: u.row })))
    .sort((a, b) => Math.abs(b.diff_pts) - Math.abs(a.diff_pts))
    .slice(0, 12);
  const qLabel = (key: string) => {
    const q = score.per_question.find((x) => x.question === key);
    return q ? `Q${q.number || ""}` : key;
  };

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-border/60 bg-card/30 p-4 space-y-2">
        <div className="text-xs text-muted-foreground">{score.benchmark_title} · {score.fieldwork} · {score.sample}</div>
        <div className="text-2xl font-semibold tabular-nums">{fmt(h.mae_pts)} points off, on average</div>
        <p className="text-[13px] text-muted-foreground leading-relaxed max-w-2xl">
          Where the real poll says 40% of people gave an answer, our {score.respondents} twins typically say somewhere between {fmt(40 - h.mae_pts, 0)}% and {fmt(40 + h.mae_pts, 0)}%.
          {" "}They pick the same most popular answer {Math.round((h.top_choice_agreement || 0) * 100)}% of the time, and {Math.round(h.within_5_pts * 100)}% of answers are within 5 points of the real figure.
          {" "}Guessing every option equally likely would be {fmt(h.uniform_baseline_mae_pts)} points off.
          {score.estimator === "likelihood" ? " Shares are averaged from each twin's stated chances (the same twin asked many times), not from one draw each." : ""}
        </p>
      </div>

      <div className="space-y-1.5">
        <div className="text-xs font-medium">By question — points off, on average</div>
        {score.per_question.map((q) => (
          <div key={q.question} className="flex items-center gap-3 text-xs">
            <span className="w-14 shrink-0 text-muted-foreground tabular-nums">Q{q.number}</span>
            <span className="flex-1 min-w-0 truncate" title={q.text}>{q.text}</span>
            <span className="w-28 shrink-0 h-1.5 rounded-full bg-muted overflow-hidden">
              <span className={`block h-full ${q.mae_pts <= 5 ? "bg-emerald-500" : q.mae_pts <= 10 ? "bg-amber-500" : "bg-red-500"}`} style={{ width: `${Math.min(100, q.mae_pts * 4)}%` }} />
            </span>
            <span className="w-10 shrink-0 text-right tabular-nums">{fmt(q.mae_pts)}</span>
          </div>
        ))}
      </div>

      {segments.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-xs font-medium">By group — points off, on average</div>
          <p className="text-[11px] text-muted-foreground">Small groups are noisy: a group of 20 twins is several points off even when the simulation is perfect. "Like the country" is how far off you would be by assuming the group answers exactly like the national total.</p>
          <table className="w-full text-xs">
            <thead className="text-muted-foreground"><tr><th className="text-left font-normal py-1">Group</th><th className="text-right font-normal">Twins</th><th className="text-right font-normal">Our gap</th><th className="text-right font-normal">"Like the country"</th></tr></thead>
            <tbody>
              {segments.map(([k, v]) => (
                <tr key={k} className="border-t border-border/40">
                  <td className="py-1">{k.replace("Segment: ", "")}</td>
                  <td className="text-right tabular-nums">{v.respondents ?? "—"}</td>
                  <td className="text-right tabular-nums">{fmt(v.mae_pts)}</td>
                  <td className="text-right tabular-nums text-muted-foreground">{fmt(v.national_baseline_mae_pts)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="space-y-1.5">
        <div className="text-xs font-medium">Where we are furthest from the real poll</div>
        <table className="w-full text-xs">
          <thead className="text-muted-foreground"><tr><th className="text-left font-normal py-1">Question</th><th className="text-left font-normal">Answer</th><th className="text-right font-normal">Real</th><th className="text-right font-normal">Ours</th></tr></thead>
          <tbody>
            {misses.map((m, i) => (
              <tr key={i} className="border-t border-border/40">
                <td className="py-1 pr-2 text-muted-foreground whitespace-nowrap">{qLabel(m.question)}{m.row ? ` · ${m.row}` : ""}</td>
                <td className="pr-2">{m.option}</td>
                <td className="text-right tabular-nums">{fmt(m.real_pct, 0)}%</td>
                <td className="text-right tabular-nums">{fmt(m.sim_pct, 0)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
