"use client";

import { useMemo, useState } from "react";
import { X, Network } from "lucide-react";
import type { Agent, FrameCategory, FrameTarget, PopulationBuild, PopulationFrame } from "@/lib/api";

/**
 * The sampling frame as a graph. The cell types are the frame's own dimensions — whatever the
 * question called for (place, age, work pattern, privacy stance …) — so nothing here is a fixed
 * list; when a build has no frame, the persona attributes stand in. Every node inflates with
 * the personas in it: a dashed ring for what the plan intends, a filled disc for the personas
 * actually written so far, growing live through a build. Only personas move a node.
 */

interface Props {
  build: PopulationBuild | null;
  frame?: PopulationFrame | null;
  agents: Partial<Agent>[];
  targetCount: number;
  spawning: boolean;
  onClose: () => void;
}

interface TypeDef { key: string; label: string; color: string; source?: string }
interface FrameNode { id: string; type: string; label: string; planned: number; actual: number }
interface FrameEdge { from: string; to: string; planned: number; actual: number }

const PALETTE = ["#38bdf8", "#facc15", "#f472b6", "#4ade80", "#a78bfa", "#fb923c", "#2dd4bf", "#fb7185", "#818cf8", "#f59e0b", "#34d399", "#e879f9"];
const SEGMENT_TYPE: TypeDef = { key: "segment", label: "Segment", color: "#2dd4bf" };
const HINTED_TYPE: TypeDef = { key: "hinted", label: "Group implied by the inputs", color: "#94a3b8" };

/** The attribute-based cells used when a build has no frame (the plan's own split). */
const ATTRIBUTE_TYPES: TypeDef[] = [
  { key: "region", label: "Place", color: "#38bdf8" }, { key: "age", label: "Age band", color: "#facc15" }, { key: "gender", label: "Gender", color: "#f472b6" },
  { key: "income", label: "Income", color: "#4ade80" }, { key: "education", label: "Education", color: "#a78bfa" }, { key: "occupation", label: "Occupation", color: "#fb923c" },
  { key: "stance", label: "Stance", color: "#818cf8" }, { key: "mood", label: "Mood", color: "#fb7185" },
];
const ATTR_KEY: Record<string, string> = { region: "region", age: "age", gender: "gender", income: "income", education: "education", occupation: "occupation" };

const INCOME_WORDS: Record<string, string[]> = { low: ["low", "lower", "bottom", "poor", "deprived", "under", "below"], middle: ["middle", "mid", "median", "average", "moderate"], high: ["high", "upper", "top", "affluent", "wealthy", "over", "above"] };
const EDU_WORDS: Record<string, string[]> = { none: ["no qualification", "none"], secondary: ["secondary", "gcse", "school", "a-level", "a level", "college"], degree: ["degree", "graduate", "bachelor", "university", "higher"], postgraduate: ["postgraduate", "master", "phd", "doctor"] };

function norm(s: string) { return (s || "").trim().toLowerCase(); }
function ageBand(age: number) { const lo = Math.max(10, Math.floor(age / 10) * 10); return `${lo}s`; }
function bandsFor(min?: number, max?: number): string[] {
  if (!min || !max || max < min) return [];
  const out: string[] = [];
  for (let a = Math.floor(min / 10) * 10; a <= max; a += 10) out.push(`${Math.max(10, a)}s`);
  return [...new Set(out)];
}
function ageBounds(c: FrameCategory): [number, number] | null {
  if (c.age_max && c.age_max >= (c.age_min || 0)) return [c.age_min || 0, c.age_max];
  const m = c.label.match(/^\s*(\d{1,3})\s*(?:-|–|to)\s*(\d{1,3})/); if (m) return [+m[1], +m[2]];
  const p = c.label.match(/^\s*(\d{1,3})\s*\+/); if (p) return [+p[1], 120];
  const u = c.label.toLowerCase().match(/^\s*(?:under|<)\s*(\d{1,3})/); if (u) return [0, +u[1] - 1];
  return null;
}
function genderKey(x: string): string {
  const v = norm(x);
  if (["f", "female", "females", "woman", "women", "girl"].includes(v) || v.startsWith("fem") || v.startsWith("wom")) return "f";
  if (["m", "male", "males", "man", "men", "boy"].includes(v) || v.startsWith("mal") || v.startsWith("men")) return "m";
  return "";
}
function keywordCategory(value: string, cats: FrameCategory[], words: Record<string, string[]>): string | null {
  const v = norm(value); if (!v) return null;
  for (const c of cats) { const l = norm(c.label); if (l && (l.includes(v) || v.includes(l))) return c.label; }
  for (const c of cats) { const l = norm(c.label); for (const ws of Object.values(words)) if (ws.some((w) => l.includes(w)) && ws.some((w) => v.includes(w))) return c.label; }
  return null;
}
/** Which published category an attribute value falls in (mirrors the backend's frame.category_of). */
function categoryOf(attr: string, cats: FrameCategory[], value?: string | null, age?: number | null): string | null {
  if (!cats.length) return null;
  if (attr === "age") { if (age == null) return null; for (const c of cats) { const b = ageBounds(c); if (b && age >= b[0] && age <= b[1]) return c.label; } return null; }
  const v = norm(value || ""); if (!v) return null;
  if (attr === "gender") { const g = genderKey(v); for (const c of cats) if (g && genderKey(c.label) === g) return c.label; return null; }
  if (attr === "income") return keywordCategory(v, cats, INCOME_WORDS);
  if (attr === "education") return keywordCategory(v, cats, EDU_WORDS);
  for (const c of cats) { const l = norm(c.label); if (l && (v.includes(l) || (v.length >= 4 && l.includes(v)))) return c.label; }
  return null;
}
/** An explicit value (from the planner or the persona writer) matched onto the published categories, or itself when there are none. */
function explicitValue(cats: FrameCategory[], raw?: string | null): string | null {
  const v = norm(raw || ""); if (!v) return null;
  if (!cats.length) return (raw || "").trim().slice(0, 60);
  for (const c of cats) if (norm(c.label) === v) return c.label;
  for (const c of cats) { const l = norm(c.label); if (l && (l.includes(v) || v.includes(l))) return c.label; }
  return null;
}

function activeTarget(frame: PopulationFrame | null | undefined, key: string): FrameTarget | null {
  const t = frame?.targets?.[key];
  return t && ["found", "proxy", "uploaded", "estimated"].includes(t.status) && t.categories?.length ? t : null;
}

export function buildFrame(build: PopulationBuild | null, agents: Partial<Agent>[], targetCount: number, frame?: PopulationFrame | null) {
  const nodes = new Map<string, FrameNode>();
  const edges = new Map<string, FrameEdge>();
  const node = (type: string, raw: string): FrameNode => {
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
  const segments = (build?.plan?.segments || []).filter((s) => s.decision !== "rejected");
  const dims = frame?.dimensions || [];
  const dynamic = dims.length > 0;

  // ── the cell types: the frame's dimensions, else the persona attributes ──
  const types: TypeDef[] = dynamic
    ? dims.map((d, i) => {
        const t = activeTarget(frame, d.key);
        const attr = t?.status === "proxy" ? t.proxy_attribute : d.attribute;
        return { key: d.key, label: d.label, color: PALETTE[i % PALETTE.length], source: t ? (t.status === "estimated" ? "model estimate" : t.source || t.status) + (t.year ? ` (${t.year})` : "") : undefined, attr };
      })
    : ATTRIBUTE_TYPES;

  // ── rings from the published targets ──
  for (const ty of types) {
    const t = dynamic ? activeTarget(frame, ty.key) : null;
    if (t) for (const c of t.categories) node(ty.key, c.label).planned = (targetCount * c.share_pct) / 100;
  }

  // ── the plan: each segment's share of every cell ──
  for (const seg of segments) {
    const count = seg.count ?? Math.round(((seg.share_pct || 0) / 100) * targetCount);
    const sNode = node("segment", seg.name);
    sNode.planned += count;
    const d = seg.demographics || {};
    const fv = (seg as { frame_values?: Record<string, string> }).frame_values || {};
    const put = (type: string, label: string | null, share: number, ringFromTarget: boolean) => {
      if (!label) return;
      const n = node(type, label);
      if (!ringFromTarget) n.planned += share;
      edge(sNode, n).planned += share;
    };
    for (const ty of types) {
      const t = dynamic ? activeTarget(frame, ty.key) : null;
      const cats = t?.categories || [];
      const ring = !!t;
      const attr = dynamic ? (ty as TypeDef & { attr?: string }).attr || "other" : ty.key;
      if (dynamic && fv[ty.key]) { put(ty.key, explicitValue(cats, fv[ty.key]), count, ring); continue; }
      const key = ATTR_KEY[attr] || attr;
      if (key === "region") {
        const vals = (d.regions || []).filter(Boolean);
        for (const v of vals) put(ty.key, cats.length ? categoryOf("region", cats, v) : v, count / vals.length, ring);
      } else if (key === "age") {
        if (cats.length) {
          if (d.age_min && d.age_max && d.age_max >= d.age_min) {
            const span = d.age_max - d.age_min + 1;
            for (const c of cats) { const b = ageBounds(c); if (!b) continue; const ov = Math.max(0, Math.min(d.age_max, b[1]) - Math.max(d.age_min, b[0]) + 1); if (ov) put(ty.key, c.label, (count * ov) / span, ring); }
          }
        } else { const bands = bandsFor(d.age_min, d.age_max); for (const b of bands) put(ty.key, b, count / bands.length, ring); }
      } else if (key === "gender") {
        if (typeof d.gender_female_pct === "number") {
          const f = (count * d.gender_female_pct) / 100;
          put(ty.key, cats.length ? categoryOf("gender", cats, "female") : "female", f, ring);
          put(ty.key, cats.length ? categoryOf("gender", cats, "male") : "male", count - f, ring);
        }
      } else if (key === "income") { if (d.income_band) put(ty.key, cats.length ? categoryOf("income", cats, d.income_band) : d.income_band, count, ring); }
      else if (key === "education") { if (d.education) put(ty.key, cats.length ? categoryOf("education", cats, d.education) : d.education, count, ring); }
      else if (key === "occupation") { const vals = (d.occupations || []).filter(Boolean); for (const v of vals) put(ty.key, cats.length ? categoryOf("occupation", cats, v) : v, count / vals.length, ring); }
      else if (key === "stance") put(ty.key, seg.stance, count, ring);
      else if (key === "mood") { if (seg.sentiment?.mood) put(ty.key, seg.sentiment.mood, count, ring); }
    }
  }
  if (segments.length === 0 && !dynamic) for (const g of build?.detected?.segments_hinted || []) node("hinted", g);

  // ── the personas written so far ──
  for (const a of agents) {
    const sNode = a.segment ? node("segment", a.segment) : null;
    if (sNode) sNode.actual += 1;
    const demo = (a.demographics || {}) as Record<string, unknown>;
    const fv = (demo.frame || {}) as Record<string, string>;
    const bump = (type: string, label: string | null) => {
      if (!label) return;
      const n = node(type, label);
      n.actual += 1;
      if (sNode) edge(sNode, n).actual += 1;
    };
    for (const ty of types) {
      const t = dynamic ? activeTarget(frame, ty.key) : null;
      const cats = t?.categories || [];
      const attr = dynamic ? (ty as TypeDef & { attr?: string }).attr || "other" : ty.key;
      if (dynamic && fv[ty.key]) { bump(ty.key, explicitValue(cats, fv[ty.key])); continue; }
      const key = ATTR_KEY[attr] || attr;
      const str = (k: string) => (typeof demo[k] === "string" ? (demo[k] as string) : undefined);
      if (key === "region") bump(ty.key, cats.length ? categoryOf("region", cats, str("region")) : str("region") || null);
      else if (key === "age") bump(ty.key, typeof a.age === "number" ? (cats.length ? categoryOf("age", cats, null, a.age) : ageBand(a.age)) : null);
      else if (key === "gender") { const g = str("gender"); if (g && g !== "n/a") bump(ty.key, cats.length ? categoryOf("gender", cats, g) : g); }
      else if (key === "income") bump(ty.key, cats.length ? categoryOf("income", cats, str("income_band")) : str("income_band") || null);
      else if (key === "education") bump(ty.key, cats.length ? categoryOf("education", cats, str("education")) : str("education") || null);
      else if (key === "occupation") bump(ty.key, cats.length ? categoryOf("occupation", cats, str("occupation")) : str("occupation") || null);
      else if (key === "stance") bump(ty.key, (a.stance as string) || null);
    }
  }
  return { nodes: [...nodes.values()], edges: [...edges.values()], types };
}

const VW = 1000, VH = 720, CX = VW / 2, CY = VH / 2;

function layout(nodes: FrameNode[], types: TypeDef[], only: string | null) {
  const segs = nodes.filter((n) => n.type === "segment" || n.type === "hinted");
  const order = types.map((t) => t.key);
  const outer = order.filter((k) => !only || k === only).flatMap((k) => nodes.filter((n) => n.type === k).sort((a, b) => Math.max(b.planned, b.actual) - Math.max(a.planned, a.actual)));
  const pos = new Map<string, { x: number; y: number }>();
  const rIn = segs.length <= 1 ? 0 : 150, rOut = 300;
  segs.forEach((n, i) => { const a = (i / Math.max(1, segs.length)) * 2 * Math.PI - Math.PI / 2; pos.set(n.id, { x: CX + rIn * Math.cos(a), y: CY + rIn * Math.sin(a) }); });
  outer.forEach((n, i) => { const a = (i / Math.max(1, outer.length)) * 2 * Math.PI - Math.PI / 2; pos.set(n.id, { x: CX + rOut * Math.cos(a), y: CY + (rOut * 0.92) * Math.sin(a) }); });
  return pos;
}

export default function SamplingFrameGraph({ build, frame, agents, targetCount, spawning, onClose }: Props) {
  const [only, setOnly] = useState<string | null>(null);
  const { nodes, edges, types } = useMemo(() => buildFrame(build, agents, targetCount, frame), [build, agents, targetCount, frame]);
  const shown = useMemo(() => nodes.filter((n) => n.type === "segment" || n.type === "hinted" || !only || n.type === only), [nodes, only]);
  const shownIds = useMemo(() => new Set(shown.map((n) => n.id)), [shown]);
  const pos = useMemo(() => layout(nodes, types, only), [nodes, types, only]);
  const colorOf = useMemo(() => new Map<string, string>([...types.map((t) => [t.key, t.color] as [string, string]), [SEGMENT_TYPE.key, SEGMENT_TYPE.color], [HINTED_TYPE.key, HINTED_TYPE.color]]), [types]);
  const maxV = Math.max(1, ...shown.map((n) => Math.max(n.planned, n.actual)));
  const radius = (v: number) => (v <= 0 ? 0 : 7 + 40 * Math.sqrt(v / maxV));
  const plannedTotal = Math.round(nodes.filter((n) => n.type === "segment").reduce((s, n) => s + n.planned, 0));
  const actualTotal = agents.length;
  const empty = nodes.length === 0;
  const perType = (key: string) => {
    const cells = nodes.filter((n) => n.type === key);
    return { cells: cells.length, planned: Math.round(cells.reduce((s, n) => s + n.planned, 0)), actual: cells.reduce((s, n) => s + n.actual, 0) };
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4" onClick={onClose}>
      <div className="w-full max-w-6xl h-[88vh] bg-background border border-border rounded-2xl flex flex-col overflow-hidden shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-border flex items-center gap-3 shrink-0">
          <Network className="w-4 h-4 text-primary" />
          <div className="min-w-0">
            <div className="text-sm font-semibold text-foreground">Sampling frame</div>
            <div className="text-[11px] text-muted-foreground">Every cell the population is drawn from. Dashed ring = what the plan intends · filled disc = personas written so far. Each persona sits in exactly one cell of every type.</div>
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
                  <p className="text-xs text-muted-foreground/70 mt-1">Detect runs first and picks the dimensions; the plan then turns them into cells with counts.</p>
                </div>
              </div>
            ) : (
              <svg width="100%" height="100%" viewBox={`0 0 ${VW} ${VH}`} preserveAspectRatio="xMidYMid meet" className="absolute inset-0">
                {edges.filter((e) => shownIds.has(e.from) && shownIds.has(e.to)).map((e) => {
                  const a = pos.get(e.from), b = pos.get(e.to);
                  if (!a || !b) return null;
                  const w = 0.6 + 4 * Math.sqrt(Math.max(e.planned, e.actual) / maxV);
                  return <line key={`${e.from}-${e.to}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={e.actual > 0 ? "rgba(45,212,191,0.35)" : "rgba(255,255,255,0.08)"} strokeWidth={w} strokeDasharray={e.actual > 0 ? undefined : "4 4"} />;
                })}
                {shown.map((n) => {
                  const p = pos.get(n.id);
                  if (!p) return null;
                  const color = colorOf.get(n.type) || "#94a3b8";
                  const rp = radius(n.planned), ra = radius(n.actual);
                  const rLabel = Math.max(rp, ra, 8);
                  const isSeg = n.type === "segment";
                  return (
                    <g key={n.id} transform={`translate(${p.x}, ${p.y})`}>
                      {rp > 0 && <circle r={rp} fill={color} fillOpacity={0.06} stroke={color} strokeOpacity={0.7} strokeWidth={1.2} strokeDasharray="5 3" />}
                      {ra > 0 && <circle r={ra} fill={color} fillOpacity={0.45} stroke={color} strokeWidth={1} style={{ transition: "r 400ms ease" }} />}
                      {rp === 0 && ra === 0 && <circle r={5} fill={color} fillOpacity={0.5} />}
                      <text y={rLabel + 13} textAnchor="middle" fill="rgba(255,255,255,0.85)" fontSize={isSeg ? 11.5 : 10} fontWeight={isSeg ? 600 : 400} fontFamily="system-ui">
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
          <div className="w-64 shrink-0 border-l border-border p-4 overflow-y-auto">
            <div className="text-[10.5px] uppercase tracking-wide text-muted-foreground mb-2">Cell types · click to focus</div>
            <div className="space-y-1.5">
              {types.filter((t) => perType(t.key).cells > 0).map((t) => {
                const s = perType(t.key);
                const on = only === t.key;
                return (
                  <button key={t.key} onClick={() => setOnly(on ? null : t.key)} className={`w-full text-left rounded-lg px-2 py-1.5 border transition-colors ${on ? "border-white/40 bg-muted/40" : "border-transparent hover:border-border"}`}>
                    <div className="flex items-center gap-2 text-xs">
                      <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: t.color }} />
                      <span className="text-foreground/90 flex-1 truncate">{t.label}</span>
                      <span className="text-muted-foreground tabular-nums">{s.cells} cell{s.cells === 1 ? "" : "s"}</span>
                    </div>
                    <div className="text-[10.5px] text-muted-foreground/70 pl-4.5 ml-[18px] tabular-nums">{s.actual} / {s.planned || plannedTotal || targetCount} personas{t.source ? ` · ring from ${t.source}` : ""}</div>
                  </button>
                );
              })}
              {perType("segment").cells > 0 && (
                <div className="flex items-center gap-2 text-xs px-2 py-1.5"><span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: SEGMENT_TYPE.color }} /><span className="text-foreground/90 flex-1">Segments</span><span className="text-muted-foreground tabular-nums">{perType("segment").cells}</span></div>
              )}
            </div>
            <p className="text-[10.5px] text-muted-foreground/70 leading-snug mt-4">A node's size is the number of personas in that cell, and nothing else. The cells of one type always add up to the whole population, because each persona sits in exactly one of them.</p>
            {frame?.dimensions?.length ? (
              <p className="text-[10.5px] text-muted-foreground/70 leading-snug mt-2">Cell types are the sampling frame's dimensions for this question, not a fixed list. A type with a published distribution draws its rings from it; the others draw them from the plan.</p>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
