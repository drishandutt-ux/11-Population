"use client";

/** Ask's own results page: the verdict share, how open the room is, strength and feeling,
 *  the reasons coded into themes, segments, and the answers in their own words. */

import { CategoryBars, MeanStat, SegmentTable, ShareBar, pct } from "../Charts";
import { segmentLabel } from "../filters";
import { InstrumentPageProps } from "./types";

export default function AskPage({ probe, dynamicDials = []}: InstrumentPageProps) {
  const a: any = probe.aggregates;
  if (!a || !a.n) return null;
  const question = probe.spec?.question;

  return (
    <div className="space-y-5">
      {a.headline && (
        <div className="rounded-xl border border-border/60 bg-card/40 p-4">
          {question && <p className="text-xs text-muted-foreground mb-3">“{question}”</p>}
          <ShareBar value={a.headline} label="Yes" />
          <p className="text-xs text-foreground/70 mt-3 leading-relaxed">{a.sentence}</p>
        </div>
      )}

      <div className="grid grid-cols-3 gap-2">
        {a.open_to && (
          <div className="rounded-lg border border-border/60 bg-card/40 px-3 py-2">
            <div className="text-[11px] text-muted-foreground">Open to it (yes or mixed)</div>
            <div className="text-lg font-semibold tabular-nums">{pct(a.open_to.share)}</div>
            <div className="text-[10px] text-muted-foreground tabular-nums">CI {pct(a.open_to.low)}–{pct(a.open_to.high)}</div>
          </div>
        )}
        {a.strength && <MeanStat label="Strength" value={a.strength} suffix="/100" />}
        {a.feeling && <MeanStat label="Feeling (-1…1)" value={a.feeling} />}
      </div>

      <div className="grid grid-cols-2 gap-5">
        {a.verdict && <CategoryBars rows={a.verdict} title="Verdict" />}
        {a.themes?.length > 0
          ? <CategoryBars rows={a.themes} title="What decided it — coded themes" />
          : a.factors?.length > 0 && <CategoryBars rows={a.factors} title="What decided it — in their words" />}
      </div>

      {a.segments && Object.keys(a.segments).length > 0 && (
        <div className="grid grid-cols-2 gap-5">
          {Object.entries(a.segments).map(([key, rows]) => (
            <SegmentTable key={key} title={segmentLabel(key, dynamicDials)} rows={rows as any} />
          ))}
        </div>
      )}

      {a.verbatims && (
        <div className="space-y-3">
          <div className="text-xs text-muted-foreground">In their own words</div>
          {Object.entries(a.verbatims as Record<string, any[]>).map(([bucket, rows]) =>
            rows.length ? (
              <div key={bucket}>
                <div className="text-[11px] uppercase tracking-wide text-muted-foreground/70 mb-1 capitalize">{bucket}</div>
                <div className="space-y-1.5">
                  {rows.map((v) => (
                    <p key={v.agent_id} className="text-xs text-foreground/75 leading-relaxed">
                      <span className="text-foreground/95">{v.name}</span>
                      <span className="text-muted-foreground"> · {v.role}</span>
                      {(v.theme || v.key_factor) && (
                        <span className="ml-1.5 text-[10px] rounded px-1.5 py-0.5 bg-primary/10 text-primary/90">{v.theme || v.key_factor}</span>
                      )}
                      {" "}— “{v.reasoning}”
                    </p>
                  ))}
                </div>
              </div>
            ) : null
          )}
        </div>
      )}
    </div>
  );
}
