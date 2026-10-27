"use client";

/** The Visuals tool's results page (the Visual Lab, step 1, 2026-10-26).
 *
 *  The image they saw comes first, then whether it works on them, what their eyes went to, what
 *  put them off (and how many said nothing did), the deciding factors coded into themes, the
 *  one change each would make, the segment cuts, and the answers in their own words. */

import { ImageRef } from "@/lib/api";
import { CategoryBars, MeanStat, SegmentTable, ShareBar, pct } from "../Charts";
import { segmentLabel } from "../filters";
import { ImageHero } from "../ImagePicker";
import NextVersion from "../NextVersion";
import ProofBlock from "../ProofBlock";
import ConfidenceBadge from "@/components/ConfidenceBadge";
import { InstrumentPageProps } from "./types";

const VERDICT_LABEL: Record<string, string> = { yes: "Works on them", mixed: "Torn", no: "Does not work" };

export default function VisualPage({ probe, dynamicDials = [], agentsById = {}, onOpenTool }: InstrumentPageProps) {
  const a: any = probe.aggregates;
  const images: ImageRef[] = Array.isArray(probe.spec?.images) ? probe.spec.images : [];
  const setting = typeof probe.spec?.setting === "string" ? probe.spec.setting : "";
  const question = probe.spec?.question;
  const retest = probe.spec?.retest && typeof probe.spec.retest === "object" ? probe.spec.retest : null;

  return (
    <div className="space-y-5">
      {retest && (
        <p className="text-[11px] text-muted-foreground">
          This is the re-test of a new version: the same twins who judged the version it came from, answering blind to what they said before.
        </p>
      )}
      {a?.proof && <ProofBlock proof={a.proof} title="What this version did to the same people" />}
      {images.length > 0 && (
        <div className="rounded-xl border border-border/60 bg-card/40 p-4 space-y-2">
          <div className="text-[11px] text-muted-foreground">
            What they saw{setting ? <> · <span className="text-foreground/70">{setting}</span></> : null}
          </div>
          <ImageHero sessionId={probe.session_id} images={images} />
        </div>
      )}

      {!a || !a.n ? null : (
        <>
          {a.headline && (
            <div className="rounded-xl border border-border/60 bg-card/40 p-4">
              {question && <p className="text-xs text-muted-foreground mb-3">“{question}”</p>}
              <ShareBar value={a.headline} label="Works on them" />
              <p className="text-xs text-foreground/70 mt-3 leading-relaxed">{a.sentence}</p>
            </div>
          )}

          {probe.status === "complete" && images.length > 0 && <NextVersion probe={probe} onOpenTool={onOpenTool} />}

          <div className="grid grid-cols-3 gap-2">
            {a.open_to && (
              <div className="rounded-lg border border-border/60 bg-card/40 px-3 py-2">
                <div className="text-[11px] text-muted-foreground">Open to it (yes or torn)</div>
                <div className="text-lg font-semibold tabular-nums">{pct(a.open_to.share)}</div>
                <div className="text-[10px] text-muted-foreground tabular-nums">CI {pct(a.open_to.low)}–{pct(a.open_to.high)}</div>
              </div>
            )}
            {a.strength && <MeanStat label="Strength" value={a.strength} suffix="/100" />}
            {a.feeling && <MeanStat label="Feeling (-1…1)" value={a.feeling} />}
          </div>

          <div className="grid grid-cols-2 gap-5">
            {a.noticed?.length > 0 && (
              <CategoryBars rows={a.noticed} title={a.noticed_coded ? "Where their eyes went first — coded" : "Where their eyes went first — in their words"} />
            )}
            <div className="space-y-2">
              {a.put_off?.length > 0
                ? <CategoryBars rows={a.put_off} title={a.put_off_coded ? "What put them off — coded" : "What put them off — in their words"} />
                : <div className="rounded-xl border border-border/60 bg-card/40 p-4 text-xs text-muted-foreground">Nobody named anything that put them off.</div>}
              {a.nothing_put_off && a.nothing_put_off.n > 0 && (
                <p className="text-[11px] text-muted-foreground px-1">
                  {pct(a.nothing_put_off.share)} said nothing put them off ({a.nothing_put_off.successes} of {a.nothing_put_off.n}).
                </p>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-5">
            {a.verdict && <CategoryBars rows={a.verdict.map((r: any) => ({ ...r, value: VERDICT_LABEL[r.value] || r.value }))} title="Verdict" />}
            {a.themes?.length > 0
              ? <CategoryBars rows={a.themes} title="What decided it — coded themes" />
              : a.factors?.length > 0 && <CategoryBars rows={a.factors} title="What decided it — in their words" />}
          </div>

          {a.changes?.length > 0 && (
            <div className="rounded-xl border border-border/60 bg-card/40 p-4 space-y-2">
              <div className="text-xs text-muted-foreground">The one thing each would change</div>
              <ul className="space-y-1">
                {a.changes.map((c: any) => (
                  <li key={c.agent_id} className="text-xs text-foreground/75 leading-relaxed">
                    <span className="text-foreground/95">{c.name}</span>
                    <span className="text-muted-foreground"> · {c.role}</span>
                    {c.verdict && <span className={`ml-1.5 text-[10px] rounded px-1.5 py-0.5 ${c.verdict === "yes" ? "bg-primary/10 text-primary/90" : c.verdict === "no" ? "bg-red-500/10 text-red-300" : "bg-muted text-muted-foreground"}`}>{VERDICT_LABEL[c.verdict] || c.verdict}</span>}
                    {" "}— “{c.change_one}”
                  </li>
                ))}
              </ul>
            </div>
          )}

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
              {(["yes", "mixed", "no"] as const).map((bucket) => {
                const rows: any[] = a.verbatims[bucket] || [];
                if (!rows.length) return null;
                return (
                  <div key={bucket}>
                    <div className="text-[11px] uppercase tracking-wide text-muted-foreground/70 mb-1">{VERDICT_LABEL[bucket]}</div>
                    <div className="space-y-2">
                      {rows.map((v) => (
                        <div key={v.agent_id} className="text-xs text-foreground/75 leading-relaxed">
                          <p>
                            <span className="text-foreground/95">{v.name}</span>
                            <span className="text-muted-foreground"> · {v.role}</span>
                            {(v.theme || v.key_factor) && (
                              <span className="ml-1.5 text-[10px] rounded px-1.5 py-0.5 bg-primary/10 text-primary/90">{v.theme || v.key_factor}</span>
                            )}
                            {" "}<ConfidenceBadge validation={agentsById[v.agent_id]?.validation} size="xs" />
                            {" "}— “{v.reasoning}”
                          </p>
                          <p className="text-[11px] text-muted-foreground mt-0.5">
                            {v.noticed_first && <>Noticed first: <span className="text-foreground/70">{v.noticed_first}</span>. </>}
                            {v.message_taken && <>Took it to say: <span className="text-foreground/70">{v.message_taken}</span>. </>}
                            {v.put_off && <>Put off by: <span className="text-foreground/70">{v.put_off}</span>.</>}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}
