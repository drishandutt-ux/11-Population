"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, SharedSession } from "@/lib/api";
import { MessageSquare, Users } from "lucide-react";

/** The landing page's *Shared with you* list (2026-10-20): sessions colleagues shared with the
 *  signed-in person. Each opens the shared chat page. Renders nothing when there are none. */
export default function SharedList({ variant = "pro" }: { variant?: "pro" | "lite" }) {
  const router = useRouter();
  const [items, setItems] = useState<SharedSession[] | null>(null);

  useEffect(() => {
    api.sharing.sharedSessions().then(setItems).catch(() => setItems([]));
  }, []);

  if (!items || items.length === 0) return null;

  if (variant === "lite") {
    return (
      <section className="mt-8">
        <h2 className="text-sm font-medium text-foreground mb-3">Shared sessions</h2>
        <div className="space-y-2">
          {items.map((s) => (
            <button key={s.id} type="button" onClick={() => router.push(`/lite/${s.id}`)} className="w-full text-left lite-card px-4 py-3.5 hover:border-foreground/20 transition-colors flex items-center gap-4">
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-foreground truncate">{s.title}</div>
                <div className="text-xs text-muted-foreground truncate">{s.query}</div>
                <div className="text-[11px] text-muted-foreground/70 mt-0.5">{s.direction === "by_you" ? `you shared it with ${s.with.join(", ")}` : `from ${s.owner.name}${s.owner.email ? ` · ${s.owner.email}` : ""}`}</div>
              </div>
              <div className="flex items-center gap-3 text-xs text-muted-foreground shrink-0">
                <span className="inline-flex items-center gap-1" title="People in the chat"><Users className="w-3.5 h-3.5" />{s.members}</span>
                <span className="inline-flex items-center gap-1" title="Messages"><MessageSquare className="w-3.5 h-3.5" />{s.messages}</span>
              </div>
            </button>
          ))}
        </div>
      </section>
    );
  }

  return (
    <div className="mt-6 shrink-0">
      <p className="text-[10px] text-muted-foreground uppercase tracking-widest mb-3">Shared with you</p>
      <div className="space-y-1.5">
        {items.map((s) => (
          <div
            key={s.id}
            className="w-full border border-border/60 rounded-md px-3.5 py-3 text-left transition-all cursor-pointer hover:border-primary/30 hover:bg-muted/30"
            onClick={() => router.push(`/session/${s.id}`)}
            title="Open the session"
          >
            <div className="flex items-center justify-between gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className="font-medium text-foreground text-xs truncate">{s.title}</span>
                  <span className="text-[10px] text-muted-foreground">{s.status}</span>
                </div>
                <p className="text-[11px] text-muted-foreground truncate">{s.query}</p>
                <p className="text-[10px] text-primary/70 truncate mt-0.5">{s.direction === "by_you" ? `you shared it with ${s.with.join(", ")}` : `from ${s.owner.name}${s.owner.email ? ` · ${s.owner.email}` : ""}`}</p>
              </div>
              <div className="flex items-center gap-2.5 text-xs text-muted-foreground shrink-0">
                <span className="flex items-center gap-1" title="People in the chat"><Users className="w-3 h-3" />{s.members}</span>
                <span className="flex items-center gap-1" title="Messages"><MessageSquare className="w-3 h-3" />{s.messages}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
