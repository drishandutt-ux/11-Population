"use client";

/** Purchase intent's own results page.
 *
 *  Everything here is specific to this tool — the decision split, the driver mix, the demand
 *  curve built from each agent's walk-away price, and the consistency check between what they
 *  said and what they would actually pay. No other instrument inherits any of it. */

import { CategoryBars, DemandCurve, MeanStat, SegmentTable, ShareBar, pct } from "../Charts";
import { InstrumentPageProps } from "./types";

export default function PurchaseIntentPage({ probe }: InstrumentPageProps) {
  const a = probe.aggregates;
  if (!a || !a.n) return null;
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
          <span className="text-foreground/80">{pct(a.at_asking_price.share)}</span> have a walk-away price at or
          above the asking price
          {a.consistency && a.consistency.contradictions > 0 && (
            <> · <span className="text-amber-400">{a.consistency.contradictions}</span>{" "}
              {a.consistency.note.toLowerCase()}</>
          )}
        </div>
      )}

      <div className="grid grid-cols-2 gap-5">
        {a.would_buy && <CategoryBars rows={a.would_buy} title="Decision" />}
        {a.drivers && <CategoryBars rows={a.drivers} title="What decided it" />}
      </div>

      {a.demand_curve && a.demand_curve.length > 0 && (
        <div className="rounded-xl border border-border/60 bg-card/40 p-4">
          <DemandCurve
            curve={a.demand_curve}
            currency={currency}
            askingPrice={probe.spec?.price ?? null}
            optimal={a.optimal_price ?? null}
          />
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
    </div>
  );
}
