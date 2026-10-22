"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Loader2, RefreshCw, Search } from "lucide-react";
import { api, UsageOverview, UsageSessionDetail, UsageSessionRow } from "@/lib/api";

const PERIODS = [
  { days: 0, label: "All time" },
  { days: 30, label: "30 days" },
  { days: 7, label: "7 days" },
  { days: 1, label: "24 hours" },
];

type SortKey = "cost_usd" | "total_tokens" | "calls" | "last_at";

export function fmtTokens(n: number) {
  if (!n) return "0";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 1 : 2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 100_000 ? 0 : 1)}k`;
  return String(n);
}

export function fmtUsd(n: number) {
  if (!n) return "$0.00";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  if (n < 100) return `$${n.toFixed(2)}`;
  return `$${Math.round(n).toLocaleString()}`;
}

function shortModel(m: string) {
  return m.replace(/^claude-/, "").replace(/-\d{8}$/, "");
}

function when(ts: string | null) {
  if (!ts) return "—";
  const d = new Date(ts.endsWith("Z") || ts.includes("+") ? ts : ts + "Z");
  return d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="border border-border/60 rounded-lg px-4 py-3">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">{label}</div>
      <div className="text-xl font-semibold text-foreground tabular-nums mt-1">{value}</div>
      {sub && <div className="text-[11px] text-muted-foreground mt-0.5 tabular-nums">{sub}</div>}
    </div>
  );
}

function SessionDetail({ row, days }: { row: UsageSessionRow; days: number }) {
  const [data, setData] = useState<UsageSessionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showCalls, setShowCalls] = useState(false);

  useEffect(() => {
    let live = true;
    api.admin.usageSession(row.session_id, days)
      .then((d) => live && setData(d))
      .catch((e) => live && setError(e?.message || "Couldn't load"));
    return () => { live = false; };
  }, [row.session_id, days]);

  if (error) return <p className="text-xs text-red-400 px-4 py-3">{error}</p>;
  if (!data) return <div className="px-4 py-3 text-xs text-muted-foreground"><Loader2 className="w-3 h-3 inline animate-spin mr-1" /> Loading breakdown…</div>;

  return (
    <div className="px-4 py-3 space-y-3 bg-muted/10">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">By execution</div>
      <table className="w-full text-xs">
        <thead className="text-[10px] text-muted-foreground">
          <tr>
            <th className="text-left font-medium py-1">Execution</th>
            <th className="text-left font-medium py-1">Model</th>
            <th className="text-right font-medium py-1">Calls</th>
            <th className="text-right font-medium py-1">Input</th>
            <th className="text-right font-medium py-1">Output</th>
            <th className="text-right font-medium py-1">Cache r/w</th>
            <th className="text-right font-medium py-1">Cost</th>
          </tr>
        </thead>
        <tbody>
          {data.executions.map((e) => (
            <tr key={e.label + e.model} className="border-t border-border/30">
              <td className="py-1 text-foreground">{e.label}{e.errors > 0 && <span className="ml-1.5 text-[10px] text-red-400">{e.errors} failed</span>}</td>
              <td className="py-1 text-muted-foreground">{shortModel(e.model)}</td>
              <td className="py-1 text-right tabular-nums">{e.calls}</td>
              <td className="py-1 text-right tabular-nums">{fmtTokens(e.input_tokens)}</td>
              <td className="py-1 text-right tabular-nums">{fmtTokens(e.output_tokens)}</td>
              <td className="py-1 text-right tabular-nums text-muted-foreground">{fmtTokens(e.cache_read_tokens)} / {fmtTokens(e.cache_creation_tokens)}</td>
              <td className="py-1 text-right tabular-nums text-foreground">{fmtUsd(e.cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <button onClick={() => setShowCalls((v) => !v)} className="text-[11px] text-primary hover:underline">
        {showCalls ? "Hide" : "Show"} individual calls ({data.recent.length}{data.recent.length === 200 ? ", most recent" : ""})
      </button>
      {showCalls && (
        <div className="max-h-72 overflow-y-auto border border-border/40 rounded">
          <table className="w-full text-[11px]">
            <thead className="sticky top-0 bg-background text-[10px] text-muted-foreground">
              <tr>
                <th className="text-left font-medium px-2 py-1">When</th>
                <th className="text-left font-medium px-2 py-1">Execution</th>
                <th className="text-left font-medium px-2 py-1">Model</th>
                <th className="text-right font-medium px-2 py-1">In</th>
                <th className="text-right font-medium px-2 py-1">Out</th>
                <th className="text-right font-medium px-2 py-1">Secs</th>
                <th className="text-right font-medium px-2 py-1">Cost</th>
              </tr>
            </thead>
            <tbody>
              {data.recent.map((c, i) => (
                <tr key={i} className="border-t border-border/30">
                  <td className="px-2 py-1 text-muted-foreground whitespace-nowrap">{when(c.created_at)}</td>
                  <td className="px-2 py-1">{c.label}{c.status !== "success" && <span className="ml-1 text-red-400">failed</span>}</td>
                  <td className="px-2 py-1 text-muted-foreground">{shortModel(c.model)}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{fmtTokens(c.input_tokens + c.cache_read_tokens + c.cache_creation_tokens)}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{fmtTokens(c.output_tokens)}</td>
                  <td className="px-2 py-1 text-right tabular-nums text-muted-foreground">{c.elapsed_sec?.toFixed(1)}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{fmtUsd(c.cost_usd)}{!c.priced && "*"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function UsageAnalyser() {
  const [days, setDays] = useState(0);
  const [data, setData] = useState<UsageOverview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<SortKey>("cost_usd");
  const [open, setOpen] = useState<string | null>(null);

  async function load(d = days) {
    setLoading(true);
    setError(null);
    try {
      setData(await api.admin.usage(d));
    } catch (e: any) {
      setError(e?.message || "Couldn't load usage");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(days); setOpen(null); }, [days]); // eslint-disable-line react-hooks/exhaustive-deps

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const list = (data?.sessions || []).filter((s) =>
      !needle || s.title.toLowerCase().includes(needle) || (s.owner_email || "").toLowerCase().includes(needle) || s.session_id.startsWith(needle)
      || s.models.some((m) => m.model.toLowerCase().includes(needle)),
    );
    return [...list].sort((a, b) =>
      sort === "last_at" ? (b.last_at || "").localeCompare(a.last_at || "") : (b[sort] as number) - (a[sort] as number),
    );
  }, [data, q, sort]);

  const t = data?.totals;
  const SortHead = ({ k, children }: { k: SortKey; children: React.ReactNode }) => (
    <th className="text-right px-3 py-2.5 font-semibold">
      <button onClick={() => setSort(k)} className={sort === k ? "text-foreground" : "hover:text-foreground"}>
        {children}{sort === k && " ↓"}
      </button>
    </th>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex border border-border/60 rounded-md overflow-hidden">
          {PERIODS.map((p) => (
            <button key={p.days} onClick={() => setDays(p.days)}
              className={`text-xs px-3 py-1.5 ${days === p.days ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground"}`}>
              {p.label}
            </button>
          ))}
        </div>
        <button onClick={() => load()} disabled={loading} className="text-muted-foreground hover:text-foreground p-1.5 rounded border border-border/60" title="Refresh">
          {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
        </button>
        <div className="ml-auto relative">
          <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter by session, owner or model"
            className="text-xs bg-transparent border border-border/60 rounded-md pl-7 pr-2 py-1.5 w-64 focus:outline-none focus:border-primary/50" />
        </div>
      </div>

      {error && <p className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">{error}</p>}

      {t && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Tile label="Total cost" value={fmtUsd(t.cost_usd)} sub={t.unpriced ? `${t.unpriced} calls estimated*` : "at Anthropic list prices"} />
          <Tile label="Total tokens" value={fmtTokens(t.total_tokens)} sub={`${fmtTokens(t.input_tokens)} in · ${fmtTokens(t.output_tokens)} out`} />
          <Tile label="LLM calls" value={t.calls.toLocaleString()} sub={`${t.errors} failed${t.web_search_requests ? ` · ${t.web_search_requests} web searches` : ""}`} />
          <Tile label="Sessions" value={String(t.sessions)} sub={t.sessions ? `${fmtUsd(t.cost_usd / Math.max(1, t.sessions))} avg per session` : undefined} />
        </div>
      )}

      {data && data.models.length > 0 && (
        <div className="border border-border/60 rounded-lg px-4 py-3">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-2">Models used</div>
          <div className="space-y-1.5">
            {data.models.map((m) => {
              const share = t && t.cost_usd ? m.cost_usd / t.cost_usd : 0;
              return (
                <div key={m.model} className="flex items-center gap-3 text-xs">
                  <span className="w-48 truncate text-foreground" title={m.model}>{shortModel(m.model)}</span>
                  <div className="flex-1 h-1.5 bg-muted/40 rounded overflow-hidden">
                    <div className="h-full bg-primary/70" style={{ width: `${Math.max(1, share * 100)}%` }} />
                  </div>
                  <span className="w-20 text-right tabular-nums text-muted-foreground">{m.calls.toLocaleString()} calls</span>
                  <span className="w-20 text-right tabular-nums text-muted-foreground">{fmtTokens(m.total_tokens)}</span>
                  <span className="w-20 text-right tabular-nums text-foreground">{fmtUsd(m.cost_usd)}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="border border-border/60 rounded-lg overflow-x-auto">
        <table className="w-full text-sm min-w-[860px]">
          <thead className="bg-muted/30 text-[10px] uppercase tracking-wider text-muted-foreground">
            <tr>
              <th className="text-left px-3 py-2.5 font-semibold">Session</th>
              <th className="text-left px-3 py-2.5 font-semibold">Models</th>
              <SortHead k="calls">Calls</SortHead>
              <th className="text-right px-3 py-2.5 font-semibold">Input</th>
              <th className="text-right px-3 py-2.5 font-semibold">Output</th>
              <th className="text-right px-3 py-2.5 font-semibold">Cache</th>
              <SortHead k="total_tokens">Tokens</SortHead>
              <SortHead k="cost_usd">Cost</SortHead>
              <SortHead k="last_at">Last call</SortHead>
            </tr>
          </thead>
          <tbody>
            {data && rows.length === 0 && (
              <tr><td colSpan={9} className="px-4 py-8 text-center text-xs text-muted-foreground">
                {data.sessions.length === 0 ? "No LLM calls recorded yet in this period. Usage is logged from the moment this feature was switched on." : "No sessions match the filter."}
              </td></tr>
            )}
            {rows.map((s) => {
              const isOpen = open === s.session_id;
              return (
                <Fragment key={s.session_id}>
                  <tr onClick={() => setOpen(isOpen ? null : s.session_id)} className="border-t border-border/40 cursor-pointer hover:bg-muted/20">
                    <td className="px-3 py-2.5 max-w-[260px]">
                      <div className="flex items-start gap-1.5">
                        {isOpen ? <ChevronDown className="w-3.5 h-3.5 mt-0.5 shrink-0 text-muted-foreground" /> : <ChevronRight className="w-3.5 h-3.5 mt-0.5 shrink-0 text-muted-foreground" />}
                        <div className="min-w-0">
                          <div className={`text-xs font-medium truncate ${s.exists ? "text-foreground" : "text-muted-foreground italic"}`} title={s.title}>{s.title}</div>
                          <div className="text-[11px] text-muted-foreground truncate">
                            {s.owner_email || (s.session_id === "none" ? "kits, global search, background jobs" : s.session_id.slice(0, 8))}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex flex-wrap gap-1">
                        {s.models.map((m) => (
                          <span key={m.model} title={`${m.model}: ${m.calls} calls, ${fmtUsd(m.cost_usd)}`} className="text-[10px] px-1.5 py-0.5 rounded border border-border text-muted-foreground">
                            {shortModel(m.model)}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-right text-xs tabular-nums">{s.calls.toLocaleString()}{s.errors > 0 && <div className="text-[10px] text-red-400">{s.errors} failed</div>}</td>
                    <td className="px-3 py-2.5 text-right text-xs tabular-nums text-muted-foreground">{fmtTokens(s.input_tokens)}</td>
                    <td className="px-3 py-2.5 text-right text-xs tabular-nums text-muted-foreground">{fmtTokens(s.output_tokens)}</td>
                    <td className="px-3 py-2.5 text-right text-xs tabular-nums text-muted-foreground">{fmtTokens(s.cache_read_tokens + s.cache_creation_tokens)}</td>
                    <td className="px-3 py-2.5 text-right text-xs tabular-nums text-foreground">{fmtTokens(s.total_tokens)}</td>
                    <td className="px-3 py-2.5 text-right text-xs tabular-nums font-medium text-foreground">{fmtUsd(s.cost_usd)}{s.unpriced > 0 && "*"}</td>
                    <td className="px-3 py-2.5 text-right text-[11px] text-muted-foreground whitespace-nowrap">{when(s.last_at)}</td>
                  </tr>
                  {isOpen && (
                    <tr className="border-t border-border/30"><td colSpan={9} className="p-0"><SessionDetail row={s} days={days} /></td></tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="text-[11px] text-muted-foreground">
        Exact token counts from every Claude call, priced at Anthropic&apos;s list rates (cache writes at the 5-minute rate, web search at $10 per 1,000).
        * = model not in the price table, priced as an estimate. Calls are tied to a session by the request that started them; work with no session
        (kit builds, global search) is grouped as &ldquo;Not tied to a session&rdquo;. Spend on deleted sessions is kept.
      </p>
    </div>
  );
}
