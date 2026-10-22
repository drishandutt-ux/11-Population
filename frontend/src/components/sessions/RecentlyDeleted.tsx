"use client";

import { useEffect, useState } from "react";
import { api, Session } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ChevronDown, Loader2, RotateCcw, Trash2 } from "lucide-react";

/** The bin (2026-10-22): sessions the signed-in person deleted in the last 30 days. Each can be
 *  restored as it was, or deleted for good now; after 30 days the server removes them itself.
 *  Collapsed by default; renders nothing when the bin is empty. `refreshKey` reloads it (bump it
 *  after a delete). `onRestored` hands the session back to the page's own list. */
export default function RecentlyDeleted({ variant = "lite", refreshKey = 0, onRestored }: { variant?: "lite" | "pro"; refreshKey?: number; onRestored?: (s: Session) => void }) {
  const [items, setItems] = useState<Session[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { api.sessions.trash().then(setItems).catch(() => setItems([])); }, [refreshKey]);

  if (items.length === 0) return null;

  async function restore(s: Session) {
    setBusy(s.id); setError(null);
    try {
      const back = await api.sessions.restore(s.id);
      setItems((prev) => prev.filter((x) => x.id !== s.id));
      onRestored?.(back);
    } catch (e: any) { setError(e?.message || "Could not restore it."); }
    finally { setBusy(null); }
  }
  async function forever(s: Session) {
    setBusy(s.id); setError(null);
    try {
      await api.sessions.deleteForever(s.id);
      setItems((prev) => prev.filter((x) => x.id !== s.id));
      setConfirmId(null);
    } catch (e: any) { setError(e?.message || "Could not delete it."); }
    finally { setBusy(null); }
  }

  const lite = variant === "lite";
  return (
    <section className={lite ? "mt-8" : "mt-6 shrink-0"}>
      <button type="button" onClick={() => setOpen((v) => !v)} className={cn("inline-flex items-center gap-1.5 text-muted-foreground hover:text-foreground", lite ? "text-[13px] font-semibold uppercase tracking-wider" : "text-[10px] uppercase tracking-widest")}>
        <Trash2 className={lite ? "w-3.5 h-3.5" : "w-3 h-3"} /> Recently deleted ({items.length})
        <ChevronDown className={cn(lite ? "w-3.5 h-3.5" : "w-3 h-3", "transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <>
          <p className={cn("text-muted-foreground mt-1.5", lite ? "lite-help" : "text-[11px]")}>Kept for 30 days, then removed for good. Restore brings a question back exactly as it was.</p>
          <div className={cn("mt-3", lite ? "space-y-2" : "space-y-1.5")}>
            {items.map((s) => {
              const left = daysLeft(s.purge_at);
              const confirming = confirmId === s.id;
              return (
                <div key={s.id} className={cn("flex items-center gap-3", lite ? "lite-card px-4 py-3 opacity-90" : "border border-border/60 rounded-md px-3.5 py-2.5")}>
                  <div className="min-w-0 flex-1">
                    <p className={cn("font-medium text-foreground truncate", lite ? "text-[14px]" : "text-xs")}>{s.title}</p>
                    <p className={cn("text-muted-foreground truncate mt-0.5", lite ? "text-[12.5px]" : "text-[11px]")}>
                      Deleted {fmtDate(s.deleted_at)} · {left <= 0 ? "removed for good today" : `removed for good in ${left} day${left === 1 ? "" : "s"}`}
                    </p>
                  </div>
                  {confirming ? (
                    <div className="flex items-center gap-2 shrink-0">
                      <span className={cn("text-red-600", lite ? "text-[12.5px]" : "text-xs")}>Delete for good? This cannot be undone.</span>
                      <button type="button" disabled={busy === s.id} onClick={() => forever(s)} className={cn("inline-flex items-center gap-1 rounded-full bg-red-600 text-white disabled:opacity-50", lite ? "h-8 px-3 text-[12.5px]" : "px-2 py-0.5 text-xs")}>
                        {busy === s.id && <Loader2 className="w-3 h-3 animate-spin" />} Delete
                      </button>
                      <button type="button" onClick={() => setConfirmId(null)} className={cn("text-muted-foreground hover:text-foreground", lite ? "text-[12.5px] px-2" : "text-xs px-1")}>Cancel</button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1.5 shrink-0">
                      <button type="button" disabled={busy === s.id} onClick={() => restore(s)} className={cn("inline-flex items-center gap-1.5 disabled:opacity-50", lite ? "lite-btn-soft h-8 px-3 text-[12.5px]" : "text-xs text-primary hover:underline px-1")} title="Bring it back to your list">
                        {busy === s.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RotateCcw className="w-3.5 h-3.5" />} Restore
                      </button>
                      <button type="button" onClick={() => setConfirmId(s.id)} className={cn("text-muted-foreground hover:text-red-600", lite ? "text-[12.5px] px-2" : "text-xs px-1")} title="Remove it for good now">Delete for good</button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          {error && <p className="mt-2 text-[12.5px] text-red-700">{error}</p>}
        </>
      )}
    </section>
  );
}

/** The server stores UTC without a zone; read it as UTC. */
function utc(iso?: string | null): Date | null {
  if (!iso) return null;
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
}
function fmtDate(iso?: string | null) {
  const d = utc(iso);
  return d ? d.toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "";
}
function daysLeft(iso?: string | null) {
  const d = utc(iso);
  return d ? Math.ceil((d.getTime() - Date.now()) / 86_400_000) : 30;
}
