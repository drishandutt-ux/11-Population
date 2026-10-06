"use client";

/** One input of the build, summarised in a dialog: what it was, what the engine read from it and
 *  what it led to, with the real figures highlighted, tables where a list of things has columns,
 *  and links to the pages where a figure came from. Nothing here is computed afresh — every line
 *  is read from the session, the build's record, the research run, the evidence on file and the
 *  knowledge graph. A button at the foot opens the pro page where the same input is analysed in
 *  full. */

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { api, DynamicDial, EvidenceItem, FrameTarget, KgSources, PopulationBuild, ResearchState } from "@/lib/api";
import { proLinks } from "@/lib/lite";
import { cn } from "@/lib/utils";
import { AlertTriangle, ArrowUpRight, Check, ChevronDown, FileText, Globe, Layers, Loader2, Minus, Paperclip, Search, User, X } from "lucide-react";

export type InputKind = "question" | "profile" | "survey" | "added" | "research" | "statistics";

type Props = {
  kind: InputKind | null;
  onClose: () => void;
  sessionId: string;
  question: string;
  dials?: DynamicDial[] | null;
  build: PopulationBuild;
  research: ResearchState | null;
  /** Whether the research had finished before the people were planned, and how many pages it found. */
  researchUsed: boolean;
  researchPages: number;
  kgSources: KgSources | null;
  /** The statistics pages read for this session (quant evidence), with their extracted facts. */
  facts: EvidenceItem[];
  /** Publisher labels, by key. */
  publisherLabels: Record<string, string>;
};

const GOOD = "#0ca30c";
const WARN = "#d99000";

const META: Record<InputKind, { title: string; icon: React.ReactNode; href: (id: string) => string; where: string }> = {
  question: { title: "Your question", icon: <FileText className="w-4 h-4" />, href: proLinks.session, where: "the session page" },
  profile: { title: "Your description", icon: <User className="w-4 h-4" />, href: proLinks.studio, where: "the Population Studio" },
  survey: { title: "Your survey", icon: <Paperclip className="w-4 h-4" />, href: proLinks.studio, where: "the Population Studio" },
  added: { title: "Things you added", icon: <Layers className="w-4 h-4" />, href: proLinks.knowledge, where: "the knowledge graph" },
  research: { title: "Found online", icon: <Globe className="w-4 h-4" />, href: proLinks.sources, where: "the Ingest tab" },
  statistics: { title: "Published statistics", icon: <Search className="w-4 h-4" />, href: proLinks.studio, where: "the Population Studio" },
};

export default function InputDialog(p: Props) {
  const { kind, onClose } = p;
  const titleId = useId();
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!kind) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = prev; };
  }, [kind, onClose]);

  if (!kind || typeof document === "undefined") return null;
  const meta = META[kind];
  const href = meta.href(p.sessionId);

  return createPortal(
    // `.lite` paints an opaque page background, so it goes on the panel, never on the full-screen wrapper.
    <div className="fixed inset-0 z-[90] flex items-end sm:items-center justify-center sm:p-6" role="presentation">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-[2px] animate-fade-in" onClick={onClose} aria-hidden />
      <div role="dialog" aria-modal="true" aria-labelledby={titleId}
        className="lite relative w-full sm:max-w-2xl max-h-[92vh] sm:max-h-[86vh] lite-float bg-card flex flex-col overflow-hidden animate-rise rounded-b-none sm:rounded-b-[1.4rem]">
        <div className="flex items-start gap-3 px-5 sm:px-6 pt-5 pb-3 border-b border-border">
          <span className="mt-0.5 w-8 h-8 rounded-xl bg-foreground/[0.05] inline-flex items-center justify-center text-foreground shrink-0">{meta.icon}</span>
          <div className="min-w-0 flex-1">
            <p className="text-[11.5px] uppercase tracking-wide text-muted-foreground">What went in</p>
            <h2 id={titleId} className="text-[18px] font-semibold tracking-tight leading-tight">{meta.title}</h2>
          </div>
          <button ref={closeRef} type="button" onClick={onClose} className="w-8 h-8 rounded-full inline-flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] transition-colors" aria-label="Close">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto px-5 sm:px-6 py-5 space-y-5">
          {kind === "question" && <QuestionBody {...p} />}
          {kind === "profile" && <ProfileBody {...p} />}
          {kind === "survey" && <SurveyBody {...p} />}
          {kind === "added" && <AddedBody {...p} />}
          {kind === "research" && <ResearchBody {...p} />}
          {kind === "statistics" && <StatisticsBody {...p} />}
        </div>
        <div className="px-5 sm:px-6 py-3 border-t border-border flex items-center justify-between gap-3 flex-wrap">
          <p className="lite-help">Read from the record of this build. The full analysis is in {meta.where}.</p>
          <div className="flex items-center gap-2 ml-auto">
            <button type="button" onClick={onClose} className="lite-btn-soft lite-btn-sm">Close</button>
            <Link href={href} className="lite-btn lite-btn-sm">See it in Pro <ArrowUpRight className="w-3.5 h-3.5" /></Link>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

// ── Each input ────────────────────────────────────────────────────────────────

/** "…in Greater Manchester, UK" — unless the population already names the place. */
function inPlace(who: string | undefined, where: string | undefined): string {
  if (!where) return "";
  const first = where.split(/[,(]/)[0].trim().toLowerCase();
  return who && first && who.toLowerCase().includes(first) ? "" : ` in ${where}`;
}

function signalsFrom(build: PopulationBuild, test: RegExp) {
  return (build.detected?.demographic_signals || []).filter((s) => test.test(s.source || ""));
}

function QuestionBody(p: Props) {
  const det = p.build.detected;
  const words = p.question.trim() ? p.question.trim().split(/\s+/).length : 0;
  const signals = signalsFrom(p.build, /query|question/i);
  const dials = p.dials || [];
  return (
    <>
      <Quote text={p.question} />
      <Stats items={[
        { value: String(words), label: words === 1 ? "word" : "words" },
        { value: det && typeof det.confidence === "number" ? `${Math.round(det.confidence)}%` : "—", label: "sure who to ask", tone: det && typeof det.confidence === "number" ? (det.confidence < 60 ? "warn" : "good") : undefined },
        { value: String(signals.length), label: signals.length === 1 ? "signal read from it" : "signals read from it" },
        { value: dials.length ? String(dials.length) : "—", label: dials.length === 1 ? "dial of its own" : "dials of its own" },
      ]} />
      {det ? (
        <Section title="What the engine read from it">
          <Para>Every step starts from this question. The engine read it first, with your description and survey, what was added and what the research found, and decided who the population is{typeof det.confidence === "number" ? <> — it is <Num>{Math.round(det.confidence)}%</Num> sure of the answer</> : null}.</Para>
          <Table cols={["", ""]} headless rows={[
            ["Who to ask", det.target_population || "—"],
            ["Where", det.geography || "—"],
            ["What it is about", det.topic || "—"],
            ["The decision at stake", det.decision || "—"],
            ["Kind of population", det.population_kind || "—"],
          ]} />
        </Section>
      ) : (
        <Para>The engine has not read this question yet — the build is still at its first step.</Para>
      )}
      {signals.length > 0 && (
        <Section title="Signals taken straight from the wording">
          <Chips items={signals.map((s) => `${s.value}`)} titles={signals.map((s) => s.attribute)} />
        </Section>
      )}
      {det?.segments_hinted?.length ? (
        <Section title="Groups it hinted at">
          <Chips items={det.segments_hinted} />
        </Section>
      ) : null}
      {dials.length > 0 && (
        <Section title="The question's own dials" help="Scales chosen for this question alone; every person carries a 0–10 position on each.">
          <Table cols={["Dial", "Low end", "High end", "Why"]} rows={dials.map((d) => [<strong key="l" className="font-medium text-foreground">{d.label}</strong>, d.low, d.high, <span key="w" className="text-muted-foreground">{d.why}</span>])} />
        </Section>
      )}
    </>
  );
}

function ProfileBody(p: Props) {
  const text = (p.build.constraints?.profile_query || "").trim();
  const det = p.build.detected;
  const signals = signalsFrom(p.build, /profile|description|analyst|dial/i);
  if (!text) {
    return (
      <>
        <Para>No description was given, so the engine worked out who the people are from the question alone{det?.target_population ? <>: <strong className="font-medium text-foreground">{det.target_population}</strong>{inPlace(det.target_population, det.geography)}</> : ""}.</Para>
        <Para>A description — who they are, where they live, what they do — is read before anything else and carries more weight than anything found online. Add one on the People screen when you next build.</Para>
      </>
    );
  }
  const words = text.split(/\s+/).length;
  return (
    <>
      <Quote text={text} />
      <Stats items={[
        { value: String(words), label: words === 1 ? "word" : "words" },
        { value: String(signals.length), label: signals.length === 1 ? "signal read from it" : "signals read from it" },
        { value: det?.segments_hinted?.length ? String(det.segments_hinted.length) : "—", label: "groups it suggested" },
      ]} />
      <Section title="How it was used">
        <Para>Your words were read first, with the question, to decide who the population is{det?.target_population ? <>: <strong className="font-medium text-foreground">{det.target_population}</strong>{inPlace(det.target_population, det.geography)}</> : ""}. What you say about the people outranks what is found online: a description of <em>UK first-time buyers</em> keeps a page about American renters out of the plan.</Para>
      </Section>
      {signals.length > 0 && (
        <Section title="Signals taken from it">
          <Chips items={signals.map((s) => s.value)} titles={signals.map((s) => s.attribute)} />
        </Section>
      )}
      {det?.segments_hinted?.length ? (
        <Section title="Groups it suggested">
          <Chips items={det.segments_hinted} />
        </Section>
      ) : null}
    </>
  );
}

function SurveyBody(p: Props) {
  const text = (p.build.constraints?.doc_context || "").trim();
  const signals = signalsFrom(p.build, /survey|document|upload|doc|file|client/i);
  const frame = p.build.frame || null;
  const uploaded = (frame?.dimensions || []).map((d) => ({ d, t: frame?.targets?.[d.key] })).filter((x) => x.t && (x.t.status === "uploaded" || x.t.provenance === "client_data"));
  if (!text && uploaded.length === 0) {
    return (
      <>
        <Para>No survey was uploaded with these people.</Para>
        <Para>A survey, a table of results or any document about the people is read alongside the question and your description, and any distribution it carries — ages, places, income bands — is matched before a published figure is looked for. Add one on the People screen when you next build.</Para>
      </>
    );
  }
  const words = text ? text.split(/\s+/).length : 0;
  return (
    <>
      <Stats items={[
        { value: words ? words.toLocaleString() : "—", label: "words" },
        { value: text ? text.length.toLocaleString() : "—", label: "characters" },
        { value: String(signals.length), label: signals.length === 1 ? "signal read from it" : "signals read from it" },
        { value: uploaded.length ? String(uploaded.length) : "—", label: uploaded.length === 1 ? "figure taken from it" : "figures taken from it" },
      ]} />
      {text && (
        <Section title="What it says">
          <Expandable text={text} />
        </Section>
      )}
      <Section title="How it was used">
        <Para>The survey was read with the question and your description when the engine decided who to ask, and again when it planned the groups. {uploaded.length ? <>Where it carried a distribution, that distribution was used in place of a published figure for <Num>{uploaded.length}</Num> of the <Num>{frame?.dimensions?.length || 0}</Num> things the people should match.</> : "It carried no distribution the people had to match, so the published figures stood."}</Para>
      </Section>
      {signals.length > 0 && (
        <Section title="Signals taken from it">
          <Chips items={signals.map((s) => s.value)} titles={signals.map((s) => s.attribute)} />
        </Section>
      )}
      {uploaded.length > 0 && (
        <Section title="Figures taken from it">
          <Table cols={["Thing to match", "Shares", "Noted as"]} rows={uploaded.map(({ d, t }) => [
            <strong key="l" className="font-medium text-foreground">{d.label}</strong>,
            <Shares key="s" t={t!} />,
            <span key="n" className="text-muted-foreground">{[t!.source, t!.year].filter(Boolean).join(", ") || t!.note || "your upload"}</span>,
          ])} />
        </Section>
      )}
    </>
  );
}

function AddedBody(p: Props) {
  const all = p.kgSources?.sources || [];
  const added = all.filter((k) => k.kind === "file" || k.kind === "text" || k.kind === "video" || k.kind === "page");
  const pieces = added.reduce((k, a) => k + a.chunks, 0);
  const total = p.kgSources?.chunks || 0;
  const others = { research: 0, social: 0, statistics: 0 } as Record<string, number>;
  for (const k of all) if (k.kind in others) others[k.kind] += k.chunks;
  if (added.length === 0) {
    return (
      <>
        <Para>Nothing was added by hand. The knowledge the people were written from came from the question{total ? <> and the <Num>{total.toLocaleString()}</Num> pieces the research and the statistics left on file</> : " and whatever the research and the statistics left on file"}.</Para>
        <Para>Files, pasted text, YouTube videos and web pages dropped into <em>Add anything</em> are read, cut into pieces and placed in the knowledge graph, where every person can reach them. Add material on the Ask screen at any time — it reaches the people straight away.</Para>
      </>
    );
  }
  return (
    <>
      <Para>
        <Num>{added.length}</Num> {added.length === 1 ? "item was" : "items were"} added by hand and read into the knowledge graph as <Num>{pieces.toLocaleString()}</Num> {pieces === 1 ? "piece" : "pieces"} of knowledge
        {total ? <> — <Num>{Math.round((pieces / total) * 100)}%</Num> of the <Num>{total.toLocaleString()}</Num> pieces on file</> : null}.
        {p.kgSources ? <> The graph holds <Num>{p.kgSources.entities.toLocaleString()}</Num> named things and <Num>{p.kgSources.relations.toLocaleString()}</Num> links between them.</> : null}
      </Para>
      <Stats items={[
        { value: String(added.length), label: added.length === 1 ? "item" : "items" },
        { value: pieces.toLocaleString(), label: "pieces of knowledge" },
        { value: others.research ? others.research.toLocaleString() : "—", label: "pieces found online" },
        { value: others.statistics ? others.statistics.toLocaleString() : "—", label: "pieces from statistics" },
      ]} />
      <Section title="What was added">
        <Table cols={["Item", "Kind", "Pieces"]} rows={added.map((a) => [
          isUrl(a.ref) ? <Ext key="n" href={a.ref} label={a.name} /> : <span key="n" className="font-medium text-foreground">{a.name}</span>,
          <span key="k" className="text-muted-foreground">{kindWord(a.kind)}</span>,
          <Num key="c">{a.chunks.toLocaleString()}</Num>,
        ])} />
      </Section>
      <Section title="How it was used">
        <Para>Each piece is tagged with where it came from and which people can reach it. When a person is written, and every time they speak, the pieces their group can reach are read first, so what you added is in their heads from the start.</Para>
      </Section>
    </>
  );
}

function ResearchBody(p: Props) {
  const run = p.research?.run || null;
  const queries = p.research?.queries || [];
  const counts = p.research?.counts || {};
  const [rows, setRows] = useState<EvidenceItem[] | null>(null);
  useEffect(() => {
    let live = true;
    if (run) api.research.evidence(p.sessionId).then((r) => { if (live) setRows(r); }).catch(() => { if (live) setRows([]); });
    return () => { live = false; };
  }, [p.sessionId, run?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!run) {
    return (
      <>
        <Para>Research the web was not run for this question.</Para>
        <Para>When it runs, the engine plans searches for the question, reads every page whole, keeps the ones that are on topic and quotes the passages that matter, so the people are written from what real sources say. Start it from the Ask screen.</Para>
      </>
    );
  }
  const read = Object.values(counts).reduce((k, v) => k + (v?.read || 0), 0);
  const onTopic = Object.values(counts).reduce((k, v) => k + (v?.on_topic || 0), 0);
  const bySource = { web: queries.filter((q) => q.source === "web").length, reddit: queries.filter((q) => q.source === "reddit").length };
  const brief = run.brief && typeof run.brief === "object" ? run.brief : null;
  const status = run.status;
  const statusWords = status === "done" || status === "complete" || status === "finished" ? "finished" : status === "running" || status === "queued" || status === "finalising" || status === "stopping" ? "still running" : status === "stopped" ? "stopped early" : status === "error" ? "stopped with an error" : status;
  const pages = (rows || []).filter((e) => e.source_class === "web" && !e.excluded);
  const posts = (rows || []).filter((e) => e.source_class === "social" && !e.excluded);
  const topPages = pages.filter((e) => e.on_topic).sort((a, b) => (b.relevance || 0) - (a.relevance || 0));
  const topPosts = posts.filter((e) => e.on_topic).sort((a, b) => (b.relevance || 0) - (a.relevance || 0));
  const inGraph = p.research?.in_graph ?? pages.filter((e) => e.in_graph).length;

  return (
    <>
      <Para>
        The research {statusWords}{run.finished_at ? ` on ${when(run.finished_at)}` : run.started_at ? `, started ${when(run.started_at)}` : ""}. It ran <Num>{queries.length}</Num> {queries.length === 1 ? "search" : "searches"}
        {bySource.web || bySource.reddit ? <> (<Num>{bySource.web}</Num> on the web{bySource.reddit ? <>, <Num>{bySource.reddit}</Num> on Reddit</> : null})</> : null}, read <Num>{read}</Num> {read === 1 ? "page" : "pages"} whole and judged <Num>{onTopic}</Num> on topic
        {typeof inGraph === "number" && inGraph > 0 ? <>; <Num>{inGraph}</Num> went into the knowledge graph</> : null}.
        {p.researchPages > 0 && !p.researchUsed ? <> It finished <strong className="font-medium text-amber-700">after the people were planned</strong>, so the plan did not see it; the people have been given the <Num>{p.researchPages}</Num> pages since.</> : p.researchUsed ? " It finished before the people were planned, so the plan was written with it in hand." : ""}
      </Para>
      <Stats items={[
        { value: String(queries.length), label: "searches" },
        { value: String(read), label: "pages read" },
        { value: String(onTopic), label: "on topic", tone: read && onTopic ? "good" : undefined },
        { value: typeof inGraph === "number" ? String(inGraph) : "—", label: "in the graph" },
      ]} />
      {Object.keys(counts).length > 0 && (
        <Section title="By source">
          <Table cols={["Source", "Read", "On topic", "Kept"]} rows={Object.entries(counts).map(([k, v]) => [
            <span key="s" className="font-medium text-foreground">{sourceWord(k)}</span>,
            <Num key="r">{v.read}</Num>,
            <Num key="o">{v.on_topic}</Num>,
            <span key="p" className="text-muted-foreground">{v.read ? `${Math.round((v.on_topic / v.read) * 100)}%` : "—"}</span>,
          ])} />
        </Section>
      )}
      {brief?.summary && (
        <Section title="What it established" help="The brief written from the on-topic evidence, handed to the engine with the question.">
          <Para><Hi text={String(brief.summary)} /></Para>
          {Array.isArray(brief.key_facts) && brief.key_facts.length > 0 && (
            <ul className="mt-2 space-y-1.5">
              {brief.key_facts.slice(0, 10).map((f: string, i: number) => (
                <li key={i} className="flex gap-2 text-[13px] leading-relaxed text-foreground/85"><Check className="w-3.5 h-3.5 mt-1 shrink-0" style={{ color: GOOD }} aria-hidden /><span><Hi text={f} /></span></li>
              ))}
            </ul>
          )}
          {Array.isArray(brief.gaps) && brief.gaps.length > 0 && (
            <div className="mt-3">
              <p className="text-[11.5px] uppercase tracking-wide text-muted-foreground">Not covered</p>
              <ul className="mt-1 space-y-1">
                {brief.gaps.slice(0, 6).map((g: string, i: number) => <li key={i} className="flex gap-2 text-[12.5px] leading-relaxed text-muted-foreground"><AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" style={{ color: WARN }} aria-hidden /><span>{g}</span></li>)}
              </ul>
            </div>
          )}
        </Section>
      )}
      <Section title={rows === null ? "Pages it kept" : `Pages it kept · ${topPages.length}`}>
        {rows === null ? (
          <p className="lite-help inline-flex items-center gap-2"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Reading the pages on file…</p>
        ) : topPages.length === 0 ? (
          <Para>No page was judged on topic{read ? <> — <Num>{read}</Num> were read and set aside</> : ""}.</Para>
        ) : (
          <>
            <Table cols={["Page", "Site", "Relevance"]} rows={topPages.slice(0, 12).map((e) => [
              <span key="t" className="block">
                <Ext href={e.source_ref} label={e.title || e.source_ref} />
                {e.structured?.judge?.reason ? <span className="block text-[11.5px] text-muted-foreground leading-snug mt-0.5 line-clamp-2">{e.structured.judge.reason}</span> : null}
              </span>,
              <span key="d" className="text-muted-foreground whitespace-nowrap">{e.author || host(e.source_ref)}</span>,
              <Bar key="r" pct={Math.round((e.relevance || 0) * 100)} />,
            ])} />
            {topPages.length > 12 && <p className="lite-help mt-2">And {topPages.length - 12} more, listed in the Ingest tab.</p>}
          </>
        )}
      </Section>
      {topPosts.length > 0 && (
        <Section title={`Posts it kept · ${topPosts.length}`} help="Social posts establish how people talk and feel, never facts.">
          <Table cols={["Post", "Where", "Score"]} rows={topPosts.slice(0, 6).map((e) => [
            <Ext key="t" href={e.source_ref} label={e.title || e.source_ref} />,
            <span key="w" className="text-muted-foreground whitespace-nowrap">{e.structured?.subreddit ? `r/${e.structured.subreddit}` : e.author || host(e.source_ref)}</span>,
            <Num key="s">{typeof e.structured?.score === "number" ? e.structured.score.toLocaleString() : "—"}</Num>,
          ])} />
        </Section>
      )}
      {queries.length > 0 && (
        <Section title="What it searched for">
          <Table cols={["Search", "Where", "Found", "Read", "On topic"]} rows={queries.slice(0, 14).map((q) => [
            <span key="q" className="text-foreground">{q.query}</span>,
            <span key="s" className="text-muted-foreground whitespace-nowrap">{sourceWord(q.source)}{q.engine && q.engine.toLowerCase() !== q.source.toLowerCase() ? ` · ${q.engine}` : ""}</span>,
            <Num key="f">{q.results}</Num>, <Num key="r">{q.read}</Num>, <Num key="o">{q.on_topic}</Num>,
          ])} />
          {queries.length > 14 && <p className="lite-help mt-2">And {queries.length - 14} more searches.</p>}
        </Section>
      )}
    </>
  );
}

function StatisticsBody(p: Props) {
  const src = p.build.sources;
  const on = !!src?.quant;
  const publishers = on ? (src.quant_sources || []).map((k) => p.publisherLabels[k] || k) : [];
  const frame = p.build.frame || null;
  const dims = frame?.dimensions || [];
  const det = p.build.detected;
  const usable = p.facts.filter((e) => (e.structured?.facts || []).length > 0 && !e.excluded);
  const facts = usable.flatMap((e) => ((e.structured?.facts || []) as any[]).map((f) => ({ ...f, page: e, rel: e.relevance || 0, label: e.structured?.source_label || e.author || host(e.source_ref) })))
    .sort((a, b) => b.rel - a.rel);
  const matched = dims.filter((d) => { const t = frame?.targets?.[d.key]; return t && (t.status === "found" || t.status === "proxy" || t.status === "uploaded"); }).length;
  const byPublisher = new Map<string, number>();
  for (const e of usable) { const k = e.structured?.source_label || e.author || host(e.source_ref); byPublisher.set(k, (byPublisher.get(k) || 0) + (e.structured?.facts || []).length); }

  if (!on) {
    return (
      <>
        <Para>No publishers were searched for this build, so the groups were sized from your description, what was added and general knowledge.</Para>
        <Para>With published statistics on, the engine searches the ticked publishers — the ONS, Nomis, gov.uk and the rest — for base rates about the people, and matches the mix to the published shares. Turn it on in the Studio when you next build.</Para>
      </>
    );
  }
  return (
    <>
      <Para>
        <Num>{publishers.length}</Num> {publishers.length === 1 ? "publisher was" : "publishers were"} searched for base rates about {det?.target_population ? <strong className="font-medium text-foreground">{det.target_population}</strong> : "these people"}{inPlace(det?.target_population, frame?.geography || det?.geography)}{src.quant_auto ? ", picked for that place automatically" : ""}.
        {usable.length ? <> <Num>{usable.length}</Num> {usable.length === 1 ? "page" : "pages"} carried usable figures — <Num>{facts.length}</Num> {facts.length === 1 ? "statistic" : "statistics"} in all, from <Num>{byPublisher.size}</Num> {byPublisher.size === 1 ? "publisher" : "publishers"}.</> : " No page read so far carried a usable figure."}
        {dims.length ? <> Figures were found for <Num>{matched}</Num> of the <Num>{dims.length}</Num> things the people should match.</> : null}
      </Para>
      <Stats items={[
        { value: String(publishers.length), label: "publishers searched" },
        { value: usable.length ? String(usable.length) : "—", label: "pages with figures" },
        { value: facts.length ? String(facts.length) : "—", label: "statistics on file" },
        { value: dims.length ? `${matched}/${dims.length}` : "—", label: "figures matched", tone: dims.length ? (matched === 0 ? "warn" : matched === dims.length ? "good" : undefined) : undefined },
      ]} />
      <Section title="Publishers searched">
        <Chips items={publishers} marks={publishers.map((l) => byPublisher.has(l) ? (byPublisher.get(l) || 0) : 0)} />
        {byPublisher.size > 0 && <p className="lite-help mt-2">A number on a chip is how many statistics that publisher gave.</p>}
      </Section>
      {dims.length > 0 && (
        <Section title="What the people had to match" help="One row per thing the mix of people should match, and where its figure came from.">
          <Table cols={["Thing to match", "Standing", "Figure"]} rows={dims.map((d) => {
            const t = frame?.targets?.[d.key];
            const st = standing(t);
            return [
              <span key="l" className="block"><strong className="font-medium text-foreground">{d.label}</strong>{d.why ? <span className="block text-[11.5px] text-muted-foreground leading-snug mt-0.5 line-clamp-2">{d.why}</span> : null}</span>,
              <span key="s" className="inline-flex items-center gap-1 whitespace-nowrap">
                {st === "matched" ? <Check className="w-3.5 h-3.5" style={{ color: GOOD }} /> : st === "assumed" ? <AlertTriangle className="w-3.5 h-3.5" style={{ color: WARN }} /> : <Minus className="w-3.5 h-3.5 text-muted-foreground" />}
                <span className={st === "assumed" ? "text-amber-700" : st === "none" ? "text-muted-foreground" : "text-foreground"}>{standingWord(st, t)}</span>
              </span>,
              t && st !== "none" ? <span key="f" className="block"><Shares t={t} /><span className="block text-[11.5px] text-muted-foreground mt-0.5">{[t.source, t.year, t.geography].filter(Boolean).join(" · ")}</span></span> : <span key="f" className="text-muted-foreground">{t?.note || "—"}</span>,
            ];
          })} />
        </Section>
      )}
      {facts.length > 0 && (
        <Section title={`Statistics found · ${facts.length}`} help="Copied from the publishers' pages as written; each links to the page it came from.">
          <Table cols={["Statistic", "Value", "Who · where · when", "Source"]} rows={facts.slice(0, 14).map((f, i) => [
            <span key="s" className="text-foreground">{f.statistic}</span>,
            <strong key="v" className="font-semibold text-foreground tabular-nums whitespace-nowrap">{f.value}</strong>,
            <span key="g" className="text-muted-foreground">{[f.group, f.geography, f.year].filter(Boolean).join(" · ")}</span>,
            <Ext key="p" href={f.page.source_ref} label={f.label} />,
          ])} />
          {facts.length > 14 && <p className="lite-help mt-2">And {facts.length - 14} more, in the Studio&apos;s figure ledger.</p>}
        </Section>
      )}
      {frame?.sizing && (frame.sizing.tam?.value || frame.sizing.sam?.value || frame.sizing.som?.value) && (
        <Section title="How big the population is">
          <Table cols={["", "People", "Source"]} headless rows={(["tam", "sam", "som"] as const).map((k) => frame.sizing![k]).filter((c) => c && c.value).map((c) => [
            <span key="l" className="font-medium text-foreground">{c.label || ""}</span>,
            <strong key="v" className="font-semibold text-foreground tabular-nums">{c.value}</strong>,
            <span key="s" className="text-muted-foreground">{[c.source, c.year].filter(Boolean).join(", ") || "—"}</span>,
          ])} />
          {frame.sizing.note && <p className="lite-help mt-2">{frame.sizing.note}</p>}
        </Section>
      )}
    </>
  );
}

// ── Pieces ─────────────────────────────────────────────────────────────────────

type Standing = "matched" | "assumed" | "none";
function standing(t: FrameTarget | undefined): Standing {
  if (!t || t.status === "skipped" || t.status === "missing") return "none";
  if (t.status === "estimated") return "assumed";
  return "matched";
}
function standingWord(s: Standing, t?: FrameTarget): string {
  if (s === "none") return "No figure found";
  if (s === "assumed") return "Assumed";
  if (t?.status === "uploaded") return "Your upload";
  if (t?.status === "proxy") return "Closest figure";
  return "Published figure";
}
function kindWord(k: string): string {
  switch (k) {
    case "file": return "file";
    case "text": return "pasted text";
    case "video": return "video";
    case "page": return "web page";
    default: return "item";
  }
}
function sourceWord(k: string): string {
  switch (k) {
    case "web": return "Web pages";
    case "reddit": return "Reddit";
    case "social": return "Social posts";
    case "quant": return "Statistics pages";
    default: return k.charAt(0).toUpperCase() + k.slice(1);
  }
}
function isUrl(s: string): boolean { return /^https?:\/\//i.test(s || ""); }
function host(u: string): string { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u || ""; } }
function when(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function Para({ children }: { children: React.ReactNode }) {
  return <p className="text-[14px] leading-relaxed text-foreground/85">{children}</p>;
}
function Num({ children }: { children: React.ReactNode }) {
  return <strong className="font-semibold text-foreground tabular-nums">{children}</strong>;
}
/** A sentence with its figures set in bold: numbers, percentages, money, years and the words that size them. */
function Hi({ text }: { text: string }) {
  const parts = useMemo(() => text.split(/((?:[£$€]\s?)?\d[\d,.]*(?:\s?(?:%|percent|pp|points|million|billion|bn|m|k|thousand))?)/gi), [text]);
  return <>{parts.map((s, i) => (i % 2 === 1 ? <Num key={i}>{s}</Num> : <span key={i}>{s}</span>))}</>;
}
function Quote({ text }: { text: string }) {
  return <blockquote className="rounded-2xl bg-foreground/[0.04] px-4 py-3 text-[15px] leading-relaxed text-foreground border-l-2 border-foreground/20">{text}</blockquote>;
}
function Section({ title, help, children }: { title: string; help?: string; children: React.ReactNode }) {
  return (
    <section>
      <p className="text-[11.5px] uppercase tracking-wide text-muted-foreground">{title}</p>
      {help && <p className="lite-help mt-0.5">{help}</p>}
      <div className="mt-2">{children}</div>
    </section>
  );
}
function Stats({ items }: { items: { value: string; label: string; tone?: "good" | "warn" }[] }) {
  return (
    <div className={cn("grid gap-2", items.length >= 4 ? "grid-cols-2 sm:grid-cols-4" : "grid-cols-3")}>
      {items.map((it, i) => (
        <div key={i} className={cn("rounded-xl border border-border px-3 py-2.5 text-center", it.value === "—" && "opacity-60")}>
          <p className={cn("text-[20px] font-semibold tracking-tight tabular-nums leading-none", it.tone === "good" ? "text-emerald-700" : it.tone === "warn" ? "text-amber-700" : "text-foreground")}>{it.value}</p>
          <p className="text-[11px] text-muted-foreground mt-1.5 leading-tight">{it.label}</p>
        </div>
      ))}
    </div>
  );
}
function Chips({ items, titles, marks }: { items: string[]; titles?: string[]; marks?: number[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((it, i) => (
        <span key={`${it}-${i}`} title={titles?.[i]} className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[12px]", marks && marks[i] ? "bg-emerald-50 text-emerald-800 border border-emerald-200" : "bg-foreground/[0.05] text-foreground/80")}>
          {it}{marks && marks[i] ? <span className="rounded-full bg-white/80 px-1.5 text-[10.5px] font-semibold tabular-nums">{marks[i]}</span> : null}
        </span>
      ))}
    </div>
  );
}
function Table({ cols, rows, headless }: { cols: string[]; rows: React.ReactNode[][]; headless?: boolean }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full text-[13px] leading-snug">
        {!headless && (
          <thead>
            <tr className="bg-foreground/[0.03] text-[11px] uppercase tracking-wide text-muted-foreground">
              {cols.map((c, i) => <th key={i} className="text-left font-medium px-3 py-2 whitespace-nowrap">{c}</th>)}
            </tr>
          </thead>
        )}
        <tbody className="divide-y divide-border">
          {rows.map((r, i) => (
            <tr key={i} className="align-top">
              {r.map((cell, j) => <td key={j} className={cn("px-3 py-2", headless && j === 0 && "text-muted-foreground whitespace-nowrap w-[1%]")}>{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function Ext({ href, label }: { href: string; label: string }) {
  if (!isUrl(href)) return <span className="font-medium text-foreground">{label}</span>;
  return (
    <a href={href} target="_blank" rel="noreferrer" className="inline-flex items-start gap-1 font-medium text-foreground hover:text-primary transition-colors" title={href}>
      <span className="line-clamp-2">{label}</span><ArrowUpRight className="w-3 h-3 mt-1 shrink-0 text-muted-foreground" />
    </a>
  );
}
function Bar({ pct }: { pct: number }) {
  const p = Math.max(0, Math.min(100, pct));
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap" title={`${p}% relevant`}>
      <span className="w-16 h-1.5 rounded-full bg-foreground/[0.07] overflow-hidden"><span className="block h-full rounded-full" style={{ width: `${p}%`, background: p >= 70 ? GOOD : p >= 40 ? "#2a78d6" : WARN }} /></span>
      <Num>{p}%</Num>
    </span>
  );
}
function Shares({ t }: { t: FrameTarget }) {
  const cats = (t.categories || []).filter((c) => typeof c.share_pct === "number");
  if (!cats.length) return <span className="text-muted-foreground">{t.note || "—"}</span>;
  return (
    <span className="flex flex-wrap gap-x-2 gap-y-0.5">
      {cats.slice(0, 8).map((c, i) => <span key={i} className="whitespace-nowrap"><span className="text-muted-foreground">{c.label}</span> <Num>{Math.round(c.share_pct)}%</Num></span>)}
      {cats.length > 8 && <span className="text-muted-foreground">+{cats.length - 8}</span>}
    </span>
  );
}
function Expandable({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > 900;
  return (
    <div>
      <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-foreground/85 rounded-2xl bg-foreground/[0.04] px-4 py-3">{open || !long ? text : `${text.slice(0, 900).trimEnd()}…`}</p>
      {long && <button type="button" onClick={() => setOpen((v) => !v)} className="mt-1.5 text-[12px] text-muted-foreground hover:text-foreground inline-flex items-center gap-1">{open ? "Less" : "Read it all"} <ChevronDown className={cn("w-3 h-3 transition-transform", open && "rotate-180")} /></button>}
    </div>
  );
}
