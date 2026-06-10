"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { api, Session } from "@/lib/api";
import { ArrowRight, Clock, Users, Plus, Trash2, Loader2, FlaskConical, TrendingUp, Brain, Lightbulb, AlertTriangle } from "lucide-react";

export default function HomePage() {
  const router = useRouter();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [title, setTitle] = useState("");
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    api.sessions.list().then((s) => setSessions(s as Session[])).catch(() => {});
  }, []);

  async function handleDelete(id: string) {
    setDeletingId(id);
    try {
      await api.sessions.delete(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      setConfirmDeleteId(null);
    } catch (e) {
      console.error(e);
    } finally {
      setDeletingId(null);
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !query.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      const session = await api.sessions.create(title.trim(), query.trim()) as Session;
      router.push(`/session/${session.id}`);
    } catch (err: any) {
      console.error(err);
      setCreateError(err?.message || "Failed to create session — is the backend online?");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="h-screen bg-background flex flex-col overflow-hidden">

      {/* ── Header ── */}
      <header className="px-8 py-3.5 flex items-center justify-between border-b border-border/50 shrink-0">
        <div className="flex items-center">
          <span className="text-base font-semibold text-foreground tracking-tight">11 Minds Population</span>
        </div>
        <span className="text-xs text-muted-foreground">Multi-agent simulation</span>
      </header>

      {/* ── Body: two columns ── */}
      <div className="flex-1 flex overflow-hidden">

        {/* Left — Hero */}
        <div className="flex-1 flex flex-col px-12 py-8 border-r border-border/40 overflow-hidden">
          <div className="shrink-0">
            <p className="text-[10px] text-primary uppercase tracking-widest mb-4 font-semibold">
              Multi-Agent Simulation Platform
            </p>
            <h1 className="text-4xl font-semibold text-foreground leading-tight mb-4">
              Simulate how real people<br />
              <span className="text-primary">think, react, and decide</span>
            </h1>
            <p className="text-muted-foreground text-sm leading-relaxed max-w-md mb-7">
              Spawn a diverse population of AI agents with distinct backgrounds, biases, and expertise.
              Feed them any context — watch them debate, challenge, and converge. Get a structured report
              grounded in real simulated discourse.
            </p>

            {/* Use-case grid */}
            <div className="grid grid-cols-2 gap-2.5 max-w-md">
              {[
                { icon: <FlaskConical className="w-3.5 h-3.5" />, label: "Product testing",         detail: "Will real users adopt this?" },
                { icon: <TrendingUp  className="w-3.5 h-3.5" />, label: "Market & stock signals",  detail: "Predict sentiment before it moves" },
                { icon: <Brain       className="w-3.5 h-3.5" />, label: "Behavioural prediction",  detail: "Model how populations respond" },
                { icon: <Lightbulb  className="w-3.5 h-3.5" />, label: "Strategy stress-testing", detail: "Find the flaws before launch" },
              ].map(({ icon, label, detail }) => (
                <div
                  key={label}
                  className="flex items-start gap-2.5 border border-border/50 rounded-lg px-3.5 py-3 bg-muted/15"
                >
                  <span className="text-primary mt-0.5 shrink-0">{icon}</span>
                  <div>
                    <p className="text-xs font-medium text-foreground">{label}</p>
                    <p className="text-[11px] text-muted-foreground/60 mt-0.5">{detail}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Illustration — edges feathered so it melts into the background */}
          <div className="relative mt-6 flex-1 min-h-[160px] overflow-hidden">
            <img
              src="/minds-network.png"
              alt="A diverse population of AI minds reasoning through a shared neural network"
              className="absolute inset-0 w-full h-full object-cover object-center"
              style={{
                maskImage:
                  "linear-gradient(to right, transparent 0%, #000 13%, #000 87%, transparent 100%), linear-gradient(to bottom, transparent 0%, #000 11%, #000 85%, transparent 100%)",
                WebkitMaskImage:
                  "linear-gradient(to right, transparent 0%, #000 13%, #000 87%, transparent 100%), linear-gradient(to bottom, transparent 0%, #000 11%, #000 85%, transparent 100%)",
                maskComposite: "intersect",
                WebkitMaskComposite: "source-in",
              }}
            />
          </div>
        </div>

        {/* Right — Form + sessions */}
        <div className="w-[420px] shrink-0 flex flex-col px-8 py-8 overflow-y-auto">

          {/* No-persistence notice */}
          <div className="border border-amber-500/25 bg-amber-500/10 rounded-lg px-4 py-3 mb-5 shrink-0 flex items-start gap-2.5">
            <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
            <div>
              <p className="text-xs font-semibold text-amber-200">No database — sessions aren&apos;t saved</p>
              <p className="text-[11px] text-amber-100/70 mt-0.5 leading-relaxed">
                This demo has no persistent storage. A restart or redeploy wipes everything, so older
                sessions can disappear or return &quot;Session not found&quot;. Treat each session as
                temporary and finish it in one sitting.
              </p>
            </div>
          </div>

          {/* New session form */}
          <div className="border border-border rounded-lg p-5 bg-card/30 shrink-0">
            <h2 className="text-sm font-medium text-foreground mb-4 flex items-center gap-2">
              <Plus className="w-3.5 h-3.5 text-primary" />
              New session
            </h2>
            <form onSubmit={handleCreate} className="space-y-3.5">
              <div>
                <label className="block text-[10px] text-muted-foreground mb-1.5 uppercase tracking-wide">Title</label>
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="e.g. AI startup idea validation"
                  className="w-full bg-muted/50 border border-border rounded-md px-3 py-2 text-foreground placeholder-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/60 focus:border-primary/40 text-sm"
                />
              </div>
              <div>
                <label className="block text-[10px] text-muted-foreground mb-1.5 uppercase tracking-wide">Query / hypothesis</label>
                <textarea
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="e.g. 'Would Gen Z adopt a subscription model for home-cooked meal kits?' or 'How will retail investors react to a Fed rate cut?'"
                  rows={4}
                  className="w-full bg-muted/50 border border-border rounded-md px-3 py-2 text-foreground placeholder-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/60 focus:border-primary/40 text-sm resize-none"
                />
              </div>
              <button
                type="submit"
                disabled={creating || !title.trim() || !query.trim()}
                className="w-full bg-primary hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed text-primary-foreground font-medium py-2.5 rounded-md flex items-center justify-center gap-2 text-sm transition-colors"
              >
                {creating ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Creating…</> : <>Create session <ArrowRight className="w-3.5 h-3.5" /></>}
              </button>
              {createError && (
                <p className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2 mt-1">
                  {createError}
                </p>
              )}
            </form>
          </div>

          {/* Recent sessions */}
          {sessions.length > 0 && (
            <div className="mt-6 flex-1 min-h-0 flex flex-col">
              <p className="text-[10px] text-muted-foreground uppercase tracking-widest mb-3 shrink-0">Recent sessions</p>
              <div className="space-y-1.5 overflow-y-auto flex-1">
                {sessions.map((s) => {
                  const isConfirming = confirmDeleteId === s.id;
                  const isDeleting = deletingId === s.id;
                  return (
                    <div
                      key={s.id}
                      className={`w-full border rounded-md px-3.5 py-3 text-left transition-all group cursor-pointer ${
                        isConfirming
                          ? "border-red-500/40 bg-red-500/5"
                          : "border-border/60 hover:border-primary/30 hover:bg-muted/30"
                      }`}
                      onClick={() => { if (!isConfirming) router.push(`/session/${s.id}`); }}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-0.5">
                            <span className="font-medium text-foreground text-xs truncate">{s.title}</span>
                            <StatusDot status={s.status} />
                          </div>
                          <p className="text-[11px] text-muted-foreground truncate">{s.query}</p>
                        </div>
                        <div className="flex items-center gap-2 shrink-0" onClick={(e) => e.stopPropagation()}>
                          {isConfirming ? (
                            <>
                              <span className="text-xs text-red-400 font-medium">Delete?</span>
                              <button
                                onClick={() => handleDelete(s.id)}
                                disabled={isDeleting}
                                className="flex items-center gap-1 text-xs bg-red-500/20 hover:bg-red-500/30 border border-red-500/40 text-red-400 px-2 py-0.5 rounded transition-colors disabled:opacity-50"
                              >
                                {isDeleting ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                                Yes
                              </button>
                              <button
                                onClick={() => setConfirmDeleteId(null)}
                                className="text-xs text-muted-foreground hover:text-foreground px-2 py-0.5 rounded border border-border/50 hover:border-border transition-colors"
                              >
                                No
                              </button>
                            </>
                          ) : (
                            <>
                              <div className="flex items-center gap-2.5 text-xs text-muted-foreground">
                                {s.agent_count > 0 && (
                                  <span className="flex items-center gap-1">
                                    <Users className="w-3 h-3" />{s.agent_count}
                                  </span>
                                )}
                                <span className="flex items-center gap-1">
                                  <Clock className="w-3 h-3" />
                                  {new Date(s.created_at).toLocaleDateString()}
                                </span>
                              </div>
                              <button
                                onClick={() => setConfirmDeleteId(s.id)}
                                className="opacity-0 group-hover:opacity-100 p-1 text-muted-foreground/50 hover:text-red-400 hover:bg-red-500/10 rounded transition-all"
                              >
                                <Trash2 className="w-3 h-3" />
                              </button>
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatusDot({ status }: { status: string }) {
  const colors: Record<string, string> = {
    created: "bg-slate-500",
    ingesting: "bg-yellow-400 animate-pulse",
    ready: "bg-emerald-400",
    simulating: "bg-blue-400 animate-pulse",
    paused: "bg-orange-400",
    complete: "bg-primary",
    error: "bg-red-400",
  };
  const labels: Record<string, string> = {
    created: "created", ingesting: "ingesting", ready: "ready",
    simulating: "simulating", paused: "paused", complete: "complete", error: "error",
  };
  return (
    <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${colors[status] || colors.created}`} />
      {labels[status] || status}
    </span>
  );
}
