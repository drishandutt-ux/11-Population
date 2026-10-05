"use client";

/** "How these people were made": the simple view's visual reading of the Studio build that wrote
 *  the roster — a strip of highlights, what went in as tiles, who they stand for with a confidence
 *  ring, the groups as a share bar, the sampling frame as a heat grid, what was assumed, and how
 *  they talk as a meter. Nothing here is computed afresh: it is the build's own record (detected
 *  population, plan, frame, log) drawn rather than listed. */

import { useEffect, useMemo, useState } from "react";
import { api, Agent, FrameReportDim, FrameTarget, PopulationBuild, PopulationSegment, QuantSource, ResearchState } from "@/lib/api";
import Detail, { DetailLink } from "@/components/lite/Detail";
import { proLinks, stanceWords } from "@/lib/lite";
import { cn } from "@/lib/utils";
import { AlertTriangle, BookOpen, Check, ChevronDown, FileText, Globe, Minus, Paperclip, Search, Sparkles, User } from "lucide-react";

type Props = {
  sessionId: string;
  question: string;
  build: PopulationBuild | null;
  agents: Agent[];
  research: ResearchState | null;
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

export default function HowMade({ sessionId, question, build, agents, research }: Props) {
  const [labels, setLabels] = useState<Record<string, string>>(PUBLISHER_FALLBACK);
  useEffect(() => {
    api.population.sources().then((r) => {
      const m: Record<string, string> = { ...PUBLISHER_FALLBACK };
      for (const s of (r.sources || []) as QuantSource[]) m[s.key] = s.label;
      setLabels(m);
    }).catch(() => {});
  }, []);

  const n = agents.length;
  const studioHref = proLinks.studio(sessionId);

  // ── A roster written without the Studio ──
  if (!build || !build.plan) {
    const by = { direct: 0, indirect: 0, neutral: 0 } as Record<string, number>;
    for (const a of agents) by[a.stance] = (by[a.stance] || 0) + 1;
    return (
      <section className="max-w-2xl mx-auto px-6 pb-24 animate-rise" style={{ animationDelay: "90ms" }}>
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

  return (
    <section className="max-w-2xl mx-auto px-6 pb-24 animate-rise" style={{ animationDelay: "90ms" }}>
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

      <div className="mt-3 space-y-3">
        {/* 1 · What went in */}
        <Detail href={proLinks.sources(sessionId)}>
          <div className="lite-card p-5 sm:p-6">
            <Head title="What went in" />
            <div className="mt-3 grid grid-cols-2 sm:grid-cols-5 gap-2">
              <Ingredient icon={<FileText className="w-4 h-4" />} label="Your question" value="read" on />
              <Ingredient icon={<User className="w-4 h-4" />} label="Description" value={profile ? `${profile.split(/\s+/).length} words` : "none"} on={!!profile} />
              <Ingredient icon={<Paperclip className="w-4 h-4" />} label="Survey" value={survey ? `${surveyWords.toLocaleString()} words` : "none"} on={!!survey} />
              <Ingredient icon={<Globe className="w-4 h-4" />} label="Online" value={researchUsed ? `${pages} page${pages === 1 ? "" : "s"}` : run && pages > 0 ? "after the plan" : "not used"} on={researchUsed} />
              <Ingredient icon={<Search className="w-4 h-4" />} label="Statistics" value={publishers.length ? `${publishers.length} publishers` : "off"} on={publishers.length > 0} />
            </div>
            {profile && <Clamp className="mt-3" label="Your description" text={profile} />}
            {publishers.length > 0 && (
              <p className="lite-help mt-3">Searched {list(publishers, publishers.length)}.{dims.length ? ` ${matched ? `Figures were found for ${matched} of the ${dims.length} things the people should match.` : `None of the ${dims.length} things the people should match had a published figure.`}` : ""}</p>
            )}
            {run && pages > 0 && !researchUsed && <p className="lite-help mt-2">The web research finished after the people were planned; they have since been given the {pages} page{pages === 1 ? "" : "s"} it found.</p>}
          </div>
        </Detail>

        {/* 2 · Who they stand for */}
        {det && (
          <Detail href={studioHref}>
            <div className="lite-card p-5 sm:p-6">
              <div className="flex gap-5">
                <div className="min-w-0 flex-1">
                  <Head title="Who they stand for" />
                  <p className="mt-3 text-[14px] leading-relaxed">{det.target_population}{det.geography ? <span className="text-muted-foreground"> · {det.geography}</span> : null}</p>
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
            </div>
          </Detail>
        )}

        {/* 3 · The groups */}
        <Detail href={studioHref}>
          <div className="lite-card p-5 sm:p-6">
            <Head title={`The ${segments.length} group${segments.length === 1 ? "" : "s"}`} />
            {plan.rationale && <p className="lite-help mt-1.5">{plan.rationale}</p>}
            <Groups segments={segments} countFor={countFor} />
          </div>
        </Detail>

        {/* 4 · Matched to published figures (heat grid) */}
        {dims.length > 0 && (
          <Detail href={studioHref}>
            <div className="lite-card p-5 sm:p-6">
              <Head title="Matched to published figures" />
              <p className="lite-help mt-1.5">Each row is one thing the mix of people should match. The cells show how far the people sit from the published share — paler is closer.</p>
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
                    <div key={d.key} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] sm:grid-cols-[180px_minmax(0,1fr)] gap-x-3 items-center">
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
            </div>
          </Detail>
        )}

        {/* 5 · What was assumed */}
        {(assumed.length > 0 || gaps.length > 0) && (
          <Detail href={studioHref}>
            <div className="lite-card p-5 sm:p-6">
              <Head title="What had to be assumed" />
              {plan.evidence_coverage && <p className="lite-help mt-1.5">{plan.evidence_coverage}</p>}
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
            </div>
          </Detail>
        )}

        {/* 6 · How they talk */}
        {plan.voice && (
          <Detail href={studioHref}>
            <div className="lite-card p-5 sm:p-6">
              <Head title="How they talk" />
              <Scale value={plan.voice.value} left="Like experts" right="Like ordinary people" />
              {plan.voice.reason && <p className="mt-3 text-[13.5px] leading-relaxed text-foreground/85">{plan.voice.reason}</p>}
            </div>
          </Detail>
        )}
      </div>

      <p className="lite-help mt-4">Everything above is read from the record of this build. <DetailLink href={studioHref} label="See the full plan and its log" /></p>
    </section>
  );
}

// ── Pieces ─────────────────────────────────────────────────────────────────────

function Head({ title }: { title: string }) {
  return <p className="lite-label">{title}</p>;
}

function Tile({ value, label, dim, tone }: { value: string; label: string; dim?: boolean; tone?: "good" | "warn" }) {
  return (
    <div className={cn("lite-card px-3 py-2.5 text-center", dim && "opacity-60")}>
      <p className={cn("text-[20px] font-semibold tracking-tight tabular-nums leading-none", tone === "good" ? "text-emerald-700" : tone === "warn" ? "text-amber-700" : "text-foreground")}>{value}</p>
      <p className="text-[11px] text-muted-foreground mt-1.5 leading-tight">{label}</p>
    </div>
  );
}

function Ingredient({ icon, label, value, on }: { icon: React.ReactNode; label: string; value: string; on: boolean }) {
  return (
    <div className={cn("rounded-xl border px-2.5 py-2.5 flex flex-col items-center text-center gap-1", on ? "border-border bg-background" : "border-dashed border-border/80 opacity-55")} title={`${label}: ${value}`}>
      <span className={cn(on ? "text-foreground" : "text-muted-foreground")}>{icon}</span>
      <p className="text-[12.5px] font-medium text-foreground leading-tight">{label}</p>
      <p className="text-[11.5px] text-muted-foreground leading-tight">{value}</p>
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
