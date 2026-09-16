"use client";

import { useMemo } from "react";
import { X, Network } from "lucide-react";
import type { Agent, PopulationBuild } from "@/lib/api";

/**
 * The sampling frame as a graph. Nodes are the cells the population is drawn from — the plan's
 * segments and the attributes they fix (place, age band, gender, income, education, occupation,
 * stance, mood). Every node inflates with the personas in it: a dashed ring for what the plan
 * intends, a filled disc for the personas actually written so far, so during a build the discs
 * grow inside their rings in real time. Only personas count — nothing else moves a node.
 */

interface Props {
  build: PopulationBuild | null;
  agents: Partial<Agent>[];
  targetCount: number;
  spawning: boolean;
  onClose: () => void;
}

type NodeType = "segment" | "region" | "age" | "gender" | "income" | "education" | "occupation" | "stance" | "mood" | "hinted";

const TYPE_META: Record<NodeType, { label: string; color: string }> = {
  segment: { label: "Segment", color: "#2dd4bf" },
  region: { label: "Place", color: "#38bdf8" },
  age: { label: "Age band", color: "#facc15" },
  gender: { label: "Gender", color: "#f472b6" },
  income: { label: "Income", color: "#4ade80" },
  education: { label: "Education", color: "#a78bfa" },
  occupation: { label: "Occupation", color: "#fb923c" },
  stance: { label: "Stance", color: "#818cf8" },
  mood: { label: "Mood", color: "#fb7185" },
  hinted: { label: "Group implied by the inputs", color: "#94a3b8" },
};
const OUTER_ORDER: NodeType[] = ["region", "age", "gender", "income", "education", "occupation", "stance", "mood"];

interface FrameNode { id: string; type: NodeType; label: string; planned: number; actual: number }
interface FrameEdge { from: string; to: string; planned: number; actual: number }

function norm(s: string) { return s.trim().toLowerCase(); }
function ageBand(age: number) { const lo = Math.max(10, Math.floor(age / 10) * 10); return `${lo}s`; }
function bandsFor(min?: number, max?: number): string[] {
  if (!min || !max || max < min) return [];
  const out: string[] = [];
  for (let a = Math.floor(min / 10) * 10; a <= max; a += 10) out.push(`${Math.max(10, a)}s`);
  return [...new Set(out)];
}

export function buildFrame(build: PopulationBuild | null, agents: Partial<Agent>[], targetCount: number): { nodes: FrameNode[]; edges: FrameEdge[] } {
  const nodes = new Map<string, FrameNode>();
  const edges = new Map<string, FrameEdge>();
  const node = (type: NodeType, raw: string): FrameNode => {
    const id = `${type}:${norm(raw)}`;
    let n = nodes.get(id);
    if (!n) { n = { id, type, label: raw.trim(), planned: 0, actual: 0 }; nodes.set(id, n); }
    return n;
  };
  const edge = (from: FrameNode, to: FrameNode): FrameEdge => {
    const key = `${from.id}→${to.id}`;
    let e = edges.get(key);
    if (!e) { e = { from: from.id, to: to.id, planned: 0, actual: 0 }; edges.set(key, e); }
    return e;
  };

  // Planned: the plan's kept segments and the attributes each one fixes.
  const segments = (build?.plan?.segments || []).filter((s) => s.decision !== "rejected");
  for (const seg of segments) {
    const count = seg.count ?? Math.round(((seg.share_pct || 0) / 100) * targetCount);
    const sNode = node("segment", seg.name);
    sNode.planned += count;
    const d = seg.demographics || {};
    const spread = (type: NodeType, values: string[] | undefined) => {
      const vals = (values || []).filter(Boolean);
      for (const v of vals) { const n = node(type, v); const share = count / vals.length; n.planned += share; edge(sNode, n).planned += share; }
    };
    spread("region", d.regions);
    spread("age", bandsFor(d.age_min, d.age_max));
    if (typeof d.gender_female_pct === "number") {
      const f = (count * d.gender_female_pct) / 100;
      const fn = node("gender", "female"); fn.planned += f; edge(sNode, fn).planned += f;
      const mn = node("gender", "male"); mn.planned += count - f; edge(sNode, mn).planned += count - f;
    }
    if (d.income_band) spread("income", [d.income_band]);
    if (d.education) spread("education", [d.education]);
    spread("occupation", d.occupations);
    spread("stance", [seg.stance]);
    if (seg.sentiment?.mood) spread("mood", [seg.sentiment.mood]);
  }
  if (segments.length === 0) {
    for (const g of build?.detected?.segments_hinted || []) node("hinted", g);
  }

  // Actual: every persona written so far, by what it carries.
  for (const a of agents) {
    const sNode = a.segment ? node("segment", a.segment) : null;
    if (sNode) sNode.actual += 1;
    const demo = (a.demographics || {}) as Record<string, string | undefined>;
    const bump = (type: NodeType, raw?: string | null) => {
      if (!raw) return;
      const n = node(type, raw);
      n.actual += 1;
      if (sNode) edge(sNode, n).actual += 1;
    };
    bump("region", demo.region);
    bump("age", typeof a.age === "number" ? ageBand(a.age) : undefined);
    bump("gender", demo.gender && demo.gender !== "n/a" ? demo.gender : undefined);
    bump("income", demo.income_band);
    bump("education", demo.education);
    bump("occupation", demo.occupation);
    bump("stance", a.stance as string | undefined);
  }
  return { nodes: [...nodes.values()], edges: [...edges.values()] };
}

const VW = 1000, VH = 720, CX = VW / 2, CY = VH / 2;

function layout(nodes: FrameNode[]) {
  const segs = nodes.filter((n) => n.type === "segment" || n.type === "hinted");
  const outer = OUTER_ORDER.flatMap((t) => nodes.filter((n) => n.type === t));
  const pos = new Map<string, { x: number; y: number }>();
  const rIn = segs.length <= 1 ? 0 : 150, rOut = 300;
  segs.forEach((n, i) => { const a = (i / Math.max(1, segs.length)) * 2 * Math.PI - Math.PI / 2; pos.set(n.id, { x: CX + rIn * Math.cos(a), y: CY + rIn * Math.sin(a) }); });
  outer.forEach((n, i) => { const a = (i / Math.max(1, outer.length)) * 2 * Math.PI - Math.PI / 2; pos.set(n.id, { x: CX + rOut * Math.cos(a), y: CY + (rOut * 0.92) * Math.sin(a) }); });
  return pos;
}

export default function SamplingFrameGraph({ build, agents, targetCount, spawning, onClose }: Props) {
  const { nodes, edges } = useMemo(() => buildFrame(build, agents, targetCount), [build, agents, targetCount]);
  const pos = useMemo(() => layout(nodes), [nodes]);
  const maxV = Math.max(1, ...nodes.map((n) => Math.max(n.planned, n.actual)));
  const radius = (v: number) => (v <= 0 ? 0 : 7 + 40 * Math.sqrt(v / maxV));
  const plannedTotal = Math.round(nodes.filter((n) => n.type === "segment").reduce((s, n) => s + n.planned, 0));
  const actualTotal = agents.length;
  const typesPresent = [...new Set(nodes.map((n) => n.type))];
  const empty = nodes.length === 0;

  return (
    <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4" onClick={onClose}>
      <div className="w-full max-w-6xl h-[88vh] bg-background border border-border rounded-2xl flex flex-col overflow-hidden shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-border flex items-center gap-3 shrink-0">
          <Network className="w-4 h-4 text-primary" />
          <div className="min-w-0">
            <div className="text-sm font-semibold text-foreground">Sampling frame</div>
            <div className="text-[11px] text-muted-foreground">Every cell the population is drawn from. Dashed ring = what the plan intends · filled disc = personas written so far.</div>
          </div>
          <div className="ml-auto flex items-center gap-3 text-xs">
            {spawning && <span className="flex items-center gap-1.5 text-primary"><span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" /> building live</span>}
            <span className="text-muted-foreground"><span className="text-foreground font-semibold tabular-nums">{actualTotal}</span> of <span className="text-foreground font-semibold tabular-nums">{plannedTotal || targetCount}</span> personas</span>
            <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors" aria-label="Close"><X className="w-4 h-4" /></button>
          </div>
        </div>

        <div className="flex-1 min-h-0 flex">
          <div className="flex-1 min-w-0 relative">
            {empty ? (
              <div className="absolute inset-0 flex items-center justify-center text-center p-8">
                <div>
                  <Network className="w-10 h-10 text-muted-foreground mx-auto mb-3" />
                  <p className="text-sm text-muted-foreground">The frame appears as soon as the plan names its segments.</p>
                  <p className="text-xs text-muted-foreground/70 mt-1">Detect runs first; the groups it implies show up here, then the plan turns them into cells with counts.</p>
                </div>
              </div>
            ) : (
              <svg width="100%" height="100%" viewBox={`0 0 ${VW} ${VH}`} preserveAspectRatio="xMidYMid meet" className="absolute inset-0">
                {edges.map((e) => {
                  const a = pos.get(e.from), b = pos.get(e.to);
                  if (!a || !b) return null;
                  const w = 0.6 + 4 * Math.sqrt(Math.max(e.planned, e.actual) / maxV);
                  return <line key={`${e.from}-${e.to}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={e.actual > 0 ? "rgba(45,212,191,0.35)" : "rgba(255,255,255,0.08)"} strokeWidth={w} strokeDasharray={e.actual > 0 ? undefined : "4 4"} />;
                })}
                {nodes.map((n) => {
                  const p = pos.get(n.id)!;
                  const color = TYPE_META[n.type].color;
                  const rp = radius(n.planned), ra = radius(n.actual);
                  const rLabel = Math.max(rp, ra, 8);
                  return (
                    <g key={n.id} transform={`translate(${p.x}, ${p.y})`}>
                      {rp > 0 && <circle r={rp} fill={color} fillOpacity={0.06} stroke={color} strokeOpacity={0.7} strokeWidth={1.2} strokeDasharray="5 3" />}
                      {ra > 0 && <circle r={ra} fill={color} fillOpacity={0.45} stroke={color} strokeWidth={1} style={{ transition: "r 400ms ease" }} />}
                      {rp === 0 && ra === 0 && <circle r={5} fill={color} fillOpacity={0.5} />}
                      <text y={rLabel + 13} textAnchor="middle" fill="rgba(255,255,255,0.85)" fontSize={n.type === "segment" ? 11.5 : 10} fontWeight={n.type === "segment" ? 600 : 400} fontFamily="system-ui">
                        {n.label.length > 22 ? n.label.slice(0, 21) + "…" : n.label}
                      </text>
                      <text y={rLabel + 25} textAnchor="middle" fill={color} fillOpacity={0.9} fontSize={9.5} fontFamily="system-ui">
                        {n.actual}{n.planned > 0 ? ` / ${Math.round(n.planned)}` : ""}
                      </text>
                    </g>
                  );
                })}
              </svg>
            )}
          </div>
          <div className="w-56 shrink-0 border-l border-border p-4 overflow-y-auto">
            <div className="text-[10.5px] uppercase tracking-wide text-muted-foreground mb-2">Cells</div>
            <div className="space-y-1.5">
              {OUTER_ORDER.concat(["segment", "hinted"]).filter((t) => typesPresent.includes(t)).map((t) => (
                <div key={t} className="flex items-center gap-2 text-xs">
                  <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: TYPE_META[t].color }} />
                  <span className="text-foreground/85 flex-1">{TYPE_META[t].label}</span>
                  <span className="text-muted-foreground tabular-nums">{nodes.filter((n) => n.type === t).length}</span>
                </div>
              ))}
            </div>
            <p className="text-[10.5px] text-muted-foreground/70 leading-snug mt-4">A node's size is the number of personas in that cell, and nothing else. A place with more personas inflates more than one with fewer, whatever the sources say about it.</p>
            {nodes.some((n) => n.type !== "segment" && n.planned === 0 && n.actual > 0) && (
              <p className="text-[10.5px] text-amber-300/80 leading-snug mt-2">Solid nodes with no ring are cells the personas brought that the plan did not name.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
