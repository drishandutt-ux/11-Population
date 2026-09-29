"use client";

import { useRef, useState } from "react";
import { AlertTriangle, Check, Loader2, Sparkles, Upload, ChevronDown } from "lucide-react";
import type { FrameCategory, FrameReportCell, PopulationBuild } from "@/lib/api";

/**
 * The sampling frame: the dimensions this population must match, where each distribution
 * came from (found · proxy · uploaded · estimated · skipped · missing), the ladder for every
 * gap, and the representativeness report — target vs planned vs achieved per cell, which
 * dimensions are matched exactly and which only weighted, thin cells, effective sample size.
 */

interface Props {
  build: PopulationBuild;
  busy: boolean;
  readOnly: boolean;
  onAction: (dimKey: string, body: { action: "estimate" | "upload" | "proxy" | "skip"; categories?: FrameCategory[]; source?: string; proxy_of?: string }) => Promise<void>;
  onEstimateAll: () => Promise<void>;
}

const STATUS_META: Record<string, { label: string; cls: string }> = {
  found: { label: "found", cls: "chip-ok" },
  proxy: { label: "proxy", cls: "chip-info" },
  uploaded: { label: "uploaded", cls: "chip-warn" },
  estimated: { label: "model estimate", cls: "chip-warn" },
  skipped: { label: "skipped", cls: "" },
  missing: { label: "no distribution", cls: "chip-bad" },
};
const MODE_META: Record<string, string> = { exact: "matched exactly", weighted: "weighted only", unmatched: "not matched" };
const LEVEL_CLS: Record<string, string> = { good: "chip-ok", fair: "chip-warn", poor: "chip-bad", none: "" };

function parseCsv(text: string): FrameCategory[] {
  const out: FrameCategory[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || /^(label|category)\b/i.test(line)) continue;
    const parts = line.split(/[,\t;]/).map((p) => p.trim().replace(/^"|"$/g, ""));
    if (parts.length < 2) continue;
    const share = parseFloat(parts[1].replace("%", ""));
    if (!parts[0] || Number.isNaN(share)) continue;
    const m = parts[0].match(/^(\d{1,3})\s*(?:-|–|to)\s*(\d{1,3})/);
    const plus = parts[0].match(/^(\d{1,3})\s*\+/);
    out.push({ label: parts[0], share_pct: share, age_min: m ? +m[1] : plus ? +plus[1] : 0, age_max: m ? +m[2] : plus ? 120 : 0 });
  }
  return out;
}

function Bar({ cell, stage }: { cell: FrameReportCell; stage: "planned" | "achieved" }) {
  const have = stage === "achieved" && cell.achieved_pct !== null ? cell.achieved_pct : cell.planned_pct;
  const max = Math.max(cell.target_pct, have, 1);
  const off = Math.abs(have - cell.target_pct);
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_120px_72px] items-center gap-2 text-xs">
      <span className="truncate text-foreground/85" title={cell.label}>{cell.label}{cell.thin && <span className="ml-1 text-amber-300" title="Too few agents to cut by">thin</span>}</span>
      <div className="relative h-1.5 bg-border/70 rounded-full">
        <div className={`absolute inset-y-0 left-0 rounded-full ${off <= 5 ? "bg-emerald-400/70" : off <= 12 ? "bg-amber-400/70" : "bg-red-400/70"}`} style={{ width: `${(100 * have) / max}%` }} />
        <div className="absolute -inset-y-[2px] w-0.5 bg-foreground/80 rounded" style={{ left: `calc(${(100 * cell.target_pct) / max}% - 1px)` }} title={`target ${cell.target_pct}%`} />
      </div>
      <span className="text-right tabular-nums text-muted-foreground">{have.toFixed(0)}% <span className="text-muted-foreground/50">/ {cell.target_pct.toFixed(0)}%</span></span>
    </div>
  );
}

export default function FrameCard({ build, busy, readOnly, onAction, onEstimateAll }: Props) {
  const frame = build.frame!;
  const report = frame.report;
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [proxyPick, setProxyPick] = useState<Record<string, string>>({});
  const [uploadSource, setUploadSource] = useState<Record<string, string>>({});
  const [working, setWorking] = useState<string | null>(null);
  const fileRefs = useRef<Record<string, HTMLInputElement | null>>({});

  const dims = frame.dimensions || [];
  const targets = frame.targets || {};
  const gaps = dims.filter((d) => (targets[d.key]?.status || "missing") === "missing");
  const withData = dims.filter((d) => ["found", "proxy", "uploaded", "estimated"].includes(targets[d.key]?.status || ""));

  async function act(key: string, body: Parameters<typeof onAction>[1]) {
    setWorking(key);
    try { await onAction(key, body); } finally { setWorking(null); }
  }

  async function onFile(key: string, file: File | null) {
    if (!file) return;
    const text = await file.text();
    const categories = parseCsv(text);
    if (categories.length < 2) { alert("The file needs at least two rows of `category, share`."); return; }
    await act(key, { action: "upload", categories, source: uploadSource[key] || file.name });
  }

  return (
    <div className="surface rounded-xl p-5 space-y-4 animate-fade-in">
      <div className="flex items-center gap-2 flex-wrap">
        <h3 className="text-[15px] font-semibold text-foreground tracking-tight">Sampling frame</h3>
        {report && report.level !== "none" && (
          <span className={`chip ${LEVEL_CLS[report.level]}`}>
            {report.stage === "achieved" ? "built" : "plan"} · {report.level} · worst cell {report.worst_deviation_pts} pts off
          </span>
        )}
        {report?.ess != null && report.n != null && (
          <span className="chip" title="Effective sample size after weighting: how many real people this panel is honestly worth">
            effective n {report.ess} of {report.n}
          </span>
        )}
        <span className="ml-auto text-[11px] text-muted-foreground/70">{frame.geography || ""}</span>
      </div>
      <p className="hint -mt-1">
        The dimensions this population must be representative on, most important first. The top three are matched exactly; the rest are corrected by weighting. Every distribution says where it came from.
      </p>

      {/* sizing funnel: TAM / SAM / SOM */}
      {frame.sizing && (
        <div className="grid grid-cols-3 gap-2">
          {(["tam", "sam", "som"] as const).map((k) => {
            const c = frame.sizing![k] || {};
            const title = { tam: "Everyone in the place", sam: "With the condition / in scope", som: "Reached by the system today" }[k];
            return (
              <div key={k} className={`rounded-lg px-3 py-2.5 ${c.value ? "surface-raised" : "border border-dashed border-border"}`} title={c.label || title}>
                <div className="text-[10.5px] text-muted-foreground"><span className="uppercase tracking-wide font-medium text-muted-foreground/80">{k}</span> · {title}</div>
                {c.value ? (
                  <>
                    <div className="text-base font-semibold text-foreground tabular-nums mt-0.5">{c.value}</div>
                    <div className="text-[10.5px] text-muted-foreground/80 truncate">{c.label}{c.source ? ` · ${c.source}` : ""}{c.year ? ` ${c.year}` : ""}</div>
                  </>
                ) : (
                  <div className="text-xs text-muted-foreground/50 mt-1">not on file</div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* dimensions */}
      <div className="space-y-2">
        {dims.map((d, k) => {
          const t = targets[d.key] || { status: "missing", categories: [], source: "", year: "", geography: "", proxy_attribute: "other", note: "" };
          const meta = STATUS_META[t.status] || STATUS_META.missing;
          const rep = report?.dimensions.find((r) => r.key === d.key);
          const isGap = t.status === "missing";
          const expanded = !!open[d.key];
          return (
            <div key={d.key} className={`rounded-lg px-4 py-3 space-y-2 ${isGap ? "bg-red-500/[0.05] ring-1 ring-red-500/15" : "surface-raised"}`}>
              <div className="flex items-start gap-3">
                <span className="text-[11px] font-medium text-muted-foreground/50 w-3 pt-0.5 tabular-nums">{k + 1}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-[13px] font-medium text-foreground">{d.label}</span>
                    <span className={`chip ${meta.cls}`}>{meta.label}</span>
                    {d.equity && <span className="chip chip-violet" title="Equity by default: every result is reported by deprivation level as well as the headline">equity · always on</span>}
                    {rep && rep.mode !== "unmatched" && <span className="chip chip-outline">{MODE_META[rep.mode]}</span>}
                    {t.status === "proxy" && <span className="text-[11px] text-sky-300/80">via {t.proxy_attribute}</span>}
                    {d.kind === "attitudinal" && <span className="text-[11px] text-muted-foreground/60">attitudinal</span>}
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5">{d.why}</p>
                  {t.status !== "missing" && t.status !== "skipped" && (
                    <p className="text-[11px] text-muted-foreground/80 mt-0.5">
                      <span className="text-foreground/70">{t.source || "—"}</span>{t.geography ? ` · ${t.geography}` : ""}{t.year ? ` · ${t.year}` : ""}
                      {t.status === "estimated" && typeof t.confidence === "number" ? ` · confidence ${t.confidence}%` : ""}
                      {t.note && t.status === "estimated" ? <span className="block italic text-amber-300/70">{t.note}</span> : null}
                    </p>
                  )}
                  {t.status === "skipped" && <p className="text-[11px] text-muted-foreground/70 mt-0.5">{t.note}</p>}
                </div>
                {(t.categories?.length || 0) > 0 && (
                  <button onClick={() => setOpen((o) => ({ ...o, [d.key]: !o[d.key] }))} className="btn btn-xs btn-ghost shrink-0"><ChevronDown className={`w-3 h-3 transition-transform ${expanded ? "rotate-180" : ""}`} /> {t.categories.length} cells</button>
                )}
              </div>

              {/* cells: target vs planned/achieved */}
              {expanded && (
                <div className="space-y-1 pl-6 animate-fade-in">
                  {rep?.cells ? rep.cells.map((c) => <Bar key={c.label} cell={c} stage={report!.stage} />) :
                    t.categories.map((c) => (
                      <div key={c.label} className="grid grid-cols-[minmax(0,1fr)_64px] text-xs"><span className="truncate text-foreground/85">{c.label}</span><span className="text-right tabular-nums text-muted-foreground">{c.share_pct}%</span></div>
                    ))}
                  {rep && rep.unplaced ? <p className="text-[11px] text-muted-foreground/60">{rep.unplaced} agent{rep.unplaced === 1 ? "" : "s"} could not be placed in a cell</p> : null}
                </div>
              )}

              {/* the ladder */}
              {isGap && !readOnly && (
                <div className="pl-6 space-y-2">
                  <p className="text-xs text-red-200/80">No published distribution found for {frame.geography || "this place"}. Choose how to fill it:</p>
                  <div className="flex flex-wrap gap-1.5 items-center">
                    <button disabled={busy || working === d.key} onClick={() => act(d.key, { action: "estimate" })} className="btn btn-xs btn-secondary" title="The model states a distribution from what it knows — labelled as a model estimate everywhere, lowers confidence; it will decline attitudinal dimensions">
                      {working === d.key ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />} Model estimate
                    </button>
                    <input ref={(el) => { fileRefs.current[d.key] = el; }} type="file" accept=".csv,.txt,.tsv" className="hidden" onChange={(e) => onFile(d.key, e.target.files?.[0] || null)} />
                    <button disabled={busy || working === d.key} onClick={() => fileRefs.current[d.key]?.click()} className="btn btn-xs btn-secondary" title="A CSV of `category, share` — a client panel, a crosstab, a spreadsheet">
                      <Upload className="w-3 h-3" /> Upload a table
                    </button>
                    <input value={uploadSource[d.key] || ""} onChange={(e) => setUploadSource((s) => ({ ...s, [d.key]: e.target.value }))} placeholder="source of the upload (optional)" className="field field-sm w-44 py-1" />
                    {withData.length > 0 && (
                      <span className="flex items-center gap-1">
                        <select value={proxyPick[d.key] || ""} onChange={(e) => setProxyPick((s) => ({ ...s, [d.key]: e.target.value }))} className="field field-sm w-auto py-1">
                          <option value="">use a proxy…</option>
                          {withData.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
                        </select>
                        <button disabled={busy || !proxyPick[d.key]} onClick={() => act(d.key, { action: "proxy", proxy_of: proxyPick[d.key] })} className="btn btn-xs btn-secondary">Use</button>
                      </span>
                    )}
                    <button disabled={busy} onClick={() => act(d.key, { action: "skip" })} className="btn btn-xs btn-ghost" title="Don't match on it; weight only where a later source appears">Skip</button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {gaps.length > 0 && !readOnly && (
        <div className="flex items-center gap-3 flex-wrap">
          <button disabled={busy} onClick={onEstimateAll} className="btn btn-sm btn-secondary">
            <Sparkles className="w-3 h-3" /> Use the model&apos;s estimate for all {gaps.length} gap{gaps.length === 1 ? "" : "s"}
          </button>
          <span className="hint">Each will be labelled as a model estimate; the model declines attitudinal ones.</span>
        </div>
      )}

      {/* report summary */}
      {report && report.level !== "none" && (
        <div className="border-t hairline pt-3 space-y-1.5 text-xs">
          <div className="flex items-center gap-2 flex-wrap text-muted-foreground">
            <Check className="w-3 h-3 text-emerald-400" />
            <span>Matched exactly: <span className="text-foreground/85">{report.matched_exactly.join(", ") || "none"}</span></span>
            <span>· weighted: <span className="text-foreground/85">{report.weighted_only.join(", ") || "none"}</span></span>
            {report.unmatched.length > 0 && <span>· not matched: <span className="text-foreground/85">{report.unmatched.join(", ")}</span></span>}
          </div>
          {report.estimated.length > 0 && (
            <div className="flex items-start gap-2 text-amber-300/90"><AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" /> Model-estimated distributions: {report.estimated.join(", ")}. The report will say so, and confidence is lower for it.</div>
          )}
          {report.thin_cells.length > 0 && (
            <div className="flex items-start gap-2 text-amber-300/90"><AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" /> Not safe to cut by (too few agents): {report.thin_cells.join("; ")}</div>
          )}
          {report.stage === "planned" && <p className="text-muted-foreground/70">Planned shares come from the segments; the built roster is checked again after Approve &amp; build, and weights are computed then.</p>}
        </div>
      )}
    </div>
  );
}
