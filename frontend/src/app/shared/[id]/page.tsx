"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, SharedChat } from "@/lib/api";
import SharedChatPanel from "@/components/sharing/SharedChatPanel";
import { ArrowLeft } from "lucide-react";

/** The shared chat as a page of its own (2026-10-20): where a colleague lands from *Shared with
 *  you*. The same panel sits inside the session as the *Chat* step / tab. */
export default function SharedChatPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const router = useRouter();
  const [head, setHead] = useState<SharedChat["session"] | null>(null);

  useEffect(() => {
    api.sharing.chat(id).then((c) => setHead(c.session)).catch(() => setHead(null));
  }, [id]);

  return (
    <div className="h-screen bg-background flex flex-col overflow-hidden">
      <header className="px-5 py-3 border-b border-border/50 flex items-center gap-4 shrink-0">
        <button onClick={() => router.push("/")} className="p-1.5 rounded text-muted-foreground hover:text-foreground hover:bg-muted/40" title="Back"><ArrowLeft className="w-4 h-4" /></button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h1 className="text-sm font-semibold text-foreground truncate">{head?.title || "Shared session"}</h1>
            {head && <span className="text-[10px] text-muted-foreground">{head.status}{head.agent_count ? ` · ${head.agent_count} twins` : ""}</span>}
          </div>
          {head && <p className="text-xs text-muted-foreground truncate" title={head.query}>{head.query}</p>}
        </div>
      </header>
      <div className="flex-1 min-h-0">
        <SharedChatPanel sessionId={id} variant="page" />
      </div>
    </div>
  );
}
