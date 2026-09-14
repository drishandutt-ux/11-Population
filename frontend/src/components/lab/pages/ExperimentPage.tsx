"use client";

/** Results of an A/B/n experiment.
 *
 *  Verdict first, then the arms side by side, then the lift on every metric the instrument
 *  declared (with its interval drawn around zero), who flipped and why, and the segment
 *  heat-map. Nothing here knows which instrument ran: labels, formats and the decision field
 *  all come from the results and the instrument declaration. */

import { useState } from "react";
import { Comparison, Experiment, Instrument, Probe } from "@/lib/api";
import { CategoryBars, HeatCell, LiftBar, ShareBar, fmtLevel, fmtLift, pct } from "../Charts";

interface Props {
  instrument: Instrument;
  experiment: Experiment;
}

const DESIGN_LABEL: Record<string, string> = {
  within: "Within-subjects — every agent answered every variant, so each agent is its own control (paired).",
  between: "Between-subjects — the population was split by seed, each agent saw one variant (unpaired).",
};

export default function ExperimentPage({ instrument, experiment }: Props) {
  const r = experiment.results;
  if (!r) return null;
  const probes: Record<string, Probe> = {};
  for (const p of experiment.probes || []) if (p.variant_key) probes[p.variant_key] = p;

  return (
    <div className="space-y-6">
      {/* Verdict */}
      <div className="rounded-xl border border-primary/30 bg-primary/5 p-4">
        <div className="text-[11px] uppercase tracking-wide text-primary/80 mb-1">Verdict</div>
        <p className="text-sm text-foreground leading-relaxed">{r.verdict || "No comparison could be made."}</p>
        <p className="text-[11px] text-muted-foreground mt-2">{DESIGN_LABEL[r.design]}</p>
      </div>

      {/* Arms side by side */}
      <div className={`grid gap-3 ${experiment.variants.length > 2 ? "grid-cols-3" : "grid-cols-2"}`}>
        {experiment.variants.map((v, i) => {
          const p = probes[v.key];
          const a: any = p?.aggregates;
          const summary = instrument.inputs.map((f) => v.spec?.[f.key]).filter(Boolean).join(" · ");
          return (
            <div key={v.key} className="rounded-xl border border-border/60 bg-card/40 p-3 min-w-0">
              <div className="flex items-baseline justify-between gap-2 mb-1">
                <span className="text-xs font-medium text-foreground">{v.label || v.key}</span>
                <span className="text-[10px] text-muted-foreground">{i === 0 ? "control" : `vs ${experiment.variants[0].label || experiment.variants[0].key}`}</span>
              </div>
              <p className="text-[11px] text-muted-foreground line-clamp-3 mb-3" title={summary}>{summary}</p>
              {a?.headline ? (
                <ShareBar value={a.headline} label={a.headline.label} />
              ) : (
                <p className="text-[11px] text-muted-foreground">{p?.status === "failed" ? p.error || "failed" : "no answers"}</p>
              )}
              {a?.sentence && <p className="text-[11px] text-foreground/70 mt-2 leading-relaxed">{a.sentence}</p>}
            </div>
          );
        })}
      </div>

      {r.comparisons.map((c) => (
        <ComparisonBlock key={c.variant} c={c} instrument={instrument} single={r.comparisons.length === 1} />
      ))}
    </div>
  );
}

function ComparisonBlock({ c, instrument, single }: { c: Comparison; instrument: Instrument; single: boolean }) {
  const primary = c.metrics.find((m) => m.primary) || c.metrics[0];
  const currency = primary?.currency || "";
  const [showControlReasons, setShowControlReasons] = useState(false);
  const allCells = Object.values(c.segments).flat();
  const maxAbs = Math.max(0, ...allCells.filter((s) => !s.thin).map((s) => Math.abs(s.mean)));

  return (
    <div className="space-y-5">
      {!single && (
        <div className="text-sm font-medium">
          {c.label} <span className="text-muted-foreground font-normal">vs {c.control_label}</span>
        </div>
      )}
      {!single && c.sentence && <p className="text-xs text-foreground/70 leading-relaxed -mt-3">{c.sentence}</p>}

      {/* Lift per metric */}
      <div className="rounded-xl border border-border/60 bg-card/40 p-4">
        <div className="flex items-baseline justify-between mb-3">
          <span className="text-xs text-muted-foreground">Lift, {c.label} vs {c.control_label}</span>
          <span className="text-[11px] text-muted-foreground tabular-nums">
            {c.flips ? `${c.n} paired agents` : `${c.n} agents`} · 95% intervals
          </span>
        </div>
        <div className="space-y-2.5">
          {c.metrics.map((m) => (
            <div key={m.key} className="grid grid-cols-[7rem_5rem_5rem_1fr] items-center gap-3">
              <span className={`text-xs truncate ${m.primary ? "text-foreground" : "text-foreground/75"}`} title={m.label}>
                {m.label}{m.primary && <span className="text-primary/70"> ●</span>}
              </span>
              <span className="text-xs tabular-nums text-muted-foreground">{fmtLevel(m.control, m.format, m.currency)}</span>
              <span className="text-xs tabular-nums text-foreground/85">{fmtLevel(m.variant, m.format, m.currency)}</span>
              <div title={`95% CI ${fmtLift(m.lift.low, m.format, m.currency)} to ${fmtLift(m.lift.high, m.format, m.currency)}`}>
                <LiftBar lift={m.lift} format={m.format} currency={m.currency} />
              </div>
            </div>
          ))}
        </div>
        <div className="grid grid-cols-[7rem_5rem_5rem_1fr] gap-3 mt-2 text-[10px] text-muted-foreground/70">
          <span />
          <span>{c.control_label}</span>
          <span>{c.label}</span>
          <span>difference · grey when the interval includes zero</span>
        </div>
      </div>

      {/* Who flipped */}
      {c.flips && (
        <div className="rounded-xl border border-border/60 bg-card/40 p-4 space-y-3">
          <div className="flex items-baseline justify-between">
            <span className="text-xs text-muted-foreground">Who changed their answer</span>
            <span className="text-xs tabular-nums text-muted-foreground">
              {c.flips.n} of {c.flips.paired} · {pct(c.flips.share.share)}
            </span>
          </div>
          {c.flips.n === 0 ? (
            <p className="text-xs text-muted-foreground">Nobody changed their {instrument.decision_key.replace(/_/g, " ")} between the two variants.</p>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-5">
                <CategoryBars rows={c.flips.direction} title="Direction" />
                {c.flips.reasons.length > 0 && <CategoryBars rows={c.flips.reasons} title="What decided the new answer" />}
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-muted-foreground">In their own words — what they said to {c.label}</span>
                <button onClick={() => setShowControlReasons((s) => !s)} className="text-[11px] text-muted-foreground hover:text-foreground">
                  {showControlReasons ? "hide" : "show"} what they said to {c.control_label}
                </button>
              </div>
              <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
                {c.flips.rows.map((f) => (
                  <div key={f.agent_id} className="text-xs leading-relaxed">
                    <span className="text-foreground/95">{f.name}</span>
                    <span className="text-muted-foreground"> · {f.role}</span>
                    <span className="ml-2 text-[10px] rounded px-1.5 py-0.5 bg-muted text-foreground/80 tabular-nums">
                      {f.from} → {f.to}
                    </span>
                    {f.driver && (
                      <span className="ml-1 text-[10px] rounded px-1.5 py-0.5 bg-primary/10 text-primary/90 capitalize">{f.driver}</span>
                    )}
                    <p className="text-foreground/75">“{f.reasoning_variant}”</p>
                    {showControlReasons && f.reasoning_control && (
                      <p className="text-muted-foreground/80 text-[11px]">to {c.control_label}: “{f.reasoning_control}”</p>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {/* Segment heat-map */}
      {primary && Object.keys(c.segments).length > 0 && (
        <div className="rounded-xl border border-border/60 bg-card/40 p-4">
          <div className="flex items-baseline justify-between mb-3">
            <span className="text-xs text-muted-foreground">Where the effect holds — {primary.label.toLowerCase()} lift by segment</span>
            <span className="text-[10px] text-muted-foreground/70">✓ interval clears zero · faded = too few agents</span>
          </div>
          <div className="grid grid-cols-2 gap-4">
            {Object.entries(c.segments).map(([key, rows]) => (
              <div key={key}>
                <div className="text-[11px] text-muted-foreground mb-1.5 capitalize">{key.replace(/_/g, " ")}</div>
                <div className="space-y-1">
                  {rows.map((s) => (
                    <div key={s.value} className="grid grid-cols-[6rem_1fr] items-center gap-2">
                      <span className={`text-xs truncate ${s.thin ? "text-muted-foreground/60" : "text-foreground/80"}`} title={s.value}>{s.value}</span>
                      <HeatCell lift={s} thin={s.thin} n={s.n} format={primary.format} currency={currency} maxAbs={maxAbs} />
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
