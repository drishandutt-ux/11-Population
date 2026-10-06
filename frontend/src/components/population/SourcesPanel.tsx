"use client";

import { useRef, useState } from "react";
import { EvidenceItem, QuantSource, ResearchState } from "@/lib/api";
import { Upload, X, FileText, Search, Loader2, ChevronDown, ExternalLink, Eye, EyeOff } from "lucide-react";
import { Section, SwitchRow } from "./controls";

/** Matches SURVEY_CHAR_LIMIT in agent_factory.py. */
const SURVEY_CHAR_LIMIT = 40000;

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
  /** The latest build's status, so the panel can say "gathering…" while the build reads publishers. */
  buildStatus?: string | null;
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
    <div className={`rounded-lg px-3 py-2.5 transition-opacity surface-raised ${item.excluded ? "opacity-40" : item.on_topic ? "" : "opacity-60"}`}>
      <div className="flex items-center gap-1.5 mb-1 min-w-0">
        <span className={`chip ${usable ? "chip-ok" : ""} max-w-[55%] truncate`}>{st.source_label || item.author}</span>
        {item.published_at && <span className="text-[10.5px] text-muted-foreground/50 tabular-nums">{item.published_at.slice(0, 10)}</span>}
        <span className={`ml-auto text-[10.5px] ${usable ? "text-emerald-300/90" : "text-muted-foreground/50"}`}>{item.on_topic ? `${facts.length} fact${facts.length === 1 ? "" : "s"}` : "nothing usable"}</span>
      </div>
      <p className="text-xs font-medium leading-snug text-foreground/90">{item.title || item.source_ref}</p>
      {facts.length > 0 && (
        <ul className="mt-1.5 space-y-1">
          {(open ? facts : facts.slice(0, 2)).map((f, k) => (
            <li key={k} className="text-[11.5px] leading-snug text-muted-foreground">
              <span className="text-foreground/90 font-semibold tabular-nums">{f.value}</span> · {f.statistic}{f.group ? ` (${f.group}${f.year ? `, ${f.year}` : ""})` : ""}
              {open && f.quote && <p className="text-[11px] italic text-muted-foreground/60 mt-0.5">“{f.quote}”</p>}
            </li>
          ))}
        </ul>
      )}
      <div className="flex items-center gap-3 mt-2 text-[11px]">
        {facts.length > 2 && (
          <button onClick={() => setOpen(!open)} className="text-muted-foreground/70 hover:text-foreground">{open ? "less" : `all ${facts.length}`}</button>
        )}
        <a href={item.source_ref} target="_blank" rel="noreferrer" className="text-muted-foreground/70 hover:text-foreground inline-flex items-center gap-1"><ExternalLink className="w-3 h-3" /> open</a>
        {item.in_graph && <span className="text-muted-foreground/50">in graph</span>}
        <button onClick={() => onToggle(item)} className="ml-auto text-muted-foreground/70 hover:text-foreground inline-flex items-center gap-1" title={item.excluded ? "Use these facts in the plan" : "Keep these facts out of the plan"}>
          {item.excluded ? <><Eye className="w-3 h-3" /> use</> : <><EyeOff className="w-3 h-3" /> ignore</>}
        </button>
      </div>
    </div>
  );
}

function StatusRow({ state, label, value }: { state: "ok" | "wait" | "none"; label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2.5">
      <span className={`dot mt-[7px] ${state === "ok" ? "bg-emerald-400" : state === "wait" ? "bg-primary animate-pulse" : "bg-muted-foreground/30"}`} />
      <div className="min-w-0 flex-1 text-xs leading-relaxed">
        <span className="text-foreground/90">{label}</span>
        <span className="text-muted-foreground"> · {value}</span>
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
  const researchActive = !!run && ["queued", "running", "stopping", "finalising"].includes(run.status);
  const usable = p.facts.filter((f) => f.on_topic && !f.excluded).length;
  const gathering = p.buildStatus === "gathering" || p.searching;

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

  const UK = new Set(["uk", "england", "scotland", "wales", "ni"]);
  const regionGroups: { title: string; test: (s: QuantSource) => boolean }[] = [
    { title: "United Kingdom", test: (s) => s.regions.some((r) => UK.has(r)) && !s.regions.includes("global") },
    { title: "United States", test: (s) => s.regions.includes("us") && !s.regions.includes("global") },
    { title: "Europe & global", test: () => true },
  ];
  const placed = new Set<string>();

  return (
    <div className="space-y-7">
      {/* The question, and what the plan can read */}
      <Section title="The question">
        <p className="text-[13px] text-foreground/85 leading-relaxed">{p.sessionQuery}</p>
      </Section>

      <Section title="On file">
        <div className="space-y-2">
          <StatusRow
            state={brief ? "ok" : researchActive ? "wait" : "none"}
            label="Evidence brief"
            value={brief
              ? <>{groups.length} stakeholder group{groups.length === 1 ? "" : "s"}{typeof brief.overall_for_pct === "number" && <> · {brief.overall_for_pct}% for / {brief.overall_against_pct}% against / {brief.overall_mixed_pct}% mixed</>}</>
              : run?.status === "stopping" || run?.status === "finalising" ? "finishing — lands in a moment"
              : researchActive ? "research running on the Ingest tab"
              : run ? `research ${run.status}, no brief` : "none — run research on the Ingest tab"}
          />
          {groups.length > 0 && (
            <ul className="pl-4 space-y-0.5">
              {groups.slice(0, 6).map((g: any, k: number) => (
                <li key={k} className="text-[11.5px] text-muted-foreground leading-snug"><span className="text-foreground/80">{g.name}</span> · {g.stance} · ~{g.share_pct}%</li>
              ))}
            </ul>
          )}
          <StatusRow state={p.kgCounts?.entities ? "ok" : "none"} label="Knowledge graph" value={p.kgCounts?.entities ? `${p.kgCounts.entities} entities, ${p.kgCounts.relations} relations` : "empty"} />
          <StatusRow state={usable ? "ok" : gathering ? "wait" : "none"} label="Statistics" value={usable ? `${usable} page${usable === 1 ? "" : "s"} with usable facts` : gathering ? "gathering…" : "none yet"} />
        </div>
      </Section>

      {/* Your own inputs */}
      <Section title="Your inputs" aside="optional">
        <div className="space-y-3">
          <div>
            <label className="eyebrow mb-1.5 block">Audience profile</label>
            <textarea value={p.profileQuery} disabled={p.disabled} onChange={(e) => p.onProfileQuery(e.target.value)} rows={2} placeholder="e.g. Parents of under-5s in the North West, mostly renting" className="field field-sm resize-none" />
          </div>
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <span className="eyebrow">Survey or panel data</span>
              <span className="text-[10.5px] text-muted-foreground/50">.txt · .csv</span>
            </div>
            {p.docContext ? (
              <div className="flex items-center gap-2 text-xs surface-raised rounded-lg px-3 py-2">
                <FileText className="w-3.5 h-3.5 text-primary shrink-0" />
                <span className="text-foreground truncate flex-1">{fileName || "uploaded document"}</span>
                <button disabled={p.disabled} onClick={() => { setFileName(null); setTrimmed(null); p.onDocContext("", ""); }} className="text-muted-foreground hover:text-foreground shrink-0"><X className="w-3.5 h-3.5" /></button>
              </div>
            ) : (
              <button disabled={p.disabled} onClick={() => inputRef.current?.click()} className="w-full flex items-center gap-2 text-xs border border-dashed border-border rounded-lg px-3 py-2.5 text-muted-foreground hover:text-foreground hover:border-muted-foreground/50 transition-colors disabled:opacity-50">
                <Upload className="w-3.5 h-3.5 shrink-0" /> Upload respondents to mirror
              </button>
            )}
            {warning && <p className="text-[11px] text-amber-300 mt-1.5">{warning}</p>}
            {trimmed && <p className="text-[11px] text-amber-300 mt-1.5">{trimmed}</p>}
            <p className="hint mt-1.5">Respondents become segments; their answers become dial values. Documents for the knowledge graph go through the Ingest tab.</p>
            <input ref={inputRef} type="file" accept=".txt,.csv,text/plain,text/csv" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); e.target.value = ""; }} />
          </div>
        </div>
      </Section>

      {/* Statistics */}
      <Section title="Statistics" aside={p.facts.length ? `${p.facts.length} page${p.facts.length === 1 ? "" : "s"} read` : undefined}>
        <SwitchRow
          on={p.quantOnBuild}
          onChange={p.onQuantOnBuild}
          disabled={p.disabled}
          title="Gather base rates automatically"
          hint="During Detect & plan the build plans its own fact targets from your dials, profile and upload, reads the ticked publishers, and tries another route when one comes back empty. Every fact keeps its quote."
        />
        <div className="space-y-2.5">
          {regionGroups.map((g) => {
            const items = p.catalogue.filter((s) => !placed.has(s.key) && g.test(s)).sort((a, b) => (b.fit ?? 3) - (a.fit ?? 3));
            items.forEach((s) => placed.add(s.key));
            if (items.length === 0) return null;
            return (
              <div key={g.title} className="space-y-1.5">
                <span className="text-[10.5px] text-muted-foreground/60">{g.title}</span>
                <div className="flex flex-wrap gap-1.5">
                  {items.map((src) => {
                    const on = p.selected.includes(src.key);
                    const fit = src.fit ?? 3;
                    const tip = `${src.domain} · ${src.kind} · readability ${fit}/5\n${src.description}${src.covers?.length ? `\nCovers: ${src.covers.join(", ")}` : ""}${src.note ? `\n${src.note}` : ""}`;
                    return (
                      <button key={src.key} type="button" disabled={p.disabled} title={tip} onClick={() => p.onSelected(on ? p.selected.filter((k) => k !== src.key) : [...p.selected, src.key])} className={`chip transition-colors disabled:opacity-50 ${on ? "chip-on" : fit <= 2 ? "text-muted-foreground/50 hover:text-foreground" : "hover:text-foreground"}`}>
                        {src.label}
                        <span className={`dot w-1 h-1 ${fit >= 4 ? "bg-emerald-400/90" : fit === 3 ? "bg-amber-400/80" : "bg-muted-foreground/40"}`} aria-label={`readability ${fit} of 5`} />
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
        {(() => {
          if (gathering) return <p className="text-[11.5px] text-primary flex items-center gap-1.5"><Loader2 className="w-3 h-3 animate-spin" /> Gathering statistics… {p.facts.length ? `${p.facts.length} page${p.facts.length === 1 ? "" : "s"} read so far` : "planning fact targets"}</p>;
          if (p.facts.length === 0) {
            if (!p.quantOnBuild) return <p className="text-[11.5px] text-amber-300/90">Gathering is off — the plan rests on the evidence brief, your uploads and general knowledge.</p>;
            if (p.buildStatus === "detecting" || p.buildStatus === "queued") return <p className="hint">Detecting the population first — statistics come next.</p>;
            return <p className="hint">Nothing gathered yet — statistics arrive during Detect &amp; plan.</p>;
          }
          return <p className="hint">{usable} page{usable === 1 ? "" : "s"} with usable facts{p.facts.length > usable ? ` · ${p.facts.length - usable} read but not usable` : ""}</p>;
        })()}
        {p.facts.length > 0 && (
          <div className="space-y-1.5 max-h-[420px] overflow-y-auto pr-0.5">
            {[...p.facts].sort((a, b) => Number(b.on_topic) - Number(a.on_topic)).map((f) => <FactCard key={f.id} item={f} onToggle={p.onToggleFact} />)}
          </div>
        )}
        {/* The manual lookup is an extra, not a step: folded away by default. */}
        <details className="group">
          <summary className="text-[11.5px] text-muted-foreground/70 hover:text-foreground cursor-pointer flex items-center gap-1 select-none">
            <ChevronDown className="w-3 h-3 transition-transform group-open:rotate-180" /> Look something up yourself
          </summary>
          <div className="mt-2 space-y-1.5">
            <div className="flex gap-1.5">
              <input value={p.quantQuery} onChange={(e) => p.onQuantQuery(e.target.value)} placeholder="e.g. UK cyclists by age 2025" onKeyDown={(e) => { if (e.key === "Enter" && !p.searching && p.quantQuery.trim()) p.onSearch(); }} className="field field-sm flex-1" />
              <button disabled={p.searching || !p.quantQuery.trim() || p.selected.length === 0} onClick={() => p.onSearch()} className="btn btn-sm btn-secondary shrink-0">
                {p.searching ? <Loader2 className="w-3 h-3 animate-spin" /> : <Search className="w-3 h-3" />} Search
              </button>
            </div>
            <p className="hint">A keyword query runs as written on the ticked publishers; a question is planned into fact targets first. Results join the facts above.</p>
          </div>
        </details>
      </Section>
    </div>
  );
}
