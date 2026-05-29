"use client";

import { useEffect, useState, useMemo, useCallback } from "react";
import { Network, Zap, X, ArrowRight, ArrowLeft, FileText } from "lucide-react";

interface Activity {
  time: number;
  source: string;
  entities: string[];
  relations: string[][];
}

interface EntityDetail {
  entity: string;
  relations_from: string[][];
  relations_to: string[][];
  mentions: string[];
}

interface Props {
  sessionId: string;
  entities: string[];
  relations: string[][];
  activity: Activity[];
}

const NODE_COLORS = [
  "#818cf8", "#a78bfa", "#f472b6", "#fb7185",
  "#fb923c", "#4ade80", "#2dd4bf", "#38bdf8",
  "#facc15", "#c084fc",
];

function seededIndex(str: string, len: number): number {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) >>> 0;
  return h % len;
}

interface NodePos { id: string; label: string; x: number; y: number; color: string }

const VW = 1000, VH = 680;

function buildLayout(entities: string[]): NodePos[] {
  const unique = [...new Set(entities)].slice(-60);
  const cx = VW / 2, cy = VH / 2;
  const perRing = [1, 8, 16, 24, 11];
  const maxR = Math.min(cx, cy) * 0.82;
  const ringRadii = [0, maxR * 0.22, maxR * 0.44, maxR * 0.68, maxR * 0.90];
  const nodes: NodePos[] = [];
  let idx = 0;
  for (let ring = 0; ring < perRing.length && idx < unique.length; ring++) {
    const count = Math.min(perRing[ring], unique.length - idx);
    const r = ringRadii[ring];
    for (let j = 0; j < count; j++) {
      const e = unique[idx++];
      const angle = ring === 0 ? 0 : (j / perRing[ring]) * 2 * Math.PI - Math.PI / 2;
      nodes.push({
        id: e,
        label: e.length > 16 ? e.slice(0, 14) + "…" : e,
        x: cx + r * Math.cos(angle),
        y: cy + r * Math.sin(angle),
        color: NODE_COLORS[seededIndex(e, NODE_COLORS.length)],
      });
    }
  }
  return nodes;
}

function timeAgo(ts: number): string {
  const s = Math.floor((Date.now() - ts) / 1000);
  if (s < 60) return `${s}s ago`;
  return `${Math.floor(s / 60)}m ago`;
}

export default function KGPanel({ sessionId, entities, relations, activity }: Props) {
  const [newEntitySet, setNewEntitySet] = useState<Set<string>>(new Set());
  const [selectedEntity, setSelectedEntity] = useState<string | null>(null);
  const [entityDetail, setEntityDetail] = useState<EntityDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [rightPanel, setRightPanel] = useState<"activity" | "detail">("activity");

  // Flash new entities
  useEffect(() => {
    if (activity.length === 0) return;
    const latest = activity[0];
    if (Date.now() - latest.time > 3000) return;
    setNewEntitySet(new Set(latest.entities));
    const t = setTimeout(() => setNewEntitySet(new Set()), 2500);
    return () => clearTimeout(t);
  }, [activity]);

  const fetchEntityDetail = useCallback(async (name: string) => {
    setDetailLoading(true);
    setEntityDetail(null);
    try {
      const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const r = await fetch(`${base}/api/v1/sessions/${sessionId}/kg/entity/${encodeURIComponent(name)}`);
      const data = await r.json();
      setEntityDetail(data);
    } catch {
      setEntityDetail(null);
    } finally {
      setDetailLoading(false);
    }
  }, [sessionId]);

  function handleNodeClick(id: string) {
    setSelectedEntity(id);
    setRightPanel("detail");
    fetchEntityDetail(id);
  }

  function closeDetail() {
    setSelectedEntity(null);
    setEntityDetail(null);
    setRightPanel("activity");
  }

  const nodes = useMemo(() => buildLayout(entities), [entities]);
  const nodeMap = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const isLive = activity.length > 0 && Date.now() - activity[0].time < 8000;

  if (entities.length === 0) {
    return (
      <div className="h-full flex items-center justify-center p-12 text-center">
        <div>
          <Network className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
          <p className="text-muted-foreground font-medium">Knowledge graph is empty</p>
          <p className="text-sm text-muted-foreground mt-1">
            Ingest content or run the simulation — entities and relations appear here live
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex overflow-hidden">
      {/* ── Graph pane ─────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="px-4 py-2 border-b border-border flex items-center gap-3 shrink-0">
          <span className="text-sm text-muted-foreground">
            <span className="text-foreground font-semibold">{entities.length}</span> entities
            &nbsp;·&nbsp;
            <span className="text-foreground font-semibold">{relations.length}</span> relations
          </span>
          {isLive && (
            <span className="flex items-center gap-1.5 text-xs text-green-400">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
              live
            </span>
          )}
          <span className="text-xs text-muted-foreground/50 ml-auto">Click any node to inspect</span>
        </div>

        <div className="flex-1 relative overflow-hidden">
          <svg
            width="100%" height="100%"
            viewBox={`0 0 ${VW} ${VH}`}
            preserveAspectRatio="xMidYMid meet"
            className="absolute inset-0"
          >
            <defs>
              <marker id="kg-arrow" markerWidth="5" markerHeight="5" refX="4" refY="2.5" orient="auto">
                <path d="M0,0 L0,5 L5,2.5 z" fill="rgba(255,255,255,0.15)" />
              </marker>
            </defs>

            {/* Relation edges */}
            {relations.map((r, i) => {
              if (r.length < 3) return null;
              const from = nodeMap.get(r[0]);
              const to = nodeMap.get(r[2]);
              if (!from || !to) return null;
              const isHighlighted = selectedEntity && (r[0] === selectedEntity || r[2] === selectedEntity);
              const mx = (from.x + to.x) / 2;
              const my = (from.y + to.y) / 2;
              return (
                <g key={i}>
                  <line
                    x1={from.x} y1={from.y} x2={to.x} y2={to.y}
                    stroke={isHighlighted ? "rgba(129,140,248,0.6)" : "rgba(255,255,255,0.08)"}
                    strokeWidth={isHighlighted ? 2 : 1.2}
                    markerEnd="url(#kg-arrow)"
                  />
                  {isHighlighted && (
                    <text x={mx} y={my} textAnchor="middle" fill="rgba(129,140,248,0.9)" fontSize={9} fontFamily="system-ui">
                      {r[1].length > 22 ? r[1].slice(0, 20) + "…" : r[1]}
                    </text>
                  )}
                </g>
              );
            })}

            {/* Nodes */}
            {nodes.map((node) => {
              const isNew = newEntitySet.has(node.id);
              const isSelected = selectedEntity === node.id;
              const isRelated = selectedEntity && relations.some(
                (r) => (r[0] === selectedEntity && r[2] === node.id) || (r[2] === selectedEntity && r[0] === node.id)
              );
              return (
                <g
                  key={node.id}
                  transform={`translate(${node.x},${node.y})`}
                  onClick={() => handleNodeClick(node.id)}
                  style={{ cursor: "pointer" }}
                >
                  {isNew && (
                    <circle r={24} fill={node.color} fillOpacity={0.25} stroke={node.color} strokeWidth={1} className="animate-ping" />
                  )}
                  {isSelected && (
                    <circle r={22} fill="none" stroke={node.color} strokeWidth={2.5} strokeDasharray="4 2" />
                  )}
                  <circle
                    r={isSelected ? 16 : isRelated ? 14 : 12}
                    fill={node.color}
                    fillOpacity={isSelected ? 0.5 : isRelated ? 0.35 : isNew ? 0.3 : 0.15}
                    stroke={node.color}
                    strokeWidth={isSelected ? 2.5 : isRelated ? 2 : isNew ? 2 : 1.2}
                  />
                  <circle r={isSelected ? 7 : 5} fill={node.color} fillOpacity={isSelected ? 1 : 0.85} />
                  <text
                    y={28}
                    textAnchor="middle"
                    fill={isSelected ? "rgba(255,255,255,1)" : isRelated ? "rgba(255,255,255,0.85)" : isNew ? "rgba(255,255,255,0.95)" : "rgba(255,255,255,0.55)"}
                    fontSize={isSelected ? 10 : 9}
                    fontFamily="system-ui"
                    fontWeight={isSelected || isNew ? "600" : "400"}
                  >
                    {node.label}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
      </div>

      {/* ── Right panel: activity feed OR entity detail ─────────────── */}
      <div className="w-80 shrink-0 border-l border-border flex flex-col">

        {rightPanel === "activity" && (
          <>
            <div className="px-4 py-2 border-b border-border flex items-center gap-2">
              <Zap className="w-3.5 h-3.5 text-yellow-400" />
              <span className="text-xs font-semibold text-foreground uppercase tracking-wide">Live Updates</span>
            </div>
            <div className="flex-1 overflow-y-auto">
              {activity.length === 0 ? (
                <p className="text-xs text-muted-foreground px-4 py-6 text-center">
                  Updates appear here as agents post
                </p>
              ) : (
                <div className="divide-y divide-border">
                  {activity.map((a, i) => (
                    <div key={i} className={`px-4 py-3 ${i === 0 ? "bg-primary/5" : ""}`}>
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-xs font-medium text-muted-foreground truncate max-w-[170px]">{a.source}</span>
                        <span className="text-xs text-muted-foreground/50 shrink-0 ml-1">{timeAgo(a.time)}</span>
                      </div>
                      {a.entities.length > 0 && (
                        <div className="flex flex-wrap gap-1 mb-1.5">
                          {a.entities.map((e) => (
                            <button
                              key={e}
                              onClick={() => handleNodeClick(e)}
                              className={`text-xs px-1.5 py-0.5 rounded font-medium transition-colors ${
                                i === 0
                                  ? "bg-primary/20 text-primary border border-primary/30 hover:bg-primary/30"
                                  : "bg-muted text-muted-foreground hover:text-foreground"
                              }`}
                            >
                              {e}
                            </button>
                          ))}
                        </div>
                      )}
                      {a.relations.slice(0, 3).map((r, ri) => (
                        <div key={ri} className="text-xs text-muted-foreground/60 flex items-center gap-1 truncate">
                          <span className="text-primary/50 shrink-0">→</span>
                          <span className="truncate">{r[0]} <em>{r[1]}</em> {r[2]}</span>
                        </div>
                      ))}
                      {a.relations.length > 3 && (
                        <div className="text-xs text-muted-foreground/40 mt-0.5">+{a.relations.length - 3} more</div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}

        {rightPanel === "detail" && (
          <>
            <div className="px-4 py-2 border-b border-border flex items-center gap-2">
              <Network className="w-3.5 h-3.5 text-primary" />
              <span className="text-xs font-semibold text-foreground uppercase tracking-wide flex-1 truncate">
                {selectedEntity ?? "Entity"}
              </span>
              <button onClick={closeDetail} className="text-muted-foreground hover:text-foreground transition-colors">
                <X className="w-3.5 h-3.5" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto">
              {detailLoading && (
                <div className="flex items-center justify-center py-12">
                  <span className="text-xs text-muted-foreground animate-pulse">Loading...</span>
                </div>
              )}
              {!detailLoading && entityDetail && (
                <div className="p-4 space-y-4">
                  {/* Entity name */}
                  <div>
                    <div
                      className="inline-block px-2 py-0.5 rounded text-xs font-bold mb-1"
                      style={{ backgroundColor: NODE_COLORS[seededIndex(entityDetail.entity, NODE_COLORS.length)] + "33", color: NODE_COLORS[seededIndex(entityDetail.entity, NODE_COLORS.length)] }}
                    >
                      entity
                    </div>
                    <h3 className="font-semibold text-foreground text-sm">{entityDetail.entity}</h3>
                  </div>

                  {/* Relations FROM */}
                  {entityDetail.relations_from.length > 0 && (
                    <div>
                      <div className="flex items-center gap-1.5 mb-2">
                        <ArrowRight className="w-3 h-3 text-blue-400" />
                        <span className="text-xs font-semibold text-blue-400 uppercase tracking-wide">Outgoing ({entityDetail.relations_from.length})</span>
                      </div>
                      <div className="space-y-1.5">
                        {entityDetail.relations_from.slice(0, 8).map((r, i) => (
                          <div key={i} className="bg-blue-500/5 border border-blue-500/10 rounded-lg px-3 py-2">
                            <div className="text-xs text-blue-300/70 italic mb-0.5">{r[1]}</div>
                            <button
                              onClick={() => { setSelectedEntity(r[2]); fetchEntityDetail(r[2]); }}
                              className="text-xs text-foreground/80 hover:text-primary transition-colors font-medium"
                            >
                              {r[2]}
                            </button>
                          </div>
                        ))}
                        {entityDetail.relations_from.length > 8 && (
                          <div className="text-xs text-muted-foreground/50 px-1">+{entityDetail.relations_from.length - 8} more</div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Relations TO */}
                  {entityDetail.relations_to.length > 0 && (
                    <div>
                      <div className="flex items-center gap-1.5 mb-2">
                        <ArrowLeft className="w-3 h-3 text-purple-400" />
                        <span className="text-xs font-semibold text-purple-400 uppercase tracking-wide">Incoming ({entityDetail.relations_to.length})</span>
                      </div>
                      <div className="space-y-1.5">
                        {entityDetail.relations_to.slice(0, 8).map((r, i) => (
                          <div key={i} className="bg-purple-500/5 border border-purple-500/10 rounded-lg px-3 py-2">
                            <button
                              onClick={() => { setSelectedEntity(r[0]); fetchEntityDetail(r[0]); }}
                              className="text-xs text-foreground/80 hover:text-primary transition-colors font-medium"
                            >
                              {r[0]}
                            </button>
                            <div className="text-xs text-purple-300/70 italic">{r[1]}</div>
                          </div>
                        ))}
                        {entityDetail.relations_to.length > 8 && (
                          <div className="text-xs text-muted-foreground/50 px-1">+{entityDetail.relations_to.length - 8} more</div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Raw mentions */}
                  {entityDetail.mentions.length > 0 && (
                    <div>
                      <div className="flex items-center gap-1.5 mb-2">
                        <FileText className="w-3 h-3 text-muted-foreground" />
                        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Mentions ({entityDetail.mentions.length})</span>
                      </div>
                      <div className="space-y-2">
                        {entityDetail.mentions.map((m, i) => (
                          <div key={i} className="bg-muted/50 rounded-lg px-3 py-2">
                            <p className="text-xs text-muted-foreground leading-relaxed line-clamp-4">{m}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {entityDetail.relations_from.length === 0 && entityDetail.relations_to.length === 0 && entityDetail.mentions.length === 0 && (
                    <p className="text-xs text-muted-foreground text-center py-4">No detailed data found for this entity yet.</p>
                  )}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
