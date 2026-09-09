"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Loader2, ShieldCheck, Users } from "lucide-react";
import { api, AdminUser } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function AdminPage() {
  const router = useRouter();
  const { me, loading } = useAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setUsers((await api.admin.users()) as AdminUser[]);
    } catch (e: any) {
      setError(e?.message || "Couldn't load users");
    }
  }

  useEffect(() => {
    if (!loading && me?.is_admin) load();
  }, [loading, me?.is_admin]);

  async function setRole(u: AdminUser, role: "admin" | "member") {
    setBusy(u.id);
    setError(null);
    try {
      await api.admin.setRole(u.id, role);
      await load();
    } catch (e: any) {
      setError(e?.message || "Couldn't change role");
    } finally {
      setBusy(null);
    }
  }

  if (loading) return null;
  if (!me?.is_admin) {
    return (
      <div className="h-screen bg-background flex items-center justify-center text-sm text-muted-foreground">
        Admins only.&nbsp;<button onClick={() => router.push("/")} className="text-primary">Back to sessions</button>
      </div>
    );
  }

  const admins = users.filter((u) => u.role === "admin").length;

  return (
    <div className="h-screen bg-background flex flex-col overflow-hidden">
      <header className="border-b border-border/60 px-5 py-3 flex items-center gap-3 shrink-0">
        <button onClick={() => router.push("/")} className="text-muted-foreground hover:text-foreground p-1 -ml-1 rounded">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <ShieldCheck className="w-4 h-4 text-primary" />
        <span className="text-sm font-medium text-foreground">Admin · Users</span>
        <span className="ml-auto text-xs text-muted-foreground">{users.length} account{users.length === 1 ? "" : "s"} · {admins} admin{admins === 1 ? "" : "s"}</span>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-3xl mx-auto space-y-4">
          <p className="text-xs text-muted-foreground">
            The first account that registered is the admin. Admins see every user&apos;s sessions (toggle on the home page) and can promote or demote accounts here. The last admin cannot be demoted.
          </p>
          {error && <p className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">{error}</p>}

          <div className="border border-border/60 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-muted/30 text-[10px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="text-left px-4 py-2.5 font-semibold">User</th>
                  <th className="text-left px-4 py-2.5 font-semibold">Role</th>
                  <th className="text-right px-4 py-2.5 font-semibold">Sessions</th>
                  <th className="text-left px-4 py-2.5 font-semibold">Joined</th>
                  <th className="px-4 py-2.5"></th>
                </tr>
              </thead>
              <tbody>
                {users.length === 0 && (
                  <tr><td colSpan={5} className="px-4 py-6 text-center text-xs text-muted-foreground"><Users className="w-4 h-4 inline mr-1" /> No accounts yet.</td></tr>
                )}
                {users.map((u) => (
                  <tr key={u.id} className="border-t border-border/40">
                    <td className="px-4 py-2.5">
                      <div className="text-foreground text-xs font-medium">{u.email || u.id}{u.is_you && <span className="ml-1.5 text-[10px] text-muted-foreground">(you)</span>}</div>
                      {u.display_name && <div className="text-[11px] text-muted-foreground">{u.display_name}</div>}
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded border ${u.role === "admin" ? "border-primary/40 text-primary bg-primary/10" : "border-border text-muted-foreground"}`}>{u.role}</span>
                    </td>
                    <td className="px-4 py-2.5 text-right text-xs tabular-nums text-muted-foreground">{u.sessions}</td>
                    <td className="px-4 py-2.5 text-xs text-muted-foreground">{new Date(u.created_at).toLocaleDateString()}</td>
                    <td className="px-4 py-2.5 text-right">
                      {u.role === "admin" ? (
                        <button
                          disabled={busy === u.id || admins <= 1}
                          onClick={() => setRole(u, "member")}
                          title={admins <= 1 ? "The last admin cannot be demoted" : "Make member"}
                          className="text-xs text-muted-foreground hover:text-foreground border border-border/60 rounded px-2 py-1 disabled:opacity-40"
                        >
                          {busy === u.id ? <Loader2 className="w-3 h-3 animate-spin" /> : "Make member"}
                        </button>
                      ) : (
                        <button
                          disabled={busy === u.id}
                          onClick={() => setRole(u, "admin")}
                          className="text-xs text-primary hover:bg-primary/10 border border-primary/40 rounded px-2 py-1 disabled:opacity-40"
                        >
                          {busy === u.id ? <Loader2 className="w-3 h-3 animate-spin" /> : "Make admin"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
