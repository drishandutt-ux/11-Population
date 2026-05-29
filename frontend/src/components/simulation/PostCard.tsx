"use client";

import { Agent, Post } from "@/lib/api";
import { stanceColor } from "@/lib/utils";
import { ThumbsUp, Flame } from "lucide-react";

interface Props {
  post: Post;
  agent: Agent | undefined;
  replies: Post[];
  agentsMap: Record<string, Agent>;
  depth?: number;
}

export default function PostCard({ post, agent, replies, agentsMap, depth = 0 }: Props) {
  if (post.type === "like" || !post.content) return null;

  const isDebate = post.type === "debate";
  const accentColor = agent?.avatar_color || "#6366f1";
  const hasReplies = replies.length > 0;

  return (
    <div className={depth === 0 ? "mt-4" : "mt-2"}>
      <div className="flex gap-3">
        {/* Left column: avatar + connector line */}
        <div className="flex flex-col items-center shrink-0" style={{ width: 24 }}>
          <div
            className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold text-white shrink-0"
            style={{ backgroundColor: accentColor }}
          >
            {agent?.name?.charAt(0) || "?"}
          </div>
          {hasReplies && (
            <div
              className="w-px flex-1 mt-1.5"
              style={{ backgroundColor: `${accentColor}28`, minHeight: 16 }}
            />
          )}
        </div>

        {/* Right column */}
        <div className="flex-1 min-w-0">
          {/* Meta row */}
          <div className="flex items-center gap-2 mb-1.5 flex-wrap" style={{ paddingTop: 2 }}>
            <span className="text-xs font-semibold text-foreground leading-none">
              {agent?.name || "Unknown"}
            </span>
            {agent?.role && (
              <span className="text-[11px] text-muted-foreground/45 truncate max-w-[200px]">
                {agent.role}
              </span>
            )}
            {agent && (
              <span className={`text-[10px] px-1.5 py-0.5 rounded border leading-none ${stanceColor(agent.stance)}`}>
                {agent.stance}
              </span>
            )}
            {isDebate && (
              <span className="flex items-center gap-0.5 text-[10px] text-red-400/80">
                <Flame className="w-2.5 h-2.5" />
                debate
              </span>
            )}
            <span className="text-[10px] text-muted-foreground/25 ml-auto">r{post.round_num}</span>
          </div>

          {/* Message body — rendered markdown */}
          <div
            className="pl-3 border-l"
            style={{ borderLeftColor: isDebate ? "rgba(248,113,113,0.4)" : `${accentColor}38` }}
          >
            <PostContent text={post.content} />
          </div>

          {/* Like count */}
          {post.likes > 0 && (
            <div className="flex items-center gap-1 mt-1.5 text-[10px] text-muted-foreground/30">
              <ThumbsUp className="w-2.5 h-2.5" />
              {post.likes}
            </div>
          )}

          {/* Replies nested inside right column */}
          {replies.map((reply) => (
            <PostCard
              key={reply.id}
              post={reply}
              agent={agentsMap[reply.agent_id]}
              replies={[]}
              agentsMap={agentsMap}
              depth={depth + 1}
            />
          ))}
        </div>
      </div>

      {depth === 0 && <div className="mt-3 border-b border-border/15" />}
    </div>
  );
}

// ── Markdown-aware content renderer ─────────────────────────────────────────

function PostContent({ text }: { text: string }) {
  const segments = parsePostContent(text);

  return (
    <div className="space-y-1.5 text-sm text-foreground/85 leading-relaxed">
      {segments.map((seg, i) => {
        if (seg.type === "paragraph") {
          return (
            <p
              key={i}
              className="leading-relaxed"
              dangerouslySetInnerHTML={{ __html: renderInline(seg.text) }}
            />
          );
        }
        if (seg.type === "bullets") {
          return (
            <ul key={i} className="space-y-0.5 pl-1">
              {seg.items!.map((item, j) => (
                <li key={j} className="flex gap-2">
                  <span className="text-muted-foreground/40 shrink-0 mt-0.5 text-xs">·</span>
                  <span dangerouslySetInnerHTML={{ __html: renderInline(item) }} />
                </li>
              ))}
            </ul>
          );
        }
        if (seg.type === "divider") {
          return <div key={i} className="border-b border-border/20 my-2" />;
        }
        return null;
      })}
    </div>
  );
}

type Segment =
  | { type: "paragraph"; text: string }
  | { type: "bullets"; items: string[] }
  | { type: "divider" };

function parsePostContent(raw: string): Segment[] {
  const lines = raw.split("\n");
  const segments: Segment[] = [];
  let bulletBuffer: string[] = [];
  let paraBuffer: string[] = [];

  function flushBullets() {
    if (bulletBuffer.length > 0) {
      segments.push({ type: "bullets", items: [...bulletBuffer] });
      bulletBuffer = [];
    }
  }

  function flushPara() {
    const text = paraBuffer.join(" ").trim();
    if (text) segments.push({ type: "paragraph", text });
    paraBuffer = [];
  }

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();

    // Horizontal rule
    if (/^-{3,}$/.test(line.trim())) {
      flushBullets();
      flushPara();
      segments.push({ type: "divider" });
      continue;
    }

    // Blank line → paragraph break
    if (!line.trim()) {
      flushBullets();
      flushPara();
      continue;
    }

    // Bullet line (- or • or *)
    if (/^[\-•\*]\s+/.test(line.trim())) {
      flushPara();
      bulletBuffer.push(line.trim().replace(/^[\-•\*]\s+/, ""));
      continue;
    }

    // Numbered list  "1. text"
    if (/^\d+\.\s+/.test(line.trim())) {
      flushPara();
      bulletBuffer.push(line.trim().replace(/^\d+\.\s+/, ""));
      continue;
    }

    // Regular line — accumulate into paragraph
    flushBullets();
    paraBuffer.push(line.trim());
  }

  flushBullets();
  flushPara();

  return segments;
}

/**
 * Render inline markdown:
 *   **bold**  → <strong>
 *   *text*    → plain text (asterisks stripped — conversational style)
 *   `code`    → <code>
 */
function renderInline(text: string): string {
  return text
    // Bold
    .replace(/\*\*(.+?)\*\*/g, "<strong class='text-foreground font-semibold'>$1</strong>")
    // Single-asterisk emphasis → just strip the markers for cleaner look
    .replace(/\*([^*\n]+?)\*/g, "$1")
    // Backtick code
    .replace(/`(.+?)`/g, "<code class='text-primary/80 bg-primary/8 px-1 rounded text-[11px]'>$1</code>")
    // Remaining lone asterisks
    .replace(/\*/g, "");
}
