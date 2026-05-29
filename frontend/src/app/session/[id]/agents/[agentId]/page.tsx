"use client";

import { useState, useEffect, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, Agent } from "@/lib/api";
import { stanceColor } from "@/lib/utils";
import { ArrowLeft, Send, Loader2, Zap } from "lucide-react";

interface Message {
  role: "user" | "assistant";
  content: string;
}

export default function AgentChatPage() {
  const { id, agentId } = useParams<{ id: string; agentId: string }>();
  const router = useRouter();
  const [agent, setAgent] = useState<Agent | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.agents.get(agentId).then((a) => setAgent(a as Agent)).catch(() => {});
  }, [agentId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  async function send() {
    if (!input.trim() || loading) return;
    const q = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: q }]);
    setLoading(true);
    try {
      const result = await api.agents.chat(agentId, q) as { reply: string };
      setMessages((prev) => [...prev, { role: "assistant", content: result.reply }]);
    } catch (e: any) {
      setMessages((prev) => [...prev, { role: "assistant", content: `Error: ${e.message}` }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Header */}
      <header className="border-b border-border px-6 py-4 flex items-center gap-4">
        <button onClick={() => router.push(`/session/${id}`)} className="text-muted-foreground hover:text-foreground">
          <ArrowLeft className="w-5 h-5" />
        </button>
        {agent && (
          <div className="flex items-center gap-3">
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center text-sm font-bold text-white"
              style={{ backgroundColor: agent.avatar_color }}
            >
              {agent.name.charAt(0)}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-semibold text-foreground">{agent.name}</span>
                <span className={`text-xs px-1.5 py-0.5 rounded border ${stanceColor(agent.stance)}`}>
                  {agent.stance}
                </span>
              </div>
              <div className="text-xs text-muted-foreground">{agent.role}</div>
            </div>
          </div>
        )}
        {agent && (
          <div className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
            <Zap className="w-3.5 h-3.5" />
            Energy {Math.round(agent.energy * 100)}%
          </div>
        )}
      </header>

      {/* Agent bio */}
      {agent && (
        <div className="px-6 py-3 bg-muted/30 border-b border-border text-sm text-muted-foreground">
          <span className="font-medium text-foreground">Background: </span>
          {agent.background}
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-3xl mx-auto space-y-4">
          {messages.length === 0 && agent && (
            <div className="text-center pt-8">
              <p className="text-muted-foreground text-sm">
                You&apos;re chatting directly with <span className="text-foreground font-medium">{agent.name}</span>.
                They will respond fully in character based on their background and the simulation context.
              </p>
              <div className="flex flex-wrap gap-2 justify-center mt-6">
                {[
                  `What's your take on this topic?`,
                  `What's your biggest concern?`,
                  `What would you recommend?`,
                  `Did anything surprise you in this debate?`,
                ].map((q) => (
                  <button
                    key={q}
                    onClick={() => { setInput(q); }}
                    className="text-xs glass rounded-full px-3 py-1.5 text-muted-foreground hover:text-foreground transition-colors"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} className={`flex gap-3 ${msg.role === "user" ? "flex-row-reverse" : ""}`}>
              <div className={`w-8 h-8 rounded-xl flex items-center justify-center text-xs font-bold shrink-0 ${
                msg.role === "user"
                  ? "bg-primary/20 text-primary"
                  : ""
              }`}
                style={msg.role === "assistant" && agent ? { backgroundColor: agent.avatar_color } : {}}
              >
                {msg.role === "user" ? "Y" : agent?.name.charAt(0) || "A"}
              </div>
              <div className={`glass rounded-2xl px-4 py-3 max-w-2xl ${
                msg.role === "user" ? "rounded-tr-sm" : "rounded-tl-sm"
              }`}>
                <p className="text-sm text-foreground/90 leading-relaxed whitespace-pre-wrap">{msg.content}</p>
              </div>
            </div>
          ))}

          {loading && (
            <div className="flex gap-3">
              <div
                className="w-8 h-8 rounded-xl flex items-center justify-center text-xs font-bold text-white shrink-0"
                style={{ backgroundColor: agent?.avatar_color || "#6366f1" }}
              >
                {agent?.name.charAt(0) || "A"}
              </div>
              <div className="glass rounded-2xl rounded-tl-sm px-4 py-3">
                <Loader2 className="w-4 h-4 text-muted-foreground animate-spin" />
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-border px-6 py-4">
        <div className="max-w-3xl mx-auto flex gap-3">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
            placeholder={agent ? `Ask ${agent.name.split(" ")[0]} anything...` : "Loading..."}
            disabled={loading || !agent}
            className="flex-1 bg-muted border border-border rounded-xl px-4 py-2.5 text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 text-sm"
          />
          <button
            onClick={send}
            disabled={loading || !input.trim() || !agent}
            className="bg-primary hover:bg-primary/90 disabled:opacity-50 text-primary-foreground px-4 py-2.5 rounded-xl transition-all"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
