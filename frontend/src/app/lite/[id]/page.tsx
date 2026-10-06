"use client";

/** The simple view of one session. One screen at a time: who to ask → getting ready → the
 *  conversation → (talk to a person · the report · lab tools). Every figure and every control
 *  behind it lives in the pro portal, one "See in detail" away. */

import { Suspense, useEffect, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useLiteSession } from "@/components/lite/useLiteSession";
import LiteShell, { LiteStep } from "@/components/lite/LiteShell";
import Detail, { DetailLink } from "@/components/lite/Detail";
import TalkBox from "@/components/lite/TalkBox";
import ConjureGrid from "@/components/lite/ConjureGrid";
import HowMade from "@/components/lite/HowMade";
import PersonaAvatar from "@/components/PersonaAvatar";
import ThreadView from "@/components/simulation/ThreadView";
import ReportChat from "@/components/report/ReportChat";
import ErrorBoundary from "@/components/ErrorBoundary";
import { LITE_DEFAULTS, proLinks, classifyText, fromFile, ingestDropped, Dropped } from "@/lib/lite";
import { api, Agent, ResearchState } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ArrowRight, Beaker, Check, FileText, Link2, Loader2, MessageCircle, Paperclip, Play, Plus, Search, Square, X } from "lucide-react";

type View = "flow" | "ask" | "people" | "report" | "lab";
const SURVEY_CHAR_LIMIT = 40000;   // matches SURVEY_CHAR_LIMIT in agent_factory.py; the card says when a file was trimmed
const TEXT_LIKE = /\.(txt|csv|tsv|md|json)$/i;

export default function LiteSessionPage() {
  // useSearchParams needs a Suspense boundary for the build's static pass.
  return (
    <Suspense fallback={<div className="lite min-h-screen" />}>
      <LiteSession />
    </Suspense>
  );
}

function LiteSession() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const params = useSearchParams();
  const s = useLiteSession(id);
  const view: View = (params.get("view") as View) || "flow";
  const setView = (v: View) => router.push(v === "flow" ? `/lite/${id}` : `/lite/${id}?view=${v}`);

  const [talkOpen, setTalkOpen] = useState(false);
  const [talkAgent, setTalkAgent] = useState<string | null>(null);
  const talkTo = (a: Agent) => { setTalkAgent(a.id); setTalkOpen(true); };

  const status = s.session?.status || "created";
  const debating = status === "simulating" || status === "paused";
  const finished = status === "complete";
  const hasPosts = s.posts.length > 0;
  // "checking": no roster yet and the latest build has not been looked up — the people form must
  // not appear over a build that is running on the server (a reader who sees the form again
  // assumes the build stopped and presses Run a second time).
  const stage: "checking" | "people" | "progress" | "ready" | "debate" =
    hasPosts || debating || (finished && s.agents.length > 0) ? "debate"
    : s.buildActive || s.spawnProgress ? "progress"
    : s.agents.length > 0 ? "ready"
    : !s.buildLoaded || !s.session ? "checking"
    : "people";
  const step: LiteStep = view === "report" ? "report" : view === "ask" ? "ask" : view === "people" ? "people" : stage === "debate" ? "debate" : "people";
  const title = s.session?.title || "";
  // The step rail is navigation: Ask (the question and what was added), People, the Conversation, the Report.
  const goStep = (st: LiteStep) => setView(st === "ask" ? "ask" : st === "people" ? "people" : st === "report" ? "report" : "flow");
  const shell = { title, onStep: goStep };

  if (s.notFound) {
    return (
      <LiteShell title="Not found">
        <div className="max-w-xl mx-auto pt-20 px-6 text-center">
          <p className="lite-h1">This question is gone.</p>
          <p className="lite-lead mt-3">It no longer exists on the server. Start a new one.</p>
          <button type="button" onClick={() => router.push("/")} className="lite-btn mt-6">Start again</button>
        </div>
      </LiteShell>
    );
  }

  // ── Lab (placeholder) ──
  if (view === "lab") {
    return (
      <LiteShell {...shell} step="debate" proHref={proLinks.lab(id)} backHref={`/lite/${id}`}>
        <div className="max-w-xl mx-auto pt-16 px-6 animate-rise">
          <div className="lite-card p-8 text-center">
            <div className="w-12 h-12 rounded-2xl bg-foreground/5 inline-flex items-center justify-center"><Beaker className="w-5 h-5 text-foreground" /></div>
            <h1 className="text-[24px] font-semibold tracking-tight mt-4">Lab tools are on their way</h1>
            <p className="lite-lead mt-2">Tests you can run on these people — what would move them, what they&apos;d pay, where they get stuck — are coming to the simple view.</p>
            <div className="mt-6 flex items-center justify-center gap-3 flex-wrap">
              <a href={proLinks.lab(id)} className="lite-btn">Open the Lab in the full portal <ArrowRight className="w-4 h-4" /></a>
              <button type="button" onClick={() => setView("flow")} className="lite-btn-soft">Back</button>
            </div>
          </div>
        </div>
      </LiteShell>
    );
  }

  // ── Report ──
  if (view === "report" && s.session) {
    return (
      <LiteShell {...shell} step="report" proHref={proLinks.report(id)} backHref={`/lite/${id}`} layout="app"
        right={<button type="button" onClick={() => setView("flow")} className="lite-pill"><MessageCircle className="w-3.5 h-3.5" /> Conversation</button>}>
        <div className="flex-1 min-h-0 flex flex-col max-w-6xl w-full mx-auto px-3 sm:px-6 pb-4">
          {/* The question the report answers, always in view above it. */}
          <Detail href={proLinks.sources(id)} at="inline" className="mb-3 shrink-0">
            <div className="flex items-baseline gap-3 pr-28">
              <span className="text-[12px] uppercase tracking-wide text-muted-foreground shrink-0">Your question</span>
              <p className="text-[15px] sm:text-[16px] font-medium text-foreground leading-snug line-clamp-2" title={s.session.query}>{s.session.query}</p>
            </div>
          </Detail>
          <div className="flex-1 min-h-0 lite-card overflow-hidden flex flex-col">
            {s.reportError && (
              <p className="m-4 mb-0 text-[13px] text-red-700 bg-red-500/10 rounded-xl px-3.5 py-2.5">{s.reportError}</p>
            )}
            {s.reportNote && (
              <p className="m-4 mb-0 inline-flex items-center gap-2 text-[13px] text-muted-foreground bg-foreground/[0.04] rounded-xl px-3.5 py-2.5"><span className="lite-dots flex gap-1"><span /><span /><span /></span> {s.reportNote}</p>
            )}
            {!s.reportContent && !s.isGeneratingReport ? (
              <div className="flex-1 flex items-center justify-center p-8 text-center">
                <div className="max-w-md animate-rise">
                  <div className="w-12 h-12 rounded-2xl bg-foreground/5 inline-flex items-center justify-center"><FileText className="w-5 h-5" /></div>
                  <h1 className="text-[24px] font-semibold tracking-tight mt-4">Ready to write the report</h1>
                  <p className="lite-lead mt-2">A short, plain answer to your question, with every number counted from what these {s.agents.length} people said.</p>
                  <button type="button" onClick={s.makeReport} className="lite-btn mt-6">Make the report <ArrowRight className="w-4 h-4" /></button>
                </div>
              </div>
            ) : (
              <ErrorBoundary label="The report">
                <ReportChat
                  sessionId={id}
                  query={s.session.query}
                  agents={s.agents}
                  posts={s.posts}
                  reportContent={s.reportContent}
                  records={s.reportRecords}
                  structure={s.reportStructure}
                  isGeneratingReport={s.isGeneratingReport}
                  onMakeReport={s.makeReport}
                  onClearReport={s.clearReport}
                  onGoToLab={() => setView("lab")}
                  initialMessages={s.reportChat}
                />
              </ErrorBoundary>
            )}
          </div>
        </div>
        <TalkBox sessionId={id} agents={s.agents} opinions={s.opinions} open={talkOpen} agentId={talkAgent} onPick={setTalkAgent} onClose={() => setTalkOpen(false)} onOpen={() => setTalkOpen(true)} launcher={false} />
      </LiteShell>
    );
  }

  // ── Ask: the question, and more material for the people ──
  if (view === "ask" && s.session) {
    return (
      <LiteShell {...shell} step="ask" proHref={proLinks.sources(id)}>
        <AskView sessionId={id} question={s.session.query} ingesting={status === "ingesting"} hasPeople={s.agents.length > 0} research={s.research} onResearch={async () => { await api.research.start(id); await s.loadResearch(); }} onNext={() => setView(s.agents.length ? "flow" : "people")} />
      </LiteShell>
    );
  }

  // ── People: who was asked (or getting them ready, or the form) ──
  if (view === "people") {
    if (stage === "checking") {
      return <LiteShell {...shell} step="people" proHref={proLinks.studio(id)}><Checking /></LiteShell>;
    }
    if (stage === "progress") {
      return (
        <LiteShell {...shell} step="people" proHref={proLinks.studio(id)}>
          <Progress buildStatus={s.build?.status || "queued"} startedAt={s.build?.created_at} spawn={s.spawnProgress} agentsSoFar={s.agents.length} error={s.build?.error || s.spawnError} sessionId={id} onRetry={() => router.refresh()} />
        </LiteShell>
      );
    }
    if (s.agents.length > 0) {
      return (
        <LiteShell {...shell} step="people" proHref={proLinks.people(id)}>
          <ReadyCard agents={s.agents} hasDebate={stage === "debate"} sessionId={id} onStart={() => s.startDebate().catch((e) => alert(e?.message || "Could not start"))} onGo={() => setView("flow")} onTalk={(a) => { setView("flow"); talkTo(a); }} />
          <HowMade sessionId={id} question={s.session?.query || ""} build={s.build} agents={s.agents} research={s.research} posts={s.posts.length} hasReport={!!s.reportContent} dials={s.session?.dynamic_dials} />
        </LiteShell>
      );
    }
    return (
      <LiteShell {...shell} step="people" proHref={proLinks.studio(id)}>
        <PeopleForm sessionId={id} question={s.session?.query || ""} researching={!!s.research?.run && ["queued", "running", "stopping", "finalising"].includes(s.research.run.status)} ingesting={status === "ingesting"} onRun={s.runSimulation} />
      </LiteShell>
    );
  }

  // ── The conversation ──
  if (stage === "debate" && s.session) {
    const n = s.posts.filter((p) => p.content && p.type !== "like").length;
    return (
      <LiteShell {...shell} step="debate" proHref={proLinks.debate(id)} layout="app">
        <div className="flex-1 min-h-0 flex flex-col max-w-6xl w-full mx-auto px-3 sm:px-6 pb-4">
          <Detail href={proLinks.debate(id)} className="flex-1 min-h-0 flex flex-col">
            <div className="flex-1 min-h-0 lite-card overflow-hidden flex flex-col">
              <ErrorBoundary label="The conversation">
                <ThreadView
                  posts={s.posts}
                  agentsMap={s.agentsMap}
                  sessionStatus={status}
                  agentOpinions={s.opinions}
                  opinionsStatus={s.opinionsStatus}
                  opinionsError={s.opinionsError}
                  onRefreshOpinions={() => s.loadOpinions()}
                  onTalk={talkTo}
                />
              </ErrorBoundary>
            </div>
          </Detail>
        </div>

        {/* What you can do now */}
        <div className="fixed bottom-5 left-1/2 -translate-x-1/2 z-30 max-w-[calc(100vw-2rem)]">
          {finished ? (
            <div className="lite-float px-2 py-2 flex items-center gap-1.5 animate-rise">
              <button type="button" onClick={() => { setTalkOpen(true); }} className="lite-btn-soft h-11 px-4"><MessageCircle className="w-4 h-4" /> Talk to a person</button>
              <button type="button" onClick={() => { setView("report"); if (!s.reportContent && !s.isGeneratingReport) s.makeReport(); }} className="lite-btn h-11 px-5">
                <FileText className="w-4 h-4" /> {s.reportContent ? "Open the report" : "Make the report"}
              </button>
              <button type="button" onClick={() => setView("lab")} className="lite-btn-soft h-11 px-4"><Beaker className="w-4 h-4" /> Lab tools</button>
            </div>
          ) : (
            <div className="lite-float px-4 h-12 flex items-center gap-3 text-[13.5px]">
              <span className="lite-dots flex gap-1"><span /><span /><span /></span>
              <span className="text-foreground">{status === "paused" ? "Paused" : "They're talking it through"}</span>
              <span className="text-muted-foreground">· {n} message{n === 1 ? "" : "s"}</span>
              {debating && (
                <button type="button" onClick={() => s.stopDebate()} className="ml-1 inline-flex items-center gap-1 text-[12.5px] text-muted-foreground hover:text-foreground" title="Stop here and use what has been said">
                  <Square className="w-3 h-3" /> Stop
                </button>
              )}
            </div>
          )}
        </div>
        <TalkBox sessionId={id} agents={s.agents} opinions={s.opinions} open={talkOpen} agentId={talkAgent} onPick={setTalkAgent} onClose={() => setTalkOpen(false)} onOpen={() => setTalkOpen(true)} launcher={!finished} />
      </LiteShell>
    );
  }

  // ── Still finding out where this question is ──
  if (stage === "checking") {
    return <LiteShell {...shell} step="people" proHref={proLinks.studio(id)}><Checking /></LiteShell>;
  }

  // ── Getting ready ──
  if (stage === "progress") {
    return (
      <LiteShell {...shell} step="people" proHref={proLinks.studio(id)}>
        <Progress buildStatus={s.build?.status || "queued"} startedAt={s.build?.created_at} spawn={s.spawnProgress} agentsSoFar={s.agents.length} error={s.build?.error || s.spawnError} sessionId={id} onRetry={() => router.refresh()} />
      </LiteShell>
    );
  }

  // ── People exist, nobody started the conversation ──
  if (stage === "ready") {
    return (
      <LiteShell {...shell} step="people" proHref={proLinks.people(id)}>
        <ReadyCard agents={s.agents} hasDebate={false} sessionId={id} onStart={() => s.startDebate().catch((e) => alert(e?.message || "Could not start"))} onGo={() => setView("flow")} onTalk={(a) => { setView("flow"); talkTo(a); }} />
        <HowMade sessionId={id} question={s.session?.query || ""} build={s.build} agents={s.agents} research={s.research} posts={s.posts.length} hasReport={!!s.reportContent} dials={s.session?.dynamic_dials} />
      </LiteShell>
    );
  }

  // ── Who should we ask? ──
  return (
    <LiteShell {...shell} step="people" proHref={proLinks.studio(id)}>
      <PeopleForm sessionId={id} question={s.session?.query || ""} researching={!!s.research?.run && ["queued", "running", "stopping", "finalising"].includes(s.research.run.status)} ingesting={status === "ingesting"} onRun={s.runSimulation} />
    </LiteShell>
  );
}

// ── Who should we ask? ─────────────────────────────────────────────────────────

function PeopleForm({ sessionId, question, researching, ingesting, onRun }: { sessionId: string; question: string; researching: boolean; ingesting: boolean; onRun: (profile: string, doc: string) => Promise<void> }) {
  const [profile, setProfile] = useState("");
  const [doc, setDoc] = useState<{ name: string; text: string; asSource?: boolean; totalChars?: number; totalRows?: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleFile(file: File) {
    setError(null);
    if (TEXT_LIKE.test(file.name) || file.type.startsWith("text/")) {
      const text = await file.text();
      const rows = (s: string) => Math.max(0, s.split("\n").length - 1);
      setDoc({ name: file.name, text: text.slice(0, SURVEY_CHAR_LIMIT), totalChars: text.length, totalRows: rows(text) });
    } else {
      // Not plain text (PDF, Word…): read it as a source instead, so nothing is lost.
      try { await api.ingest.document(sessionId, file); setDoc({ name: file.name, text: "", asSource: true }); }
      catch (e: any) { setError(e?.message || "That file could not be read."); }
    }
  }

  async function run(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try { await onRun(profile, doc?.text || ""); }
    catch (err: any) { setError(err?.message || "Could not start. Please try again."); setBusy(false); }
  }

  return (
    <div className="max-w-2xl mx-auto pt-10 sm:pt-14 px-5 sm:px-6 pb-24">
      <p className="text-[13px] text-muted-foreground animate-rise">Your question</p>
      <p className="text-[17px] sm:text-[19px] font-medium text-foreground mt-1 leading-snug animate-rise">{question}</p>
      {(researching || ingesting) && (
        <p className="mt-2 inline-flex items-center gap-2 text-[12.5px] text-muted-foreground animate-fade-in"><span className="lite-dots flex gap-1"><span /><span /><span /></span> Still reading up on it in the background — you can carry on.</p>
      )}

      <h1 className="lite-h1 mt-8 animate-rise" style={{ animationDelay: "60ms" }}>Who should we ask?</h1>
      <form onSubmit={run} className="mt-6 animate-rise" style={{ animationDelay: "120ms" }}>
        <Detail href={proLinks.studio(sessionId)}>
          <div className="lite-card p-5 sm:p-6">
            <label className="lite-label" htmlFor="profile">Describe the people <span className="text-muted-foreground font-normal">(optional)</span></label>
            <p className="lite-help mt-0.5">Who they are, where they live, what matters to them. Leave it empty and we&apos;ll work it out from the question and what we found.</p>
            <textarea id="profile" value={profile} onChange={(e) => setProfile(e.target.value)} rows={3} placeholder="e.g. Parents of under-5s in London, mostly renting, busy, price-aware" className="lite-field mt-3" />

            <div className="mt-5">
              <p className="lite-label">Have a survey? <span className="text-muted-foreground font-normal">(optional)</span></p>
              <p className="lite-help mt-0.5">Drop a spreadsheet or document of real answers and the people will be shaped to match them.</p>
              {doc ? (
                <div className="mt-3 flex items-center gap-3 rounded-2xl border border-border bg-background px-4 py-3">
                  <Paperclip className="w-4 h-4 text-muted-foreground shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="text-[13.5px] font-medium truncate">{doc.name}</p>
                    <p className="text-[12px] text-muted-foreground">{doc.asSource ? "Read as a source — the people will know what's in it." : `${doc.text.length.toLocaleString()} characters will shape the people.`}</p>
                    {!doc.asSource && (doc.totalChars || 0) > doc.text.length && (
                      <p className="text-[12px] text-amber-700">Trimmed to the first {SURVEY_CHAR_LIMIT.toLocaleString()} characters — about {Math.max(0, doc.text.split("\n").length - 1).toLocaleString()} of {(doc.totalRows || 0).toLocaleString()} rows reach the people. Split a larger file, or add it as a source instead.</p>
                    )}
                  </div>
                  <button type="button" onClick={() => setDoc(null)} className="text-muted-foreground hover:text-foreground" title="Remove"><X className="w-4 h-4" /></button>
                </div>
              ) : (
                <button type="button" onClick={() => fileRef.current?.click()}
                  onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
                  onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files?.[0]; if (f) handleFile(f); }}
                  className={cn("mt-3 w-full rounded-2xl border border-dashed px-4 py-5 text-[13.5px] text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors flex items-center justify-center gap-2", drag ? "border-primary bg-primary/5" : "border-border")}>
                  <Paperclip className="w-4 h-4" /> Drop a file here, or click to choose
                </button>
              )}
              <input ref={fileRef} type="file" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); e.currentTarget.value = ""; }} />
            </div>
          </div>
        </Detail>

        <div className="mt-5 flex items-center gap-4 flex-wrap">
          <button type="submit" disabled={busy} className="lite-btn">
            {busy ? <><Loader2 className="w-4 h-4 animate-spin" /> Starting…</> : <><Play className="w-4 h-4" /> Run simulation</>}
          </button>
          <p className="lite-help max-w-sm">We&apos;ll create about {LITE_DEFAULTS.count} people who fit, let them read everything, and start them talking. A few minutes.</p>
        </div>
        {error && <p className="mt-3 text-[13px] text-red-700 bg-red-500/10 rounded-xl px-3.5 py-2.5">{error}</p>}
      </form>
    </div>
  );
}

// ── Getting ready ──────────────────────────────────────────────────────────────

const STEPS = [
  { key: "read", label: "Reading your material", help: "What you added, what we found online, and the published facts about these people." },
  { key: "make", label: "Creating the people", help: "Each one with a life, a place and a point of view that fits the picture." },
  { key: "talk", label: "Starting the conversation", help: "They read the question and begin to talk it through." },
];

/** A quiet screen for the second or two before the latest build is known. */
function Checking() {
  return (
    <div className="max-w-2xl mx-auto pt-16 px-6 pb-16 animate-fade-in">
      <p className="inline-flex items-center gap-2 text-[13.5px] text-muted-foreground"><span className="lite-dots flex gap-1"><span /><span /><span /></span> Checking where this question is…</p>
    </div>
  );
}

function Progress({ buildStatus, startedAt, spawn, agentsSoFar, error, sessionId, onRetry }: { buildStatus: string; startedAt?: string | null; spawn: { current: number; total: number } | null; agentsSoFar: number; error?: string | null; sessionId: string; onRetry: () => void }) {
  const current = buildStatus === "spawning" ? 1 : buildStatus === "complete" ? 2 : 0;
  const failed = buildStatus === "error" || buildStatus === "stopped" || !!error;
  // The clock runs from the build's own start on the server, so leaving and coming back shows
  // the true elapsed time rather than restarting at zero.
  const mounted = useRef(Date.now());
  const [, tick] = useState(0);
  useEffect(() => { const t = setInterval(() => tick((x) => x + 1), 1000); return () => clearInterval(t); }, []);
  const startedMs = startedAt ? Date.parse(/Z$|[+-]\d\d:\d\d$/.test(startedAt) ? startedAt : startedAt + "Z") : NaN;
  const mins = Math.max(0, Math.floor((Date.now() - (Number.isFinite(startedMs) ? startedMs : mounted.current)) / 60000));

  return (
    <div className="max-w-2xl mx-auto pt-10 sm:pt-14 px-6 pb-16 animate-rise">
      <Detail href={proLinks.studio(sessionId)}>
        <div className="lite-card p-7 sm:p-8">
          {!failed && <ConjureGrid className="mb-7" />}
          <h1 className="text-[24px] font-semibold tracking-tight">{failed ? "Something stopped" : "Getting everyone ready"}</h1>
          <p className="lite-lead mt-1.5">{failed ? "The people could not be created this time." : `Usually a few minutes. This runs on the server, so you can open other pages or close the tab and it carries on.${mins >= 1 ? ` Running for ${mins} min.` : ""}`}</p>
          <ol className="mt-6 space-y-4">
            {STEPS.map((st, i) => {
              const done = !failed && i < current;
              const active = !failed && i === current;
              return (
                <li key={st.key} className="flex gap-3.5">
                  <span className={cn("mt-0.5 w-6 h-6 rounded-full inline-flex items-center justify-center shrink-0 text-[11px] font-semibold transition-colors",
                    done ? "bg-primary text-primary-foreground" : active ? "bg-foreground text-background" : "bg-foreground/5 text-muted-foreground")}>
                    {done ? <Check className="w-3.5 h-3.5" /> : active ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : i + 1}
                  </span>
                  <div className="min-w-0">
                    <p className={cn("text-[15px] font-medium", active || done ? "text-foreground" : "text-muted-foreground")}>
                      {st.label}
                      {active && i === 1 && (spawn || agentsSoFar > 0) && <span className="text-muted-foreground font-normal"> · {spawn ? `${spawn.current} of ${spawn.total}` : agentsSoFar}</span>}
                    </p>
                    <p className="lite-help mt-0.5">{st.help}</p>
                  </div>
                </li>
              );
            })}
          </ol>
          {failed && (
            <div className="mt-6 flex items-center gap-3 flex-wrap">
              {error && <p className="w-full text-[12.5px] text-red-700 bg-red-500/10 rounded-xl px-3.5 py-2.5">{error}</p>}
              <button type="button" onClick={onRetry} className="lite-btn-soft lite-btn-sm">Try again</button>
              <DetailLink href={proLinks.studio(sessionId)} label="See what happened in detail" />
            </div>
          )}
        </div>
      </Detail>
    </div>
  );
}

// ── The people who were asked ──────────────────────────────────────────────────

function ReadyCard({ agents, hasDebate, sessionId, onStart, onGo, onTalk }: { agents: Agent[]; hasDebate: boolean; sessionId: string; onStart: () => void; onGo: () => void; onTalk: (a: Agent) => void }) {
  const [showAll, setShowAll] = useState(false);
  const shown = showAll ? agents : agents.slice(0, 16);
  return (
    <div className="max-w-6xl mx-auto pt-12 px-4 sm:px-6 pb-8 animate-rise">
      <Detail href={proLinks.people(sessionId)}>
        <div className="lite-card p-7 sm:p-8">
          <div className="text-center">
            <div className="flex justify-center -space-x-2 mb-5">
              {agents.slice(0, 7).map((a) => (
                <span key={a.id} className="w-9 h-9 rounded-full border-2 border-card overflow-hidden inline-flex"><PersonaAvatar agent={a} size={32} /></span>
              ))}
              {agents.length > 7 && <div className="w-9 h-9 rounded-full border-2 border-card bg-foreground/5 flex items-center justify-center text-[11px] font-semibold">+{agents.length - 7}</div>}
            </div>
            <h1 className="text-[24px] font-semibold tracking-tight">{agents.length} people{hasDebate ? " were asked" : " are ready"}</h1>
            <p className="lite-lead mt-2">{hasDebate ? "Each one answered as themselves. Click a name to talk to them." : "They've read your material. Start the conversation and watch it unfold."}</p>
            {hasDebate ? (
              <button type="button" onClick={onGo} className="lite-btn mt-6"><MessageCircle className="w-4 h-4" /> Go to the conversation</button>
            ) : (
              <button type="button" onClick={onStart} className="lite-btn mt-6"><Play className="w-4 h-4" /> Start the conversation</button>
            )}
          </div>
          <div className="mt-7 border-t border-border pt-5">
            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-1.5">
              {shown.map((a) => (
                <button key={a.id} type="button" onClick={() => onTalk(a)} className="text-left flex items-center gap-3 px-2.5 py-2 rounded-xl hover:bg-foreground/5 transition-colors" title={`Talk to ${a.name}`}>
                  <PersonaAvatar agent={a} size={32} className="shrink-0" />
                  <div className="min-w-0">
                    <p className="text-[13.5px] font-medium text-foreground truncate">{a.name} <span className="text-muted-foreground font-normal">· {a.age}</span></p>
                    <p className="text-[12px] text-muted-foreground truncate">{a.verdict || a.role}</p>
                  </div>
                </button>
              ))}
            </div>
            {agents.length > 16 && (
              <button type="button" onClick={() => setShowAll((v) => !v)} className="mt-3 text-[12.5px] text-muted-foreground hover:text-foreground">{showAll ? "Show fewer" : `Show all ${agents.length}`}</button>
            )}
          </div>
        </div>
      </Detail>
    </div>
  );
}

// ── Ask: the question, and more material ───────────────────────────────────────

function AskView({ sessionId, question, ingesting, hasPeople, research, onResearch, onNext }: { sessionId: string; question: string; ingesting: boolean; hasPeople: boolean; research: ResearchState | null; onResearch: () => Promise<void>; onNext: () => void }) {
  const [addText, setAddText] = useState("");
  const [starting, setStarting] = useState(false);
  const run = research?.run || null;
  const researching = !!run && ["queued", "running", "stopping", "finalising"].includes(run.status);
  const researched = !!run && run.status === "complete";
  const pages = Object.values(research?.counts || {}).reduce((n, c) => n + (c?.on_topic || 0), 0);
  const [added, setAdded] = useState<{ item: Dropped; state: "adding" | "done" | "failed" }[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  async function add(item: Dropped) {
    setAdded((p) => [...p, { item, state: "adding" }]);
    try { await ingestDropped(sessionId, item); setAdded((p) => p.map((x) => (x.item.id === item.id ? { ...x, state: "done" } : x))); }
    catch { setAdded((p) => p.map((x) => (x.item.id === item.id ? { ...x, state: "failed" } : x))); }
  }
  function addFromText() { const d = classifyText(addText); if (d) { add(d); setAddText(""); } }

  return (
    <div className="max-w-2xl mx-auto pt-10 sm:pt-14 px-5 sm:px-6 pb-24">
      <p className="text-[13px] text-muted-foreground animate-rise">Your question</p>
      <Detail href={proLinks.sources(sessionId)}>
        <h1 className="lite-h1 mt-2 animate-rise" style={{ animationDelay: "60ms" }}>{question}</h1>
      </Detail>
      {ingesting && (
        <p className="mt-3 inline-flex items-center gap-2 text-[12.5px] text-muted-foreground animate-fade-in"><span className="lite-dots flex gap-1"><span /><span /><span /></span> Reading what you added…</p>
      )}

      <Detail href={proLinks.sources(sessionId)}>
        <div className="lite-card p-5 sm:p-6 mt-8 animate-rise flex items-center gap-4 flex-wrap" style={{ animationDelay: "90ms" }}>
          <div className="min-w-0 flex-1">
            <p className="lite-label">Research the web</p>
            <p className="lite-help mt-0.5">
              {researching ? "Looking up what people are saying online about your question. 3–5 minutes, in the background."
                : researched ? `Done — ${pages} useful page${pages === 1 ? "" : "s"} found and given to the people.`
                : run ? `Stopped early — ${pages} useful page${pages === 1 ? "" : "s"} kept. Run it again to continue.`
                : "Looks up what people are saying online about your question and gives it to the people. 3–5 minutes."}
            </p>
          </div>
          {researching ? (
            <span className="lite-pill"><span className="lite-dots flex gap-1"><span /><span /><span /></span> Researching</span>
          ) : (
            <button type="button" disabled={starting} onClick={async () => { setStarting(true); try { await onResearch(); } catch (e: any) { alert(e?.message || "Could not start research"); } finally { setStarting(false); } }} className="lite-btn-soft lite-btn-sm">
              {starting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />} {researched || run ? "Research again" : "Start research"}
            </button>
          )}
        </div>
      </Detail>

      <div className="lite-card p-5 sm:p-6 mt-4 animate-rise" style={{ animationDelay: "120ms" }}>
        <p className="lite-label">Add more material</p>
        <p className="lite-help mt-0.5">A file, a web page, a YouTube video or some text. Everything you add is read and remembered{hasPeople ? " — the people know it from now on" : ""}.</p>
        {added.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {added.map(({ item, state }) => (
              <span key={item.id} className={cn("lite-pill max-w-full", state === "failed" && "text-red-700")}>
                {state === "adding" ? <Loader2 className="w-3.5 h-3.5 animate-spin text-muted-foreground" /> : state === "done" ? <Check className="w-3.5 h-3.5 text-primary" /> : <X className="w-3.5 h-3.5" />}
                <span className="truncate max-w-[220px]">{item.label}</span>
              </span>
            ))}
          </div>
        )}
        <div className="mt-3 flex items-center gap-2">
          <div className="flex-1 flex items-center gap-2 rounded-2xl border border-border bg-background px-3 h-11 focus-within:border-primary/50 focus-within:ring-2 focus-within:ring-primary/20 transition-all">
            <Link2 className="w-4 h-4 text-muted-foreground shrink-0" />
            <input value={addText} onChange={(e) => setAddText(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addFromText(); } }}
              onPaste={(e) => { const t = e.clipboardData.getData("text"); if (t && t.length > 300) { e.preventDefault(); const d = classifyText(t); if (d) add(d); } }}
              placeholder="Paste a link or some text, then press Enter" className="lite-input text-[14px]" />
            {addText.trim() && <button type="button" onClick={addFromText} className="w-7 h-7 rounded-full bg-foreground text-background inline-flex items-center justify-center shrink-0" title="Add"><Plus className="w-4 h-4" /></button>}
          </div>
          <button type="button" onClick={() => fileRef.current?.click()} className="lite-btn-soft h-11 px-4 shrink-0" title="Add a file"><Paperclip className="w-4 h-4" /> <span className="hidden sm:inline">File</span></button>
          <input ref={fileRef} type="file" multiple className="hidden" onChange={(e) => { for (const f of Array.from(e.target.files || [])) add(fromFile(f)); e.currentTarget.value = ""; }} />
        </div>
      </div>

      <div className="mt-5">
        <button type="button" onClick={onNext} className="lite-btn-soft">{hasPeople ? "Go to the conversation" : "Who should we ask?"} <ArrowRight className="w-4 h-4" /></button>
      </div>
    </div>
  );
}
