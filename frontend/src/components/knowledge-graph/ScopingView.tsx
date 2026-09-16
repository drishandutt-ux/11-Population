"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Check, Eye, EyeOff, Filter, RefreshCw, Sparkles, User } from "lucide-react";
import { api, type Agent, type KnowledgeUnit, type ScopeRule, type ScopingPreview, type ScopingState } from "@/lib/api";

interface Props {
  sessionId: string;
  agents: Agent[];
}

const PROV_COLORS: Record<string, string> = {
  official_statistic: "#38bdf8", peer_reviewed: "#4ade80", grey_literature: "#94a3b8", commissioned_research: "#a78bfa",
  client_data: "#facc15", social_signal: "#f472b6", model_inference: "#fb923c",
};
const DIM_COLORS: Record<string, string> = {
  geography: "#38bdf8", role: "#4ade80", channel: "#fb923c", condition: "#fb7185", stage: "#facc15", segment: "#f472b6",
  register: "#a78bfa", time: "#2dd4bf", provenance: "#94a3b8", project: "#64748b", licence: "#64748b", arm: "#64748b",
};
const FACET_ORDER = ["geography", "role", "channel", "condition", "stage", "segment", "register", "time"];

function timeAgo(iso: string): string {
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

function facetList(v: string[] | string | undefined): string[] {
  if (v === undefined || v === null || v === "") return [];
  return Array.isArray(v) ? v : [String(v)];
}

function Chip({ text, color, dim }: { text: string; color: string; dim?: boolean }) {
  return (
    <span className="inline-block px-1.5 py-0.5 rounded text-[10.5px] font-medium leading-tight" style={{ backgroundColor: color + (dim ? "1a" : "2e"), color, opacity: dim ? 0.6 : 1 }}>
      {text}
    </span>
  );
}

function UnitCard({ unit, highlight, extra }: { unit: KnowledgeUnit; highlight?: string[]; extra?: React.ReactNode }) {
  const prov = unit.provenance_class;
  return (
    <div className="rounded-lg border border-border/60 bg-muted/20 px-3 py-2 space-y-1.5">
      <div className="flex flex-wrap items-center gap-1">
        <Chip text={prov.replace(/_/g, " ")} color={PROV_COLORS[prov] || "#94a3b8"} />
        <Chip text={String(unit.facets.register || "lay")} color={DIM_COLORS.register} />
        {FACET_ORDER.filter((k) => k !== "register").flatMap((k) => facetList(unit.facets[k]).map((v) => (
          <Chip key={k + v} text={v} color={DIM_COLORS[k]} dim={highlight ? !highlight.includes(k) : false} />
        )))}
      </div>
      <p className="text-xs text-foreground/85 leading-relaxed line-clamp-3">{unit.text}</p>
      {unit.source_ref && <p className="text-[10.5px] text-muted-foreground/60 truncate">{unit.source_ref}</p>}
      {extra}
    </div>
  );
}

export default function ScopingView({ sessionId, agents }: Props) {
  const [state, setState] = useState<ScopingState | null>(null);
  const [loading, setLoading] = useState(true);
  const [tagging, setTagging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<{ dim: string; value: string } | null>(null);
  const [agentId, setAgentId] = useState<string>("");
  const [preview, setPreview] = useState<ScopingPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [panel, setPanel] = useState<"sees" | "hidden" | "block" | "policy">("sees");
  const [policyText, setPolicyText] = useState("");
  const [policySaving, setPolicySaving] = useState(false);
  const [policyMsg, setPolicyMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const s = await api.scoping.state(sessionId);
      setState(s);
      setPolicyText(JSON.stringify(s.policy?.rules ?? [], null, 2));
      setError(null);
    } catch (e: any) {
      setError(e?.message || "Could not load scoping.");
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (!agentId && agents.length > 0) setAgentId(agents[0].id); }, [agents, agentId]);

  const loadPreview = useCallback(async () => {
    if (!agentId || !state?.tagged) { setPreview(null); return; }
    setPreviewLoading(true);
    try {
      setPreview(await api.scoping.preview(sessionId, agentId));
    } catch (e: any) {
      setError(e?.message || "Preview failed.");
    } finally {
      setPreviewLoading(false);
    }
  }, [sessionId, agentId, state?.tagged]);

  useEffect(() => { loadPreview(); }, [loadPreview, state?.policy?.version, state?.snapshot_id]);

  async function tag() {
    setTagging(true);
    setError(null);
    try {
      const s = await api.scoping.tag(sessionId);
      setState(s);
      setPolicyText(JSON.stringify(s.policy?.rules ?? [], null, 2));
    } catch (e: any) {
      setError(e?.message || "Tagging failed.");
    } finally {
      setTagging(false);
    }
  }

  async function savePolicy() {
    setPolicySaving(true);
    setPolicyMsg(null);
    try {
      const rules = JSON.parse(policyText) as ScopeRule[];
      const r = await api.scoping.setPolicy(sessionId, rules, "edited in the Scoping view");
      setPolicyMsg(`Saved as version ${r.version}.`);
      await load();
    } catch (e: any) {
      setPolicyMsg(e?.message || "Could not save.");
    } finally {
      setPolicySaving(false);
    }
  }

  const units = useMemo(() => {
    const all = state?.units || [];
    if (!filter) return all;
    return all.filter((u) => filter.dim === "provenance" ? u.provenance_class === filter.value : facetList(u.facets[filter.dim]).includes(filter.value));
  }, [state, filter]);

  const agent = agents.find((a) => a.id === agentId);

  if (loading) return <div className="h-full flex items-center justify-center text-xs text-muted-foreground animate-pulse">Loading scoping…</div>;

  return (
    <div className="h-full flex overflow-hidden">
      {/* ── Knowledge pane ─────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="px-4 py-2 border-b border-border flex items-center gap-3 shrink-0">
          {state?.tagged ? (
            <span className="text-sm text-muted-foreground">
              <span className="text-foreground font-semibold">{state.unit_count}</span> knowledge units tagged
              {state.stale && (
                <span className="ml-3 inline-flex items-center gap-1 text-xs text-amber-400"><AlertTriangle className="w-3 h-3" /> the graph has {state.chunk_count} chunks now — re-tag</span>
              )}
            </span>
          ) : (
            <span className="text-sm text-muted-foreground">Nothing tagged yet. The graph holds <span className="text-foreground">{state?.chunk_count ?? 0}</span> chunks of knowledge.</span>
          )}
          <button
            onClick={tag}
            disabled={tagging || (state?.chunk_count ?? 0) === 0}
            className="ml-auto flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-primary/15 text-primary border border-primary/30 hover:bg-primary/25 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            title={(state?.chunk_count ?? 0) === 0 ? "Ingest sources or run research first" : undefined}
          >
            {tagging ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
            {tagging ? "Tagging…" : state?.tagged ? "Re-tag the knowledge" : "Tag the knowledge"}
          </button>
        </div>
        {error && <div className="px-4 py-2 text-xs text-red-300 bg-red-500/10 border-b border-red-500/20">{error}</div>}

        {state?.tagged ? (
          <>
            {/* facet coverage */}
            <div className="px-4 py-2 border-b border-border/60 space-y-1 shrink-0 max-h-44 overflow-y-auto">
              {["provenance", ...FACET_ORDER].map((dim) => {
                const vals = state.counts[dim];
                if (!vals || Object.keys(vals).length === 0) return null;
                return (
                  <div key={dim} className="flex items-start gap-2">
                    <span className="text-[10.5px] uppercase tracking-wide text-muted-foreground w-20 shrink-0 pt-0.5">{dim}</span>
                    <div className="flex flex-wrap gap-1">
                      {Object.entries(vals).sort((a, b) => b[1] - a[1]).map(([v, n]) => {
                        const on = filter?.dim === dim && filter.value === v;
                        return (
                          <button key={v} onClick={() => setFilter(on ? null : { dim, value: v })} className={`rounded transition-opacity ${on ? "ring-1 ring-white/60" : "hover:opacity-80"}`}>
                            <Chip text={`${v.replace(/_/g, " ")} · ${n}`} color={dim === "provenance" ? (PROV_COLORS[v] || "#94a3b8") : DIM_COLORS[dim] || "#94a3b8"} />
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
              <div className="text-[10.5px] text-muted-foreground/60 pt-1">Click a value to filter the units below{filter ? ` · showing ${units.length} of ${state.unit_count}` : ""}.</div>
            </div>
            <div className="flex-1 overflow-y-auto p-3 space-y-2">
              {units.map((u) => <UnitCard key={u.id} unit={u} />)}
              {units.length === 0 && <p className="text-xs text-muted-foreground text-center py-8">No units match that value.</p>}
            </div>
          </>
        ) : (
          <div className="flex-1 overflow-y-auto p-6">
            <div className="max-w-xl space-y-3 text-sm text-muted-foreground">
              <p><span className="text-foreground font-medium">Scoping</span> decides what each twin is allowed to know. Tagging reads every chunk in the graph once, classifies its provenance, and marks which places, roles, channels, conditions, stages and segments it is about, using the ontology as the vocabulary, plus how specialist it is.</p>
              <p>Every twin then gets an <span className="text-foreground">exposure profile</span> from its place, role, segment and register, and a <span className="text-foreground">policy</span> of rules matches the two. The debate, the Lab and chat give each twin only what it can reach, with a note on how it knows it.</p>
              <div className="pt-2">
                <div className="text-[10.5px] uppercase tracking-wide text-muted-foreground mb-2">Dimensions</div>
                <div className="grid grid-cols-1 gap-1.5">
                  {state?.dimensions.map((d) => (
                    <div key={d.key} className="rounded-lg border border-border/60 px-3 py-2">
                      <div className="flex items-center gap-2 text-xs"><span className="w-2 h-2 rounded-full" style={{ backgroundColor: DIM_COLORS[d.key] || "#94a3b8" }} /><span className="text-foreground font-medium">{d.label}</span><span className="text-muted-foreground/70">{d.semantics} · default {d.default}</span></div>
                      <p className="text-[11px] text-muted-foreground/80 mt-0.5">{d.description}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── Twin pane ──────────────────────────────────────────────── */}
      <div className="w-[26rem] shrink-0 border-l border-border flex flex-col overflow-hidden">
        <div className="px-4 py-2 border-b border-border flex items-center gap-2">
          <User className="w-3.5 h-3.5 text-primary" />
          <span className="text-xs font-semibold text-foreground uppercase tracking-wide">What a twin knows</span>
        </div>
        <div className="px-4 py-2 border-b border-border/60">
          <select value={agentId} onChange={(e) => setAgentId(e.target.value)} className="w-full bg-input border border-border rounded-lg px-2 py-1.5 text-xs text-foreground" aria-label="Twin">
            {agents.length === 0 && <option value="">No agents in this session yet</option>}
            {agents.map((a) => <option key={a.id} value={a.id}>{a.name} · {a.role}{a.demographics?.region ? ` · ${a.demographics.region}` : ""}</option>)}
          </select>
        </div>

        {!state?.tagged ? (
          <p className="text-xs text-muted-foreground px-4 py-6">Tag the knowledge first, then pick a twin to see what it can and cannot know.</p>
        ) : !agent ? (
          <p className="text-xs text-muted-foreground px-4 py-6">Spawn a population, then pick a twin.</p>
        ) : (
          <div className="flex-1 overflow-y-auto">
            {/* profile */}
            <div className="px-4 py-3 border-b border-border/60 space-y-1.5">
              <div className="text-[10.5px] uppercase tracking-wide text-muted-foreground">Exposure profile{preview?.profile ? ` · ${preview.profile.band}` : ""}</div>
              {previewLoading && !preview && <p className="text-xs text-muted-foreground animate-pulse">Working out what {agent.name} can reach…</p>}
              {preview?.profile && FACET_ORDER.concat(["arm"]).map((k) => {
                const vals = facetList(preview.profile!.values[k] as string[] | string | undefined);
                const basis = preview.profile!.basis[k] || "";
                if (vals.length === 0 && /not applied|no /.test(basis)) return null;
                return (
                  <div key={k} className="flex items-start gap-2">
                    <span className="text-[10.5px] uppercase tracking-wide text-muted-foreground w-16 shrink-0 pt-0.5">{k}</span>
                    <div className="min-w-0">
                      <div className="flex flex-wrap gap-1">{vals.length ? vals.map((v) => <Chip key={v} text={v} color={DIM_COLORS[k] || "#94a3b8"} />) : <span className="text-[11px] text-muted-foreground/60">none</span>}</div>
                      <div className="text-[10.5px] text-muted-foreground/60 leading-snug" title={basis}>{basis}</div>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* tabs */}
            <div className="px-4 pt-2 flex gap-1 border-b border-border/60">
              {([
                ["sees", <><Eye className="w-3 h-3" /> Sees {preview ? `(${preview.visible_total ?? preview.visible.length})` : ""}</>],
                ["hidden", <><EyeOff className="w-3 h-3" /> Hidden {preview ? `(${preview.hidden_total ?? preview.hidden.length})` : ""}</>],
                ["block", <>Prompt block</>],
                ["policy", <><Filter className="w-3 h-3" /> Policy v{state.policy?.version ?? 0}</>],
              ] as [typeof panel, React.ReactNode][]).map(([key, label]) => (
                <button key={key} onClick={() => setPanel(key)} className={`flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-t-md border-b-2 transition-colors ${panel === key ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}>
                  {label}
                </button>
              ))}
            </div>

            <div className="p-3 space-y-2">
              {panel === "sees" && preview && (
                preview.visible.length === 0 ? <p className="text-xs text-muted-foreground text-center py-6">Nothing reaches this twin under the current policy.</p> :
                preview.visible.map((v) => (
                  <UnitCard key={v.unit.id} unit={v.unit} extra={
                    <div className="flex items-center justify-between text-[10.5px]">
                      <span className="text-primary/90 italic">{v.route}</span>
                      <span className="text-muted-foreground/60">score {v.score}{v.applied.length ? ` · ${v.applied.join(", ")}` : ""}</span>
                    </div>
                  } />
                ))
              )}
              {panel === "hidden" && preview && (
                preview.hidden.length === 0 ? <p className="text-xs text-muted-foreground text-center py-6">Nothing is hidden from this twin.</p> :
                preview.hidden.map((h) => (
                  <UnitCard key={h.unit.id} unit={h.unit} highlight={h.failed.map((f) => f[0])} extra={
                    <div className="space-y-0.5">
                      {h.failed.map(([dim, why], i) => (
                        <div key={i} className="text-[10.5px] text-amber-300/80"><span className="uppercase tracking-wide text-amber-400/70">{dim}</span> · {why}</div>
                      ))}
                    </div>
                  } />
                ))
              )}
              {panel === "block" && preview && (
                <div>
                  <p className="text-[10.5px] text-muted-foreground/70 mb-2">Exactly what this twin is given as “things you happen to know” in the debate, the Lab and chat.</p>
                  <pre className="whitespace-pre-wrap text-[11px] leading-relaxed text-foreground/85 bg-muted/30 rounded-lg p-3 border border-border/60">{preview.block || "(empty)"}</pre>
                </div>
              )}
              {panel === "policy" && (
                <div className="space-y-2">
                  <p className="text-[10.5px] text-muted-foreground/70">Rules run in order after the base match. <code>when</code>: own · unscoped · any · [values]. <code>effect</code>: deny · require · allow (with <code>override</code>) · boost (<code>weight</code>) · route (<code>route</code>). Saving creates a new version; previews and every later turn use it.</p>
                  <textarea value={policyText} onChange={(e) => setPolicyText(e.target.value)} spellCheck={false} className="w-full h-64 bg-input border border-border rounded-lg p-2 text-[11px] font-mono text-foreground" />
                  <div className="flex items-center gap-2">
                    <button onClick={savePolicy} disabled={policySaving} className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-primary/15 text-primary border border-primary/30 hover:bg-primary/25 disabled:opacity-40">
                      {policySaving ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />} Save as new version
                    </button>
                    {policyMsg && <span className="text-[11px] text-muted-foreground">{policyMsg}</span>}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
