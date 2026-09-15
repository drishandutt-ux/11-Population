"use client";

import { useRef, useState } from "react";
import { EvidenceItem, QuantSource, ResearchState } from "@/lib/api";
import { Database, Upload, X, FileText, Search, Loader2, ChevronDown, ChevronUp, ExternalLink, Eye, EyeOff, BookOpen, Network, CheckCircle2, AlertCircle } from "lucide-react";

/** Matches SURVEY_CHAR_LIMIT in agent_factory.py. */
const SURVEY_CHAR_LIMIT = 8000;

interface Props {
  sessionQuery: string;
  research: ResearchState | null;
  kgCounts: { entities: number; relations: number } | null;
  catalogue: QuantSource[];
  selected: string[];
  onSelected: (keys: string[]) => void;
  quantQuery: string;
  onQuantQuery: (q: string) => void;
  quantOnBuild: boolean;
  onQuantOnBuild: (v: boolean) => void;
  onSearch: () => Promise<void>;
  searching: boolean;
  facts: EvidenceItem[];
  onToggleFact: (item: EvidenceItem) => Promise<void>;
  profileQuery: string;
  onProfileQuery: (v: string) => void;
  docContext: string;
  onDocContext: (text: string, name: string) => void;
  disabled?: boolean;
}

function FactCard({ item, onToggle }: { item: EvidenceItem; onToggle: (i: EvidenceItem) => void }) {
  const [open, setOpen] = useState(false);
  const st = item.structured || {};
  const facts: { statistic: string; value: string; group: string; geography: string; year: string; quote: string }[] = st.facts || [];
  const usable = item.on_topic && !item.excluded;
  return (
    <div className={`rounded-lg border px-3 py-2 transition-colors ${item.excluded ? "border-border/20 opacity-40" : item.on_topic ? "border-emerald-500/25 bg-emerald-500/5" : "border-border/25 opacity-70"}`}>
      <div className="flex items-center gap-2 mb-1">
        <span className="text-[9px] uppercase tracking-wide px-1.5 py-0.5 rounded border border-emerald-500/30 text-emerald-300">{st.source_label || item.author}</span>
        {item.published_at && <span className="text-[10px] text-muted-foreground/50">{item.published_at.slice(0, 10)}</span>}
        {item.in_graph && <span className="text-[9px] text-emerald-400/80 border border-emerald-500/25 rounded px-1">in graph</span>}
        <span className={`ml-auto text-[10px] ${usable ? "text-emerald-400" : "text-muted-foreground/50"}`}>{item.on_topic ? `${facts.length} fact${facts.length === 1 ? "" : "s"}` : "nothing usable"}</span>
      </div>
      <p className="text-[11px] font-medium leading-snug text-foreground/90">{item.title || item.source_ref}</p>
      {facts.length > 0 && (
        <ul className="mt-1.5 space-y-1">
          {(open ? facts : facts.slice(0, 2)).map((f, k) => (
            <li key={k} className="text-[10px] leading-snug text-muted-foreground/85">
              <span className="text-foreground/85 font-semibold">{f.value}</span> — {f.statistic}{f.group ? ` (${f.group}${f.year ? `, ${f.year}` : ""})` : ""}
              {open && f.quote && <p className="text-[10px] italic text-muted-foreground/60 mt-0.5">“{f.quote}”</p>}
            </li>
          ))}
        </ul>
      )}
      <div className="flex items-center gap-3 mt-1.5 text-[10px]">
        {facts.length > 2 && (
          <button onClick={() => setOpen(!open)} className="text-muted-foreground/60 hover:text-foreground flex items-center gap-0.5">
            {open ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}{open ? "less" : `all ${facts.length}`}
          </button>
        )}
        <a href={item.source_ref} target="_blank" rel="noreferrer" className="text-muted-foreground/60 hover:text-foreground flex items-center gap-0.5"><ExternalLink className="w-3 h-3" /> open</a>
        <button onClick={() => onToggle(item)} className="ml-auto text-muted-foreground/60 hover:text-foreground flex items-center gap-0.5" title={item.excluded ? "Use these facts in the plan" : "Keep these facts out of the plan"}>
          {item.excluded ? <><Eye className="w-3 h-3" /> use</> : <><EyeOff className="w-3 h-3" /> ignore</>}
        </button>
      </div>
    </div>
  );
}

export default function SourcesPanel(p: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [trimmed, setTrimmed] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const run = p.research?.run ?? null;
  const brief = run?.brief ?? null;
  const groups: any[] = Array.isArray(brief?.groups) ? brief.groups : [];
  const researchActive = run && ["queued", "running", "stopping", "finalising"].includes(run.status);
  const usable = p.facts.filter((f) => f.on_topic && !f.excluded).length;

  function handleFile(file: File) {
    if (file.type === "application/pdf") { setWarning("PDF is not supported here — convert to .txt or .csv."); return; }
    setWarning(null);
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = (e.target?.result as string) || "";
      const cut = text.slice(0, SURVEY_CHAR_LIMIT);
      setTrimmed(text.length > SURVEY_CHAR_LIMIT ? `Trimmed to the first ${SURVEY_CHAR_LIMIT.toLocaleString()} characters — about ${cut.split("\n").length - 1} of ${text.split("\n").length - 1} rows reach the model.` : null);
      setFileName(file.name);
      p.onDocContext(cut, file.name);
    };
    reader.readAsText(file);
  }

  return (
    <div className="space-y-4">
      {/* What the plan reads */}
      <div className="glass rounded-2xl p-4 space-y-2.5">
        <div className="flex items-center gap-2">
          <BookOpen className="w-3.5 h-3.5 text-primary" />
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">What the plan reads</span>
        </div>
        <p className="text-[11px] text-foreground/85 leading-snug">{p.sessionQuery}</p>
        <div className="space-y-1.5 text-[11px]">
          <div className="flex items-start gap-2">
            {brief ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0 mt-px" /> : researchActive ? <Loader2 className="w-3.5 h-3.5 text-primary animate-spin shrink-0 mt-px" /> : <AlertCircle className="w-3.5 h-3.5 text-yellow-400 shrink-0 mt-px" />}
            <span className="text-muted-foreground leading-snug">
              {brief
                ? <>Evidence brief · <span className="text-foreground/85">{groups.length} stakeholder group{groups.length === 1 ? "" : "s"}</span>{typeof brief.overall_for_pct === "number" && <> · {brief.overall_for_pct}% for / {brief.overall_against_pct}% against / {brief.overall_mixed_pct}% mixed</>}</>
                : run?.status === "stopping" || run?.status === "finalising" ? "Research is finishing — the brief lands in a moment"
                : researchActive ? "Research still running on the Ingest tab — the brief lands when it finishes (or press Stop there to use what it has)"
                : run ? `Research ${run.status} without a brief. The plan will use the knowledge graph, statistics and your dials.`
                : "No evidence brief yet. Run research on the Ingest tab for real stakeholder groups and quotes."}
            </span>
          </div>
          {groups.length > 0 && (
            <ul className="pl-5 space-y-0.5">
              {groups.slice(0, 6).map((g: any, k: number) => (
                <li key={k} className="text-[10px] text-muted-foreground/80 leading-snug"><span className="text-foreground/80">{g.name}</span> · {g.stance} · ~{g.share_pct}%</li>
              ))}
            </ul>
          )}
          <div className="flex items-start gap-2">
            <Network className={`w-3.5 h-3.5 shrink-0 mt-px ${p.kgCounts?.entities ? "text-emerald-400" : "text-muted-foreground/40"}`} />
            <span className="text-muted-foreground">{p.kgCounts?.entities ? `Knowledge graph · ${p.kgCounts.entities} entities, ${p.kgCounts.relations} relations` : "Knowledge graph is empty"}</span>
          </div>
          <div className="flex items-start gap-2">
            <Database className={`w-3.5 h-3.5 shrink-0 mt-px ${usable ? "text-emerald-400" : "text-muted-foreground/40"}`} />
            <span className="text-muted-foreground">{usable ? `Statistics · ${usable} page${usable === 1 ? "" : "s"} with usable facts` : "No statistics gathered yet"}</span>
          </div>
        </div>
      </div>

      {/* Your own inputs */}
      <div className="glass rounded-2xl p-4 space-y-3">
        <div className="flex items-center gap-2">
          <Upload className="w-3.5 h-3.5 text-primary" />
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Your inputs</span>
        </div>
        <div>
          <label className="text-[10px] text-muted-foreground mb-1 block">Audience profile <span className="text-muted-foreground/50">(optional)</span></label>
          <textarea value={p.profileQuery} disabled={p.disabled} onChange={(e) => p.onProfileQuery(e.target.value)} rows={2} placeholder={`e.g. "Parents of under-5s in the North West, mostly renting"`} className="w-full bg-muted/50 border border-border rounded-lg px-2.5 py-2 text-[11px] text-foreground placeholder-muted-foreground/40 focus:outline-none focus:ring-1 focus:ring-primary/50 resize-none" />
        </div>
        <div>
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] text-muted-foreground">Survey / panel data</span>
            <span className="text-[10px] text-muted-foreground/50">.txt, .csv</span>
          </div>
          {p.docContext ? (
            <div className="flex items-center gap-2 text-[11px] bg-muted/50 border border-border rounded-lg px-3 py-2">
              <FileText className="w-3.5 h-3.5 text-primary shrink-0" />
              <span className="text-foreground truncate flex-1">{fileName || "uploaded document"}</span>
              <button disabled={p.disabled} onClick={() => { setFileName(null); setTrimmed(null); p.onDocContext("", ""); }} className="text-muted-foreground hover:text-foreground shrink-0"><X className="w-3 h-3" /></button>
            </div>
          ) : (
            <button disabled={p.disabled} onClick={() => inputRef.current?.click()} className="w-full flex items-center gap-2 text-[11px] border border-dashed border-border/60 rounded-lg px-3 py-2 text-muted-foreground hover:text-foreground hover:border-border transition-colors">
              <Upload className="w-3.5 h-3.5 shrink-0" /> Upload respondents to mirror (optional)
            </button>
          )}
          {warning && <p className="text-[10px] text-yellow-400 mt-1">{warning}</p>}
          {trimmed && <p className="text-[10px] text-yellow-400 mt-1">{trimmed}</p>}
          <p className="text-[10px] text-muted-foreground/50 mt-1">Respondents become segments and their answers become dial values. For the knowledge graph, use the Ingest tab.</p>
          <input ref={inputRef} type="file" accept=".txt,.csv,text/plain,text/csv" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); e.target.value = ""; }} />
        </div>
      </div>

      {/* Statistics search */}
      <div className="glass rounded-2xl p-4 space-y-3">
        <div className="flex items-center gap-2">
          <Database className="w-3.5 h-3.5 text-emerald-400" />
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Statistics & surveys</span>
        </div>
        <p className="text-[10px] text-muted-foreground/70 leading-snug">Base rates from statistics publishers: how big each group is, ages, regions, incomes, what polls found. Every fact keeps its quote.</p>
        <div className="flex flex-wrap gap-1">
          {p.catalogue.map((src) => {
            const on = p.selected.includes(src.key);
            return (
              <button key={src.key} disabled={p.disabled} title={`${src.domain} · ${src.description}`} onClick={() => p.onSelected(on ? p.selected.filter((k) => k !== src.key) : [...p.selected, src.key])} className={`text-[10px] px-2 py-1 rounded-lg border transition-colors ${on ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-300" : "border-border/50 text-muted-foreground hover:text-foreground"}`}>{src.label}</button>
            );
          })}
        </div>
        <label className="flex items-start gap-2 cursor-pointer">
          <input type="checkbox" checked={p.quantOnBuild} disabled={p.disabled} onChange={(e) => p.onQuantOnBuild(e.target.checked)} className="mt-0.5 accent-[hsl(var(--primary))]" />
          <span className="text-[10px] text-muted-foreground leading-relaxed"><span className="text-foreground/80">Search these while planning.</span> The build writes its own queries from what it detects and reads the ticked publishers before it proposes segments.</span>
        </label>
        <div className="flex gap-1.5">
          <input value={p.quantQuery} onChange={(e) => p.onQuantQuery(e.target.value)} placeholder="Search now, e.g. UK cyclists by age 2025" onKeyDown={(e) => { if (e.key === "Enter" && !p.searching && p.quantQuery.trim()) p.onSearch(); }} className="flex-1 bg-muted/50 border border-border rounded-lg px-2.5 py-1.5 text-[11px] text-foreground placeholder-muted-foreground/40 focus:outline-none focus:ring-1 focus:ring-primary/50" />
          <button disabled={p.searching || !p.quantQuery.trim() || p.selected.length === 0} onClick={() => p.onSearch()} className="shrink-0 flex items-center gap-1 text-[11px] font-medium px-2.5 py-1.5 rounded-lg bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/25 disabled:opacity-40 transition-colors">
            {p.searching ? <Loader2 className="w-3 h-3 animate-spin" /> : <Search className="w-3 h-3" />} Search
          </button>
        </div>
        {p.facts.length > 0 ? (
          <div className="space-y-1.5 max-h-[420px] overflow-y-auto pr-0.5">
            {[...p.facts].sort((a, b) => Number(b.on_topic) - Number(a.on_topic)).map((f) => <FactCard key={f.id} item={f} onToggle={p.onToggleFact} />)}
          </div>
        ) : (
          <p className="text-[10px] text-muted-foreground/50">Nothing gathered yet.</p>
        )}
      </div>
    </div>
  );
}
