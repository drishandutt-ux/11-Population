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
interface Link { from: string; to: string; n: number }

function buildMap(facets: PopulationFacet[], agents: Partial<Agent>[]) {
  const cells = new Map<string, Cell>();
  const links = new Map<string, Link>();
  const placed: Record<string, number> = {};
  const segFacet = facets.find((f) => f.attribute === "segment");
  for (const a of agents) {
    const mine: Cell[] = [];
    for (const f of facets) {
      const label = cellOf(f, a);
      if (!label) continue;
      const id = `${f.key}:${label.toLowerCase()}`;
      let c = cells.get(id);
      if (!c) { c = { id, facet: f.key, label, n: 0 }; cells.set(id, c); }
      c.n += 1;
      placed[f.key] = (placed[f.key] || 0) + 1;
      mine.push(c);
    }
    if (segFacet) {
      const s = mine.find((c) => c.facet === segFacet.key);
      if (s) for (const c of mine) if (c !== s) { const k = `${s.id}→${c.id}`; const l = links.get(k) || { from: s.id, to: c.id, n: 0 }; l.n += 1; links.set(k, l); }
    }
  }
  return { cells: [...cells.values()], links: [...links.values()], placed };
}

const VW = 1000, VH = 720, CX = VW / 2, CY = VH / 2, R = 292;

/** Each facet owns an arc of the ring, in rank order; its cells sit along the arc, biggest first. */
function layout(facets: PopulationFacet[], cells: Cell[]) {
  const pos = new Map<string, { x: number; y: number }>();
  const arcs: { key: string; label: string; mid: number }[] = [];
  const groups = facets.map((f) => cells.filter((c) => c.facet === f.key).sort((a, b) => b.n - a.n)).filter((g) => g.length > 0);
  const total = groups.reduce((s, g) => s + g.length, 0) || 1;
  let a0 = -Math.PI / 2;
  for (const g of groups) {
    const span = (2 * Math.PI * g.length) / total;
    g.forEach((c, i) => {
      const a = a0 + (span * (i + 0.5)) / g.length;
      pos.set(c.id, { x: CX + R * Math.cos(a), y: CY + R * 0.9 * Math.sin(a) });
    });
    arcs.push({ key: g[0].facet, label: facets.find((f) => f.key === g[0].facet)?.label || g[0].facet, mid: a0 + span / 2 });
    a0 += span;
  }
  return { pos, arcs };
}

export default function SamplingFrameGraph({ build, agents, targetCount, spawning, onClose }: Props) {
  const all = useMemo<PopulationFacet[]>(() => (build?.plan?.facets?.length ? build.plan.facets : ATTRIBUTE_FACETS), [build]);
  const [topN, setTopN] = useState<number>(Math.min(all.length, 10));
  const [only, setOnly] = useState<string | null>(null);
  const facets = useMemo(() => all.slice(0, topN), [all, topN]);
  const shownFacets = useMemo(() => (only ? facets.filter((f) => f.key === only) : facets), [facets, only]);
  const { cells, links, placed } = useMemo(() => buildMap(facets, agents), [facets, agents]);
  const shownCells = useMemo(() => cells.filter((c) => !only || c.facet === only), [cells, only]);
  const shownIds = useMemo(() => new Set(shownCells.map((c) => c.id)), [shownCells]);
  const { pos, arcs } = useMemo(() => layout(shownFacets, shownCells), [shownFacets, shownCells]);
  const colorOf = useMemo(() => new Map(all.map((f, i) => [f.key, PALETTE[i % PALETTE.length]])), [all]);
  const maxN = Math.max(1, ...shownCells.map((c) => c.n));
  const radius = (n: number) => 8 + 42 * Math.sqrt(n / maxN);
  const total = agents.length;

  return (
    <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4" onClick={onClose}>
      <div className="w-full max-w-6xl h-[88vh] bg-background border border-border rounded-2xl flex flex-col overflow-hidden shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-border flex items-center gap-3 shrink-0">
          <Network className="w-4 h-4 text-primary" />
          <div className="min-w-0">
            <div className="text-sm font-semibold text-foreground">Who is in this population</div>
            <div className="text-[11px] text-muted-foreground">Every persona sits in exactly one cell of every facet. A cell's size is the number of personas in it, and nothing else.</div>
          </div>
          <div className="ml-auto flex items-center gap-3 text-xs">
            {spawning && <span className="flex items-center gap-1.5 text-primary"><span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" /> building live</span>}
            <span className="text-muted-foreground"><span className="text-foreground font-semibold tabular-nums">{total}</span>{targetCount > total ? <> of <span className="text-foreground font-semibold tabular-nums">{targetCount}</span></> : null} personas</span>
            <label className="flex items-center gap-1.5 text-muted-foreground">show
              <select value={topN} onChange={(e) => { setTopN(+e.target.value); setOnly(null); }} className="bg-input border border-border rounded-lg px-2 py-1 text-xs text-foreground">
                {[5, 8, 10, 15].filter((n) => n <= all.length || n === 5).map((n) => <option key={n} value={Math.min(n, all.length)}>top {Math.min(n, all.length)}</option>)}
              </select>
            </label>
            <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors" aria-label="Close"><X className="w-4 h-4" /></button>
          </div>
        </div>

        <div className="flex-1 min-h-0 flex">
          <div className="flex-1 min-w-0 relative">
            {total === 0 ? (
              <div className="absolute inset-0 flex items-center justify-center text-center p-8">
                <div>
                  <Network className="w-10 h-10 text-muted-foreground mx-auto mb-3" />
                  <p className="text-sm text-muted-foreground">The map fills in as personas are written.</p>
                  <p className="text-xs text-muted-foreground/70 mt-1">{all.length} facets are ready for this population: {all.slice(0, 6).map((f) => f.label).join(", ")}{all.length > 6 ? "…" : ""}. Approve the plan to start.</p>
                </div>
              </div>
            ) : (
              <svg width="100%" height="100%" viewBox={`0 0 ${VW} ${VH}`} preserveAspectRatio="xMidYMid meet" className="absolute inset-0">
                {links.filter((l) => shownIds.has(l.from) && shownIds.has(l.to)).map((l) => {
                  const a = pos.get(l.from), b = pos.get(l.to);
                  if (!a || !b) return null;
                  return <line key={`${l.from}-${l.to}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="rgba(255,255,255,0.07)" strokeWidth={0.5 + 3 * Math.sqrt(l.n / maxN)} />;
                })}
                {arcs.map((arc) => {
                  const x = CX + (R + 62) * Math.cos(arc.mid), y = CY + (R * 0.9 + 62) * Math.sin(arc.mid);
                  return <text key={arc.key} x={x} y={y} textAnchor="middle" fill={colorOf.get(arc.key) || "#94a3b8"} fillOpacity={0.85} fontSize={11} fontWeight={600} fontFamily="system-ui">{arc.label}</text>;
                })}
                {shownCells.map((c) => {
                  const p = pos.get(c.id);
                  if (!p) return null;
                  const color = colorOf.get(c.facet) || "#94a3b8";
                  const r = radius(c.n);
                  return (
                    <g key={c.id} transform={`translate(${p.x}, ${p.y})`}>
                      <circle r={r} fill={color} fillOpacity={0.4} stroke={color} strokeWidth={1} style={{ transition: "r 400ms ease" }} />
                      <text y={4} textAnchor="middle" fill="#fff" fontSize={r > 16 ? 12 : 9} fontWeight={700} fontFamily="system-ui">{c.n}</text>
                      <text y={r + 13} textAnchor="middle" fill="rgba(255,255,255,0.85)" fontSize={10} fontFamily="system-ui">{c.label.length > 20 ? c.label.slice(0, 19) + "…" : c.label}</text>
                      <text y={r + 24} textAnchor="middle" fill={color} fillOpacity={0.8} fontSize={9} fontFamily="system-ui">{Math.round((100 * c.n) / total)}%</text>
                    </g>
                  );
                })}
              </svg>
            )}
          </div>
          <div className="w-72 shrink-0 border-l border-border p-4 overflow-y-auto">
            <div className="text-[10.5px] uppercase tracking-wide text-muted-foreground mb-2">Facets, most important first · click to focus</div>
            <div className="space-y-1">
              {facets.map((f, i) => {
                const mine = cells.filter((c) => c.facet === f.key);
                const on = only === f.key;
                const missing = total - (placed[f.key] || 0);
                return (
                  <button key={f.key} onClick={() => setOnly(on ? null : f.key)} title={f.why} className={`w-full text-left rounded-lg px-2 py-1.5 border transition-colors ${on ? "border-white/40 bg-muted/40" : "border-transparent hover:border-border"}`}>
                    <div className="flex items-center gap-2 text-xs">
                      <span className="text-[10px] text-muted-foreground/60 w-4 tabular-nums">{i + 1}</span>
                      <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: colorOf.get(f.key) }} />
                      <span className="text-foreground/90 flex-1 truncate">{f.label}</span>
                      <span className="text-muted-foreground tabular-nums">{mine.length} cell{mine.length === 1 ? "" : "s"}</span>
                    </div>
                    <div className="ml-[38px] text-[10.5px] text-muted-foreground/70 truncate">
                      {mine.length ? mine.slice(0, 4).map((c) => `${c.label} ${c.n}`).join(" · ") + (mine.length > 4 ? " · …" : "") : total ? "no persona carries this yet" : "—"}
                      {missing > 0 && mine.length ? ` · ${missing} not placed` : ""}
                    </div>
                  </button>
                );
              })}
            </div>
            <p className="text-[10.5px] text-muted-foreground/70 leading-snug mt-4">The facets are chosen per question when the plan is composed — what a reader needs to understand this population — and ranked. The number in a cell is personas; the percentage is of the whole population.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
