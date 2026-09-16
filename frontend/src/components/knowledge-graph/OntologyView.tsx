"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowLeft, ArrowRight, FileText, Layers, RefreshCw, Sparkles, X } from "lucide-react";
import { api, apiFetch, type Ontology, type OntologyEdge, type OntologyNode, type OntologySchema, type OntologyState } from "@/lib/api";

interface Props {
  sessionId: string;
  /** Live entity count from the session page, so the "graph has grown" hint updates without a refetch. */
  liveEntityCount: number;
}

interface EntityDetail {
  entity: string;
  relations_from: string[][];
  relations_to: string[][];
  mentions: string[];
}

const COL_W = 190;
const ROW_H = 30;
const TOP = 64;
const LEFT = 90;
const NODE_R = 6;

function timeAgo(iso: string): string {
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function short(t: string, n = 20): string {
  return t.length > n ? t.slice(0, n - 1) + "…" : t;
}

interface Placed extends OntologyNode { x: number; y: number; color: string; col: number }

/** Swim-lane layout: one column per class (in schema order, only classes that have nodes);
 *  geography ordered by containment level, everything else by how often it is mentioned. */
function layout(onto: Ontology, schema: OntologySchema, hidden: Set<string>) {
  const levelRank = new Map(schema.geo_levels.map((l, i) => [l, i]));
  const classes = schema.classes.filter((c) => (onto.counts[c.key] || 0) > 0 && !hidden.has(c.key));
  const colOf = new Map(classes.map((c, i) => [c.key, i]));
  const colorOf = new Map(schema.classes.map((c) => [c.key, c.color]));
  const byClass = new Map<string, OntologyNode[]>();
  for (const n of onto.nodes) {
    if (hidden.has(n.cls)) continue;
    if (!byClass.has(n.cls)) byClass.set(n.cls, []);
    byClass.get(n.cls)!.push(n);
  }
  const placed: Placed[] = [];
  let maxRows = 0;
  for (const [cls, nodes] of byClass) {
    const col = colOf.get(cls);
    if (col === undefined) continue;
    nodes.sort((a, b) => {
      if (cls === "geography") {
        const ra = levelRank.get(a.level || "") ?? 99, rb = levelRank.get(b.level || "") ?? 99;
        if (ra !== rb) return ra - rb;
      }
      return b.mentions - a.mentions || a.id.localeCompare(b.id);
    });
    nodes.forEach((n, row) => {
      placed.push({ ...n, x: LEFT + col * COL_W, y: TOP + row * ROW_H, color: colorOf.get(cls) || "#94a3b8", col });
    });
    maxRows = Math.max(maxRows, nodes.length);
  }
  const width = Math.max(960, LEFT * 2 + classes.length * COL_W);
  const height = Math.max(520, TOP + maxRows * ROW_H + 40);
  return { placed, classes, width, height };
}

function edgePath(a: Placed, b: Placed): string {
  const x1 = a.x + NODE_R, y1 = a.y, x2 = b.x - NODE_R, y2 = b.y;
  if (a.col === b.col) {
    // same lane (within, precedes): bow out to the left of the column
    const bow = Math.min(60, 18 + Math.abs(y2 - y1) * 0.25);
    return `M ${a.x - NODE_R} ${y1} C ${a.x - bow} ${y1}, ${b.x - bow} ${y2}, ${b.x - NODE_R} ${y2}`;
  }
  if (a.col > b.col) {
    // right-to-left: leave from the left of a, arrive at the right of b
    const dx = (a.x - b.x) * 0.4;
    return `M ${a.x - NODE_R} ${y1} C ${a.x - dx} ${y1}, ${b.x + 120 + dx} ${y2}, ${b.x + 118} ${y2}`;
  }
  const dx = (x2 - x1) * 0.45;
  return `M ${x1 + 118} ${y1} C ${x1 + 118 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
}

export default function OntologyView({ sessionId, liveEntityCount }: Props) {
  const [state, setState] = useState<OntologyState | null>(null);
  const [loading, setLoading] = useState(true);
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<EntityDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const load = useCallback(async () => {
    try {
      setState(await api.kg.ontology(sessionId));
      setError(null);
    } catch (e: any) {
      setError(e?.message || "Could not load the ontology.");
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => { load(); }, [load]);

  async function build() {
    setBuilding(true);
    setError(null);
    try {
      setState(await api.kg.buildOntology(sessionId));
      setSelected(null);
      setDetail(null);
    } catch (e: any) {
      setError(e?.message || "The build failed.");
    } finally {
      setBuilding(false);
    }
  }

  const fetchDetail = useCallback(async (name: string, inferred: boolean) => {
    setDetail(null);
    if (inferred) return;
    setDetailLoading(true);
    try {
      const r = await apiFetch(`/sessions/${sessionId}/kg/entity/${encodeURIComponent(name)}`);
      setDetail(await r.json());
    } catch {
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  }, [sessionId]);

  const onto = state?.ontology || null;
  const schema = state?.schema || null;

  const graph = useMemo(() => (onto && schema ? layout(onto, schema, hidden) : null), [onto, schema, hidden]);
  const nodeMap = useMemo(() => new Map((graph?.placed || []).map((n) => [n.id, n])), [graph]);
  const edges = useMemo(() => (onto?.edges || []).filter((e) => nodeMap.has(e.head) && nodeMap.has(e.tail)), [onto, nodeMap]);
  const selectedNode = selected ? nodeMap.get(selected) || onto?.nodes.find((n) => n.id === selected) || null : null;
  const grown = onto ? liveEntityCount !== onto.entity_count : false;

  function pick(id: string) {
    const n = onto?.nodes.find((x) => x.id === id);
    setSelected(id);
    fetchDetail(id, !!n?.inferred);
  }

  function toggleClass(key: string) {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }

  if (loading) {
    return <div className="h-full flex items-center justify-center text-xs text-muted-foreground animate-pulse">Loading ontology…</div>;
  }

  return (
    <div className="h-full flex overflow-hidden">
      {/* ── Graph pane ─────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="px-4 py-2 border-b border-border flex items-center gap-3 shrink-0">
          {onto ? (
            <span className="text-sm text-muted-foreground">
              <span className="text-foreground font-semibold">{onto.nodes.length}</span> typed nodes
              &nbsp;·&nbsp;
              <span className="text-foreground font-semibold">{onto.edges.length}</span> typed edges
              &nbsp;·&nbsp;
              <span className="text-foreground/70">{onto.nodes.filter((n) => n.inferred).length} inferred</span>
            </span>
          ) : (
            <span className="text-sm text-muted-foreground">The schema — the classes and predicates a typed graph is built from</span>
          )}
          {(state?.stale || grown) && onto && (
            <span className="flex items-center gap-1 text-xs text-amber-400">
              <AlertTriangle className="w-3 h-3" /> graph has grown since this was built
            </span>
          )}
          <button
            onClick={build}
            disabled={building || liveEntityCount === 0}
            className="ml-auto flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-primary/15 text-primary border border-primary/30 hover:bg-primary/25 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            title={liveEntityCount === 0 ? "Ingest sources or run research first" : undefined}
          >
            {building ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
            {building ? "Classifying…" : onto ? "Rebuild from the graph" : "Build from this session's graph"}
          </button>
        </div>

        {error && (
          <div className="px-4 py-2 text-xs text-red-300 bg-red-500/10 border-b border-red-500/20">{error}</div>
        )}

        <div className="flex-1 relative overflow-auto">
          {onto && graph ? (
            <svg width={graph.width} height={graph.height} className="block">
              <defs>
                <marker id="onto-arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                  <path d="M0,0 L0,6 L6,3 z" fill="rgba(255,255,255,0.25)" />
                </marker>
              </defs>

              {/* lane headers */}
              {graph.classes.map((c, i) => (
                <g key={c.key} transform={`translate(${LEFT + i * COL_W - NODE_R - 6}, 20)`}>
                  <rect width={COL_W - 20} height={26} rx={6} fill={c.color} fillOpacity={0.12} stroke={c.color} strokeOpacity={0.35} />
                  <text x={10} y={17} fill={c.color} fontSize={11} fontWeight={600} fontFamily="system-ui">
                    {c.label}
                  </text>
                  <text x={COL_W - 30} y={17} textAnchor="end" fill={c.color} fillOpacity={0.8} fontSize={10} fontFamily="system-ui">
                    {onto.counts[c.key] || 0}
                  </text>
                </g>
              ))}

              {/* edges */}
              {edges.map((e, i) => {
                const a = nodeMap.get(e.head)!, b = nodeMap.get(e.tail)!;
                const hot = selected && (e.head === selected || e.tail === selected);
                const dim = selected && !hot;
                return (
                  <path
                    key={i}
                    d={edgePath(a, b)}
                    fill="none"
                    stroke={hot ? a.color : "rgba(255,255,255,0.10)"}
                    strokeOpacity={hot ? 0.9 : dim ? 0.35 : 1}
                    strokeWidth={hot ? 1.8 : 1}
                    strokeDasharray={e.inferred ? "4 3" : undefined}
                    markerEnd="url(#onto-arrow)"
                  />
                );
              })}

              {/* nodes */}
              {graph.placed.map((n) => {
                const isSel = selected === n.id;
                const related = selected && edges.some((e) => (e.head === selected && e.tail === n.id) || (e.tail === selected && e.head === n.id));
                const dim = selected && !isSel && !related;
                return (
                  <g key={n.id} transform={`translate(${n.x}, ${n.y})`} onClick={() => pick(n.id)} style={{ cursor: "pointer" }} opacity={dim ? 0.35 : 1}>
                    {isSel && <circle r={NODE_R + 5} fill="none" stroke={n.color} strokeWidth={2} strokeDasharray="3 2" />}
                    <circle
                      r={isSel ? NODE_R + 1 : NODE_R}
                      fill={n.color}
                      fillOpacity={n.inferred ? 0.15 : isSel ? 1 : 0.85}
                      stroke={n.color}
                      strokeWidth={n.inferred ? 1.5 : 0}
                      strokeDasharray={n.inferred ? "2 2" : undefined}
                    />
                    <text x={NODE_R + 6} y={4} fill={isSel ? "#fff" : related ? "rgba(255,255,255,0.9)" : "rgba(255,255,255,0.7)"} fontSize={10.5} fontFamily="system-ui" fontWeight={isSel ? 600 : 400}>
                      {short(n.id)}
                    </text>
                    {n.level && (
                      <text x={NODE_R + 6} y={14} fill={n.color} fillOpacity={0.7} fontSize={8} fontFamily="system-ui">
                        {n.level.replace("_", " ")}
                      </text>
                    )}
                  </g>
                );
              })}
            </svg>
          ) : schema ? (
            <SchemaGraph schema={schema} />
          ) : null}
        </div>
      </div>

      {/* ── Right panel ─────────────────────────────────────────────── */}
      <div className="w-80 shrink-0 border-l border-border flex flex-col overflow-hidden">
        {selectedNode ? (
          <>
            <div className="px-4 py-2 border-b border-border flex items-center gap-2">
              <Layers className="w-3.5 h-3.5 text-primary" />
              <span className="text-xs font-semibold text-foreground uppercase tracking-wide flex-1 truncate">{selectedNode.id}</span>
              <button onClick={() => { setSelected(null); setDetail(null); }} className="text-muted-foreground hover:text-foreground transition-colors">
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              <NodeHeader node={selectedNode} schema={schema!} />
              <EdgeList title="Outgoing" icon={<ArrowRight className="w-3 h-3 text-blue-400" />} tone="blue" edges={edges.filter((e) => e.head === selected)} side="tail" onPick={pick} />
              <EdgeList title="Incoming" icon={<ArrowLeft className="w-3 h-3 text-purple-400" />} tone="purple" edges={edges.filter((e) => e.tail === selected)} side="head" onPick={pick} />
              {selectedNode.inferred && (
                <p className="text-xs text-muted-foreground/70 italic">Inferred: this place was never named in a source. It was added because a smaller area sits inside it.</p>
              )}
              {detailLoading && <p className="text-xs text-muted-foreground animate-pulse">Loading mentions…</p>}
              {detail && detail.mentions.length > 0 && (
                <div>
                  <div className="flex items-center gap-1.5 mb-2">
                    <FileText className="w-3 h-3 text-muted-foreground" />
                    <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Mentions ({detail.mentions.length})</span>
                  </div>
                  <div className="space-y-2">
                    {detail.mentions.map((m, i) => (
                      <div key={i} className="bg-muted/50 rounded-lg px-3 py-2">
                        <p className="text-xs text-muted-foreground leading-relaxed line-clamp-4">{m}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </>
        ) : (
          <>
            <div className="px-4 py-2 border-b border-border flex items-center gap-2">
              <Layers className="w-3.5 h-3.5 text-primary" />
              <span className="text-xs font-semibold text-foreground uppercase tracking-wide">Ontology</span>
            </div>
            <div className="flex-1 overflow-y-auto">
              <div className="px-4 py-3 border-b border-border text-xs text-muted-foreground space-y-1">
                {onto ? (
                  <>
                    <div>Built <span className="text-foreground">{timeAgo(onto.built_at)}</span> from <span className="text-foreground">{onto.entity_count}</span> entities and <span className="text-foreground">{onto.relation_count}</span> relations.</div>
                    <div className="text-muted-foreground/70">{onto.classified} classified · {onto.typed} relations typed · {onto.model}</div>
                    {grown && <div className="text-amber-400">The graph now has {liveEntityCount} entities — rebuild to include them.</div>}
                  </>
                ) : (
                  <div>
                    Nothing built yet. The knowledge graph holds <span className="text-foreground">{liveEntityCount}</span> free-text entities;
                    building classifies each one into a class below, types every relation, and adds the geography containment the sources implied.
                  </div>
                )}
              </div>
              {schema && (
                <div className="px-4 py-3 space-y-1.5">
                  <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">Classes {onto ? "· click to hide" : ""}</div>
                  {schema.classes.map((c) => {
                    const count = onto?.counts[c.key] || 0;
                    const off = hidden.has(c.key);
                    return (
                      <button
                        key={c.key}
                        onClick={() => onto && toggleClass(c.key)}
                        className={`w-full text-left rounded-lg px-2.5 py-2 border transition-colors ${off ? "opacity-40 border-transparent" : "border-border/60 hover:border-border"}`}
                        title={c.description}
                      >
                        <div className="flex items-center gap-2">
                          <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: c.color }} />
                          <span className="text-xs font-medium text-foreground flex-1">{c.label}</span>
                          {onto && <span className="text-xs text-muted-foreground">{count}</span>}
                        </div>
                        <p className="text-[11px] text-muted-foreground/70 leading-snug mt-1 line-clamp-2">{c.description}</p>
                      </button>
                    );
                  })}
                  <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mt-4 mb-2">Predicates</div>
                  <div className="flex flex-wrap gap-1">
                    {schema.predicates.map((p) => (
                      <span key={p.key} className="text-[11px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground" title={`${p.domain.join(", ")} → ${p.range.join(", ")}: ${p.description}`}>
                        {p.label}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function NodeHeader({ node, schema }: { node: OntologyNode; schema: OntologySchema }) {
  const cls = schema.classes.find((c) => c.key === node.cls);
  const color = cls?.color || "#94a3b8";
  return (
    <div>
      <div className="flex items-center gap-2 mb-1">
        <span className="inline-block px-2 py-0.5 rounded text-xs font-bold" style={{ backgroundColor: color + "33", color }}>{cls?.label || node.cls}</span>
        {node.level && <span className="text-xs text-muted-foreground">{node.level.replace("_", " ")}</span>}
        {node.inferred && <span className="text-xs text-amber-400/80">inferred</span>}
      </div>
      <h3 className="font-semibold text-foreground text-sm">{node.id}</h3>
      <p className="text-xs text-muted-foreground mt-0.5">{node.mentions} mention{node.mentions === 1 ? "" : "s"} in the sources</p>
    </div>
  );
}

function EdgeList({ title, icon, tone, edges, side, onPick }: { title: string; icon: React.ReactNode; tone: "blue" | "purple"; edges: OntologyEdge[]; side: "head" | "tail"; onPick: (id: string) => void }) {
  if (edges.length === 0) return null;
  const box = tone === "blue" ? "bg-blue-500/5 border-blue-500/10" : "bg-purple-500/5 border-purple-500/10";
  const label = tone === "blue" ? "text-blue-400" : "text-purple-400";
  const pred = tone === "blue" ? "text-blue-300/70" : "text-purple-300/70";
  return (
    <div>
      <div className="flex items-center gap-1.5 mb-2">
        {icon}
        <span className={`text-xs font-semibold uppercase tracking-wide ${label}`}>{title} ({edges.length})</span>
      </div>
      <div className="space-y-1.5">
        {edges.slice(0, 12).map((e, i) => (
          <div key={i} className={`border rounded-lg px-3 py-2 ${box}`}>
            <div className={`text-xs italic ${pred}`}>
              {e.predicate.replace(/_/g, " ")}
              {e.verb && <span className="not-italic text-muted-foreground/60"> · “{e.verb}”</span>}
              {e.inferred && <span className="not-italic text-amber-400/70"> · inferred</span>}
            </div>
            <button onClick={() => onPick(e[side])} className="text-xs text-foreground/80 hover:text-primary transition-colors font-medium">{e[side]}</button>
          </div>
        ))}
        {edges.length > 12 && <div className="text-xs text-muted-foreground/50 px-1">+{edges.length - 12} more</div>}
      </div>
    </div>
  );
}

/** The schema as a graph: one node per class in a ring, one edge per predicate with an explicit domain and range. */
function SchemaGraph({ schema }: { schema: OntologySchema }) {
  const W = 960, H = 560, cx = W / 2, cy = H / 2, R = 200;
  const classes = schema.classes.filter((c) => c.key !== "other");
  const pos = new Map(classes.map((c, i) => {
    const a = (i / classes.length) * 2 * Math.PI - Math.PI / 2;
    return [c.key, { x: cx + R * Math.cos(a), y: cy + R * Math.sin(a), color: c.color, label: c.label }];
  }));
  const links: { from: string; to: string; label: string }[] = [];
  for (const p of schema.predicates) {
    for (const d of p.domain) for (const r of p.range) {
      if (d === "*" || r === "*" || !pos.has(d) || !pos.has(r)) continue;
      links.push({ from: d, to: r, label: p.label });
    }
  }
  return (
    <svg width="100%" height="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet" className="absolute inset-0">
      <defs>
        <marker id="schema-arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
          <path d="M0,0 L0,6 L6,3 z" fill="rgba(255,255,255,0.3)" />
        </marker>
      </defs>
      {links.map((l, i) => {
        const a = pos.get(l.from)!, b = pos.get(l.to)!;
        if (l.from === l.to) {
          return <path key={i} d={`M ${a.x} ${a.y - 22} C ${a.x - 50} ${a.y - 80}, ${a.x + 50} ${a.y - 80}, ${a.x} ${a.y - 22}`} fill="none" stroke={a.color} strokeOpacity={0.5} strokeWidth={1.2} markerEnd="url(#schema-arrow)" />;
        }
        const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
        const nx = -(b.y - a.y), ny = b.x - a.x, len = Math.hypot(nx, ny) || 1;
        const qx = mx + (nx / len) * 40, qy = my + (ny / len) * 40;
        const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 1;
        return (
          <g key={i}>
            <path d={`M ${a.x + (dx / d) * 24} ${a.y + (dy / d) * 24} Q ${qx} ${qy} ${b.x - (dx / d) * 26} ${b.y - (dy / d) * 26}`} fill="none" stroke={a.color} strokeOpacity={0.45} strokeWidth={1.2} markerEnd="url(#schema-arrow)" />
            <text x={(a.x + 2 * qx + b.x) / 4} y={(a.y + 2 * qy + b.y) / 4} textAnchor="middle" fill="rgba(255,255,255,0.55)" fontSize={9} fontFamily="system-ui">{l.label}</text>
          </g>
        );
      })}
      {classes.map((c) => {
        const p = pos.get(c.key)!;
        return (
          <g key={c.key} transform={`translate(${p.x}, ${p.y})`}>
            <circle r={22} fill={c.color} fillOpacity={0.18} stroke={c.color} strokeWidth={1.5} />
            <text y={40} textAnchor="middle" fill="rgba(255,255,255,0.85)" fontSize={11} fontWeight={600} fontFamily="system-ui">{c.label}</text>
          </g>
        );
      })}
    </svg>
  );
}
