"use client";

import { Fragment, ReactNode, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { api, Playbook, PlaybookLink, PlaybookSection, PlaybookVariable } from "@/lib/api";
import { X, Plus, Trash2, Download, Save, Check, Loader2, ArrowUp, ArrowDown, FileText, BookOpen, RefreshCw } from "lucide-react";

const AXES = ["demographic", "behavioural", "value-based", "needs-based", "attitudinal", "other"];
const KIND_HINT: Record<PlaybookVariable["kind"], string> = {
  dial: "a 0–10 dial on every twin, drawn inside its segment's range, pushing the standard dials below",
  category: "one label per twin, a cell on the population map",
  rule: "a behaviour every twin follows",
};

export function downloadText(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

const fileName = (title: string) => `${(title || "playbook").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "playbook"}.md`;
const dialWords = (path: string) => path.split(".").slice(1).join(".").replace(/_/g, " ");
const cap = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

// ── the analyst's own markdown, rendered as React (no HTML injection) ─────────

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /\*\*(.+?)\*\*|\*([^*\s][^*]*?)\*/g;
  let last = 0; let m: RegExpExecArray | null; let k = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(m[1] ? <strong key={k++} className="text-foreground/95 font-medium">{m[1]}</strong> : <em key={k++}>{m[2]}</em>);
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  const lines = text.split("\n");
  let i = 0; let key = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    if (line.trim().startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        const cells = lines[i].trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
        if (!cells.every((c) => /^:?-+:?$/.test(c))) rows.push(cells);
        i++;
      }
      const [head, ...body] = rows;
      blocks.push(
        <div key={key++} className="overflow-x-auto">
          <table className="text-xs w-full border-collapse">
            <thead><tr>{head.map((c, j) => <th key={j} className="text-left font-medium text-muted-foreground px-2 py-1 border-b border-border/60">{inline(c)}</th>)}</tr></thead>
            <tbody>{body.map((r, j) => <tr key={j}>{r.map((c, n) => <td key={n} className="px-2 py-1 border-b border-border/30 text-foreground/85 align-top">{inline(c)}</td>)}</tr>)}</tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && (/^\s*[-*]\s+/.test(lines[i]) || (items.length > 0 && /^\s{2,}\S/.test(lines[i])))) {
        if (/^\s*[-*]\s+/.test(lines[i])) items.push(lines[i].replace(/^\s*[-*]\s+/, "")); else items[items.length - 1] += " " + lines[i].trim();
        i++;
      }
      blocks.push(<ul key={key++} className="list-disc pl-5 space-y-0.5 text-xs text-foreground/85">{items.map((t, j) => <li key={j}>{inline(t)}</li>)}</ul>);
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !lines[i].trim().startsWith("|") && !/^\s*[-*]\s+/.test(lines[i])) { para.push(lines[i].trim()); i++; }
    blocks.push(<p key={key++} className="text-xs text-foreground/85 leading-relaxed">{inline(para.join(" "))}</p>);
  }
  return <div className="space-y-2">{blocks}</div>;
}

// ── small pieces ─────────────────────────────────────────────────────────────

function Reads({ children, tone = "on" }: { children: ReactNode; tone?: "on" | "kept" | "quiet" }) {
  const cls = tone === "on" ? "border-primary/40 bg-primary/[0.04]" : tone === "kept" ? "border-sky-400/30 bg-sky-400/[0.03]" : "border-border/40";
  return <div className={`mt-2 border-l-2 ${cls} rounded-r-md pl-3 pr-2 py-2 space-y-2`}>{children}</div>;
}
const ReadsLabel = ({ children }: { children: ReactNode }) => <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground/80">{children}</p>;

interface Props {
  playbook: Playbook;
  /** The document's sections with what was taken from each; fetched when not given. */
  view?: PlaybookSection[] | null;
  onClose: () => void;
  onUse: (pb: Playbook) => void;
  onSaved?: (pb: Playbook) => void;
}

/** "What I understood", on the analyst's own document: every section shown as they wrote it, in
 *  their order, with what the Studio takes from it underneath. Controls appear only where a part
 *  drives the build (shares, ranges, dial links); everything else is marked as kept as written. */
export default function PlaybookReview({ playbook, view: initialView, onClose, onUse, onSaved }: Props) {
  const [pb, setPb] = useState<Playbook>(playbook);
  const [view, setView] = useState<PlaybookSection[] | null>(initialView || null);
  const [dialPaths, setDialPaths] = useState<string[]>([]);
  const [edited, setEdited] = useState(false);
  const [mode, setMode] = useState<"doc" | "text">("doc");
  const [text, setText] = useState(playbook.source_markdown || "");
  const [busy, setBusy] = useState<"" | "save" | "download" | "read">("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => { api.playbooks.dials().then((r) => setDialPaths(r.dial_paths)).catch(() => {}); }, []);
  useEffect(() => { if (!view) api.playbooks.view(playbook).then((r) => setView(r.view)).catch(() => setView([])); }, [view, playbook]);

  const set = (patch: Partial<Playbook>) => { setPb((p) => ({ ...p, ...patch })); setSaved(false); setEdited(true); };
  const varIndex = (key: string) => pb.variables.findIndex((v) => v.key === key);
  const setVar = (k: number, patch: Partial<PlaybookVariable>) => set({ variables: pb.variables.map((v, j) => (j === k ? { ...v, ...patch } : v)) });
  const setLink = (k: number, j: number, patch: Partial<PlaybookLink> | null) => {
    const links = pb.variables[k].links.slice();
    if (patch === null) links.splice(j, 1); else links[j] = { ...links[j], ...patch };
    setVar(k, { links });
  };
  const segIndex = (name: string) => pb.segments.findIndex((s) => s.name === name);
  const setSeg = (k: number, patch: Partial<Playbook["segments"][number]>) => set({ segments: pb.segments.map((x, j) => (j === k ? { ...x, ...patch } : x)) });
  const segNames = pb.segments.map((s) => s.name);
  const shareSum = pb.segments.filter((s) => s.share_mode === "given").reduce((n, s) => n + (s.share_pct || 0), 0);

  // What the document shows somewhere; anything else (added here, or read without a home) goes last.
  const shown = useMemo(() => {
    const segs = new Set<string>(); const vars = new Set<string>(); const rules = new Set<number>(); let approach = false;
    for (const s of view || []) { s.uses.segments.forEach((x) => segs.add(x)); s.uses.variables.forEach((x) => vars.add(x)); s.uses.rules.forEach((x) => rules.add(x)); approach = approach || s.uses.approach; }
    return { segs, vars, rules, approach };
  }, [view]);
  const looseSegs = pb.segments.filter((s) => !shown.segs.has(s.name));
  const looseVars = pb.variables.filter((v) => !shown.vars.has(v.key));
  const looseRules = pb.rules.map((r, j) => ({ r, j })).filter(({ j }) => !shown.rules.has(j));

  const save = async () => {
    setBusy("save"); setError(null);
    try {
      const r = pb.id ? await api.playbooks.update(pb.id, pb, edited) : await api.playbooks.save(pb, edited);
      const next = { ...r.playbook, id: r.id };
      setPb(next); setView(r.view); setSaved(true); onSaved?.(next);
    } catch (e: any) { setError(e?.message || "Could not save the playbook"); } finally { setBusy(""); }
  };
  const download = async () => {
    setBusy("download"); setError(null);
    try { const r = await api.playbooks.render(pb, edited); downloadText(fileName(pb.title), r.markdown); }
    catch (e: any) { setError(e?.message || "Could not write the file"); } finally { setBusy(""); }
  };
  const reread = async () => {
    if (edited && !window.confirm("Reading the text again replaces the settings you changed in the reading. Carry on?")) return;
    setBusy("read"); setError(null);
    try {
      const r = await api.playbooks.parse(text);
      setPb({ ...r.playbook, id: pb.id }); setView(r.view); setEdited(false); setSaved(false); setMode("doc");
    } catch (e: any) { setError(e?.message || "Could not read it"); } finally { setBusy(""); }
  };

  // ── what each kind of part looks like under its section ──
  const segmentRow = (k: number) => {
    const s = pb.segments[k];
    return (
      <div key={s.name + k} className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-foreground/90 min-w-[10rem] flex-1">{s.name}</span>
        <select value={s.share_mode} onChange={(e) => setSeg(k, { share_mode: e.target.value as Playbook["segments"][number]["share_mode"], share_pct: e.target.value === "given" ? (s.share_pct ?? 10) : null })} className="field field-sm w-auto text-[11px]">
          <option value="given">share I state</option>
          <option value="find">find it</option>
          <option value="planner">planner&apos;s estimate</option>
        </select>
        {s.share_mode === "given" && <input type="number" min={0} max={100} value={s.share_pct ?? ""} onChange={(e) => setSeg(k, { share_pct: +e.target.value })} className="field field-sm w-16 text-center tabular-nums" />}
        <button type="button" title="Leave this segment out of the build" onClick={() => set({ segments: pb.segments.filter((_, j) => j !== k) })} className="text-muted-foreground/50 hover:text-red-300"><Trash2 className="w-3.5 h-3.5" /></button>
        {s.attributes && Object.keys(s.attributes).length > 0 && (
          <div className="basis-full flex flex-wrap gap-1">{Object.entries(s.attributes).map(([a, v]) => <span key={a} className="chip text-[10px]" title="Kept as written: given to the planner and to this segment's twins">{a}: {v}</span>)}</div>
        )}
      </div>
    );
  };

  const variableBlock = (k: number) => {
    const v = pb.variables[k];
    return (
      <div key={v.key} className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <select value={v.kind} onChange={(e) => setVar(k, { kind: e.target.value as PlaybookVariable["kind"] })} className="field field-sm w-auto text-[11px]">
            <option value="dial">dial 0–10</option>
            <option value="category">category</option>
            <option value="rule">rule</option>
          </select>
          <span className="text-[11px] text-muted-foreground">{KIND_HINT[v.kind]}</span>
          <span className={`chip text-[10px] ${v.evidence_mode === "none" ? "chip-warn" : ""}`} title={v.evidence}>{v.evidence_mode === "find" ? "looked up in the research" : v.evidence_mode === "source" ? "source named" : "your hypothesis"}</span>
          <button type="button" title="Leave this variable out of the build" onClick={() => set({ variables: pb.variables.filter((_, j) => j !== k) })} className="ml-auto text-muted-foreground/50 hover:text-red-300"><Trash2 className="w-3.5 h-3.5" /></button>
        </div>
        {v.kind === "dial" && (
          <>
            <div className="flex flex-wrap gap-1.5 items-center">
              <span className="text-[11px] text-muted-foreground">Range</span>
              {v.by_segment.map((e, j) => (
                <span key={j} className="inline-flex items-center gap-1 rounded-full border border-border/60 pl-2 pr-1 py-0.5 text-[11px]">
                  <span className={segNames.length && !segNames.includes(e.segment) ? "text-amber-300/90" : "text-foreground/85"} title={segNames.length && !segNames.includes(e.segment) ? "Not one of your named segments — matched to the plan's segments by meaning" : ""}>{e.segment}</span>
                  <input type="number" min={0} max={10} value={e.low ?? 0} onChange={(ev) => setVar(k, { by_segment: v.by_segment.map((x, n) => (n === j ? { ...x, low: Math.min(+ev.target.value, x.high ?? 10) } : x)) })} className="w-8 bg-transparent text-center tabular-nums" />
                  <span className="text-muted-foreground">–</span>
                  <input type="number" min={0} max={10} value={e.high ?? 10} onChange={(ev) => setVar(k, { by_segment: v.by_segment.map((x, n) => (n === j ? { ...x, high: Math.max(+ev.target.value, x.low ?? 0) } : x)) })} className="w-8 bg-transparent text-center tabular-nums" />
                </span>
              ))}
              {v.by_segment.length === 0 && <span className="text-[11px] text-foreground/80">{v.range ? `${v.range[0]}–${v.range[1]} for everyone` : "not given — fitted to each planned segment from who it is"}</span>}
            </div>
            <div className="flex flex-wrap gap-1.5 items-center">
              <span className="text-[11px] text-muted-foreground">Pushes</span>
              {v.links.map((ln, j) => (
                <span key={j} className="inline-flex items-center gap-1 rounded-full border border-border/60 pl-2 pr-1 py-0.5 text-[11px]">
                  <button type="button" onClick={() => setLink(k, j, { direction: ln.direction > 0 ? -1 : 1 })} title="Flip direction" className={ln.direction > 0 ? "text-emerald-300" : "text-sky-300"}>
                    {ln.direction > 0 ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />}
                  </button>
                  <span className="text-foreground/85" title={ln.dial}>{dialWords(ln.dial)}</span>
                  <select value={ln.strength} onChange={(e) => setLink(k, j, { strength: +e.target.value })} className="bg-transparent text-[11px] text-muted-foreground" title="Strength">
                    {[1, 2, 3].map((n) => <option key={n} value={n}>×{n}</option>)}
                  </select>
                  <button type="button" onClick={() => setLink(k, j, null)} className="text-muted-foreground/60 hover:text-red-300"><X className="w-3 h-3" /></button>
                </span>
              ))}
              {dialPaths.length > 0 && v.links.length < 8 && (
                <select value="" onChange={(e) => e.target.value && setVar(k, { links: [...v.links, { dial: e.target.value, direction: 1, strength: 2 }] })} className="field field-sm w-auto text-[11px]">
                  <option value="">+ dial…</option>
                  {dialPaths.filter((p) => !v.links.some((l) => l.dial === p)).map((p) => <option key={p} value={p}>{p.replace(".", " · ").replace(/_/g, " ")}</option>)}
                </select>
              )}
            </div>
          </>
        )}
        {v.kind === "category" && (
          <p className="text-[11px] text-foreground/80">Labels: {v.values.join(" · ") || "—"}{v.by_segment.length > 0 && <span className="text-muted-foreground"> · {v.by_segment.map((e) => `${e.segment} → ${(e.values || []).join(" / ")}`).join(" · ")}</span>}</p>
        )}
        {v.notes && Object.keys(v.notes).length > 0 && (
          <div className="flex flex-wrap gap-1">{Object.entries(v.notes).map(([a, x]) => <span key={a} className="chip text-[10px]" title="Kept as written: given to the planner">{cap(a)}: {x}</span>)}</div>
        )}
      </div>
    );
  };

  const ruleRow = (j: number) => {
    const r = pb.rules[j];
    return (
      <div key={j} className="flex items-center gap-2 text-[11px]">
        <select value={r.segment} onChange={(e) => set({ rules: pb.rules.map((x, n) => (n === j ? { ...x, segment: e.target.value } : x)) })} className="field field-sm w-auto text-[11px]">
          <option value="">every twin</option>
          {[...new Set([...segNames, r.segment].filter(Boolean))].map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
        <span className="text-foreground/80 truncate flex-1" title={r.text}>{r.text}</span>
        <button type="button" onClick={() => set({ rules: pb.rules.filter((_, n) => n !== j) })} className="text-muted-foreground/50 hover:text-red-300"><Trash2 className="w-3.5 h-3.5" /></button>
      </div>
    );
  };

  const approachControls = (
    <div className="flex flex-wrap items-center gap-2 text-[11px]">
      <span className="text-muted-foreground">segments defined by</span>
      <select value={pb.approach.primary} onChange={(e) => set({ approach: { ...pb.approach, primary: e.target.value } })} className="field field-sm w-auto text-[11px]">
        {AXES.map((a) => <option key={a} value={a}>{a}</option>)}
      </select>
      <span className="text-muted-foreground">match exactly on</span>
      <input value={pb.approach.match_exactly.join(", ")} onChange={(e) => set({ approach: { ...pb.approach, match_exactly: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) } })} placeholder="role, region" className="field field-sm w-48 text-[11px]" />
    </div>
  );

  const reading = (s: PlaybookSection): ReactNode => {
    const u = s.uses;
    const parts: ReactNode[] = [];
    if (u.front) parts.push(
      <Fragment key="front">
        <ReadsLabel>The Studio reads — title and place</ReadsLabel>
        <div className="grid sm:grid-cols-2 gap-2">
          <input value={pb.title} onChange={(e) => set({ title: e.target.value })} className="field field-sm" title="Title" />
          <input value={pb.geography} onChange={(e) => set({ geography: e.target.value })} placeholder="geography" className="field field-sm" title="Geography" />
        </div>
      </Fragment>,
    );
    if (u.approach) parts.push(<Fragment key="approach"><ReadsLabel>The Studio reads — the planner composes segments this way</ReadsLabel>{approachControls}</Fragment>);
    if (u.segments.length) parts.push(
      <Fragment key="segs">
        <ReadsLabel>The Studio reads — {u.segments.length} segments, kept exactly as named{shareSum > 0 ? ` · stated shares sum to ${shareSum}%` : ""}</ReadsLabel>
        <div className="space-y-1.5">{u.segments.map((n) => segIndex(n)).filter((k) => k >= 0).map(segmentRow)}</div>
      </Fragment>,
    );
    const vars = u.variables.map(varIndex).filter((k) => k >= 0);
    if (vars.length) parts.push(<Fragment key="vars"><ReadsLabel>The Studio reads</ReadsLabel>{vars.map(variableBlock)}</Fragment>);
    const rules = u.rules.filter((j) => pb.rules[j]);
    if (rules.length) parts.push(<Fragment key="rules"><ReadsLabel>The Studio reads — rules the twins follow</ReadsLabel>{rules.map(ruleRow)}</Fragment>);
    if (u.unsure) parts.push(<p key="unsure" className="text-[11px] text-muted-foreground">The Studio asks about these only if the research cannot settle them.</p>);
    if (parts.length) return <Reads>{parts}</Reads>;
    if (u.extras.length) {
      const ex = (pb.extras || [])[u.extras[0]];
      return <Reads tone="kept"><p className="text-[11px] text-sky-200/80">Kept as written — the planner reads it and {ex?.applies_to ? `every ${ex.applies_to} twin` : "every twin"} is given it.</p></Reads>;
    }
    if (s.body && s.level >= 2) return <Reads tone="quiet"><p className="text-[11px] text-muted-foreground">Read by the planner as part of your text.</p></Reads>;
    return null;
  };

  if (typeof document === "undefined") return null;
  // Portalled to <body>: the cards it opens from animate in with a transform, which would make them
  // the containing block of a fixed overlay and clip it to the card.
  return createPortal(
    <div className="fixed inset-0 z-50 bg-black/60 flex items-start justify-center overflow-y-auto p-4 sm:p-6" onClick={onClose}>
      <div className="w-full max-w-4xl rounded-xl border border-border bg-background shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 px-5 py-4 border-b hairline">
          <div className="min-w-0">
            <div className="text-sm font-medium text-foreground">What I understood from your playbook</div>
            <p className="text-[11px] text-muted-foreground mt-0.5 leading-relaxed">
              Your document as you wrote it, with what the Studio takes from each part underneath. Nothing is dropped: parts with no setting of their own are kept as written and given to the planner and the twins they are about. Research still runs and <span className="text-foreground/80">flags</span> disagreements without changing your choices.
              {pb.parsed_by === "template" && " Read with the template reader (the model was unavailable)."}
            </p>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <div className="inline-flex rounded-md border border-border/60 p-0.5">
              <button type="button" onClick={() => setMode("doc")} className={`btn btn-xs ${mode === "doc" ? "btn-secondary" : "btn-ghost"}`}><BookOpen className="w-3 h-3" /> Reading</button>
              <button type="button" onClick={() => { setText(pb.source_markdown || ""); setMode("text"); }} className={`btn btn-xs ${mode === "text" ? "btn-secondary" : "btn-ghost"}`}><FileText className="w-3 h-3" /> Edit text</button>
            </div>
            <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground ml-2"><X className="w-4 h-4" /></button>
          </div>
        </div>

        <div className="px-5 py-4 space-y-3 max-h-[calc(100vh-11rem)] overflow-y-auto">
          {mode === "text" ? (
            <div className="space-y-2">
              <textarea value={text} onChange={(e) => setText(e.target.value)} rows={24} className="field text-xs font-mono w-full leading-relaxed" />
              <button type="button" disabled={!text.trim() || !!busy} onClick={reread} className="btn btn-sm btn-primary">{busy === "read" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />} Read it again</button>
            </div>
          ) : !view ? (
            <p className="hint flex items-center gap-2"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Laying out your document…</p>
          ) : (
            <>
              {view.map((s) => {
                if (s.level === 1 && !s.body) return <h2 key={s.id} className="text-base font-semibold text-foreground pt-1">{s.heading}</h2>;
                return (
                  <section key={s.id} className={s.level >= 3 ? "ml-4" : ""}>
                    <div className={s.level >= 3 ? "rounded-lg border border-border/40 px-3 py-2.5" : "rounded-lg border border-border/50 bg-card/30 px-4 py-3"}>
                      <h3 className={`text-[13px] ${s.level >= 3 ? "font-medium" : "font-semibold"} text-foreground mb-1.5`}>{s.heading}</h3>
                      {s.fields && Object.keys(s.fields).length > 0 && (
                        <dl className="grid grid-cols-[7rem_1fr] gap-x-3 gap-y-0.5 text-xs">
                          {Object.entries(s.fields).map(([k, v]) => <Fragment key={k}><dt className="text-muted-foreground">{cap(k.replace(/_/g, " "))}</dt><dd className="text-foreground/85">{v}</dd></Fragment>)}
                        </dl>
                      )}
                      {s.body && <Markdown text={s.body} />}
                      {reading(s)}
                    </div>
                  </section>
                );
              })}

              {(looseSegs.length > 0 || looseVars.length > 0 || looseRules.length > 0 || !shown.approach) && (
                <section className="rounded-lg border border-dashed border-border/60 px-4 py-3 space-y-3">
                  <h3 className="text-[13px] font-semibold text-foreground">Also read from your text</h3>
                  {!shown.approach && <Reads><ReadsLabel>Approach</ReadsLabel>{approachControls}</Reads>}
                  {looseSegs.length > 0 && <Reads><ReadsLabel>Segments</ReadsLabel>{looseSegs.map((s) => segmentRow(segIndex(s.name)))}</Reads>}
                  {looseVars.map((v) => <Reads key={v.key}><ReadsLabel>{v.label}</ReadsLabel>{variableBlock(varIndex(v.key))}</Reads>)}
                  {looseRules.length > 0 && <Reads><ReadsLabel>Rules</ReadsLabel>{looseRules.map(({ j }) => ruleRow(j))}</Reads>}
                </section>
              )}

              <div className="flex flex-wrap gap-2 pt-1">
                <button type="button" onClick={() => set({ segments: [...pb.segments, { name: `Segment ${pb.segments.length + 1}`, share_pct: null, share_mode: "planner", description: "", source: "" }] })} className="btn btn-xs btn-ghost"><Plus className="w-3 h-3" /> Segment</button>
                <button type="button" onClick={() => { const label = window.prompt("Name of the variable (e.g. Burnout)"); if (label) set({ variables: [...pb.variables, { key: label.toLowerCase().replace(/[^a-z0-9]+/g, "_"), label, kind: "dial", what: "", low: "", high: "", range: [3, 7], by_segment: [], values: [], shows_up_as: "", evidence: "", evidence_mode: "none", links: [] }] }); }} className="btn btn-xs btn-ghost"><Plus className="w-3 h-3" /> Variable</button>
                <button type="button" onClick={() => { const t = window.prompt("The rule, as you'd brief an actor"); if (t) set({ rules: [...pb.rules, { segment: "", text: t }] }); }} className="btn btn-xs btn-ghost"><Plus className="w-3 h-3" /> Rule</button>
              </div>
            </>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2 px-5 py-3 border-t hairline">
          {error && <span className="text-[11px] text-red-300 mr-auto">{error}</span>}
          <button type="button" disabled={!!busy} onClick={download} className="btn btn-sm btn-ghost" title={edited ? "Your document as written, with the settings you changed appended as 'Studio settings'" : "Your document exactly as written"}>
            {busy === "download" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />} Download .md
          </button>
          <button type="button" disabled={!!busy || !pb.title.trim()} onClick={save} className="btn btn-sm btn-secondary" title="Shared: everyone on the team can see and use it">
            {busy === "save" ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : saved ? <Check className="w-3.5 h-3.5" /> : <Save className="w-3.5 h-3.5" />} {saved ? "Saved to the library" : pb.id ? "Save changes to the library" : "Save to the library"}
          </button>
          <button type="button" disabled={mode === "text"} onClick={() => onUse(pb)} className="btn btn-sm btn-primary ml-auto" title={mode === "text" ? "Read the edited text again first" : ""}><Check className="w-3.5 h-3.5" /> Use for this build</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
