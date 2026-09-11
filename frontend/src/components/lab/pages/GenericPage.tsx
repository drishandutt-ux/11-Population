"use client";

/** Fallback results view for an instrument with no page of its own.
 *
 *  A new instrument is usable the moment its backend file exists: it renders its declared
 *  KPIs, its plain-language sentence and any distributions its aggregator produced, without
 *  waiting for bespoke UI. Tools graduate to their own page when they earn one. */

import { Interval, MeanInterval } from "@/lib/api";
import { CategoryBars, MeanStat, ShareBar, money } from "../Charts";
import { InstrumentPageProps } from "./types";

const isInterval = (v: any): v is Interval =>
  v && typeof v === "object" && typeof v.share === "number" && typeof v.low === "number";
const isMean = (v: any): v is MeanInterval =>
  v && typeof v === "object" && typeof v.mean === "number" && typeof v.median === "number";
const isDistribution = (v: any) =>
  Array.isArray(v) && v.length > 0 && typeof v[0]?.value !== "undefined" && typeof v[0]?.share === "number";

export default function GenericPage({ instrument, probe }: InstrumentPageProps) {
  const agg: Record<string, any> = probe.aggregates || {};

  return (
    <div className="space-y-5">
      {agg.headline && isInterval(agg.headline) && (
        <div className="rounded-xl border border-border/60 bg-card/40 p-4">
          <ShareBar value={agg.headline} label={(agg.headline as any).label || instrument.label} />
          {agg.sentence && <p className="text-xs text-foreground/70 mt-3 leading-relaxed">{agg.sentence}</p>}
        </div>
      )}

      {/* KPIs the instrument declared, in the order it declared them. */}
      <div className="grid grid-cols-3 gap-2">
        {instrument.kpis.map((k) => {
          const v = agg[k.key];
          if (isMean(v)) {
            return <MeanStat key={k.key} label={k.label} value={v} currency={k.format === "money" ? (v as any).currency || "GBP" : undefined} />;
          }
          if (isInterval(v)) {
            return (
              <div key={k.key} className="rounded-lg border border-border/60 bg-card/40 px-3 py-2">
                <div className="text-[11px] text-muted-foreground">{k.label}</div>
                <div className="text-lg font-semibold tabular-nums">{Math.round(v.share * 100)}%</div>
              </div>
            );
          }
          if (typeof v === "number") {
            return (
              <div key={k.key} className="rounded-lg border border-border/60 bg-card/40 px-3 py-2">
                <div className="text-[11px] text-muted-foreground">{k.label}</div>
                <div className="text-lg font-semibold tabular-nums">
                  {k.format === "money" ? money(v) : v}
                </div>
              </div>
            );
          }
          return null;
        })}
      </div>

      {/* Any distribution the aggregator produced, rendered without knowing what it means. */}
      <div className="grid grid-cols-2 gap-5">
        {Object.entries(agg).map(([key, value]) =>
          isDistribution(value) ? (
            <CategoryBars key={key} rows={value as any} title={key.replace(/_/g, " ")} />
          ) : null
        )}
      </div>

      <p className="text-[10px] text-muted-foreground/60">
        Generic view — this instrument has no results page of its own yet.
      </p>
    </div>
  );
}
