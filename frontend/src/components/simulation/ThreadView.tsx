"use client";

import { useEffect, useRef } from "react";
import { Agent, Post } from "@/lib/api";
import PostCard from "./PostCard";
import { MessageSquare, FileText, Loader2, Clock } from "lucide-react";

interface Props {
  posts: Post[];
  agentsMap: Record<string, Agent>;
  sessionStatus?: string;
  pendingSimulation?: boolean;
  onMakeReport?: () => void;
  isGeneratingReport?: boolean;
}

export default function ThreadView({
  posts,
  agentsMap,
  sessionStatus = "created",
  pendingSimulation = false,
  onMakeReport,
  isGeneratingReport = false,
}: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [posts.length]);

  const topLevel = posts.filter((p) => !p.parent_id && p.type !== "like" && p.content);
  const repliesFor = (postId: string) =>
    posts.filter((p) => p.parent_id === postId && p.type !== "like" && p.content);

  return (
    <div className="h-full flex flex-col min-h-0">
      {/* Toolbar */}
      <div className="px-5 py-2.5 border-b border-border/40 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2 text-xs text-muted-foreground/60">
          {posts.length > 0 && (
            <>
              <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
              {posts.length} posts
            </>
          )}
        </div>
        {posts.length > 0 && onMakeReport && (
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

      {/* Thread scroll area */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {posts.length === 0 ? (
          <div className="h-full flex items-center justify-center text-center p-12">
            {pendingSimulation ? (
              /* Waiting for ingestion to finish before simulation starts */
              <div className="max-w-xs">
                <div className="w-10 h-10 rounded-lg border border-yellow-500/30 bg-yellow-500/5 flex items-center justify-center mx-auto mb-3">
                  <Clock className="w-4 h-4 text-yellow-400 animate-pulse" />
                </div>
                <p className="text-sm font-medium text-foreground/80 mb-1">Waiting for ingestion…</p>
                <p className="text-xs text-muted-foreground/50">Simulation will start automatically once all content has been processed.</p>
              </div>
            ) : sessionStatus === "simulating" ? (
              /* Simulation running — first round not done yet */
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
              /* Not started */
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
            {topLevel.map((post) => (
              <PostCard
                key={post.id}
                post={post}
                agent={agentsMap[post.agent_id]}
                replies={repliesFor(post.id)}
                agentsMap={agentsMap}
              />
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>
    </div>
  );
}
