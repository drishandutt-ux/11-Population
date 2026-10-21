"use client";

/** The growth with the rules in place, as a picture rather than a paragraph (2026-10-21): the end
 *  of the journey then → now with its interval, who moved (further / back / unchanged) as one
 *  stacked bar, the biggest gain as a before → after pair, and why it moved in the twins' own words
 *  grouped three ways with a count beside each reason. The counted sentence stays one tap away. */

import { useState } from "react";
import { JourneyGrowth, LeverWhyRow } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ArrowRight, ArrowUpRight, ArrowDownRight, Minus, Quote } from "lucide-react";

const pct = (v: number | null | undefined) => (typeof v === "number" ? `${Math.round(v * 100)}%` : "—");
const pts = (v: number) => `${Math.round(v * 100) >= 0 ? "+" : ""}${Math.round(v * 100)}`;
const num = (v: number) => Math.round(v).toLocaleString();

export default function GrowthInfographic({ growth }: { growth: JourneyGrowth }) {
  const [asText, setAsText] = useState(false);
  const end = growth.end;
  const mv = growth.movement;
  const total = Math.max(mv.n, 1);
  const biggest = growth.transitions.filter((t) => t.then != null && t.lift > 0).sort((a, b) => b.lift - a.lift)[0] || null;
  const why = growth.why;
  const tone = end.lift > 0 ? "up" : end.lift < 0 ? "down" : "flat";

  return (
    <div className="lite-card p-5 sm:p-6 space-y-5">
      <div className="space-y-2">
        <div className="text-[13px] text-muted-foreground">With the rules in place{growth.assumed ? <span className="ml-2 text-amber-700">· assumed effect, not a forecast</span> : null}</div>
        <div className="flex flex-wrap gap-1.5">{growth.rules.map((r) => <span key={r.rule_id} className="lite-pill-quiet cursor-default">{r.lever}{r.basis_class === "assumption" ? " · assumed" : ""}</span>)}</div>
      </div>

      {/* three tiles: the end of the journey, who moved, the biggest gain */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Tile label={`Reach “${end.label}”`}>
          <div className="flex items-end gap-2">
            <span className="text-[26px] font-semibold tabular-nums leading-none text-muted-foreground/70">{pct(end.then)}</span>
            <ArrowRight className="w-4 h-4 mb-1.5 text-muted-foreground/50" />
            <span className={cn("text-[34px] font-semibold tabular-nums leading-none", tone === "up" ? "text-emerald-700" : tone === "down" ? "text-red-700" : "")}>{pct(end.now)}</span>
          </div>
          <div className="mt-2 flex items-center gap-1.5 flex-wrap">
            <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-medium tabular-nums", tone === "up" ? "bg-emerald-500/12 text-emerald-700" : tone === "down" ? "bg-red-500/12 text-red-700" : "bg-foreground/[0.06] text-foreground/70")}>
              {tone === "up" ? <ArrowUpRight className="w-3 h-3" /> : tone === "down" ? <ArrowDownRight className="w-3 h-3" /> : <Minus className="w-3 h-3" />}{pts(end.lift)} points
            </span>
            <span className="text-[11.5px] text-muted-foreground">{end.significant ? "a real change" : "could be zero"} · likely {pts(end.low)} to {pts(end.high)} · {end.n} people</span>
          </div>
          {end.people_moved != null && end.people_then != null && end.people_now != null && (
            <div className="mt-1.5 text-[12px] text-muted-foreground tabular-nums">≈{num(end.people_then)} → ≈{num(end.people_now)} people ({end.people_moved >= 0 ? "+" : ""}{num(end.people_moved)})</div>
          )}
        </Tile>

        <Tile label="Who moved">
          <div className="h-3 rounded-full overflow-hidden flex bg-foreground/[0.06]">
            {mv.up > 0 && <div className="h-full bg-emerald-500/80" style={{ width: `${(mv.up / total) * 100}%` }} title={`${mv.up} got further`} />}
            {mv.unchanged > 0 && <div className="h-full bg-foreground/15" style={{ width: `${(mv.unchanged / total) * 100}%` }} title={`${mv.unchanged} unchanged`} />}
            {mv.down > 0 && <div className="h-full bg-red-500/75" style={{ width: `${(mv.down / total) * 100}%` }} title={`${mv.down} fell back`} />}
          </div>
          <div className="mt-2.5 grid grid-cols-3 gap-1 text-[12px]">
            <Legend n={mv.up} label="further" dot="bg-emerald-500/80" text="text-emerald-700" />
            <Legend n={mv.unchanged} label="same" dot="bg-foreground/20" text="text-foreground/70" />
            <Legend n={mv.down} label="back" dot="bg-red-500/75" text="text-red-700" />
          </div>
          <div className="mt-1.5 text-[11.5px] text-muted-foreground">of {mv.n} asked both times{growth.covered < growth.n ? ` · the rules reach ${growth.covered} of them` : ""}</div>
        </Tile>

        <Tile label="Biggest gain">
          {biggest ? (
            <>
              <div className="text-[13px] leading-snug"><span className="font-medium">{biggest.from.label}</span> <ArrowRight className="inline w-3 h-3 text-muted-foreground/60 -mt-0.5" /> <span className="font-medium">{biggest.to.label}</span></div>
              <div className="mt-2.5 space-y-1.5">
                <Bar label="before" value={biggest.then || 0} cls="bg-foreground/20" />
                <Bar label="now" value={biggest.now || 0} cls="bg-emerald-500/80" strong />
              </div>
              <div className="mt-1.5 text-[11.5px] text-muted-foreground">get through this step · {pts(biggest.lift)} points</div>
            </>
          ) : (
            <div className="text-[13px] text-muted-foreground">No step got easier.</div>
          )}
        </Tile>
      </div>

      {/* why, in their words */}
      {why && (why.through.length + why.back.length + why.still_stuck.length) > 0 && (
        <div>
          <div className="text-[13px] text-muted-foreground mb-2">Why, in their words{why.coded ? "" : " · one person per line"}</div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <WhyColumn title="Got further" n={why.n.through} rows={why.through} accent="border-emerald-500/60" badge="bg-emerald-500/12 text-emerald-700" />
            <WhyColumn title="Fell back" n={why.n.back} rows={why.back} accent="border-red-500/60" badge="bg-red-500/12 text-red-700" />
            <WhyColumn title="Still stuck" n={why.n.still_stuck} rows={why.still_stuck} accent="border-foreground/25" badge="bg-foreground/[0.06] text-foreground/70" />
          </div>
        </div>
      )}

      <div>
        <button type="button" onClick={() => setAsText((v) => !v)} className="text-[12px] text-muted-foreground hover:text-foreground">{asText ? "Hide the sentence" : "Read it as a sentence"}</button>
        {asText && <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">{growth.sentence}</p>}
      </div>
    </div>
  );
}

function Tile({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl bg-foreground/[0.03] px-4 py-3.5 min-w-0">
      <div className="text-[11.5px] uppercase tracking-wide text-muted-foreground mb-2 leading-snug">{label}</div>
      {children}
    </div>
  );
}

function Legend({ n, label, dot, text }: { n: number; label: string; dot: string; text: string }) {
  return (
    <div className="min-w-0">
      <div className={cn("text-[18px] font-semibold tabular-nums leading-none", text)}>{n}</div>
      <div className="mt-1 flex items-center gap-1 text-muted-foreground"><span className={cn("w-2 h-2 rounded-full shrink-0", dot)} /><span>{label}</span></div>
    </div>
  );
}

function Bar({ label, value, cls, strong }: { label: string; value: number; cls: string; strong?: boolean }) {
  return (
    <div className="flex items-center gap-2 text-[12px]">
      <span className="w-11 text-muted-foreground shrink-0">{label}</span>
      <div className="flex-1 h-2.5 rounded-full bg-foreground/[0.06] overflow-hidden"><div className={cn("h-full rounded-full", cls)} style={{ width: `${Math.round(value * 100)}%` }} /></div>
      <span className={cn("w-10 text-right tabular-nums", strong ? "font-semibold text-emerald-700" : "text-muted-foreground")}>{pct(value)}</span>
    </div>
  );
}

function WhyColumn({ title, n, rows, accent, badge }: { title: string; n: number; rows: LeverWhyRow[]; accent: string; badge: string }) {
  const lead = rows[0];
  return (
    <div className={cn("rounded-2xl border-l-[3px] bg-foreground/[0.03] px-4 py-3.5 min-w-0", accent)}>
      <div className="flex items-baseline gap-2 mb-2"><span className="text-[14px] font-medium">{title}</span><span className="text-[12px] text-muted-foreground tabular-nums">{n}</span></div>
      {rows.length === 0 ? (
        <div className="text-[12.5px] text-muted-foreground">Nobody.</div>
      ) : (
        <ul className="space-y-1.5">
          {rows.slice(0, 3).map((r, i) => (
            <li key={i} className="flex items-start gap-2 text-[12.5px] leading-snug">
              <span className={cn("shrink-0 rounded-full px-1.5 py-px text-[11px] font-medium tabular-nums mt-px", badge)}>{r.n}</span>
              <span className="min-w-0">{r.reason}</span>
            </li>
          ))}
        </ul>
      )}
      {lead?.quote && (
        <div className="mt-3 flex items-start gap-1.5 text-[12px] text-muted-foreground leading-snug">
          <Quote className="w-3 h-3 shrink-0 mt-0.5 opacity-60" />
          <span>“{lead.quote}”{lead.who ? <span className="opacity-80"> — {lead.who}</span> : null}</span>
        </div>
      )}
    </div>
  );
}
