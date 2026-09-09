"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api, EvidenceItem, ResearchQuery, ResearchRun, ResearchState } from "@/lib/api";
import {
  Globe, MessageSquare, Loader2, CheckCircle2, Circle, Square, Plus, AlertCircle, ExternalLink,
  EyeOff, Eye, Search, Gauge, ChevronDown, ChevronUp, Sparkles, FlaskConical,
} from "lucide-react";

interface Props {
  sessionId: string;
  state: ResearchState | null;
  items: EvidenceItem[];
  onStart: () => Promise<void>;
  onStop: () => Promise<void>;
  onAddSubQuestion: (text: string) => Promise<void>;
  onToggleExclude: (item: EvidenceItem) => Promise<void>;
}

const STATUS_LABEL: Record<string, string> = {
  queued: "queued", running: "researching…", stopping: "stopping…", finalising: "building the brief…", complete: "complete", stopped: "stopped", interrupted: "interrupted", error: "failed",
};

function fmtSecs(s: number) {
  const m = Math.floor(s / 60), r = s % 60;
  return m ? `${m}m ${r.toString().padStart(2, "0")}s` : `${r}s`;
}

function QueryRow({ q }: { q: ResearchQuery }) {
  const icon = q.source === "web" ? <Globe className="w-3 h-3 text-sky-400" /> : <MessageSquare className="w-3 h-3 text-orange-400" />;
  const status =
    q.status === "running" ? <Loader2 className="w-3 h-3 animate-spin text-primary" />
    : q.status === "done" ? <CheckCircle2 className="w-3 h-3 text-emerald-400" />
    : q.status === "error" ? <AlertCircle className="w-3 h-3 text-red-400" />
    : <Circle className="w-3 h-3 text-muted-foreground/40" />;
  return (
    <div className="flex items-start gap-2 py-1.5 border-b border-border/20 last:border-0">
      <span className="mt-0.5 shrink-0">{icon}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-foreground/85 truncate">{q.query}</span>
          <span className="text-[9px] text-muted-foreground/50 shrink-0">r{q.round}</span>
        </div>
        {q.note && <p className="text-[10px] text-muted-foreground/60 leading-snug mt-0.5 line-clamp-2">{q.note}</p>}
      </div>
      <span className="mt-0.5 shrink-0" title={q.status}>{status}</span>
    </div>
  );
}

function ItemCard({ item, onToggleExclude }: { item: EvidenceItem; onToggleExclude: (i: EvidenceItem) => void }) {
  const [open, setOpen] = useState(false);
  const social = item.source_class === "social";
  const s = item.structured || {};
  const muted = item.excluded || !item.on_topic;
  return (
    <div className={`rounded-lg border px-3 py-2.5 transition-colors ${item.excluded ? "border-border/20 opacity-40" : item.on_topic ? "border-border/50 bg-card/40" : "border-border/25 opacity-70"}`}>
      <div className="flex items-center gap-2 mb-1">
        <span className={`text-[9px] uppercase tracking-wide px-1.5 py-0.5 rounded border ${social ? "border-orange-500/30 text-orange-300" : "border-sky-500/30 text-sky-300"}`}>
          {social ? (s.subreddit || "reddit") : (item.author || "web")}
        </span>
        {item.published_at && <span className="text-[10px] text-muted-foreground/50">{item.published_at.slice(0, 10)}</span>}
        {item.in_graph && <span className="text-[9px] text-emerald-400/80 border border-emerald-500/25 rounded px-1">in graph</span>}
        <span className={`ml-auto text-[10px] tabular-nums ${item.on_topic ? "text-primary" : "text-muted-foreground/50"}`} title="relevance">
          {item.on_topic ? "on-topic" : "off-topic"} · {Math.round((item.relevance || 0) * 100)}%
        </span>
      </div>
      <p className={`text-xs font-medium leading-snug ${muted ? "text-foreground/60" : "text-foreground/90"}`}>{item.title || item.source_ref}</p>
      <p className={`text-[11px] leading-snug mt-1 ${open ? "" : "line-clamp-3"} text-muted-foreground/75`}>{item.text}</p>
      {social && Array.isArray(s.public_comments) && s.public_comments.length > 0 && open && (
        <div className="mt-2 space-y-1 border-l border-border/40 pl-2">
          {s.public_comments.slice(0, 6).map((c: any, k: number) => (
            <p key={k} className="text-[10px] text-muted-foreground/70 leading-snug"><span className="text-foreground/60">{c.author}</span> · {c.likes} pts — {c.text}</p>
          ))}
        </div>
      )}
      <div className="flex items-center gap-3 mt-1.5 text-[10px]">
        <button onClick={() => setOpen(!open)} className="text-muted-foreground/60 hover:text-foreground flex items-center gap-0.5">
          {open ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}{open ? "less" : "more"}
        </button>
        <a href={item.source_ref} target="_blank" rel="noreferrer" className="text-muted-foreground/60 hover:text-foreground flex items-center gap-0.5">
          <ExternalLink className="w-3 h-3" /> open
        </a>
        <button onClick={() => onToggleExclude(item)} className="ml-auto text-muted-foreground/60 hover:text-foreground flex items-center gap-0.5" title={item.excluded ? "Include in graph and personas" : "Exclude from graph and personas"}>
          {item.excluded ? <><Eye className="w-3 h-3" /> include</> : <><EyeOff className="w-3 h-3" /> exclude</>}
        </button>
        {social && typeof s.score === "number" && <span className="text-muted-foreground/50">{s.score} pts · {s.comments ?? 0} comments</span>}
      </div>
    </div>
  );
}

export default function ResearchPanel({ sessionId, state, items, onStart, onStop, onAddSubQuestion, onToggleExclude }: Props) {
  const run: ResearchRun | null = state?.run ?? null;
  const queries = state?.queries ?? [];
  const [subq, setSubq] = useState("");
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState<"all" | "on" | "web" | "social">("all");
  const feedRef = useRef<HTMLDivElement>(null);
  const [now, setNow] = useState(Date.now());
  const active = run?.status === "running" || run?.status === "queued" || run?.status === "stopping" || run?.status === "finalising";
  const canStop = run?.status === "running" || run?.status === "queued";

  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);

  const counts = useMemo(() => {
    const c = { web: { read: 0, on: 0 }, social: { read: 0, on: 0 }, graph: 0, comments: 0 };
    for (const i of items) {
      if (i.excluded) continue;
      const k = i.source_class === "social" ? "social" : "web";
      c[k].read += 1;
      if (i.on_topic) c[k].on += 1;
      if (i.in_graph) c.graph += 1;
      if (i.source_class === "social") c.comments += (i.structured?.public_comments?.length || 0);
    }
    return c;
  }, [items]);

  const stance = useMemo(() => {
    const b = run?.brief;
    if (!b || !b.groups?.length) return null;
    return { f: b.overall_for_pct || 0, a: b.overall_against_pct || 0, m: b.overall_mixed_pct || 0 };
  }, [run?.brief]);

  const visible = items.filter((i) => filter === "all" || (filter === "on" ? i.on_topic : i.source_class === (filter === "web" ? "web" : "social")));
  const elapsed = run?.started_at ? Math.max(0, Math.floor(((run.finished_at ? new Date(run.finished_at).getTime() : now) - new Date(run.started_at).getTime()) / 1000)) : 0;
  const budget = run?.budget || {};
  const subqs: { id: string; text: string; kind: string }[] = run?.frame?.sub_questions || [];
  const covered = new Set<string>(run?.covered || []);

  async function act(fn: () => Promise<void>) {
    setBusy(true);
    try { await fn(); } finally { setBusy(false); }
  }

  if (!run) {
    return (
      <div className="rounded-lg border border-border/60 p-5 text-center">
        <Search className="w-6 h-6 text-primary mx-auto mb-2" />
        <p className="text-sm font-medium text-foreground mb-1">Research this question</p>
        <p className="text-xs text-muted-foreground/70 mb-4 max-w-md mx-auto">
          Decomposes the query into sub-questions, searches the web and Reddit, reads the pages and threads, judges what is relevant, refines, and stops when coverage is good enough. Everything lands live below.
        </p>
        <button onClick={() => act(onStart)} disabled={busy} className="bg-primary hover:bg-primary/90 disabled:opacity-50 text-primary-foreground text-sm font-medium px-4 py-2 rounded-md inline-flex items-center gap-2">
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />} Start research
        </button>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] gap-4">
      {/* ── Left: plan + progress ───────────────────────────────────────── */}
      <div className="space-y-3 min-w-0">
        <div className="rounded-lg border border-border/60 p-4">
          <div className="flex items-center gap-2 mb-2">
            {active ? <Loader2 className="w-3.5 h-3.5 animate-spin text-primary" /> : run.status === "complete" ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> : <AlertCircle className="w-3.5 h-3.5 text-yellow-400" />}
            <span className="text-xs font-semibold text-foreground">Research · {STATUS_LABEL[run.status] || run.status}</span>
            <span className="ml-auto text-[10px] text-muted-foreground/60 tabular-nums">{fmtSecs(elapsed)}</span>
            {active ? (
              <button onClick={() => act(onStop)} disabled={busy || !canStop} className="text-[10px] flex items-center gap-1 border border-red-500/40 text-red-400 rounded px-1.5 py-0.5 hover:bg-red-500/10 disabled:opacity-50">
                {canStop ? <><Square className="w-2.5 h-2.5" /> Stop</> : <><Loader2 className="w-2.5 h-2.5 animate-spin" /> {run?.status === "finalising" ? "Finishing" : "Stopping"}</>}
              </button>
            ) : (
              <button onClick={() => act(onStart)} disabled={busy} className="text-[10px] flex items-center gap-1 border border-border/60 text-muted-foreground rounded px-1.5 py-0.5 hover:text-foreground disabled:opacity-50">
                <Sparkles className="w-2.5 h-2.5" /> Run again
              </button>
            )}
          </div>
          {run.note && (!active || run.status === "stopping" || run.status === "finalising") && <p className="text-[10px] text-muted-foreground/70 mb-2">{run.note}</p>}

          {/* Sub-question checklist */}
          {run.frame ? (
            <div className="space-y-1">
              {run.frame.subject && <p className="text-[10px] text-muted-foreground/70 mb-1.5"><span className="uppercase tracking-wide">Subject</span> · {run.frame.subject}</p>}
              {subqs.map((q) => (
                <div key={q.id} className="flex items-start gap-2 text-[11px]">
                  {covered.has(q.id) ? <CheckCircle2 className="w-3 h-3 text-emerald-400 mt-0.5 shrink-0" /> : <Circle className="w-3 h-3 text-muted-foreground/40 mt-0.5 shrink-0" />}
                  <span className={covered.has(q.id) ? "text-foreground/80" : "text-muted-foreground/80"}>{q.text} <span className="text-[9px] text-muted-foreground/40">{q.kind}</span></span>
                </div>
              ))}
              {run.frame.lookalikes?.length > 0 && <p className="text-[10px] text-muted-foreground/50 mt-1.5">Excluding look-alikes: {run.frame.lookalikes.join(", ")}</p>}
            </div>
          ) : (
            <p className="text-[11px] text-muted-foreground/70 flex items-center gap-1.5"><Loader2 className="w-3 h-3 animate-spin" /> Framing the question…</p>
          )}

          {/* Add a sub-question */}
          <form className="flex gap-1.5 mt-3" onSubmit={(e) => { e.preventDefault(); if (subq.trim()) act(() => onAddSubQuestion(subq.trim()).then(() => setSubq(""))); }}>
            <input value={subq} onChange={(e) => setSubq(e.target.value)} placeholder="Add a sub-question to research…" className="flex-1 bg-muted/40 border border-border/60 rounded px-2 py-1 text-[11px] text-foreground placeholder-muted-foreground/40 focus:outline-none focus:ring-1 focus:ring-primary/50" />
            <button type="submit" disabled={!subq.trim() || busy} className="text-[10px] border border-border/60 rounded px-2 text-muted-foreground hover:text-foreground disabled:opacity-40 flex items-center gap-1"><Plus className="w-3 h-3" /> Add</button>
          </form>
        </div>

        {/* Queries */}
        <div className="rounded-lg border border-border/60 p-4">
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground/60 mb-1.5">Queries {run.plan?.rationale ? <span className="normal-case text-muted-foreground/50">· {run.plan.rationale}</span> : null}</p>
          {queries.length === 0 ? <p className="text-[11px] text-muted-foreground/60">Planning queries…</p> : queries.map((q) => <QueryRow key={q.id} q={q} />)}
        </div>

        {/* Verdicts */}
        {run.verdicts?.length > 0 && (
          <div className="rounded-lg border border-border/60 p-4 space-y-1.5">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Judge</p>
            {run.verdicts.slice(-6).map((v: any, k: number) => (
              <div key={k} className="text-[10px] leading-snug">
                <span className={`px-1 rounded border mr-1 ${v.source === "web" ? "border-sky-500/30 text-sky-300" : "border-orange-500/30 text-orange-300"}`}>{v.source} r{v.round}</span>
                <span className="text-foreground/75">{v.on_topic}/{v.read} on-topic · {v.reason}</span>
                {v.missing?.length > 0 && <span className="text-yellow-400/80"> Missing: {v.missing.join("; ")}</span>}
              </div>
            ))}
          </div>
        )}

        {/* Budget */}
        <div className="rounded-lg border border-border/60 p-4">
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground/60 mb-2 flex items-center gap-1"><Gauge className="w-3 h-3" /> Budget</p>
          <div className="grid grid-cols-3 gap-2 text-center">
            {[["queries", budget.queries, budget.max_queries], ["pages", budget.pages, budget.max_pages], ["seconds", elapsed, budget.max_seconds]].map(([l, u, m]) => (
              <div key={l as string} className="bg-muted/30 rounded p-2">
                <div className="text-sm font-semibold text-foreground tabular-nums">{u ?? 0}<span className="text-muted-foreground/50 text-[10px]"> / {m ?? "–"}</span></div>
                <div className="text-[9px] uppercase tracking-wide text-muted-foreground/60">{l as string}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Right: evidence feed ────────────────────────────────────────── */}
      <div className="space-y-3 min-w-0">
        <div className="rounded-lg border border-border/60 p-3">
          <div className="grid grid-cols-4 gap-2 text-center">
            {[
              ["Web", `${counts.web.on}/${counts.web.read}`, "on-topic / read"],
              ["Reddit", `${counts.social.on}/${counts.social.read}`, `${counts.comments} comments`],
              ["In graph", String(counts.graph), "items ingested"],
              ["Stance", stance ? `${stance.f}/${stance.a}/${stance.m}` : "–", "for / against / mixed"],
            ].map(([l, v, d]) => (
              <div key={l} className="bg-muted/30 rounded p-2">
                <div className="text-[9px] uppercase tracking-wide text-muted-foreground/60">{l}</div>
                <div className="text-sm font-semibold text-foreground tabular-nums">{v}</div>
                <div className="text-[9px] text-muted-foreground/50">{d}</div>
              </div>
            ))}
          </div>
          <div className="flex gap-1 mt-2">
            {(["all", "on", "web", "social"] as const).map((f) => (
              <button key={f} onClick={() => setFilter(f)} className={`text-[10px] px-2 py-0.5 rounded border ${filter === f ? "border-primary/50 text-primary bg-primary/10" : "border-border/40 text-muted-foreground/70 hover:text-foreground"}`}>
                {f === "all" ? "All" : f === "on" ? "On-topic" : f === "web" ? "Web" : "Reddit"}
              </button>
            ))}
            <span className="ml-auto text-[10px] text-muted-foreground/50 self-center">{visible.length} items · off-topic kept, greyed</span>
          </div>
        </div>

        <div ref={feedRef} className="space-y-2 max-h-[560px] overflow-y-auto pr-1">
          {visible.length === 0 ? (
            <p className="text-[11px] text-muted-foreground/60 text-center py-8">{active ? "Evidence will appear here as pages and threads are read…" : "No evidence yet."}</p>
          ) : (
            [...visible].reverse().map((i) => <ItemCard key={i.id} item={i} onToggleExclude={onToggleExclude} />)
          )}
        </div>

        {/* Brief + recommendations */}
        {run.brief && run.brief.groups?.length > 0 && (
          <div className="rounded-lg border border-primary/30 bg-primary/5 p-4">
            <p className="text-[10px] uppercase tracking-wider text-primary font-semibold mb-1.5">Evidence brief</p>
            <p className="text-xs text-foreground/85 leading-relaxed mb-2">{run.brief.summary}</p>
            <div className="space-y-1.5">
              {run.brief.groups.map((g: any, k: number) => (
                <div key={k} className="text-[11px]">
                  <span className="font-medium text-foreground/90">{g.name}</span>
                  <span className={`ml-1.5 text-[9px] px-1 rounded border ${g.stance === "for" ? "border-emerald-500/30 text-emerald-300" : g.stance === "against" ? "border-red-500/30 text-red-300" : "border-border text-muted-foreground"}`}>{g.stance} · ~{g.share_pct}%</span>
                  {g.arguments?.length > 0 && <span className="text-muted-foreground/75"> — {g.arguments.slice(0, 2).join("; ")}</span>}
                  {g.quotes?.[0] && <p className="text-[10px] text-muted-foreground/60 italic mt-0.5">“{g.quotes[0]}”</p>}
                </div>
              ))}
            </div>
            {run.brief.gaps?.length > 0 && <p className="text-[10px] text-yellow-400/80 mt-2">Gaps: {run.brief.gaps.join("; ")}</p>}
          </div>
        )}
        {run.recommendations && run.recommendations.length > 0 && (
          <div className="rounded-lg border border-border/60 p-4">
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground/60 mb-2 flex items-center gap-1"><FlaskConical className="w-3 h-3" /> Recommended tools</p>
            <div className="space-y-2">
              {run.recommendations.map((r: any, k: number) => (
                <div key={k} className="flex items-start gap-2 text-[11px]">
                  <span className="text-[9px] px-1.5 py-0.5 rounded border border-primary/40 text-primary shrink-0 mt-0.5">{Math.round((r.confidence || 0) * 100)}%</span>
                  <div className="min-w-0">
                    <span className="font-medium text-foreground/90">{r.label || r.tool}</span>
                    <span className="text-muted-foreground/75"> — {r.reason}</span>
                    {r.spec_summary && <p className="text-[10px] text-muted-foreground/60 mt-0.5">{r.spec_summary}{r.variants?.length ? ` · Variants: ${r.variants.join(" vs ")}` : ""}{r.price_anchors?.length ? ` · Prices: ${r.price_anchors.join(", ")}` : ""}</p>}
                  </div>
                </div>
              ))}
            </div>
            <p className="text-[10px] text-muted-foreground/50 mt-2">Tools open in the Tools menu (next phase). Nothing is run automatically.</p>
          </div>
        )}
      </div>
    </div>
  );
}
