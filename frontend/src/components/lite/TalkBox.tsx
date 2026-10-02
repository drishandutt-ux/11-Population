"use client";

/** Talk to a person: a floating chat box over the simple view. Pick who to talk to, hover their
 *  name to see who they are, type. Uses the same 1:1 chat endpoint as the pro portal. */

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, Agent } from "@/lib/api";
import { firstSentence, proLinks, stanceWords } from "@/lib/lite";
import { DetailLink } from "./Detail";
import { cn } from "@/lib/utils";
import { ArrowUp, ChevronDown, Loader2, MessageCircle, X } from "lucide-react";
import PersonaAvatar from "@/components/PersonaAvatar";

type Msg = { role: "user" | "assistant"; content: string };

type Props = {
  sessionId: string;
  agents: Agent[];
  opinions: Record<string, string>;
  open: boolean;
  agentId: string | null;
  onPick: (agentId: string) => void;
  onClose: () => void;
  onOpen: () => void;
  /** Show the floating "Talk to a person" launcher while closed (off when the screen has its own button). */
  launcher?: boolean;
};

const OPENERS = ["What do you really think about this?", "What worries you most?", "What would change your mind?"];

export default function TalkBox({ sessionId, agents, opinions, open, agentId, onPick, onClose, onOpen, launcher = true }: Props) {
  const [history, setHistory] = useState<Record<string, Msg[]>>({});
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [picker, setPicker] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const agent = agents.find((a) => a.id === agentId) || null;
  const msgs = agent ? history[agent.id] || [] : [];

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs.length, open]);
  useEffect(() => { if (open && !agent && agents.length) onPick(agents[0].id); }, [open, agent, agents, onPick]);
  useEffect(() => { if (open) setTimeout(() => inputRef.current?.focus(), 50); }, [open, agentId]);

  async function send(text?: string) {
    const q = (text ?? input).trim();
    if (!q || !agent || loading) return;
    setInput("");
    setHistory((h) => ({ ...h, [agent.id]: [...(h[agent.id] || []), { role: "user", content: q }] }));
    setLoading(true);
    try {
      const r = (await api.agents.chat(agent.id, q)) as { reply: string };
      setHistory((h) => ({ ...h, [agent.id]: [...(h[agent.id] || []), { role: "assistant", content: r.reply }] }));
    } catch (e: any) {
      setHistory((h) => ({ ...h, [agent.id]: [...(h[agent.id] || []), { role: "assistant", content: `Sorry — that didn't go through. ${e?.message || ""}`.trim() }] }));
    } finally {
      setLoading(false);
    }
  }

  if (!agents.length) return null;

  if (!open) {
    if (!launcher) return null;
    return (
      <button type="button" onClick={onOpen} className="fixed bottom-5 right-5 z-40 lite-btn h-12 px-5 shadow-xl" title="Talk to one of the people">
        <MessageCircle className="w-4 h-4" /> Talk to a person
      </button>
    );
  }

  return (
    <div className="fixed bottom-5 right-5 z-40 w-[min(400px,calc(100vw-2.5rem))] h-[min(560px,calc(100vh-6rem))] lite-float flex flex-col overflow-hidden">
      {/* Who */}
      <div className="px-4 pt-3.5 pb-3 flex items-center gap-3 border-b border-border">
        {agent && (
          <>
            <Avatar agent={agent} size={36} />
            <div className="min-w-0 flex-1">
              <PersonaName agent={agent} sessionId={sessionId} verdict={opinions[agent.id] || agent.verdict || ""} />
              <p className="text-[12px] text-muted-foreground truncate">{agent.role}</p>
            </div>
          </>
        )}
        <button type="button" onClick={() => setPicker((p) => !p)} className="lite-pill h-8 px-2.5 shrink-0" title="Talk to someone else">
          Change <ChevronDown className={cn("w-3.5 h-3.5 transition-transform", picker && "rotate-180")} />
        </button>
        <button type="button" onClick={onClose} className="w-8 h-8 rounded-full inline-flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-foreground/5 shrink-0" title="Close">
          <X className="w-4 h-4" />
        </button>
      </div>

      {picker ? (
        <div className="flex-1 overflow-y-auto p-2">
          {agents.map((a) => (
            <button key={a.id} type="button" onClick={() => { onPick(a.id); setPicker(false); }}
              className={cn("w-full text-left flex items-center gap-3 px-2.5 py-2 rounded-xl hover:bg-foreground/5 transition-colors", a.id === agentId && "bg-foreground/5")}>
              <Avatar agent={a} size={30} />
              <div className="min-w-0 flex-1">
                <p className="text-[13px] font-medium text-foreground truncate">{a.name} <span className="text-muted-foreground font-normal">· {a.age}</span></p>
                <p className="text-[12px] text-muted-foreground truncate">{opinions[a.id] || a.verdict || a.role}</p>
              </div>
            </button>
          ))}
        </div>
      ) : (
        <>
          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
            {msgs.length === 0 && agent && (
              <div className="pt-4">
                <p className="text-[13px] text-muted-foreground text-center leading-relaxed">
                  You&apos;re talking to <span className="text-foreground font-medium">{agent.name}</span>. They answer as themselves — hover their name to see who they are.
                </p>
                <div className="flex flex-wrap gap-1.5 justify-center mt-4">
                  {OPENERS.map((q) => (
                    <button key={q} type="button" onClick={() => send(q)} className="lite-pill hover:border-primary/40 hover:text-primary transition-colors">{q}</button>
                  ))}
                </div>
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
                <div className={cn("max-w-[85%] px-3.5 py-2.5 text-[13.5px] leading-relaxed whitespace-pre-wrap",
                  m.role === "user" ? "rounded-2xl rounded-br-md bg-foreground text-background" : "rounded-2xl rounded-bl-md bg-foreground/5 text-foreground")}>
                  {m.content}
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex justify-start"><div className="rounded-2xl rounded-bl-md bg-foreground/5 px-3.5 py-3 lite-dots flex gap-1"><span /><span /><span /></div></div>
            )}
            <div ref={bottomRef} />
          </div>
          <form onSubmit={(e) => { e.preventDefault(); send(); }} className="p-3 border-t border-border">
            <div className="flex items-end gap-2 rounded-2xl border border-border bg-background px-3 py-2 focus-within:border-primary/50 focus-within:ring-2 focus-within:ring-primary/20 transition-all">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                rows={1}
                placeholder={agent ? `Ask ${agent.name.split(" ")[0]} anything…` : "Ask anything…"}
                className="lite-input text-[14px] max-h-28 leading-relaxed py-1"
              />
              <button type="submit" disabled={!input.trim() || loading} className="w-8 h-8 rounded-full bg-foreground text-background inline-flex items-center justify-center shrink-0 disabled:opacity-30 transition-opacity" title="Send">
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowUp className="w-4 h-4" />}
              </button>
            </div>
          </form>
        </>
      )}
    </div>
  );
}

export function Avatar({ agent, size = 28 }: { agent: Agent; size?: number }) {
  return <PersonaAvatar agent={agent} size={size} className="shrink-0" />;
}

/** The person's name; hovering it shows who they are, with a way into their full page. The card
 *  is portalled to the body at a fixed position so no scroll container or layer can sit over it. */
export function PersonaName({ agent, sessionId, verdict, className }: { agent: Agent; sessionId: string; verdict?: string; className?: string }) {
  const place = agent.demographics?.region || "";
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const nameRef = useRef<HTMLSpanElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const enter = () => {
    if (timer.current) clearTimeout(timer.current);
    const r = nameRef.current?.getBoundingClientRect();
    if (!r) return;
    const width = 288;
    const left = Math.max(8, Math.min(r.left, window.innerWidth - width - 8));
    setPos({ left, top: r.bottom + 8 });
  };
  const leave = () => { timer.current = setTimeout(() => setPos(null), 220); };
  return (
    <span className={cn("relative inline-block max-w-full", className)} onMouseEnter={enter} onMouseLeave={leave}>
      <span ref={nameRef} tabIndex={0} onFocus={enter} onBlur={leave} className="text-[14px] font-semibold text-foreground truncate cursor-help border-b border-dotted border-muted-foreground/40 focus:outline-none">{agent.name}</span>
      {pos && typeof document !== "undefined" && createPortal(
        <div className="lite fixed w-72 lite-float bg-card p-4 z-[100]" style={{ left: pos.left, top: pos.top }} onMouseEnter={enter} onMouseLeave={leave}>
          <div className="flex items-center gap-3">
            <Avatar agent={agent} size={40} />
            <div className="min-w-0">
              <p className="text-[14px] font-semibold text-foreground truncate">{agent.name}, {agent.age}</p>
              <p className="text-[12px] text-muted-foreground truncate">{agent.role}{place ? ` · ${place}` : ""}</p>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <span className="chip">{stanceWords(agent.stance)}</span>
            {agent.segment && <span className="chip">{agent.segment}</span>}
          </div>
          {verdict && <p className="mt-3 text-[13px] text-foreground leading-relaxed">“{verdict}”</p>}
          {agent.background && <p className="mt-2 text-[12.5px] text-muted-foreground leading-relaxed">{firstSentence(agent.background, 180)}</p>}
          <div className="mt-3"><DetailLink href={proLinks.person(sessionId, agent.id)} label="See in detail" /></div>
        </div>,
        document.body,
      )}
    </span>
  );
}
