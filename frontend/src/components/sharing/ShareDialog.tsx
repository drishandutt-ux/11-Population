"use client";

import { useEffect, useMemo, useState } from "react";
import { api, Peer, ShareMember } from "@/lib/api";
import { Check, Loader2, Search, Share2, X } from "lucide-react";

/** Share a session with colleagues (2026-10-20): a picker over the people on the signed-in
 *  person's email domain. Saving replaces the set; the session then appears under *Shared with
 *  you* for them and opens as the shared chat. Owner only. */
export default function ShareDialog({ sessionId, title, onClose, onChanged }: { sessionId: string; title: string; onClose: () => void; onChanged?: (members: ShareMember[]) => void }) {
  const [peers, setPeers] = useState<Peer[] | null>(null);
  const [members, setMembers] = useState<ShareMember[]>([]);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.sharing.peers(), api.sharing.shares(sessionId)])
      .then(([p, s]) => {
        setPeers(p);
        setMembers(s.members);
        setChosen(new Set(s.members.filter((m) => !m.is_owner).map((m) => m.user_id)));
      })
      .catch((e: any) => { setPeers([]); setError(e?.message || "Could not load your colleagues."); });
  }, [sessionId]);

  const shown = useMemo(() => {
    const f = filter.trim().toLowerCase();
    return (peers || []).filter((p) => !f || (p.name || "").toLowerCase().includes(f) || (p.email || "").toLowerCase().includes(f));
  }, [peers, filter]);

  function toggle(id: string) {
    setChosen((prev) => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const r = await api.sharing.setShares(sessionId, Array.from(chosen));
      setMembers(r.members);
      onChanged?.(r.members);
      onClose();
    } catch (e: any) {
      setError(e?.message || "Could not save.");
    } finally {
      setSaving(false);
    }
  }

  const owner = members.find((m) => m.is_owner);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="w-[440px] max-w-[94vw] bg-card border border-border rounded-xl shadow-2xl p-5" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 mb-1">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-foreground flex items-center gap-2"><Share2 className="w-4 h-4 text-primary" /> Share this session</h3>
            <p className="text-xs text-muted-foreground truncate mt-0.5" title={title}>{title}</p>
          </div>
          <button onClick={onClose} className="p-1 text-muted-foreground hover:text-foreground" aria-label="Close"><X className="w-4 h-4" /></button>
        </div>
        <p className="text-[11px] text-muted-foreground mb-3">
          Colleagues you pick see it under <span className="text-foreground">Shared with you</span> and open a chat where you can all talk about it and ask the report with <code className="text-primary">@report</code>. They do not get your controls.
        </p>
        {owner && <p className="text-[11px] text-muted-foreground mb-2">Owner: <span className="text-foreground">{owner.name}</span>{owner.email ? ` · ${owner.email}` : ""}</p>}
        <div className="relative mb-2">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-muted-foreground/60" />
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Find a colleague" className="w-full bg-muted/50 border border-border rounded-md pl-8 pr-3 py-2 text-xs text-foreground placeholder-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/60" />
        </div>
        <div className="max-h-64 overflow-y-auto border border-border/60 rounded-md divide-y divide-border/40">
          {peers === null ? (
            <div className="px-3 py-6 text-xs text-muted-foreground flex items-center gap-2"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading your colleagues…</div>
          ) : shown.length === 0 ? (
            <div className="px-3 py-6 text-xs text-muted-foreground">{peers.length === 0 ? "Nobody else on your email domain has signed in yet." : "No one matches."}</div>
          ) : shown.map((p) => {
            const on = chosen.has(p.id);
            return (
              <button key={p.id} type="button" onClick={() => toggle(p.id)} className={`w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-muted/40 ${on ? "bg-primary/5" : ""}`}>
                <span className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 ${on ? "bg-primary border-primary text-primary-foreground" : "border-border"}`}>{on && <Check className="w-3 h-3" />}</span>
                <span className="min-w-0">
                  <span className="block text-xs text-foreground truncate">{p.name}</span>
                  <span className="block text-[10.5px] text-muted-foreground truncate">{p.email}</span>
                </span>
              </button>
            );
          })}
        </div>
        {error && <p className="text-xs text-red-400 mt-2">{error}</p>}
        <div className="flex items-center justify-between mt-4">
          <span className="text-[11px] text-muted-foreground">{chosen.size === 0 ? "Not shared with anyone" : `Shared with ${chosen.size} ${chosen.size === 1 ? "person" : "people"}`}</span>
          <div className="flex items-center gap-2">
            <button onClick={onClose} className="text-xs px-3 py-1.5 rounded-md border border-border/60 text-muted-foreground hover:text-foreground">Cancel</button>
            <button onClick={save} disabled={saving || peers === null} className="text-xs px-3 py-1.5 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-40 flex items-center gap-1.5">
              {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />} Save
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
