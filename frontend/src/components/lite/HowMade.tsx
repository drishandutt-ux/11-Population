"use client";

/** "How these people were made": the simple view's visual reading of the Studio build that wrote
 *  the roster — a strip of highlights, what went in as tiles, who they stand for with a confidence
 *  ring, the groups as a share bar, the sampling frame as a heat grid, what was assumed, and how
 *  they talk as a meter. Nothing here is computed afresh: it is the build's own record (detected
 *  population, plan, frame, log) drawn rather than listed. */

import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { api, Agent, DynamicDial, EvidenceItem, FrameReportDim, FrameTarget, KgSource, KgSources, PopulationBuild, PopulationLogEntry, PopulationSegment, QuantSource, ResearchState } from "@/lib/api";
import Detail, { DetailLink } from "@/components/lite/Detail";
import InputDialog, { InputKind } from "@/components/lite/InputDialog";
import { proLinks, stanceWords } from "@/lib/lite";
import { cn } from "@/lib/utils";
import { AlertTriangle, BookOpen, Check, ChevronDown, Circle, FileText, Globe, Layers, Loader2, MessageSquare, Minus, Paperclip, ScrollText, Search, Sparkles, User, Users } from "lucide-react";

type Props = {
  sessionId: string;
  question: string;
  build: PopulationBuild | null;
  agents: Agent[];
  research: ResearchState | null;
  /** Posts in the conversation so far, and whether a report has been written — the flow's last two nodes. */
  posts?: number;
  hasReport?: boolean;
  /** The question's own dials, shown in the "Your question" summary. */
  dials?: DynamicDial[] | null;
};

// Categorical palette (validated order; a 9th group folds into "Other").
const SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"];
const OTHER = "#9a9994";
// Status colours — always with an icon and a word, never alone.
const GOOD = "#0ca30c";
const WARN = "#d99000";
const NONE = "#c9c8c3";
// One-hue ramp for the heat grid (how far the people sit from the published share).
const HEAT = ["#eef4fc", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95"];

const PUBLISHER_FALLBACK: Record<string, string> = {
  ons: "ONS", nomis: "Nomis", govuk: "gov.uk", fca: "FCA", ofcom: "Ofcom", moreincommon: "More in Common", opinium: "Opinium",
  census: "US Census", pew: "Pew", bls: "BLS", gallup: "Gallup",
};

function moodWords(mood: PopulationSegment["sentiment"]["mood"]): string {
  switch (mood) {
    case "for": return "for";
    case "against": return "against";
    case "mixed": return "split";
    case "uncertain": return "unsure";
    default: return "";
  }
}
function list(items: string[], max = 3): string {
  const shown = items.filter(Boolean).slice(0, max);
  if (shown.length <= 1) return shown[0] || "";
  return `${shown.slice(0, -1).join(", ")} and ${shown[shown.length - 1]}`;
}

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

export default function HowMade({ sessionId, question, build, agents, research, posts = 0, hasReport = false, dials = null }: Props) {
  const [labels, setLabels] = useState<Record<string, string>>(PUBLISHER_FALLBACK);
  useEffect(() => {
    api.population.sources().then((r) => {
      const m: Record<string, string> = { ...PUBLISHER_FALLBACK };
      for (const s of (r.sources || []) as QuantSource[]) m[s.key] = s.label;
      setLabels(m);
    }).catch(() => {});
  }, []);
  // What the graph was fed and which statistics pages carry figures: the flow's "added" and
  // "statistics" nodes. Read again whenever the build moves, so a page left open keeps up.
  const [kgSources, setKgSources] = useState<KgSources | null>(null);
  const [factRows, setFactRows] = useState<EvidenceItem[] | null>(null);
  // Which input's summary dialog is open, if any.
  const [openInput, setOpenInput] = useState<InputKind | null>(null);
  const buildKey = `${build?.id || ""}:${build?.status || ""}:${agents.length}`;
  useEffect(() => {
    api.kg.sources(sessionId).then(setKgSources).catch(() => {});
    api.population.facts(sessionId).then((rows) => setFactRows(rows as EvidenceItem[])).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, buildKey]);

  const n = agents.length;
  const studioHref = proLinks.studio(sessionId);
  const factPages = factRows ? factRows.filter((e) => (e.structured?.facts || []).length > 0).length : null;

  // ── A roster written without the Studio ──
  if (!build || !build.plan) {
    const by = { direct: 0, indirect: 0, neutral: 0 } as Record<string, number>;
    for (const a of agents) by[a.stance] = (by[a.stance] || 0) + 1;
    return (
      <section className="max-w-6xl mx-auto px-4 sm:px-6 pb-24 animate-rise" style={{ animationDelay: "90ms" }}>
        <h2 className="text-[18px] font-semibold tracking-tight">How these people were made</h2>
        <Detail href={proLinks.people(sessionId)}>
          <div className="lite-card p-5 sm:p-6 mt-3">
            <p className="text-[14px] leading-relaxed">These {n} people were written straight from your question and everything that was added, each with a life, a place and a point of view that fits. No plan of groups was drawn up first.</p>
            <div className="mt-4 grid grid-cols-3 gap-2">
              <Tile value={String(by.direct)} label="directly affected" />
              <Tile value={String(by.indirect)} label="affected indirectly" />
              <Tile value={String(by.neutral)} label="looking on" />
            </div>
          </div>
        </Detail>
      </section>
    );
  }

  const c = build.constraints || {};
  const plan = build.plan;
  const det = build.detected;
  const frame = build.frame || null;
  const log = build.log || [];

  const profile = (c.profile_query || "").trim();
  const survey = (c.doc_context || "").trim();
  const surveyWords = survey ? survey.split(/\s+/).length : 0;
  const briefMissing = log.some((e) => e.stage === "detect" && /no evidence brief/i.test(e.message));
  const run = research?.run || null;
  const pages = Object.values(research?.counts || {}).reduce((k, v) => k + (v?.on_topic || 0), 0);
  const researchUsed = !briefMissing && !!run && pages > 0;
  const publishers = build.sources?.quant ? (build.sources.quant_sources || []).map((k) => labels[k] || k) : [];
  const segments = plan.segments.filter((s) => s.decision !== "rejected");

  const dims = frame?.dimensions || [];
  const standings = dims.map((d) => standing(frame?.targets?.[d.key]));
  const matched = standings.filter((s) => s === "matched").length;
  const reportDims: Record<string, FrameReportDim> = Object.fromEntries((frame?.report?.dimensions || []).map((d) => [d.key, d]));

  const assumed: string[] = [...(plan.assumptions || [])];
  dims.forEach((d, i) => { if (standings[i] === "assumed") assumed.push(`${d.label}: no published figure for this place, so a spread was assumed.`); });
  const unevidenced = segments.filter((s) => !s.evidence?.length).length;
  if (unevidenced) assumed.push(`${unevidenced} of the ${segments.length} groups ${unevidenced === 1 ? "is" : "are"} sized from general knowledge, not a published figure.`);
  const gaps = det?.gaps || [];

  const intro = [
    `${n} people were written from your question`,
    profile ? "your description of them" : "",
    survey ? "your survey" : "",
    researchUsed ? `${pages} page${pages === 1 ? "" : "s"} found online` : "",
    publishers.length ? "published statistics" : "",
  ].filter(Boolean);
  const introText = intro.length > 1 ? `${intro.slice(0, -1).join(", ")} and ${intro[intro.length - 1]}.` : `${intro[0]}.`;

  const countFor = (s: PopulationSegment) => {
    const k = agents.filter((a) => a.segment === s.id || a.segment === s.name).length;
    return k || s.count || Math.round((s.share_pct / 100) * n);
  };

  // One line per folded card, read from the same record — what the card says before it is opened.
  const whoLine = det ? [det.target_population, typeof det.confidence === "number" ? `${Math.round(det.confidence)}% sure` : ""].filter(Boolean).join(" · ") : "";
  const bySize = segments.slice().sort((a, b) => b.share_pct - a.share_pct);
  const groupsLine = bySize.length
    ? bySize.slice(0, 2).map((s) => `${s.name} ${Math.round(s.share_pct)}%`).join(" · ") + (bySize.length > 2 ? ` · ${bySize.length - 2} more` : "")
    : "";
  const matchedLabels = dims.filter((_, i) => standings[i] === "matched").map((d) => d.label);
  const assumedLabels = dims.filter((_, i) => standings[i] === "assumed").map((d) => d.label);
  const unmatchedCount = dims.length - matchedLabels.length - assumedLabels.length;
  const matchLine = dims.length
    ? [
        matchedLabels.length ? `Matched on ${list(matchedLabels, 2)}` : "Nothing matched to a published figure",
        assumedLabels.length ? `${assumedLabels.length} assumed` : "",
        unmatchedCount ? `${unmatchedCount} with no figure` : "",
        frame?.report?.level && frame.report.level !== "none" ? `overall ${frame.report.level}` : "",
      ].filter(Boolean).join(" · ")
    : "";
  const coverage = /(\d{1,3})\s*%\s*evidence/i.exec(plan.evidence_coverage || "");
  const assumedLine = [
    coverage ? `${coverage[1]}% evidence` : "",
    assumed.length ? `${assumed.length} assumption${assumed.length === 1 ? "" : "s"}` : "",
    gaps.length ? `${gaps.length} thing${gaps.length === 1 ? "" : "s"} could not be found` : "",
  ].filter(Boolean).join(" · ");
  const voiceWord = plan.voice ? (plan.voice.value < 35 ? "Like experts" : plan.voice.value > 65 ? "Like ordinary people" : "Between experts and ordinary people") : "";
  const voiceLine = plan.voice ? [voiceWord, (plan.voice.reason || "").split(/(?<=[.!?])\s/)[0]].filter(Boolean).join(" · ") : "";

  return (
    <section className="max-w-6xl mx-auto px-4 sm:px-6 pb-24 animate-rise" style={{ animationDelay: "90ms" }}>
      <h2 className="text-[18px] font-semibold tracking-tight">How these people were made</h2>
      <p className="lite-lead mt-1">{introText}</p>

      {/* Highlights */}
      <div className="mt-4 grid grid-cols-3 sm:grid-cols-6 gap-2">
        <Tile value={String(n)} label="people" />
        <Tile value={String(segments.length)} label={segments.length === 1 ? "group" : "groups"} />
        <Tile value={researchUsed ? String(pages) : "—"} label="pages read online" dim={!researchUsed} />
        <Tile value={publishers.length ? String(publishers.length) : "—"} label="publishers searched" dim={!publishers.length} />
        <Tile value={dims.length ? `${matched}/${dims.length}` : "—"} label="figures matched" dim={!dims.length} tone={dims.length ? (matched === 0 ? "warn" : matched === dims.length ? "good" : undefined) : undefined} />
        <Tile value={typeof det?.confidence === "number" ? `${Math.round(det.confidence)}%` : "—"} label="sure who they are" dim={typeof det?.confidence !== "number"} />
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-2 items-start">
        {/* 1 · What went in — the full width */}
        <Detail href={proLinks.sources(sessionId)} className="lg:col-span-2">
          <div className="lite-card p-5 sm:p-6 h-full">
            <Head title="Where these people came from" />
            <p className="lite-help mt-1">What went in on the left, what the engine did with it in the middle, what came out on the right. Each input opens a summary of what it was and how it was used; the engine and what came out open the page where they are analysed in full.</p>
            <Flow
              sessionId={sessionId}
              n={n}
              groups={segments.length}
              profileWords={profile ? profile.split(/\s+/).length : 0}
              surveyWords={surveyWords}
              added={(kgSources?.sources || []).filter((k) => k.kind === "file" || k.kind === "text" || k.kind === "video" || k.kind === "page")}
              research={{ ran: !!run, pages, used: researchUsed, late: !!run && pages > 0 && !researchUsed, bySource: research?.counts || {} }}
              statistics={{ publishers: publishers.length, pages: factPages, dims: dims.length, matched }}
              detected={det ? { who: det.target_population, where: det.geography, confidence: typeof det.confidence === "number" ? det.confidence : null } : null}
              assumptions={assumed.length}
              log={log}
              status={build.status}
              segmentsForBar={segments.map((sg) => ({ id: sg.id, name: sg.name, share: sg.share_pct }))}
              posts={posts}
              hasReport={hasReport}
              onOpen={setOpenInput}
            />
            <div className="mt-5 grid gap-x-6 gap-y-3 md:grid-cols-2">
              {profile && <Clamp label="Your description" text={profile} />}
              {publishers.length > 0 && (
                <div>
                  <p className="text-[11.5px] uppercase tracking-wide text-muted-foreground">Statistics searched</p>
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {publishers.map((pub) => <span key={pub} className="rounded-full bg-foreground/[0.05] px-2 py-0.5 text-[11.5px] text-foreground/80">{pub}</span>)}
                  </div>
                  {dims.length > 0 && <p className="lite-help mt-2">{matched ? `Figures were found for ${matched} of the ${dims.length} things the people should match.` : `None of the ${dims.length} things the people should match had a published figure.`}</p>}
                </div>
              )}
              {run && pages > 0 && !researchUsed && <p className="lite-help md:col-span-2">The web research finished after the people were planned; they have since been given the {pages} page{pages === 1 ? "" : "s"} it found.</p>}
            </div>
          </div>
        </Detail>

        {/* 2 · Who they stand for */}
        {det && (
          <Detail href={studioHref}>
            <Fold title="Who they stand for" line={whoLine}>
              <div className="flex gap-5">
                <div className="min-w-0 flex-1">
                  <p className="text-[14px] leading-relaxed">{det.target_population}{det.geography ? <span className="text-muted-foreground"> · {det.geography}</span> : null}</p>
                  {det.demographic_signals?.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {det.demographic_signals.slice(0, 6).map((sg, i) => (
                        <span key={i} className="inline-flex items-center gap-1.5 rounded-full border border-border bg-background pl-2.5 pr-1 py-0.5 text-[12px]" title={`${sg.attribute}${sg.source ? ` — from ${sg.source}` : ""}`}>
                          <span className="text-foreground">{sg.value}</span>
                          <span className="rounded-full bg-foreground/5 px-1.5 py-px text-[10.5px] text-muted-foreground">{/query/i.test(sg.source || "") ? "your question" : sg.source || sg.attribute}</span>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                {typeof det.confidence === "number" && <Ring pct={det.confidence} label="sure" />}
              </div>
              {typeof det.confidence === "number" && det.confidence < 60 && <p className="lite-help mt-3">Under 60% sure — treat the groups below as a best guess.</p>}
            </Fold>
          </Detail>
        )}

        {/* 3 · The groups */}
        <Detail href={studioHref}>
          <Fold title={`The ${segments.length} group${segments.length === 1 ? "" : "s"}`} line={groupsLine}>
            {plan.rationale && <p className="lite-help">{plan.rationale}</p>}
            <Groups segments={segments} countFor={countFor} />
          </Fold>
        </Detail>

        {/* 4 · Matched to published figures (heat grid) */}
        {dims.length > 0 && (
          <Detail href={studioHref}>
            <Fold title="Matched to published figures" line={matchLine}>
              <p className="lite-help">Each row is one thing the mix of people should match. The cells show how far the people sit from the published share — paler is closer.</p>
              <div className="mt-3 space-y-2">
                {dims.map((d, i) => {
                  const t = frame?.targets?.[d.key];
                  const st = standings[i];
                  const rd = reportDims[d.key];
                  const allCells = (rd?.cells || []).filter((cc) => typeof cc.target_pct === "number");
                  // Nobody placed on this scale yet (every cell empty): the heat strip would read as "0%" everywhere, which is not what happened.
                  const unplaced = allCells.length > 0 && allCells.every((cc) => !(cc.achieved_n || 0) && !(cc.achieved_pct || 0) && !(cc.planned_pct || 0));
                  const cells = unplaced ? [] : allCells;
                  const colour = st === "matched" ? GOOD : st === "assumed" ? WARN : NONE;
                  const src = t && st !== "none" ? [t.source, t.year].filter(Boolean).join(", ") : "";
                  return (
                    <div key={d.key} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] sm:grid-cols-[170px_minmax(0,1fr)] gap-x-3 items-center">
                      <div className="min-w-0">
                        <p className="text-[13px] font-medium text-foreground truncate" title={d.why}>{d.label}</p>
                        <p className="text-[11.5px] text-muted-foreground inline-flex items-center gap-1 truncate max-w-full" title={src || t?.note || ""}>
                          <span className="w-2 h-2 rounded-sm shrink-0" style={{ background: colour }} aria-hidden />
                          {st === "matched" ? <Check className="w-3 h-3 shrink-0" style={{ color: GOOD }} /> : st === "assumed" ? <AlertTriangle className="w-3 h-3 shrink-0" style={{ color: WARN }} /> : <Minus className="w-3 h-3 shrink-0" />}
                          <span className="truncate">{standingWord(st, t)}{src ? ` · ${src}` : ""}</span>
                        </p>
                      </div>
                      {cells.length > 0 ? (
                        <div className="flex gap-0.5 h-7" role="img" aria-label={`${d.label}: ${cells.map((cc) => `${cc.label} target ${Math.round(cc.target_pct)}%, people ${cc.achieved_pct == null ? Math.round(cc.planned_pct) : Math.round(cc.achieved_pct)}%`).join("; ")}`}>
                          {cells.map((cc, j) => {
                            const got = cc.achieved_pct == null ? cc.planned_pct : cc.achieved_pct;
                            const gap = Math.abs((got ?? 0) - cc.target_pct);
                            const step = Math.min(HEAT.length - 1, Math.floor(gap / 4)); // 0–4 pts pale … 24+ pts dark
                            return (
                              <div key={j} className="flex-1 rounded-[3px] relative group/cell" style={{ background: HEAT[step] }}
                                title={`${cc.label} · published ${Math.round(cc.target_pct)}% · these people ${Math.round(got ?? 0)}%${cc.thin ? " · too few to trust" : ""}`}>
                                <span className={cn("absolute inset-0 flex items-center justify-center text-[10.5px] tabular-nums", step >= 4 ? "text-white" : "text-foreground/80")}>{Math.round(got ?? 0)}%</span>
                              </div>
                            );
                          })}
                        </div>
                      ) : (
                        <div className="h-7 rounded-[3px] border border-dashed border-border flex items-center px-2 text-[11.5px] text-muted-foreground truncate">{st === "none" ? "not matched" : unplaced ? "the people were not placed on this scale" : "no cells on file"}</div>
                      )}
                    </div>
                  );
                })}
              </div>
              {frame?.report && (
                <div className="mt-4 flex items-center gap-3 flex-wrap">
                  <Meter steps={["none", "poor", "fair", "good"]} value={frame.report.level} label="Overall match" />
                  {frame.report.level === "poor" && <p className="lite-help">The report&apos;s numbers are a rough guide, not a measurement.</p>}
                </div>
              )}
            </Fold>
          </Detail>
        )}

        {/* 5 · What was assumed */}
        {(assumed.length > 0 || gaps.length > 0) && (
          <Detail href={studioHref}>
            <Fold title="What had to be assumed" line={assumedLine}>
              {plan.evidence_coverage && <p className="lite-help">{plan.evidence_coverage}</p>}
              {assumed.length > 0 && (
                <ul className="mt-3 space-y-1.5">
                  {assumed.map((a, i) => (
                    <li key={i} className="flex gap-2 text-[13px] leading-relaxed text-foreground/85">
                      <AlertTriangle className="w-3.5 h-3.5 mt-1 shrink-0" style={{ color: WARN }} aria-hidden />
                      <span>{a}</span>
                    </li>
                  ))}
                </ul>
              )}
              {gaps.length > 0 && (
                <div className="mt-3">
                  <p className="text-[11.5px] uppercase tracking-wide text-muted-foreground">Could not be found</p>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {gaps.map((g, i) => <span key={i} className="rounded-full border border-dashed border-border px-2.5 py-0.5 text-[12px] text-muted-foreground">{g}</span>)}
                  </div>
                </div>
              )}
            </Fold>
          </Detail>
        )}

        {/* 6 · How they talk */}
        {plan.voice && (
          <Detail href={studioHref} className="lg:col-span-2">
            <Fold title="How they talk" line={voiceLine}>
              <div className="md:flex md:items-start md:gap-8">
                <div className="md:w-72 shrink-0">
                  <Scale value={plan.voice.value} left="Like experts" right="Like ordinary people" />
                </div>
                {plan.voice.reason && <p className="mt-3 md:mt-0 text-[13.5px] leading-relaxed text-foreground/85">{plan.voice.reason}</p>}
              </div>
            </Fold>
          </Detail>
        )}
      </div>

      <p className="lite-help mt-4">Everything above is read from the record of this build. <DetailLink href={studioHref} label="See the full plan and its log" /></p>

      <InputDialog kind={openInput} onClose={() => setOpenInput(null)} sessionId={sessionId} question={question} dials={dials} build={build} research={research}
        researchUsed={researchUsed} researchPages={pages} kgSources={kgSources} facts={factRows || []} publisherLabels={labels} />
    </section>
  );
}

// ── The flow: what went in → the engine → what came out ──────────────────────────

type FlowProps = {
  sessionId: string;
  n: number;
  groups: number;
  profileWords: number;
  surveyWords: number;
  added: KgSource[];
  research: { ran: boolean; pages: number; used: boolean; late: boolean; bySource: Record<string, { read: number; on_topic: number }> };
  statistics: { publishers: number; pages: number | null; dims: number; matched: number };
  detected: { who: string; where: string; confidence: number | null } | null;
  assumptions: number;
  log: PopulationLogEntry[];
  status: PopulationBuild["status"];
  segmentsForBar: { id: string; name: string; share: number }[];
  posts: number;
  hasReport: boolean;
  /** Opens the summary dialog for one of the inputs. */
  onOpen: (k: InputKind) => void;
};

type EdgeState = "used" | "late" | "off";
type StepState = "done" | "warn" | "running" | "skipped" | "error";

const EDGE_STYLE: Record<EdgeState, { stroke: string; dash?: string; opacity: number; width: number }> = {
  used: { stroke: "currentColor", opacity: 0.35, width: 1.5 },
  late: { stroke: WARN, dash: "5 4", opacity: 0.9, width: 1.5 },
  off: { stroke: "currentColor", dash: "2 4", opacity: 0.18, width: 1 },
};

function kindWord(k: KgSource["kind"]): string {
  switch (k) {
    case "file": return "file";
    case "text": return "pasted text";
    case "video": return "video";
    case "page": return "web page";
    default: return "item";
  }
}
function plural(n: number, one: string, many = `${one}s`): string { return `${n.toLocaleString()} ${n === 1 ? one : many}`; }

/** The build as a picture: source boxes on the left feed the engine's steps in the middle, which
 *  feed the people, the conversation and the report on the right. Every figure is read from the
 *  record of the build, the research run, the knowledge graph and the session, so the picture
 *  changes with the data — a source that was not used is drawn faint with a dotted line, research
 *  that landed after the plan runs straight to the writing step in amber, a step still running
 *  spins. The connectors are drawn in an SVG over the boxes from their measured positions, so
 *  they follow any width; on a narrow screen the three columns stack and the lines give way to
 *  arrows between them. */
function Flow(p: FlowProps) {
  const uid = useId().replace(/:/g, "");
  const wrap = useRef<HTMLDivElement>(null);
  const nodes = useRef<Record<string, HTMLElement | null>>({});
  const [paths, setPaths] = useState<{ d: string; state: EdgeState; key: string }[]>([]);
  const [wide, setWide] = useState(false);

  // ── The record, read into the picture ──
  const ok = (stage: string) => p.log.some((e) => e.stage === stage && e.level === "ok");
  const any = (stage: string) => p.log.some((e) => e.stage === stage);
  const errAt = (stage: string) => p.log.some((e) => e.stage === stage && e.level === "error");
  const scoped = (() => { for (const e of p.log) { const m = /Knowledge scoped: (\d+) units/.exec(e.message || ""); if (m) return Number(m[1]); } return null; })();
  const running = (stages: string[]) => stages.includes(p.status);
  const stepState = (stage: string, run: string[], present: boolean, warn = false): StepState =>
    errAt(stage) ? "error" : running(run) ? "running" : !present ? "skipped" : warn ? "warn" : "done";

  const addedChunks = p.added.reduce((k, a) => k + a.chunks, 0);
  const researchState: EdgeState = p.research.used ? "used" : p.research.late ? "late" : "off";
  const statsOn = p.statistics.publishers > 0;
  const steps: { key: string; label: string; figure: string; state: StepState; detail: string }[] = [
    {
      key: "understand", label: "Understand who to ask",
      figure: p.detected ? [p.detected.who, p.detected.confidence != null ? `${Math.round(p.detected.confidence)}% sure` : ""].filter(Boolean).join(" · ") : "not yet",
      state: stepState("detect", ["queued", "detecting"], !!p.detected, p.detected?.confidence != null && p.detected.confidence < 60),
      detail: "Reads the question, your description and survey, what was added and what the research found, and decides who the population is.",
    },
    {
      key: "gather", label: "Gather published figures",
      figure: statsOn ? (p.statistics.dims ? `${p.statistics.matched} of ${p.statistics.dims} matched` : `${plural(p.statistics.publishers, "publisher")} searched`) : "not used",
      state: stepState("gather", ["gathering", "clarifying"], statsOn && (any("gather") || any("frame")), statsOn && p.statistics.dims > 0 && p.statistics.matched === 0),
      detail: "Searches the ticked publishers for base rates about these people and matches the mix to the published shares.",
    },
    {
      key: "plan", label: "Plan the groups",
      figure: `${plural(p.groups, "group")}${p.assumptions ? ` · ${plural(p.assumptions, "assumption")}` : ""}`,
      state: stepState("plan", ["planning", "awaiting_review"], p.groups > 0, p.assumptions > 0),
      detail: "Composes the population as a set of real slices, each sized by evidence where it exists and by general knowledge where it does not.",
    },
    {
      key: "write", label: "Write the people",
      figure: `${plural(p.n, "person", "people")}${scoped != null ? ` · ${plural(scoped, "piece")} of knowledge` : ""}`,
      state: stepState("spawn", ["spawning"], p.n > 0),
      detail: scoped != null ? `Each person is written from what their group can reach: ${scoped} tagged pieces of knowledge from everything on file.` : "Each person is written from the plan and the shared summary of everything on file.",
    },
  ];
  if (any("validate")) steps.push({ key: "check", label: "Check they behave", figure: ok("validate") ? "checked" : "checking", state: stepState("validate", [], ok("validate")), detail: "Each person is tested for knowledge, register, refusal and stability." });

  const sources: { key: InputKind; icon: React.ReactNode; label: string; figure: string; state: EdgeState; to: string; detail: string }[] = [
    { key: "question", icon: <FileText className="w-4 h-4" />, label: "Your question", figure: "read first", state: "used", to: "understand", detail: "The question every step starts from." },
    { key: "profile", icon: <User className="w-4 h-4" />, label: "Your description", figure: p.profileWords ? plural(p.profileWords, "word") : "none given", state: p.profileWords ? "used" : "off", to: "understand", detail: "Who you said the people are." },
    { key: "survey", icon: <Paperclip className="w-4 h-4" />, label: "Your survey", figure: p.surveyWords ? plural(p.surveyWords, "word") : "none given", state: p.surveyWords ? "used" : "off", to: "understand", detail: "The survey or document uploaded with the people." },
    {
      key: "added", icon: <Layers className="w-4 h-4" />, label: "Things you added",
      figure: p.added.length ? `${plural(p.added.length, "item")} · ${plural(addedChunks, "piece")} on file` : "nothing added",
      state: p.added.length ? "used" : "off", to: "understand",
      detail: p.added.length ? p.added.slice(0, 6).map((a) => `${a.name} (${kindWord(a.kind)}, ${plural(a.chunks, "piece")})`).join("; ") : "Files, pasted text, videos and web pages dropped into Add anything.",
    },
    {
      key: "research", icon: <Globe className="w-4 h-4" />, label: "Found online",
      figure: p.research.ran ? (p.research.pages ? `${plural(p.research.pages, "page")}${p.research.late ? " · after the plan" : ""}` : "nothing yet") : "not run",
      state: researchState, to: p.research.late ? "write" : "understand",
      detail: p.research.ran ? Object.entries(p.research.bySource).map(([k, v]) => `${k}: ${v.on_topic} on topic of ${v.read} read`).join("; ") || "The web research run." : "Research the web was switched off.",
    },
    {
      key: "statistics", icon: <Search className="w-4 h-4" />, label: "Published statistics",
      figure: statsOn ? `${plural(p.statistics.publishers, "publisher")}${p.statistics.pages ? ` · ${plural(p.statistics.pages, "page")} with figures` : ""}` : "switched off",
      state: statsOn ? "used" : "off", to: "gather",
      detail: statsOn ? "Base rates searched for among the ticked publishers." : "No publishers were searched.",
    },
  ];

  const outputs: { key: string; icon: React.ReactNode; label: string; figure: string; on: boolean; href: string }[] = [
    { key: "people", icon: <Users className="w-4 h-4" />, label: "The people", figure: `${plural(p.n, "person", "people")} in ${plural(p.groups, "group")}`, on: p.n > 0, href: proLinks.people(p.sessionId) },
    { key: "conversation", icon: <MessageSquare className="w-4 h-4" />, label: "The conversation", figure: p.posts ? plural(p.posts, "post") : "not started", on: p.posts > 0, href: proLinks.debate(p.sessionId) },
    { key: "report", icon: <ScrollText className="w-4 h-4" />, label: "The report", figure: p.hasReport ? "written" : "not yet", on: p.hasReport, href: proLinks.report(p.sessionId) },
  ];

  // ── Connectors, measured from the boxes ──
  const edgeSpec = useMemo(() => {
    const list: { from: string; to: string; state: EdgeState; key: string; kind: "in" | "out" | "down" }[] = [];
    for (const s of sources) list.push({ from: s.key, to: `step:${s.to}`, state: s.state, key: `in:${s.key}`, kind: "in" });
    list.push({ from: "step:write", to: "people", state: p.n > 0 ? "used" : "off", key: "out:people", kind: "out" });
    list.push({ from: "people", to: "conversation", state: p.posts > 0 ? "used" : "off", key: "down:conv", kind: "down" });
    list.push({ from: "conversation", to: "report", state: p.hasReport ? "used" : "off", key: "down:report", kind: "down" });
    return list;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sources.map((s) => `${s.key}:${s.state}:${s.to}`).join(","), p.n, p.posts, p.hasReport]);

  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const measure = () => {
      const isWide = window.matchMedia("(min-width: 768px)").matches;
      setWide(isWide);
      if (!isWide) { setPaths([]); return; }
      const box = el.getBoundingClientRect();
      const engine = nodes.current["engine"]?.getBoundingClientRect();
      const rect = (k: string) => nodes.current[k]?.getBoundingClientRect();
      const out: { d: string; state: EdgeState; key: string }[] = [];
      for (const e of edgeSpec) {
        const a = rect(e.from), b = rect(e.to);
        if (!a || !b) continue;
        let x1: number, y1: number, x2: number, y2: number;
        if (e.kind === "in") {
          x1 = a.right - box.left; y1 = a.top + a.height / 2 - box.top;
          x2 = (engine ? engine.left : b.left) - box.left; y2 = b.top + b.height / 2 - box.top;
        } else if (e.kind === "out") {
          x1 = (engine ? engine.right : a.right) - box.left; y1 = a.top + a.height / 2 - box.top;
          x2 = b.left - box.left; y2 = b.top + b.height / 2 - box.top;
        } else {
          x1 = a.left + a.width / 2 - box.left; y1 = a.bottom - box.top;
          x2 = b.left + b.width / 2 - box.left; y2 = b.top - box.top;
          out.push({ d: `M${x1},${y1} L${x2},${y2 - 1}`, state: e.state, key: e.key });
          continue;
        }
        const dx = Math.max(24, (x2 - x1) / 2);
        out.push({ d: `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2 - 1},${y2}`, state: e.state, key: e.key });
      }
      setPaths(out);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    window.addEventListener("resize", measure);
    return () => { ro.disconnect(); window.removeEventListener("resize", measure); };
  }, [edgeSpec, steps.length]);

  const reg = (k: string) => (el: HTMLElement | null) => { nodes.current[k] = el; };
  const total = p.segmentsForBar.reduce((k, s) => k + s.share, 0) || 100;

  return (
    <div ref={wrap} className="relative mt-4">
      {wide && (
        <svg className="absolute inset-0 w-full h-full pointer-events-none text-foreground" aria-hidden>
          <defs>
            {(["used", "late", "off"] as EdgeState[]).map((st) => (
              <marker key={st} id={`${uid}-${st}`} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0,0.5 L7.5,4 L0,7.5 Z" fill={EDGE_STYLE[st].stroke} fillOpacity={EDGE_STYLE[st].opacity} />
              </marker>
            ))}
          </defs>
          {paths.map((pt) => (
            <path key={pt.key} d={pt.d} fill="none" stroke={EDGE_STYLE[pt.state].stroke} strokeOpacity={EDGE_STYLE[pt.state].opacity} strokeWidth={EDGE_STYLE[pt.state].width} strokeDasharray={EDGE_STYLE[pt.state].dash} strokeLinecap="round" markerEnd={`url(#${uid}-${pt.state})`} />
          ))}
        </svg>
      )}

      <div className="grid gap-y-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)_minmax(0,1fr)] md:gap-x-12 lg:gap-x-16 md:items-center">
        {/* What went in */}
        <div className="flex flex-col gap-2">
          <p className="text-[11.5px] uppercase tracking-wide text-muted-foreground">What went in</p>
          {sources.map((s) => (
            <button key={s.key} type="button" onClick={() => p.onOpen(s.key)} ref={reg(s.key) as any} title={`${s.label} · ${s.figure}. ${s.detail} Opens a summary of this input.`}
              className={cn("group/node w-full text-left rounded-xl border px-3 py-2 flex items-center gap-2.5 transition-colors hover:border-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40",
                s.state === "off" ? "border-dashed border-border/80 bg-transparent opacity-55" : s.state === "late" ? "border-amber-300 bg-amber-50/60" : "border-border bg-background")}>
              <span className={cn("shrink-0", s.state === "off" ? "text-muted-foreground" : "text-foreground")}>{s.icon}</span>
              <span className="min-w-0 flex-1">
                <span className="block text-[12.5px] font-medium leading-tight text-foreground truncate">{s.label}</span>
                <span className={cn("block text-[11.5px] leading-tight truncate tabular-nums", s.state === "late" ? "text-amber-700" : "text-muted-foreground")}>{s.figure}</span>
              </span>
            </button>
          ))}
        </div>

        <div className="md:hidden flex justify-center text-muted-foreground" aria-hidden><ChevronDown className="w-4 h-4" /></div>

        {/* The engine */}
        <div ref={reg("engine") as any} className="rounded-2xl border border-primary/25 bg-primary/[0.04] p-3 sm:p-4 relative">
          <p className="text-[11.5px] uppercase tracking-wide text-primary">The engine · Population Studio</p>
          <ol className="mt-2 space-y-1.5">
            {steps.map((st, i) => (
              <li key={st.key} ref={reg(`step:${st.key}`) as any} title={`${st.label}: ${st.figure}. ${st.detail}`}
                className={cn("rounded-xl border bg-background px-3 py-2 flex items-center gap-2.5", st.state === "skipped" ? "border-dashed border-border/80 opacity-55" : "border-border")}>
                <span className="w-5 h-5 rounded-full bg-foreground/[0.06] text-[11px] font-semibold tabular-nums flex items-center justify-center shrink-0">{i + 1}</span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[12.5px] font-medium leading-tight text-foreground truncate">{st.label}</span>
                  <span className="block text-[11.5px] leading-tight text-muted-foreground truncate tabular-nums">{st.figure}</span>
                </span>
                <StepMark state={st.state} />
              </li>
            ))}
          </ol>
        </div>

        <div className="md:hidden flex justify-center text-muted-foreground" aria-hidden><ChevronDown className="w-4 h-4" /></div>

        {/* What came out */}
        <div className="flex flex-col gap-4">
          <p className="text-[11.5px] uppercase tracking-wide text-muted-foreground -mb-2">What came out</p>
          {outputs.map((o) => (
            <Link key={o.key} href={o.href} ref={reg(o.key) as any} title={`${o.label} · ${o.figure}. Opens the page where it is shown in full.`}
              className={cn("rounded-xl border px-3 py-2 flex items-center gap-2.5 transition-colors hover:border-primary/50", o.on ? "border-border bg-background" : "border-dashed border-border/80 opacity-55")}>
              <span className={cn("shrink-0", o.on ? "text-foreground" : "text-muted-foreground")}>{o.icon}</span>
              <span className="min-w-0 flex-1">
                <span className="block text-[12.5px] font-medium leading-tight text-foreground truncate">{o.label}</span>
                <span className="block text-[11.5px] leading-tight text-muted-foreground truncate tabular-nums">{o.figure}</span>
                {o.key === "people" && p.segmentsForBar.length > 0 && (
                  <span className="mt-1.5 flex h-1.5 gap-[2px] rounded-full overflow-hidden" aria-hidden>
                    {p.segmentsForBar.slice(0, 8).map((sg, i) => <span key={sg.id} style={{ width: `${(sg.share / total) * 100}%`, background: SERIES[i] }} title={`${sg.name} · ${Math.round(sg.share)}%`} />)}
                    {p.segmentsForBar.length > 8 && <span style={{ width: `${(p.segmentsForBar.slice(8).reduce((k, sg) => k + sg.share, 0) / total) * 100}%`, background: OTHER }} />}
                  </span>
                )}
              </span>
            </Link>
          ))}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-muted-foreground">
        <span className="inline-flex items-center gap-1.5"><span className="w-5 h-0 border-t-[1.5px] border-foreground/35" aria-hidden /> used in the plan</span>
        <span className="inline-flex items-center gap-1.5"><span className="w-5 h-0 border-t-[1.5px] border-dashed" style={{ borderColor: WARN }} aria-hidden /> arrived after the plan, given to the people since</span>
        <span className="inline-flex items-center gap-1.5"><span className="w-5 h-0 border-t border-dotted border-foreground/30" aria-hidden /> not used</span>
      </div>
    </div>
  );
}

function StepMark({ state }: { state: StepState }) {
  if (state === "running") return <span className="inline-flex items-center gap-1 text-[11px] text-primary shrink-0"><Loader2 className="w-3.5 h-3.5 animate-spin" /> running</span>;
  if (state === "done") return <span className="inline-flex items-center gap-1 text-[11px] shrink-0" style={{ color: GOOD }}><Check className="w-3.5 h-3.5" /> done</span>;
  if (state === "warn") return <span className="inline-flex items-center gap-1 text-[11px] text-amber-700 shrink-0"><AlertTriangle className="w-3.5 h-3.5" /> with gaps</span>;
  if (state === "error") return <span className="inline-flex items-center gap-1 text-[11px] text-red-700 shrink-0"><AlertTriangle className="w-3.5 h-3.5" /> failed</span>;
  return <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground shrink-0"><Circle className="w-3 h-3" /> skipped</span>;
}

// ── Pieces ─────────────────────────────────────────────────────────────────────

function Head({ title }: { title: string }) {
  return <p className="lite-label">{title}</p>;
}

/** A card folded to its heading and a one-line reading of what is inside; the chevron (or the
 *  heading) opens it, and the line gives way to the content. Closed by default so the page reads
 *  as a list of findings first. The right padding keeps the one-liner clear of the hover pill. */
function Fold({ title, line, children }: { title: string; line?: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className="lite-card p-5 sm:p-6 h-full">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-controls={id} className="w-full flex items-start gap-2.5 text-left pr-24 group/fold">
        <ChevronDown className={cn("w-4 h-4 mt-0.5 shrink-0 text-muted-foreground transition-transform group-hover/fold:text-foreground", open ? "rotate-0" : "-rotate-90")} aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="lite-label block">{title}</span>
          {line && !open && <span className="lite-help block truncate" title={line}>{line}</span>}
        </span>
      </button>
      {open && <div id={id} className="mt-3 pl-[26px]">{children}</div>}
    </div>
  );
}

function Tile({ value, label, dim, tone }: { value: string; label: string; dim?: boolean; tone?: "good" | "warn" }) {
  return (
    <div className={cn("lite-card px-3 py-2.5 text-center", dim && "opacity-60")}>
      <p className={cn("text-[20px] font-semibold tracking-tight tabular-nums leading-none", tone === "good" ? "text-emerald-700" : tone === "warn" ? "text-amber-700" : "text-foreground")}>{value}</p>
      <p className="text-[11px] text-muted-foreground mt-1.5 leading-tight">{label}</p>
    </div>
  );
}

function Clamp({ label, text, className }: { label: string; text: string; className?: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > 180;
  return (
    <div className={className}>
      <p className="text-[11.5px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={cn("text-[13px] leading-relaxed text-foreground/85 mt-1", !open && "line-clamp-2")}>{text}</p>
      {long && <button type="button" onClick={() => setOpen((v) => !v)} className="mt-1 text-[12px] text-muted-foreground hover:text-foreground inline-flex items-center gap-1">{open ? "Less" : "Read it all"} <ChevronDown className={cn("w-3 h-3 transition-transform", open && "rotate-180")} /></button>}
    </div>
  );
}

function Ring({ pct, label }: { pct: number; label: string }) {
  const r = 26, c = 2 * Math.PI * r, p = Math.max(0, Math.min(100, pct));
  return (
    <div className="shrink-0 flex flex-col items-center" title={`How sure the plan was about who this population is: ${Math.round(p)}%`}>
      <svg width="68" height="68" viewBox="0 0 68 68" role="img" aria-label={`${Math.round(p)}% sure`}>
        <circle cx="34" cy="34" r={r} fill="none" stroke="currentColor" strokeOpacity="0.08" strokeWidth="6" />
        <circle cx="34" cy="34" r={r} fill="none" stroke={p < 60 ? WARN : SERIES[0]} strokeWidth="6" strokeLinecap="round" strokeDasharray={`${(p / 100) * c} ${c}`} transform="rotate(-90 34 34)" />
        <text x="34" y="38" textAnchor="middle" className="fill-current" fontSize="15" fontWeight="600">{Math.round(p)}%</text>
      </svg>
      <p className="text-[11px] text-muted-foreground -mt-1">{label}</p>
    </div>
  );
}

function Groups({ segments, countFor }: { segments: PopulationSegment[]; countFor: (s: PopulationSegment) => number }) {
  const [open, setOpen] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  // Up to eight groups keep their own colour; any beyond fold into one grey "Other".
  const rows = useMemo(() => {
    const sorted = segments.slice().sort((a, b) => b.share_pct - a.share_pct);
    const own = sorted.slice(0, 8).map((s, i) => ({ s, colour: SERIES[i], count: countFor(s) }));
    const rest = sorted.slice(8);
    return { own, rest, restShare: rest.reduce((k, s) => k + s.share_pct, 0), restCount: rest.reduce((k, s) => k + countFor(s), 0) };
  }, [segments, countFor]);
  const total = rows.own.reduce((k, r) => k + r.s.share_pct, 0) + rows.restShare || 100;

  return (
    <>
      <div className="mt-3 flex h-3.5 gap-[2px]" role="img" aria-label={rows.own.map((r) => `${r.s.name} ${Math.round(r.s.share_pct)}%`).join(", ")}>
        {rows.own.map((r) => (
          <button key={r.s.id} type="button" className="rounded-[3px] transition-opacity first:rounded-l-full last:rounded-r-full"
            style={{ width: `${(r.s.share_pct / total) * 100}%`, background: r.colour, opacity: hover && hover !== r.s.id ? 0.35 : 1 }}
            title={`${r.s.name} · ${r.count} people · ${Math.round(r.s.share_pct)}%`}
            onMouseEnter={() => setHover(r.s.id)} onMouseLeave={() => setHover(null)} onClick={() => setOpen(open === r.s.id ? null : r.s.id)} aria-label={r.s.name} />
        ))}
        {rows.rest.length > 0 && <span className="rounded-r-full" style={{ width: `${(rows.restShare / total) * 100}%`, background: OTHER }} title={`Other · ${rows.restCount} people · ${Math.round(rows.restShare)}%`} />}
      </div>
      <ul className="mt-3 divide-y divide-border">
        {rows.own.map((r) => {
          const s = r.s, d = s.demographics || {};
          const isOpen = open === s.id;
          const bits = [
            d.age_min && d.age_max ? `ages ${d.age_min}–${d.age_max}` : "",
            d.regions?.length ? list(d.regions, 3) : "",
            d.income_band ? `${d.income_band} income` : "",
            d.occupations?.length ? `e.g. ${list(d.occupations, 2)}` : "",
          ].filter(Boolean).join(" · ");
          return (
            <li key={s.id} className={cn("transition-colors", hover === s.id && "bg-foreground/[0.03]")} onMouseEnter={() => setHover(s.id)} onMouseLeave={() => setHover(null)}>
              <button type="button" onClick={() => setOpen(isOpen ? null : s.id)} className="w-full text-left py-2.5 flex items-start gap-2.5" aria-expanded={isOpen}>
                <span className="w-2.5 h-2.5 rounded-full shrink-0 mt-[5px]" style={{ background: r.colour }} aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline justify-between gap-3">
                    <span className="text-[13.5px] font-medium text-foreground leading-snug">{s.name}</span>
                    <span className="text-[12px] text-muted-foreground tabular-nums shrink-0">{r.count} {r.count === 1 ? "person" : "people"} · {Math.round(s.share_pct)}%</span>
                  </span>
                  <span className="mt-0.5 flex items-center gap-x-2 gap-y-0.5 flex-wrap text-[11.5px] text-muted-foreground">
                    <span>{stanceWords(s.stance)}</span>
                    {s.sentiment?.mood && <><span aria-hidden>·</span><span>{moodWords(s.sentiment.mood)}</span></>}
                    <span aria-hidden>·</span>
                    <span className="inline-flex items-center gap-1" title={s.evidence?.length ? s.evidence[0] : "No published figure — sized from general knowledge"}>
                      {s.evidence?.length ? <><Check className="w-3 h-3" style={{ color: GOOD }} /> published figure</> : <><AlertTriangle className="w-3 h-3" style={{ color: WARN }} /> <span className="text-amber-700">assumed</span></>}
                    </span>
                  </span>
                </span>
                <ChevronDown className={cn("w-3.5 h-3.5 text-muted-foreground shrink-0 mt-1 transition-transform", isOpen && "rotate-180")} />
              </button>
              {isOpen && (
                <div className="pb-3 pl-5 text-[12.5px] leading-relaxed space-y-1 animate-fade-in">
                  {s.description && <p className="text-foreground/85">{s.description}</p>}
                  {bits && <p className="text-muted-foreground">{bits}</p>}
                  <p className={s.evidence?.length ? "text-foreground/85" : "text-amber-700"}>
                    {s.evidence?.length ? <><span className="text-muted-foreground">Based on: </span>{s.evidence[0]}</> : <>Assumed — no published figure{s.rationale ? `: ${s.rationale.charAt(0).toLowerCase()}${s.rationale.slice(1)}` : "."}</>}
                  </p>
                </div>
              )}
            </li>
          );
        })}
        {rows.rest.length > 0 && (
          <li className="py-2 flex items-center gap-2.5 text-[13px]">
            <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: OTHER }} aria-hidden />
            <span className="flex-1 text-muted-foreground truncate">Other · {list(rows.rest.map((s) => s.name), rows.rest.length)}</span>
            <span className="text-[12px] text-muted-foreground tabular-nums">{rows.restCount} · {Math.round(rows.restShare)}%</span>
          </li>
        )}
      </ul>
    </>
  );
}

function Meter({ steps, value, label }: { steps: string[]; value: string; label: string }) {
  const idx = Math.max(0, steps.indexOf(value));
  const colour = value === "good" ? GOOD : value === "fair" ? SERIES[0] : value === "poor" ? WARN : NONE;
  return (
    <div className="inline-flex items-center gap-2.5" title={`${label}: ${value}`}>
      <span className="text-[12px] text-muted-foreground">{label}</span>
      <span className="flex gap-[2px]" aria-hidden>
        {steps.map((s, i) => <span key={s} className="w-6 h-2 rounded-[2px]" style={{ background: i <= idx && value !== "none" ? colour : "rgba(0,0,0,0.07)" }} />)}
      </span>
      <span className="text-[12.5px] font-medium capitalize" style={{ color: value === "none" ? undefined : colour }}>{value}</span>
    </div>
  );
}

function Scale({ value, left, right }: { value: number; left: string; right: string }) {
  const p = Math.max(0, Math.min(100, value));
  return (
    <div className="mt-3" title={`${Math.round(p)} on a 0–100 scale from experts to ordinary people`}>
      <div className="relative h-2 rounded-full bg-foreground/[0.07]">
        <div className="absolute inset-y-0 left-1/2 w-px bg-foreground/15" aria-hidden />
        <div className="absolute -top-1 w-4 h-4 rounded-full border-2 border-card shadow-sm" style={{ left: `calc(${p}% - 8px)`, background: SERIES[0] }} aria-hidden />
      </div>
      <div className="mt-1.5 flex justify-between text-[11.5px] text-muted-foreground">
        <span className="inline-flex items-center gap-1"><BookOpen className="w-3 h-3" /> {left}</span>
        <span className="inline-flex items-center gap-1">{right} <Sparkles className="w-3 h-3" /></span>
      </div>
    </div>
  );
}
