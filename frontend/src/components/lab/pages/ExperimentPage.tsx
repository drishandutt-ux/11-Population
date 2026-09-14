"use client";

/** Results of an A/B/n experiment.
 *
 *  Reads as a comparison, not as two probes: the verdict, then the primary metric as a
 *  before/after with one big delta, the lift on every metric, one compact line per arm for
 *  context, how the same agents moved between answers (a flow, with the movers' own words),
 *  and where the effect holds by segment. Nothing here knows which instrument ran. */

import { useState } from "react";
import { Comparison, Experiment, Instrument, Preference, Probe } from "@/lib/api";
import { CategoryBars, DeltaHero, FlowDiagram, HeatCell, LiftBar, fmtLevel, fmtLift, optionColor, pct } from "../Charts";

interface Props {
  instrument: Instrument;
  experiment: Experiment;
}

const DESIGN_LABEL: Record<string, string> = {
  within: "Same agents answered every variant, in separate calls with no memory of the other — each agent is its own control.",
  between: "The population was split by seed; each agent saw one variant, so the arms are compared as independent groups.",
  choice: "Every agent saw all the options at once and picked a winner and a runner-up — a direct preference, one call per agent.",
};

export default function ExperimentPage({ instrument, experiment }: Props) {
  const r = experiment.results;
  if (!r) return null;
  const probes: Record<string, Probe> = {};
  for (const p of experiment.probes || []) if (p.variant_key) probes[p.variant_key] = p;

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-primary/30 bg-primary/5 p-4">
        <div className="text-[11px] uppercase tracking-wide text-primary/80 mb-1">Verdict</div>
        <p className="text-sm text-foreground leading-relaxed">{r.verdict || "No comparison could be made."}</p>
        <p className="text-[11px] text-muted-foreground mt-2">{DESIGN_LABEL[r.design]}</p>
      </div>

      {r.design === "choice" && r.preference && (
        <ChoiceBlock preference={r.preference} headToHead={r.head_to_head || []} keys={experiment.variants.map((v) => v.key)} n={r.n || 0} clear={!!r.clear_winner} />
      )}

      {r.comparisons.map((c) => (
        <ComparisonBlock key={c.variant} c={c} instrument={instrument} single={r.comparisons.length === 1} />
      ))}

      {/* The arms, one line each: context for the deltas above, and a way to see each level. */}
      <div className="rounded-xl border border-border/60 bg-card/40 divide-y divide-border/40">
        <div className="px-3 py-2 text-[11px] text-muted-foreground">
          {r.design === "choice" ? "The options, as the agents saw them" : `The arms — each is a full ${instrument.label.toLowerCase()} run on its own`}
        </div>
        {experiment.variants.map((v, i) => {
          const p = probes[v.key];
          const a: any = p?.aggregates;
          const summary = instrument.inputs.map((f) => v.spec?.[f.key]).filter(Boolean).join(" · ");
          return (
            <div key={v.key} className="grid grid-cols-[2.2rem_8rem_1fr_5rem_3.5rem] items-center gap-3 px-3 py-2">
              <span className="text-[10px] font-medium rounded px-1.5 py-0.5 bg-primary/10 text-primary text-center">{v.key}</span>
              <span className="text-xs text-foreground truncate" title={v.label || v.key}>
                {v.label || v.key}{i === 0 && <span className="text-muted-foreground"> · control</span>}
              </span>
              <span className="text-[11px] text-muted-foreground truncate" title={summary}>{summary}</span>
              <span className="text-sm tabular-nums text-right text-foreground/90">
                {r.design === "choice"
                  ? pct(r.preference?.find((x) => x.key === v.key)?.share || 0)
                  : a?.headline ? pct(a.headline.share) : p?.status === "failed" ? "failed" : "—"}
              </span>
              <span className="text-[10px] tabular-nums text-right text-muted-foreground">
                {r.design === "choice"
                  ? `${r.preference?.find((x) => x.key === v.key)?.successes ?? 0}/${r.n ?? 0}`
                  : a?.headline ? `${a.headline.successes}/${a.headline.n}` : ""}
              </span>
            </div>
          );
        })}
      </div>
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
        <div>
          <div className="text-sm font-medium">{c.label} <span className="text-muted-foreground font-normal">vs {c.control_label}</span></div>
          {c.sentence && <p className="text-xs text-foreground/70 leading-relaxed mt-1">{c.sentence}</p>}
        </div>
      )}

      {/* The result: one delta, big. */}
      {primary && (
        <div className="rounded-xl border border-border/60 bg-card/40 p-4">
          <DeltaHero
            label={`${primary.label} — ${c.flips ? `${c.n} agents, each answering both` : `${c.n} agents, split between the arms`}`}
            controlLabel={c.control_label}
            variantLabel={c.label}
            control={primary.control}
            variant={primary.variant}
            lift={primary.lift}
            format={primary.format}
            currency={primary.currency}
          />
        </div>
      )}

      {/* Every other metric's lift. */}
      <div className="rounded-xl border border-border/60 bg-card/40 p-4">
        <div className="flex items-baseline justify-between mb-3">
          <span className="text-xs text-muted-foreground">Lift on every metric, {c.label} vs {c.control_label}</span>
          <span className="text-[10px] text-muted-foreground/70">grey = the 95% interval includes zero</span>
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
          <span /><span>{c.control_label}</span><span>{c.label}</span><span>difference, with its interval</span>
        </div>
      </div>

      {/* How the same people moved. */}
      {c.flips && (
        <div className="rounded-xl border border-border/60 bg-card/40 p-4 space-y-4">
          <div className="flex items-baseline justify-between">
            <span className="text-xs text-muted-foreground">How the same agents moved — {instrument.decision_key.replace(/_/g, " ")}</span>
            <span className="text-xs tabular-nums text-muted-foreground">
              <span className="text-amber-300">{c.flips.n}</span> of {c.flips.paired} changed · {pct(c.flips.share.share)}
            </span>
          </div>
          <div className="grid grid-cols-[1.4fr_1fr] gap-5 items-start">
            <FlowDiagram matrix={c.flips.matrix || []} controlLabel={c.control_label} variantLabel={c.label} />
            {c.flips.n > 0 && c.flips.reasons.length > 0 ? (
              <CategoryBars rows={c.flips.reasons} title="What decided the new answer" />
            ) : (
              <p className="text-xs text-muted-foreground">Nobody changed their answer between the two variants.</p>
            )}
          </div>
          {c.flips.n > 0 && (
            <>
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-muted-foreground">The movers, in their own words — what they said to {c.label}</span>
                <button onClick={() => setShowControlReasons((s) => !s)} className="text-[11px] text-muted-foreground hover:text-foreground">
                  {showControlReasons ? "hide" : "show"} what they said to {c.control_label}
                </button>
              </div>
              <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
                {c.flips.rows.map((f) => (
                  <div key={f.agent_id} className="text-xs leading-relaxed border-l-2 border-amber-300/60 pl-2.5">
                    <span className="text-foreground/95">{f.name}</span>
                    <span className="text-muted-foreground"> · {f.role}</span>
                    <span className="ml-2 text-[10px] rounded px-1.5 py-0.5 bg-muted text-foreground/80 tabular-nums">{f.from} → {f.to}</span>
                    {f.driver && <span className="ml-1 text-[10px] rounded px-1.5 py-0.5 bg-primary/10 text-primary/90 capitalize">{f.driver}</span>}
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

      {/* Where it holds. */}
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


/** The choose-between-them result: a preference race with intervals, who came second to whom,
 *  what made each option win, and where each wins by segment. */
function ChoiceBlock({ preference, headToHead, keys, n, clear }: {
  preference: Preference[]; headToHead: { first: string; second: string; count: number }[]; keys: string[]; n: number; clear: boolean;
}) {
  const [open, setOpen] = useState<string | null>(preference[0]?.key || null);
  const shown = preference.find((p) => p.key === open) || preference[0];
  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-border/60 bg-card/40 p-4">
        <div className="flex items-baseline justify-between mb-3">
          <span className="text-xs text-muted-foreground">Preferred by — {n} agents, each choosing once</span>
          <span className="text-[10px] text-muted-foreground/70">{clear ? "intervals do not overlap: a settled order" : "intervals overlap: the order is not settled"}</span>
        </div>
        <div className="space-y-2">
          {preference.map((p, i) => {
            const color = optionColor(keys, p.key);
            return (
              <button key={p.key} onClick={() => setOpen(p.key)} className={`w-full text-left grid grid-cols-[2rem_8rem_1fr_5rem_5rem] items-center gap-3 rounded-lg px-2 py-1.5 ${open === p.key ? "bg-muted/50" : "hover:bg-muted/30"}`}>
                <span className="text-[10px] font-medium rounded px-1.5 py-0.5 text-center" style={{ background: `${color}22`, color }}>{p.key}</span>
                <span className={`text-xs truncate ${i === 0 ? "text-foreground" : "text-foreground/75"}`} title={p.label}>{p.label}{i === 0 && <span className="text-muted-foreground"> · winner</span>}</span>
                <div className="relative h-4 bg-muted rounded-sm overflow-hidden">
                  <div className="absolute inset-y-0 rounded-sm" style={{ left: `${p.low * 100}%`, width: `${Math.max(1, (p.high - p.low) * 100)}%`, background: color, opacity: 0.25 }} />
                  <div className="absolute inset-y-0 rounded-sm" style={{ width: `${Math.max(1, p.share * 100)}%`, background: color, opacity: 0.85 }} />
                </div>
                <span className="text-sm tabular-nums text-right" style={{ color }}>{pct(p.share)}</span>
                <span className="text-[10px] tabular-nums text-right text-muted-foreground">2nd for {p.runner_up}</span>
              </button>
            );
          })}
        </div>
        {headToHead.length > 0 && (
          <p className="text-[11px] text-muted-foreground mt-3">
            Most common ranking: {headToHead.slice(0, 3).map((h) => `${h.first} then ${h.second} (${h.count})`).join(" · ")}
          </p>
        )}
      </div>

      {shown && (
        <div className="rounded-xl border border-border/60 bg-card/40 p-4 space-y-4">
          <div className="text-xs text-muted-foreground">Why <span className="text-foreground/90">{shown.label}</span> wins for the {shown.successes} who chose it</div>
          <div className="grid grid-cols-2 gap-5">
            {shown.themes.length > 0 ? <CategoryBars rows={shown.themes} title="What made it win — coded themes" /> : <p className="text-xs text-muted-foreground">No reasons coded.</p>}
            {shown.segments && Object.keys(shown.segments).length > 0 && (
              <div className="space-y-3">
                {Object.entries(shown.segments).slice(0, 2).map(([key, rows]) => (
                  <div key={key}>
                    <div className="text-[11px] text-muted-foreground mb-1 capitalize">Share choosing it, by {key.replace(/_/g, " ")}</div>
                    {rows.map((s) => (
                      <div key={s.value} className={`flex items-center gap-2 ${s.thin ? "opacity-45" : ""}`}>
                        <span className="w-20 shrink-0 text-xs text-foreground/80 truncate">{s.value}</span>
                        <div className="flex-1 h-3 bg-muted rounded-sm overflow-hidden"><div className="h-full bg-primary/70" style={{ width: `${s.share * 100}%` }} /></div>
                        <span className="w-16 text-right text-xs tabular-nums text-muted-foreground">{pct(s.share)} <span className="opacity-60">n={s.n}</span></span>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>
          {shown.verbatims.length > 0 && (
            <div className="space-y-1.5">
              {shown.verbatims.map((v) => (
                <p key={v.agent_id} className="text-xs text-foreground/75 leading-relaxed">
                  <span className="text-foreground/95">{v.name}</span><span className="text-muted-foreground"> · {v.role}</span>
                  {(v.theme || v.key_factor) && <span className="ml-1.5 text-[10px] rounded px-1.5 py-0.5 bg-primary/10 text-primary/90">{v.theme || v.key_factor}</span>}
                  {" "}— “{v.reasoning}”
                </p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
