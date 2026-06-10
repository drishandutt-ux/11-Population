"use client";

import { useEffect, useRef } from "react";
import { Agent, Post } from "@/lib/api";
import PostCard from "./PostCard";
import { stanceColor } from "@/lib/utils";
import { MessageSquare, FileText, Loader2, Clock } from "lucide-react";

interface Props {
  posts: Post[];
  agentsMap: Record<string, Agent>;
  sessionStatus?: string;
  pendingSimulation?: boolean;
  onMakeReport?: () => void;
  isGeneratingReport?: boolean;
  agentOpinions?: Record<string, string>;
}


export default function ThreadView({
  posts,
  agentsMap,
  sessionStatus = "created",
  pendingSimulation = false,
  onMakeReport,
  isGeneratingReport = false,
  agentOpinions = {},
}: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [posts.length]);

  const topLevel = posts.filter((p) => !p.parent_id && p.type !== "like" && p.content);
  const repliesFor = (postId: string) =>
    posts.filter((p) => p.parent_id === postId && p.type !== "like" && p.content);

  // Build per-agent opinion: first top-level post content
  const agentList = Object.values(agentsMap);
  const agentFirstPost: Record<string, Post> = {};
  for (const post of topLevel) {
    if (!agentFirstPost[post.agent_id]) {
      agentFirstPost[post.agent_id] = post;
    }
  }

  // At 1000-agent scale, cap the DOM: render the latest top-level posts and
  // prioritise agents who have already posted in the opinions sidebar.
  const MAX_THREAD = 400;
  const MAX_OPINIONS = 150;
  const visibleTop = topLevel.length > MAX_THREAD ? topLevel.slice(-MAX_THREAD) : topLevel;
  const sortedAgents = [...agentList].sort(
    (a, b) => (agentFirstPost[b.id] ? 1 : 0) - (agentFirstPost[a.id] ? 1 : 0)
  );
  const visibleAgents = sortedAgents.slice(0, MAX_OPINIONS);

  function scrollToPost(postId: string) {
    document.getElementById(`post-${postId}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  const hasContent = posts.length > 0;

  return (
    <div className="h-full flex flex-col min-h-0">
      {/* Toolbar */}
      <div className="px-5 py-2.5 border-b border-border/40 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2 text-xs text-muted-foreground/60">
          {hasContent && (
            <>
              <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
              {posts.length} posts
            </>
          )}
        </div>
        {hasContent && onMakeReport && (
          <button
            onClick={onMakeReport}
            disabled={isGeneratingReport}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded border border-primary/35 text-primary hover:bg-primary/8 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isGeneratingReport ? (
              <><Loader2 className="w-3 h-3 animate-spin" />Generating…</>
            ) : (
              <><FileText className="w-3 h-3" />Make Report</>
            )}
          </button>
        )}
      </div>

      {/* Body: thread left + opinions right */}
      <div className="flex-1 flex overflow-hidden min-h-0">
        {/* Thread scroll area */}
        <div className="flex-1 overflow-y-auto min-h-0">
          {!hasContent ? (
            <div className="h-full flex items-center justify-center text-center p-12">
              {pendingSimulation ? (
                <div className="max-w-xs">
                  <div className="w-10 h-10 rounded-lg border border-yellow-500/30 bg-yellow-500/5 flex items-center justify-center mx-auto mb-3">
                    <Clock className="w-4 h-4 text-yellow-400 animate-pulse" />
                  </div>
                  <p className="text-sm font-medium text-foreground/80 mb-1">Waiting for ingestion…</p>
                  <p className="text-xs text-muted-foreground/50">Simulation will start automatically once all content has been processed.</p>
                </div>
              ) : sessionStatus === "simulating" ? (
                <div className="max-w-xs">
                  <div className="flex items-center justify-center gap-1.5 mb-4">
                    {[0, 1, 2, 3, 4].map((i) => (
                      <span
                        key={i}
                        className="w-1.5 h-1.5 rounded-full bg-primary animate-bounce"
                        style={{ animationDelay: `${i * 120}ms`, animationDuration: "900ms" }}
                      />
                    ))}
                  </div>
                  <p className="text-sm font-medium text-foreground/80 mb-1">Agents are thinking…</p>
                  <p className="text-xs text-muted-foreground/50">First posts will appear in a few seconds.</p>
                </div>
              ) : (
                <div>
                  <div className="w-10 h-10 rounded-lg border border-border flex items-center justify-center mx-auto mb-3">
                    <MessageSquare className="w-4 h-4 text-muted-foreground/50" />
                  </div>
                  <p className="text-sm text-muted-foreground/70">No posts yet</p>
                  <p className="text-xs text-muted-foreground/40 mt-1">Start the simulation to see agents debate</p>
                </div>
              )}
            </div>
          ) : (
            <div className="px-5 py-4 max-w-2xl mx-auto">
              {topLevel.length > MAX_THREAD && (
                <p className="text-[11px] text-muted-foreground/60 text-center mb-3">
                  Showing the latest {MAX_THREAD} of {topLevel.length.toLocaleString()} top-level posts.
                </p>
              )}
              {visibleTop.map((post) => (
                <div key={post.id} id={`post-${post.id}`}>
                  <PostCard
                    post={post}
                    agent={agentsMap[post.agent_id]}
                    replies={repliesFor(post.id)}
                    agentsMap={agentsMap}
                  />
                </div>
              ))}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        {/* Agent opinions sidebar */}
        {agentList.length > 0 && (
          <div className="w-72 shrink-0 border-l border-border/40 overflow-y-auto flex flex-col">
            <div className="px-3 pt-3 pb-2 border-b border-border/30 shrink-0">
              <p className="text-[10px] font-semibold text-muted-foreground/50 uppercase tracking-wider">
                Agent Opinions
                {agentList.length > MAX_OPINIONS && (
                  <span className="ml-1 normal-case font-normal text-muted-foreground/40">
                    · top {MAX_OPINIONS} of {agentList.length.toLocaleString()}
                  </span>
                )}
              </p>
            </div>
            <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
              {visibleAgents.map((agent) => {
                const firstPost = agentFirstPost[agent.id];
                // Prefer Claude-generated one-liner verdict; fall back to first-post excerpt
                const verdict = agentOpinions[agent.id] || null;
                const hasPosted = !!firstPost;

                return (
                  <button
                    key={agent.id}
                    onClick={() => firstPost && scrollToPost(firstPost.id)}
                    disabled={!hasPosted}
                    className="w-full text-left p-2.5 rounded-lg border border-border/30 bg-card/30 hover:bg-card/60 hover:border-border/60 transition-all disabled:opacity-40 disabled:cursor-default group"
                  >
                    {/* Agent header */}
                    <div className="flex items-center gap-2 mb-1.5">
                      <div
                        className="w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold text-white shrink-0"
                        style={{ backgroundColor: agent.avatar_color || "#6366f1" }}
                      >
                        {agent.name.charAt(0)}
                      </div>
                      <span className="text-[11px] font-semibold text-foreground/90 truncate flex-1 leading-none">
                        {agent.name}
                      </span>
                      <span className={`text-[9px] px-1 py-0.5 rounded border leading-none shrink-0 ${stanceColor(agent.stance)}`}>
                        {agent.stance}
                      </span>
                    </div>

                    {/* Verdict, placeholder, or "forming" */}
                    {verdict ? (
                      <p className="text-[11px] text-foreground/80 leading-snug font-medium group-hover:text-foreground transition-colors">
                        {verdict}
                      </p>
                    ) : hasPosted ? (
                      <div className="flex items-center gap-1.5">
                        <span className="w-1 h-1 rounded-full bg-primary/40 animate-pulse" />
                        <span className="w-1 h-1 rounded-full bg-primary/40 animate-pulse" style={{ animationDelay: "200ms" }} />
                        <span className="w-1 h-1 rounded-full bg-primary/40 animate-pulse" style={{ animationDelay: "400ms" }} />
                        <span className="text-[10px] text-muted-foreground/50 ml-0.5">summarising…</span>
                      </div>
                    ) : (
                      <div className="flex items-center gap-1.5">
                        <span className="w-1 h-1 rounded-full bg-muted-foreground/30 animate-pulse" />
                        <span className="w-1 h-1 rounded-full bg-muted-foreground/30 animate-pulse" style={{ animationDelay: "200ms" }} />
                        <span className="w-1 h-1 rounded-full bg-muted-foreground/30 animate-pulse" style={{ animationDelay: "400ms" }} />
                        <span className="text-[10px] text-muted-foreground/40 ml-0.5">forming opinion…</span>
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
