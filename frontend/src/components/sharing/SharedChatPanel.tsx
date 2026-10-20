"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, SharedChat, SharedMessage, ShareMember, WSEvent } from "@/lib/api";
import { getSessionWS } from "@/lib/websocket";
import ShareDialog from "./ShareDialog";
import { AtSign, Bot, ChevronDown, ChevronRight, ExternalLink, FileText, Loader2, LogOut, Send, Share2, Users } from "lucide-react";

/** The session's chat (2026-10-20): the owner and the colleagues it was shared with talk to each
 *  other here and ask the report agent with `@report`. Lives as the *Chat* step of the simple
 *  view, the *Chat* tab of the pro session and the `/shared/[id]` page; live over the session's
 *  websocket. While nobody else is in it, it says so and offers to share. */

/** The report's prose carries citation tokens (`[[record:…]]`, `[[twin:…|post:…]]`) that the pro
 *  report renders as chips; here they are dropped, and the markdown markers with them. */
export function cleanReportText(text: string): string {
  return (text || "")
    .replace(/\s*\[\[[^\]]*\]\]/g, "")
    .replace(/\(\s*:\s*/g, "(")
    .replace(/\(\s*\)/g, "")
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/^#+\s*/gm, "")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}

type Props = {
  sessionId: string;
  /** `page` is the `/shared/[id]` page (its own header); `embedded` sits inside a session page and carries a compact bar of its own. */
  variant?: "page" | "embedded";
  /** The embedded bar's *Open session* link is pointless inside the session itself. */
  hideOpen?: boolean;
};

export default function SharedChatPanel({ sessionId, variant = "embedded", hideOpen = false }: Props) {
  const router = useRouter();
  const [chat, setChat] = useState<SharedChat | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [pendingReport, setPendingReport] = useState(false);
  const [showReport, setShowReport] = useState(true);
  const [share, setShare] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const load = useCallback(async () => {
    try {
      setChat(await api.sharing.chat(sessionId));
      setError(null);
    } catch (e: any) {
      setError(e?.message || "This chat is not available to you.");
    }
  }, [sessionId]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const ws = getSessionWS(sessionId);   // connects on creation; shared with the rest of the page
    const off = ws.subscribe((event: WSEvent) => {
      if (event.type === "shared_message") {
        const m = event.message as SharedMessage;
        setChat((prev) => prev && !prev.messages.some((x) => x.id === m.id) ? { ...prev, messages: [...prev.messages, m] } : prev);
        if (m.kind === "report") setPendingReport(false);
      } else if (event.type === "shares_changed") {
        setChat((prev) => prev ? { ...prev, members: event.members as ShareMember[] } : prev);
      }
    });
    return () => { off(); };
  }, [sessionId]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [chat?.messages.length, pendingReport]);

  async function send() {
    const text = draft.trim();
    if (!text || sending) return;
    setSending(true);
    try {
      const r = await api.sharing.send(sessionId, text);
      setChat((prev) => prev && !prev.messages.some((x) => x.id === r.message.id) ? { ...prev, messages: [...prev.messages, r.message] } : prev);
      if (r.report_pending) setPendingReport(true);
      setDraft("");
    } catch (e: any) {
      setError(e?.message || "Could not send.");
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  }

  function askReport() {
    setDraft((d) => (/@report\b/i.test(d) ? d : `@report ${d}`));
    inputRef.current?.focus();
  }

  async function leave() {
    if (!chat) return;
    try {
      await api.sharing.unshare(sessionId, chat.you.id);
      router.push("/");
    } catch (e: any) {
      setError(e?.message || "Could not leave.");
    }
  }

  const members = chat?.members || [];
  const others = members.filter((m) => chat && m.user_id !== chat.you.id);
  const reportParas = useMemo(() => cleanReportText(chat?.report?.answer || "").split(/\n{2,}/).map((p) => p.trim()).filter(Boolean), [chat?.report?.answer]);

  if (error && !chat) {
    return (
      <div className="h-full flex items-center justify-center p-8">
        <div className="max-w-sm text-center">
          <p className="text-sm text-foreground mb-2">{error}</p>
          <button onClick={() => router.push("/")} className="text-xs text-primary hover:underline">Back to the start</button>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col min-h-0">
      {/* who is here, and the share / open / leave actions */}
      <div className={`px-5 py-2 border-b border-border/40 flex items-center gap-3 shrink-0 ${variant === "page" ? "" : "bg-muted/10"}`}>
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground min-w-0" title={members.map((m) => `${m.name}${m.email ? ` · ${m.email}` : ""}${m.is_owner ? " (owner)" : ""}`).join("\n")}>
          <Users className="w-3.5 h-3.5 shrink-0" />
          <span className="truncate">
            {!chat ? "…" : others.length === 0
              ? "Only you are in this chat so far"
              : `In this chat: ${members.map((m) => m.name).join(", ")}`}
          </span>
        </div>
        <div className="ml-auto flex items-center gap-2 shrink-0">
          {chat?.you.is_owner && (
            <button onClick={() => setShare(true)} className={`flex items-center gap-1 text-xs px-2.5 py-1.5 rounded border ${others.length === 0 ? "border-primary/40 text-primary bg-primary/10 hover:bg-primary/20" : "border-border/60 text-muted-foreground hover:text-foreground"}`} title="Choose the colleagues who can read and talk here">
              <Share2 className="w-3.5 h-3.5" /> {others.length === 0 ? "Share with colleagues" : "Share"}
            </button>
          )}
          {chat?.you.can_open && !hideOpen && (
            <button onClick={() => router.push(`/session/${sessionId}`)} className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded border border-primary/35 text-primary hover:bg-primary/10" title="Open the session itself"><ExternalLink className="w-3.5 h-3.5" /> Open session</button>
          )}
          {chat && !chat.you.is_owner && (
            <button onClick={leave} className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded border border-border/60 text-muted-foreground hover:text-red-400" title="Leave this shared session"><LogOut className="w-3.5 h-3.5" /> Leave</button>
          )}
        </div>
      </div>

      <div className="flex-1 flex min-h-0">
        {/* the report, for everyone in the chat */}
        <aside className={`${showReport ? "w-[360px]" : "w-10"} shrink-0 border-r border-border/40 flex flex-col min-h-0 transition-all`}>
          <button onClick={() => setShowReport((v) => !v)} className="px-3 py-2.5 flex items-center gap-2 text-xs font-medium text-foreground border-b border-border/40 shrink-0" title={showReport ? "Fold the report away" : "Show the report"}>
            {showReport ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
            <FileText className="w-3.5 h-3.5 text-primary" />
            {showReport && (chat?.report ? (chat.report.is_report ? "The report" : "Latest answer from the report") : "No report yet")}
            {showReport && chat?.report?.created_at && <span className="ml-auto text-[10px] text-muted-foreground font-normal">{new Date(chat.report.created_at).toLocaleDateString()}</span>}
          </button>
          {showReport && (
            <div className="flex-1 overflow-y-auto px-4 py-3 text-xs text-foreground/85 leading-relaxed space-y-2">
              {!chat ? (
                <p className="text-muted-foreground flex items-center gap-2"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading…</p>
              ) : !chat.report ? (
                <p className="text-muted-foreground">No report has been made for this session yet. You can still ask the report agent — it answers from the session's records, evidence and discussion.</p>
              ) : (
                <>
                  {!chat.report.is_report && <p className="text-[11px] text-muted-foreground italic">Asked: {chat.report.question}</p>}
                  {reportParas.map((p, i) => <p key={i} className={/^[A-Z][A-Z &]{3,}$/.test(p.split("\n")[0]) ? "font-semibold text-foreground" : ""}>{p}</p>)}
                </>
              )}
            </div>
          )}
        </aside>

        {/* the chat */}
        <main className="flex-1 flex flex-col min-h-0">
          <div className="flex-1 overflow-y-auto px-6 py-4">
            {chat && chat.messages.length === 0 && (
              <div className="max-w-md mx-auto text-center mt-12">
                <p className="text-sm text-foreground/80 mb-1">Nobody has said anything yet.</p>
                <p className="text-xs text-muted-foreground">
                  {others.length === 0 && chat.you.is_owner
                    ? <>Share this session with colleagues and talk it through here together. Put <code className="text-primary">@report</code> in a message to ask the report agent — it answers from this session's records, evidence and discussion, for everyone to read.</>
                    : <>Talk to the others here. Put <code className="text-primary">@report</code> in a message to ask the report agent — it answers from this session's records, evidence and discussion.</>}
                </p>
                {others.length === 0 && chat.you.is_owner && (
                  <button onClick={() => setShare(true)} className="mt-4 inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md bg-primary text-primary-foreground hover:bg-primary/90"><Share2 className="w-3.5 h-3.5" /> Share with colleagues</button>
                )}
              </div>
            )}
            <div className="max-w-2xl mx-auto space-y-3">
              {chat?.messages.map((m) => <MessageRow key={m.id} m={m} mine={!!chat && m.user_id === chat.you.id} />)}
              {pendingReport && (
                <div className="flex items-start gap-3">
                  <span className="w-7 h-7 rounded-full bg-primary/15 text-primary flex items-center justify-center shrink-0"><Bot className="w-3.5 h-3.5" /></span>
                  <div className="text-xs text-muted-foreground flex items-center gap-2 pt-1.5"><Loader2 className="w-3.5 h-3.5 animate-spin" /> The report is answering…</div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          </div>
          <div className="border-t border-border/40 px-6 py-3 shrink-0">
            <div className="max-w-2xl mx-auto">
              {error && <p className="text-xs text-red-400 mb-2">{error}</p>}
              <div className="flex items-end gap-2">
                <button onClick={askReport} className="flex items-center gap-1 text-xs px-2.5 py-2 rounded-md border border-primary/35 text-primary hover:bg-primary/10 shrink-0" title="Ask the report agent (adds @report to your message)"><AtSign className="w-3.5 h-3.5" /> report</button>
                <textarea
                  ref={inputRef}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                  placeholder="Say something to the group, or @report to ask the report"
                  rows={2}
                  className="flex-1 bg-muted/50 border border-border rounded-md px-3 py-2 text-sm text-foreground placeholder-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/60 resize-none"
                />
                <button onClick={send} disabled={sending || !draft.trim()} className="p-2.5 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-40 shrink-0" title="Send (Enter)">
                  {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                </button>
              </div>
              <p className="text-[10.5px] text-muted-foreground/60 mt-1.5">Enter sends, Shift+Enter for a new line. Everyone in this chat sees every message, including the report's answers.</p>
            </div>
          </div>
        </main>
      </div>

      {share && chat && <ShareDialog sessionId={sessionId} title={chat.session.title} onClose={() => setShare(false)} onChanged={(m) => setChat((prev) => prev ? { ...prev, members: m } : prev)} />}
    </div>
  );
}

function MessageRow({ m, mine }: { m: SharedMessage; mine: boolean }) {
  const isReport = m.kind === "report";
  const when = m.created_at ? new Date(m.created_at).toLocaleString([], { hour: "2-digit", minute: "2-digit", day: "numeric", month: "short" }) : "";
  const paras = (isReport ? cleanReportText(m.content) : m.content).split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);
  return (
    <div className={`flex items-start gap-3 ${mine && !isReport ? "flex-row-reverse" : ""}`}>
      <span className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 text-[10px] font-semibold ${isReport ? "bg-primary/15 text-primary" : "bg-muted text-foreground/80"}`} title={m.author_name}>
        {isReport ? <Bot className="w-3.5 h-3.5" /> : (m.author_name || "?").slice(0, 2).toUpperCase()}
      </span>
      <div className={`max-w-[80%] ${mine && !isReport ? "text-right" : ""}`}>
        <div className={`text-[10.5px] text-muted-foreground mb-0.5 ${mine && !isReport ? "text-right" : ""}`}>{isReport ? "Report" : m.author_name}{when ? ` · ${when}` : ""}</div>
        <div className={`rounded-lg px-3 py-2 text-sm leading-relaxed text-left ${isReport ? "bg-primary/8 border border-primary/20 text-foreground/90" : mine ? "bg-primary/15 text-foreground" : "bg-muted/50 text-foreground/90"}`}>
          {paras.map((p, i) => <p key={i} className={i ? "mt-2" : ""}>{p}</p>)}
        </div>
      </div>
    </div>
  );
}
