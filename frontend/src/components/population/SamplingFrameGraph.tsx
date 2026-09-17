"use client";

import { useMemo, useState } from "react";
import { X, Network } from "lucide-react";
import type { Agent, PopulationBuild, PopulationFacet, PopulationFrame } from "@/lib/api";

/**
 * The population map. The cell types are the plan's facets — the 5–15 things a reader needs to
 * understand who is in this population for this question (where they live, what they earn, how
 * they commute …), chosen and ranked per plan. Every persona sits in exactly one cell of every
 * facet, and a cell's size is the number of personas in it. Nothing else moves a node; the map
 * fills in live as personas are written.
 */

interface Props {
  build: PopulationBuild | null;
  /** Kept for the Studio's call; the map draws personas, not targets. */
  frame?: PopulationFrame | null;
  agents: Partial<Agent>[];
  targetCount: number;
  spawning: boolean;
  onClose: () => void;
}

const PALETTE = ["#38bdf8", "#facc15", "#4ade80", "#fb923c", "#f472b6", "#a78bfa", "#2dd4bf", "#fb7185", "#818cf8", "#f59e0b", "#34d399", "#e879f9", "#60a5fa", "#fcd34d", "#c084fc"];

/** What the map falls back to when a plan has no facets (older builds, lineups). */
const ATTRIBUTE_FACETS: PopulationFacet[] = [
  { key: "place", label: "Where they live", why: "", kind: "attribute", attribute: "region", values_hint: [] },
  { key: "age_band", label: "Age band", why: "", kind: "attribute", attribute: "age", values_hint: [] },
  { key: "income", label: "Income band", why: "", kind: "attribute", attribute: "income_band", values_hint: [] },
  { key: "occupation", label: "Occupation", why: "", kind: "attribute", attribute: "occupation", values_hint: [] },
  { key: "gender", label: "Gender", why: "", kind: "attribute", attribute: "gender", values_hint: [] },
  { key: "segment", label: "Segment", why: "", kind: "attribute", attribute: "segment", values_hint: [] },
  { key: "stance", label: "Stance on the topic", why: "", kind: "attribute", attribute: "stance", values_hint: [] },
  { key: "education", label: "Education", why: "", kind: "attribute", attribute: "education", values_hint: [] },
];

function band(h: number): string {
  if (h >= 70) return "reactive"; if (h >= 60) return "defensive"; if (h >= 50) return "balanced"; if (h >= 20) return "tempered"; return "expert";
}

/** The cell an agent sits in for one facet (mirrors the backend's facets.cell_of). */
export function cellOf(f: PopulationFacet, a: Partial<Agent>): string | null {
  const demo = (a.demographics || {}) as Record<string, unknown>;
  if (f.kind === "persona") { const v = (demo.facets as Record<string, string> | undefined)?.[f.key]; return v ? String(v).trim().slice(0, 60) : null; }
  switch (f.attribute) {
    case "age": return typeof a.age === "number" ? `${Math.max(10, Math.floor(a.age / 10) * 10)}s` : null;
    case "register": return band(typeof a.humanity === "number" ? a.humanity : 0);
    case "segment": return a.segment ? String(a.segment) : null;
    case "stance": return a.stance ? String(a.stance) : null;
    case "gender": { const g = demo.gender; return typeof g === "string" && g && !["n/a", "na"].includes(g.toLowerCase()) ? g : null; }
    default: { const v = demo[f.attribute]; return typeof v === "string" && v ? v.trim().slice(0, 60) : null; }
  }
}

interface Cell { id: string; facet: string; label: string; n: number }

function buildMap(facets: PopulationFacet[], agents: Partial<Agent>[]) {
  const cells = new Map<string, Cell>();
  const placed: Record<string, number> = {};
  for (const a of agents) {
    for (const f of facets) {
      const label = cellOf(f, a);
      if (!label) continue;
      const id = `${f.key}:${label.toLowerCase()}`;
      let c = cells.get(id);
      if (!c) { c = { id, facet: f.key, label, n: 0 }; cells.set(id, c); }
      c.n += 1;
      placed[f.key] = (placed[f.key] || 0) + 1;
    }
  }
  return { cells: [...cells.values()], placed };
}

const SHOW_CELLS = 8;   // biggest cells shown per facet; the tail folds into "others"
const D_MIN = 30, D_MAX = 104;

export default function SamplingFrameGraph({ build, agents, targetCount, spawning, onClose }: Props) {
  const all = useMemo<PopulationFacet[]>(() => (build?.plan?.facets?.length ? build.plan.facets : ATTRIBUTE_FACETS), [build]);
  const [topN, setTopN] = useState<number>(Math.min(all.length, 10));
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const facets = useMemo(() => all.slice(0, topN), [all, topN]);
  const { cells, placed } = useMemo(() => buildMap(facets, agents), [facets, agents]);
  const colorOf = useMemo(() => new Map(all.map((f, i) => [f.key, PALETTE[i % PALETTE.length]])), [all]);
  const total = agents.length;
  const maxN = Math.max(1, ...cells.map((c) => c.n));
  const diameter = (n: number) => Math.round(D_MIN + (D_MAX - D_MIN) * Math.sqrt(n / maxN));

  return (
    <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4" onClick={onClose}>
      <div className="w-full max-w-6xl h-[88vh] bg-background border border-border rounded-2xl flex flex-col overflow-hidden shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-border flex items-center gap-3 shrink-0">
          <Network className="w-4 h-4 text-primary" />
          <div className="min-w-0">
            <div className="text-sm font-semibold text-foreground">Who is in this population</div>
            <div className="text-[11px] text-muted-foreground">One panel per facet, most important first. Every persona sits in exactly one cell of every facet; a cell's size is the number of personas in it.</div>
          </div>
          <div className="ml-auto flex items-center gap-3 text-xs">
            {spawning && <span className="flex items-center gap-1.5 text-primary"><span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" /> building live</span>}
            <span className="text-muted-foreground"><span className="text-foreground font-semibold tabular-nums">{total}</span>{targetCount > total ? <> of <span className="text-foreground font-semibold tabular-nums">{targetCount}</span></> : null} personas</span>
            <label className="flex items-center gap-1.5 text-muted-foreground">show
              <select value={topN} onChange={(e) => setTopN(+e.target.value)} className="bg-input border border-border rounded-lg px-2 py-1 text-xs text-foreground">
                {[...new Set([5, 8, 10, 15, all.length].filter((n) => n <= all.length))].sort((a, b) => a - b).map((n) => <option key={n} value={n}>{n === all.length ? `all ${n}` : `top ${n}`}</option>)}
              </select>
            </label>
            <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors" aria-label="Close"><X className="w-4 h-4" /></button>
          </div>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto p-4">
          {total === 0 ? (
            <div className="h-full flex items-center justify-center text-center p-8">
              <div>
                <Network className="w-10 h-10 text-muted-foreground mx-auto mb-3" />
                <p className="text-sm text-muted-foreground">The map fills in as personas are written.</p>
                <p className="text-xs text-muted-foreground/70 mt-1">{all.length} facets are ready for this population: {all.slice(0, 6).map((f) => f.label).join(", ")}{all.length > 6 ? "…" : ""}. Approve the plan to start.</p>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              {facets.map((f, i) => {
                const color = colorOf.get(f.key) || "#94a3b8";
                const mine = cells.filter((c) => c.facet === f.key).sort((a, b) => b.n - a.n || a.label.localeCompare(b.label));
                const open = !!expanded[f.key];
                const shown = open ? mine : mine.slice(0, SHOW_CELLS);
                const rest = mine.slice(shown.length);
                const restN = rest.reduce((s, c) => s + c.n, 0);
                const missing = total - (placed[f.key] || 0);
                return (
                  <div key={f.key} className="rounded-xl border border-border/60 bg-muted/10 px-4 py-3">
                    <div className="flex items-baseline gap-2 mb-2">
                      <span className="text-[10px] text-muted-foreground/60 tabular-nums w-4">{i + 1}</span>
                      <span className="w-2.5 h-2.5 rounded-full shrink-0 self-center" style={{ backgroundColor: color }} />
                      <span className="text-sm font-semibold text-foreground">{f.label}</span>
                      <span className="text-[11px] text-muted-foreground">{mine.length} cell{mine.length === 1 ? "" : "s"}{missing > 0 ? ` · ${missing} not placed` : ""}</span>
                      {f.why && <span className="ml-auto text-[10.5px] text-muted-foreground/60 truncate max-w-[45%]" title={f.why}>{f.why}</span>}
                    </div>
                    {mine.length === 0 ? (
                      <p className="text-[11px] text-muted-foreground/70 py-3">No persona carries this yet.</p>
                    ) : (
                      <div className="flex flex-wrap items-end gap-x-3 gap-y-3">
                        {shown.map((c) => {
                          const d = diameter(c.n);
                          return (
                            <div key={c.id} className="flex flex-col items-center w-[84px]" title={`${c.label}: ${c.n} persona${c.n === 1 ? "" : "s"} (${Math.round((100 * c.n) / total)}%)`}>
                              <div className="rounded-full flex items-center justify-center font-bold text-white transition-all duration-300" style={{ width: d, height: d, backgroundColor: color + "66", boxShadow: `inset 0 0 0 1px ${color}`, fontSize: d > 44 ? 14 : 11 }}>{c.n}</div>
                              <div className="text-[10.5px] text-foreground/85 mt-1 truncate w-full text-center">{c.label}</div>
                              <div className="text-[10px] tabular-nums" style={{ color }}>{Math.round((100 * c.n) / total)}%</div>
                            </div>
                          );
                        })}
                        {rest.length > 0 && (
                          <button onClick={() => setExpanded((e) => ({ ...e, [f.key]: true }))} className="flex flex-col items-center w-[84px] group" title={rest.map((c) => `${c.label} ${c.n}`).join(" · ")}>
                            <div className="rounded-full flex items-center justify-center font-bold text-foreground/80 border border-dashed border-border group-hover:border-foreground/60 transition-colors" style={{ width: diameter(restN), height: diameter(restN), fontSize: diameter(restN) > 44 ? 14 : 11 }}>{restN}</div>
                            <div className="text-[10.5px] text-muted-foreground mt-1 text-center">{rest.length} others</div>
                            <div className="text-[10px] text-muted-foreground/70 tabular-nums">{Math.round((100 * restN) / total)}%</div>
                          </button>
                        )}
                        {open && mine.length > SHOW_CELLS && (
                          <button onClick={() => setExpanded((e) => ({ ...e, [f.key]: false }))} className="self-center text-[10.5px] text-muted-foreground hover:text-foreground">show fewer</button>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
