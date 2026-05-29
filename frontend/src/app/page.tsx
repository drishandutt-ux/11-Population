"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { api, Session } from "@/lib/api";
import { ArrowRight, Clock, Users, Plus, Trash2, Loader2, FlaskConical, TrendingUp, Brain, Lightbulb } from "lucide-react";

export default function HomePage() {
  const router = useRouter();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [title, setTitle] = useState("");
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
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
    try {
      const session = await api.sessions.create(title.trim(), query.trim()) as Session;
      router.push(`/session/${session.id}`);
    } catch (err) {
      console.error(err);
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Header */}
      <header className="px-8 py-4 flex items-center justify-between border-b border-border/50">
        <div className="flex items-center">
          {/* mix-blend-mode:screen dissolves the dark logo background into the app background */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/logo.png"
            alt="11 Population"
            style={{ mixBlendMode: "screen" }}
            className="h-14 w-auto object-contain select-none"
          />
        </div>
        <span className="text-xs text-muted-foreground">Multi-agent simulation</span>
      </header>

      <div className="flex-1 max-w-2xl mx-auto w-full px-6 py-16">
        {/* Hero */}
        <div className="mb-14">
          <p className="text-xs text-primary uppercase tracking-widest mb-5 font-medium">Multi-Agent Simulation Platform</p>
          <h1 className="text-4xl font-semibold text-foreground leading-tight mb-4">
            Simulate how real people<br />
            <span className="text-primary">think, react, and decide</span>
          </h1>
          <p className="text-muted-foreground text-sm leading-relaxed max-w-lg mb-8">
            Spawn a diverse population of AI agents with distinct backgrounds, biases, and expertise.
            Feed them any context — then watch them debate, challenge, and converge. Get a structured
            report grounded in real simulated discourse.
          </p>

          {/* Use-case chips */}
          <div className="grid grid-cols-2 gap-2.5">
            {[
              { icon: <FlaskConical className="w-3.5 h-3.5" />, label: "Product testing", detail: "Will real users adopt this?" },
              { icon: <TrendingUp className="w-3.5 h-3.5" />,  label: "Market & stock signals", detail: "Predict sentiment before it moves" },
              { icon: <Brain className="w-3.5 h-3.5" />,       label: "Behavioural prediction", detail: "Model how populations respond" },
              { icon: <Lightbulb className="w-3.5 h-3.5" />,   label: "Strategy stress-testing", detail: "Find the flaws before launch" },
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

        {/* Create Session Form */}
        <div className="mb-14">
          <div className="border border-border rounded-lg p-6 bg-card/30">
            <h2 className="text-sm font-medium text-foreground mb-5 flex items-center gap-2">
              <Plus className="w-3.5 h-3.5 text-primary" />
              New session
            </h2>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-xs text-muted-foreground mb-1.5 uppercase tracking-wide">Title</label>
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="e.g. AI startup idea validation"
                  className="w-full bg-muted/50 border border-border rounded-md px-3.5 py-2.5 text-foreground placeholder-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-primary/60 focus:border-primary/40 text-sm"
                />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1.5 uppercase tracking-wide">Query / hypothesis</label>
                <textarea
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="What should the population simulate? e.g. 'Would Gen Z adopt a subscription model for home-cooked meal kits?' or 'How will retail investors react to a Fed rate cut?' or 'Is our B2B pricing strategy competitive?'"
                  rows={4}
                  className="w-full bg-muted/50 border border-border rounded-md px-3.5 py-2.5 text-foreground placeholder-muted-foreground/60 focus:outline-none focus:ring-1 focus:ring-primary/60 focus:border-primary/40 text-sm resize-none"
                />
              </div>
              <button
                type="submit"
                disabled={creating || !title.trim() || !query.trim()}
                className="w-full bg-primary hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed text-primary-foreground font-medium py-2.5 rounded-md flex items-center justify-center gap-2 text-sm transition-colors"
              >
                {creating ? "Creating…" : "Create session"}
                {!creating && <ArrowRight className="w-3.5 h-3.5" />}
              </button>
            </form>
          </div>
        </div>

        {/* Recent Sessions */}
        {sessions.length > 0 && (
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-widest mb-4">Recent sessions</p>
            <div className="space-y-2">
              {sessions.map((s) => {
                const isConfirming = confirmDeleteId === s.id;
                const isDeleting = deletingId === s.id;
                return (
                  <div
                    key={s.id}
                    className={`w-full border rounded-md px-4 py-3.5 text-left transition-all group cursor-pointer ${
                      isConfirming
                        ? "border-red-500/40 bg-red-500/5"
                        : "border-border/60 hover:border-primary/30 hover:bg-muted/30"
                    }`}
                    onClick={() => {
                      if (!isConfirming) router.push(`/session/${s.id}`);
                    }}
                  >
                    <div className="flex items-center justify-between gap-3">
                      {/* Left: title + query */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2.5 mb-0.5">
                          <span className="font-medium text-foreground text-sm truncate">{s.title}</span>
                          <StatusDot status={s.status} />
                        </div>
                        <p className="text-xs text-muted-foreground truncate">{s.query}</p>
                      </div>

                      {/* Right: meta / confirm delete */}
                      <div className="flex items-center gap-2 shrink-0" onClick={(e) => e.stopPropagation()}>
                        {isConfirming ? (
                          <>
                            <span className="text-xs text-red-400 font-medium">Delete?</span>
                            <button
                              onClick={() => handleDelete(s.id)}
                              disabled={isDeleting}
                              className="flex items-center gap-1 text-xs bg-red-500/20 hover:bg-red-500/30 border border-red-500/40 text-red-400 px-2.5 py-1 rounded transition-colors disabled:opacity-50"
                            >
                              {isDeleting ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                              Yes, delete
                            </button>
                            <button
                              onClick={() => setConfirmDeleteId(null)}
                              className="text-xs text-muted-foreground hover:text-foreground px-2 py-1 rounded border border-border/50 hover:border-border transition-colors"
                            >
                              Cancel
                            </button>
                          </>
                        ) : (
                          <>
                            <div className="flex items-center gap-3 text-xs text-muted-foreground">
                              {s.agent_count > 0 && (
                                <span className="flex items-center gap-1">
                                  <Users className="w-3 h-3" />
                                  {s.agent_count}
                                </span>
                              )}
                              <span className="flex items-center gap-1">
                                <Clock className="w-3 h-3" />
                                {new Date(s.created_at).toLocaleDateString()}
                              </span>
                            </div>
                            <button
                              onClick={() => setConfirmDeleteId(s.id)}
                              className="opacity-0 group-hover:opacity-100 p-1.5 text-muted-foreground/50 hover:text-red-400 hover:bg-red-500/10 rounded transition-all"
                              title="Delete session"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
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

      <footer className="px-8 py-4 border-t border-border/40 text-center">
        <p className="text-xs text-muted-foreground/50">11 Population &mdash; multi-agent simulation platform</p>
      </footer>
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
    <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${colors[status] || colors.created}`} />
      {labels[status] || status}
    </span>
  );
}
