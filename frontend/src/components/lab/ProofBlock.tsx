"use client";

/** The proof behind a new version (the Visual Lab, 2026-10-27): the paired re-test, read as a
 *  result — who it won, who it lost, by how much, where it paid and where it cost, and the
 *  movers in their own words. Rendered on the image's card, on the Next version panel and at the
 *  top of the re-test run's own results page. */

import { useState } from "react";
import { ChevronDown, ChevronRight, Loader2, TrendingDown, TrendingUp, Minus } from "lucide-react";
import { ImageProof, RetestState } from "@/lib/api";
import { pct } from "./Charts";

const pts = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(Math.round(v * 100))} pts`;

export function ProofLine({ retest, proof, compact = false }: { retest?: RetestState | null; proof?: ImageProof | null; compact?: boolean }) {
  if (proof) {
    const Icon = proof.verdict === "won" ? TrendingUp : proof.verdict === "lost" ? TrendingDown : Minus;
    const cls = proof.verdict === "won" ? "text-emerald-300" : proof.verdict === "lost" ? "text-red-300" : "text-muted-foreground";
    return (
      <span className={`inline-flex items-center gap-1 ${cls} ${compact ? "text-[10px]" : "text-[11px]"}`}>
        <Icon className="w-3.5 h-3.5" />
        {compact
          ? `${pts(proof.lift.mean)} on the same ${proof.n_paired} twins · won ${proof.won}, lost ${proof.lost}`
          : proof.sentence}
      </span>
    );
  }
  if (retest?.status === "running") {
    return <span className={`inline-flex items-center gap-1 text-muted-foreground ${compact ? "text-[10px]" : "text-[11px]"}`}><Loader2 className="w-3 h-3 animate-spin" /> Testing on the same {retest.agents} twins…</span>;
  }
  if (retest?.status === "failed") {
    return <span className={`text-red-300 ${compact ? "text-[10px]" : "text-[11px]"}`}>The re-test did not finish{retest.error ? `: ${retest.error}` : ""}.</span>;
  }
  return null;
}

export default function ProofBlock({ proof, title = "What it did to the same people" }: { proof: ImageProof; title?: string }) {
  const [open, setOpen] = useState(false);
  const Icon = proof.verdict === "won" ? TrendingUp : proof.verdict === "lost" ? TrendingDown : Minus;
  const tone = proof.verdict === "won" ? "border-emerald-500/30 bg-emerald-500/5" : proof.verdict === "lost" ? "border-red-500/30 bg-red-500/5" : "border-border/60 bg-card/40";
  const segKeys = Object.keys(proof.by_segment || {});
  return (
    <div className={`rounded-xl border p-4 space-y-3 ${tone}`}>
      <div className="flex items-start gap-2">
        <Icon className={`w-4 h-4 mt-0.5 shrink-0 ${proof.verdict === "won" ? "text-emerald-300" : proof.verdict === "lost" ? "text-red-300" : "text-muted-foreground"}`} />
        <div className="min-w-0 flex-1">
          <div className="text-[11px] uppercase tracking-wide text-muted-foreground/80">{title}</div>
          <p className="text-sm text-foreground leading-relaxed mt-0.5">{proof.sentence}</p>
          {proof.trade_off && <p className="text-[11px] text-foreground/75 mt-1">{proof.trade_off}</p>}
          {proof.expected && <p className="text-[11px] text-muted-foreground mt-1">Expected before the test: <span className="text-foreground/70">{proof.expected}</span></p>}
        </div>
      </div>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(7rem,1fr))] gap-2">
        <Tile label="Works on them" value={`${pct(proof.before.share)} → ${pct(proof.after.share)}`} sub={`${proof.n_paired} paired twins`} />
        <Tile label="Won over" value={String(proof.won)} sub={`of ${proof.rejecters} it did not work on`} good />
        <Tile label="Lost" value={String(proof.lost)} sub={`of ${proof.believers} it did`} bad={proof.lost > 0} />
        <Tile label="Shift" value={pts(proof.lift.mean)} sub={`95% CI ${pts(proof.lift.low)} to ${pts(proof.lift.high)}`} />
        <Tile label="Feeling" value={`${proof.feeling_lift.mean >= 0 ? "+" : ""}${proof.feeling_lift.mean.toFixed(2)}`} sub="−1 to 1, paired" />
      </div>

      {segKeys.length > 0 && (
        <div>
          <div className="text-[11px] text-muted-foreground mb-1">Where it paid and where it cost</div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {segKeys.slice(0, 4).map((k) => (
              <div key={k} className="rounded-lg border border-border/50 bg-background/40 p-2.5">
                <div className="text-[10px] uppercase tracking-wide text-muted-foreground/70 mb-1">{k.replace(/^dyn:/, "").replace(/_/g, " ")}</div>
                <ul className="space-y-0.5">
                  {proof.by_segment[k].map((b) => (
                    <li key={b.value} className={`flex items-center gap-2 text-[11px] ${b.thin ? "opacity-60" : ""}`}>
                      <span className="w-28 truncate text-foreground/85" title={b.value}>{b.value}</span>
                      <span className="tabular-nums text-muted-foreground w-20">{pct(b.before)} → {pct(b.after)}</span>
                      <span className={`tabular-nums font-medium ${b.lift > 0 ? "text-emerald-300" : b.lift < 0 ? "text-red-300" : "text-muted-foreground"}`}>{pts(b.lift)}</span>
                      <span className="text-[10px] text-muted-foreground">won {b.won} · lost {b.lost} · n={b.n}{b.thin ? " · thin" : ""}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}

      {proof.movers.length > 0 && (
        <div>
          <button type="button" onClick={() => setOpen((v) => !v)} className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground">
            {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />} The people who changed their mind, in their own words ({proof.movers.length})
          </button>
          {open && (
            <ul className="mt-2 space-y-2">
              {proof.movers.map((m) => (
                <li key={m.agent_id} className="text-[11px] leading-relaxed">
                  <span className="text-foreground/95">{m.name}</span><span className="text-muted-foreground"> · {m.role}</span>
                  <span className={`ml-1.5 text-[10px] rounded px-1.5 py-0.5 ${m.kind === "won" ? "bg-emerald-500/10 text-emerald-300" : "bg-red-500/10 text-red-300"}`}>{m.from} → {m.to}</span>
                  <div className="text-muted-foreground mt-0.5">Before: “{m.before_reasoning}”{m.before_put_off && m.before_put_off !== "nothing" ? ` — put off by ${m.before_put_off}` : ""}</div>
                  <div className="text-foreground/80">After: “{m.after_reasoning}”{m.after_put_off && m.after_put_off !== "nothing" ? ` — put off by ${m.after_put_off}` : ""}</div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function Tile({ label, value, sub, good, bad }: { label: string; value: string; sub?: string; good?: boolean; bad?: boolean }) {
  return (
    <div className="rounded-lg bg-background/50 border border-border/40 px-3 py-2">
      <div className="text-[10px] text-muted-foreground">{label}</div>
      <div className={`text-lg font-semibold tabular-nums ${good ? "text-emerald-300" : bad ? "text-red-300" : ""}`}>{value}</div>
      {sub && <div className="text-[10px] text-muted-foreground">{sub}</div>}
    </div>
  );
}
