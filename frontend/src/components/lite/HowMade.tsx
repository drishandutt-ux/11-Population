"use client";

/** "How these people were made": the simple view's plain reading of the Studio build that wrote
 *  the roster — what went in, who the people are, the groups they were split into and what each
 *  rests on, and what had to be assumed. Nothing here is computed afresh: it is the build's own
 *  record (detected population, plan, sampling frame, log) read out in ordinary words. */

import { useEffect, useState } from "react";
import { api, Agent, FrameTarget, PopulationBuild, PopulationSegment, QuantSource, ResearchState } from "@/lib/api";
import Detail, { DetailLink } from "@/components/lite/Detail";
import { proLinks, stanceWords } from "@/lib/lite";
import { cn } from "@/lib/utils";
import { BookOpen, Globe, HelpCircle, MessageSquareQuote, Paperclip, Users } from "lucide-react";

type Props = {
  sessionId: string;
  question: string;
  build: PopulationBuild | null;
  agents: Agent[];
  research: ResearchState | null;
};

const PUBLISHER_FALLBACK: Record<string, string> = {
  ons: "ONS", nomis: "Nomis", govuk: "gov.uk statistics", fca: "FCA Financial Lives", ofcom: "Ofcom",
  moreincommon: "More in Common", opinium: "Opinium", census: "US Census Bureau", pew: "Pew Research", bls: "BLS", gallup: "Gallup",
};

function moodWords(mood: PopulationSegment["sentiment"]["mood"]): string {
  switch (mood) {
    case "for": return "mostly for";
    case "against": return "mostly against";
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

function words(n: number): string { return n.toLocaleString(); }

/** One plain line for a sampling-frame dimension: where its figures came from, or that none were found. */
function frameLine(label: string, t: FrameTarget | undefined): { text: string; assumed: boolean } {
  if (!t || t.status === "skipped" || t.status === "missing") return { text: `${label}: no published figure was found, so the people were not matched on it.`, assumed: false };
  const src = [t.source, t.year].filter(Boolean).join(", ");
  if (t.status === "estimated") return { text: `${label}: no published figure for this place, so a spread was assumed${t.note && /equal/i.test(t.note) ? " (equal shares)" : ""}.`, assumed: true };
  if (t.status === "uploaded") return { text: `${label}: matched to the figures you uploaded${src ? ` (${src})` : ""}.`, assumed: false };
  if (t.status === "proxy") return { text: `${label}: matched to the closest published figures${src ? ` (${src})` : ""}.`, assumed: false };
  return { text: `${label}: matched to published figures${src ? ` (${src})` : ""}.`, assumed: false };
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

  // ── A roster written without the Studio (an older session, or the pro spawn button) ──
  if (!build || !build.plan) {
    const by = { direct: 0, indirect: 0, neutral: 0 } as Record<string, number>;
    for (const a of agents) by[a.stance] = (by[a.stance] || 0) + 1;
    return (
      <section className="max-w-2xl mx-auto px-6 pb-24 animate-rise" style={{ animationDelay: "90ms" }}>
        <h2 className="text-[18px] font-semibold tracking-tight">How these people were made</h2>
        <Detail href={proLinks.people(sessionId)}>
          <div className="lite-card p-5 sm:p-6 mt-3 space-y-3">
            <p className="text-[14px] leading-relaxed">
              These {n} people were written straight from your question and everything that was added, each with a life, a place and a point of view that fits. No separate plan of groups was drawn up first.
            </p>
            <p className="lite-help">
              {by.direct} directly affected · {by.indirect} affected indirectly · {by.neutral} looking on. The full portal shows every detail behind each person.
            </p>
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

  // What went in.
  const profile = (c.profile_query || "").trim();
  const survey = (c.doc_context || "").trim();
  const surveyWords = survey ? survey.split(/\s+/).length : 0;
  const briefMissing = log.some((e) => e.stage === "detect" && /no evidence brief/i.test(e.message));
  const run = research?.run || null;
  const pages = Object.values(research?.counts || {}).reduce((k, v) => k + (v?.on_topic || 0), 0);
  const researchUsed = !briefMissing && !!run && pages > 0;
  const publishers = build.sources?.quant ? (build.sources.quant_sources || []).map((k) => labels[k] || k) : [];
  const segments = plan.segments.filter((s) => s.decision !== "rejected");

  // The sampling frame in plain lines, and which of them had to be assumed.
  const frameLines = (frame?.dimensions || []).map((d) => frameLine(d.label, frame?.targets?.[d.key]));
  const matched = frameLines.filter((l) => !l.assumed && /matched to/.test(l.text)).length;

  // Everything that was assumed, in one list.
  const assumed: string[] = [];
  for (const a of plan.assumptions || []) assumed.push(a);
  for (const l of frameLines) if (l.assumed) assumed.push(l.text);
  const unevidenced = segments.filter((s) => !s.evidence?.length).length;
  if (unevidenced) assumed.push(`${unevidenced} of the ${segments.length} groups ${unevidenced === 1 ? "is" : "are"} sized from general knowledge rather than a published figure (marked "Assumed" above).`);
  const gaps = det?.gaps || [];

  const intro = [
    `${n} people were written from your question`,
    profile ? "your description of them" : "",
    survey ? "your survey" : "",
    researchUsed ? `${pages} useful page${pages === 1 ? "" : "s"} found online` : "",
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
      <p className="lite-lead mt-1">{introText} Split into {segments.length} group{segments.length === 1 ? "" : "s"} so the mix matches the real population as closely as the figures allow.</p>

      <div className="mt-4 space-y-3">
        {/* 1 · What went in */}
        <Detail href={proLinks.sources(sessionId)}>
          <div className="lite-card p-5 sm:p-6">
            <Head icon={<Paperclip className="w-4 h-4" />} title="What went in" />
            <ul className="mt-3 space-y-2 text-[14px] leading-relaxed">
              <Row label="Your question" value={question} />
              {profile && <Row label="Your description" value={profile} />}
              {survey && <Row label="Your survey" value={`${words(surveyWords)} words of real answers shaped who they are.`} />}
              <Row
                label="Found online"
                value={researchUsed ? `${pages} useful page${pages === 1 ? "" : "s"} about your question were read before the people were planned.`
                  : run && pages > 0 ? `The web research finished after the people were planned, so the plan leaned on the question and the statistics. The people have since been given the ${pages} page${pages === 1 ? "" : "s"} it found.`
                  : "No web research was used when the people were planned."}
              />
              {publishers.length > 0 && (
                <Row label="Published statistics" value={`Searched ${list(publishers, publishers.length)}${frameLines.length ? ` for the figures the people should match. ${matched ? `Found figures for ${matched} of ${frameLines.length} things` : `No matching figures were found for the ${frameLines.length} things it looked for`}.` : "."}`} />
              )}
            </ul>
          </div>
        </Detail>

        {/* 2 · Who they are */}
        {det && (
          <Detail href={studioHref}>
            <div className="lite-card p-5 sm:p-6">
              <Head icon={<Users className="w-4 h-4" />} title="Who they stand for" />
              <p className="mt-3 text-[14px] leading-relaxed">{det.target_population}{det.geography ? ` — ${det.geography}` : ""}.</p>
              {det.demographic_signals?.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {det.demographic_signals.slice(0, 5).map((sg, i) => (
                    <li key={i} className="lite-help">
                      <span className="text-foreground">{sg.value}</span>
                      <span className="text-muted-foreground"> · {sg.attribute}{sg.source ? `, from ${/query/i.test(sg.source) ? "your question" : sg.source}` : ""}</span>
                    </li>
                  ))}
                </ul>
              )}
              {typeof det.confidence === "number" && (
                <p className="lite-help mt-3">How sure we were who this population is: <span className="text-foreground font-medium">{Math.round(det.confidence)}%</span>{det.confidence < 60 ? " — treat the groups below as a best guess." : ""}</p>
              )}
            </div>
          </Detail>
        )}

        {/* 3 · The groups */}
        <Detail href={studioHref}>
          <div className="lite-card p-5 sm:p-6">
            <Head icon={<BookOpen className="w-4 h-4" />} title={`The ${segments.length} group${segments.length === 1 ? "" : "s"} they were split into`} />
            {plan.rationale && <p className="lite-help mt-1.5">{plan.rationale}</p>}
            <ol className="mt-3 divide-y divide-border">
              {segments.map((s) => {
                const d = s.demographics || {};
                const bits = [
                  d.age_min && d.age_max ? `ages ${d.age_min}–${d.age_max}` : "",
                  d.regions?.length ? list(d.regions, 3) : "",
                  d.income_band ? `${d.income_band} income` : "",
                  d.occupations?.length ? `e.g. ${list(d.occupations, 2)}` : "",
                ].filter(Boolean).join(" · ");
                const k = countFor(s);
                return (
                  <li key={s.id} className="py-3 first:pt-0 last:pb-0">
                    <div className="flex items-baseline justify-between gap-3">
                      <p className="text-[14px] font-medium text-foreground">{s.name}</p>
                      <p className="text-[12.5px] text-muted-foreground shrink-0">{k} {k === 1 ? "person" : "people"} · {Math.round(s.share_pct)}%</p>
                    </div>
                    {bits && <p className="lite-help mt-0.5">{bits}</p>}
                    <p className="lite-help mt-0.5">{stanceWords(s.stance)}{s.sentiment?.mood ? ` · ${moodWords(s.sentiment.mood)}` : ""}</p>
                    <p className={cn("text-[12.5px] mt-1.5 leading-relaxed", s.evidence?.length ? "text-foreground/80" : "text-amber-700")}>
                      {s.evidence?.length ? <><span className="text-muted-foreground">Based on: </span>{s.evidence[0]}</> : <><span className="font-medium">Assumed</span> — no published figure; sized from general knowledge{s.rationale ? `: ${s.rationale.charAt(0).toLowerCase()}${s.rationale.slice(1)}` : "."}</>}
                    </p>
                  </li>
                );
              })}
            </ol>
          </div>
        </Detail>

        {/* 4 · What the figures matched */}
        {frameLines.length > 0 && (
          <Detail href={studioHref}>
            <div className="lite-card p-5 sm:p-6">
              <Head icon={<Globe className="w-4 h-4" />} title="What the people were matched to" />
              <p className="lite-help mt-1.5">The mix of people was checked against published figures where any could be found.</p>
              <ul className="mt-3 space-y-1.5">
                {frameLines.map((l, i) => (
                  <li key={i} className={cn("text-[13px] leading-relaxed", /matched to/.test(l.text) ? "text-foreground/80" : "text-muted-foreground")}>{l.text}</li>
                ))}
              </ul>
              {frame?.report && frame.report.level !== "none" && (
                <p className="lite-help mt-3">Overall match to the real population: <span className="text-foreground font-medium">{frame.report.level}</span>{frame.report.level === "poor" ? " — the numbers in the report are a rough guide, not a measurement." : ""}</p>
              )}
            </div>
          </Detail>
        )}

        {/* 5 · What was assumed */}
        {(assumed.length > 0 || gaps.length > 0 || plan.evidence_coverage) && (
          <Detail href={studioHref}>
            <div className="lite-card p-5 sm:p-6">
              <Head icon={<HelpCircle className="w-4 h-4" />} title="What had to be assumed" />
              {plan.evidence_coverage && <p className="lite-help mt-1.5">{plan.evidence_coverage}</p>}
              {assumed.length > 0 && (
                <ul className="mt-3 space-y-1.5">
                  {assumed.map((a, i) => <li key={i} className="text-[13px] leading-relaxed text-foreground/80 flex gap-2"><span className="text-amber-600 shrink-0">•</span><span>{a}</span></li>)}
                </ul>
              )}
              {gaps.length > 0 && (
                <p className="lite-help mt-3"><span className="text-foreground">Could not be found: </span>{list(gaps, gaps.length)}.</p>
              )}
            </div>
          </Detail>
        )}

        {/* 6 · How they talk */}
        {plan.voice?.reason && (
          <Detail href={studioHref}>
            <div className="lite-card p-5 sm:p-6">
              <Head icon={<MessageSquareQuote className="w-4 h-4" />} title="How they talk" />
              <p className="mt-3 text-[14px] leading-relaxed">{plan.voice.reason}</p>
              <p className="lite-help mt-1.5">{plan.voice.value <= 35 ? "Mostly like experts arguing from the numbers." : plan.voice.value >= 65 ? "Mostly like ordinary people reacting from their own lives." : "A mix of expert argument and ordinary reaction, as the real population would be."}</p>
            </div>
          </Detail>
        )}
      </div>

      <p className="lite-help mt-4">Every figure above comes from the record of this build. <DetailLink href={studioHref} label="See the full plan and its log" /></p>
    </section>
  );
}

function Head({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-7 h-7 rounded-lg bg-foreground/5 inline-flex items-center justify-center text-foreground">{icon}</span>
      <p className="lite-label">{title}</p>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <li className="flex gap-3">
      <span className="text-muted-foreground shrink-0 w-[132px] sm:w-[150px] text-[13px] pt-0.5">{label}</span>
      <span className="min-w-0 flex-1 text-foreground">{value}</span>
    </li>
  );
}
