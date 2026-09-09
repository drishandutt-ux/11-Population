"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import type { User } from "@supabase/supabase-js";
import { getClient, loadAuthConfig, authHeaders } from "./supabase";
import { Loader2 } from "lucide-react";

export interface Me {
  id: string;
  email: string | null;
  role: "admin" | "member";
  is_admin: boolean;
}

interface AuthState {
  user: User | null;
  me: Me | null;
  loading: boolean;        // true until the auth config AND the session are known
  enabled: boolean;        // false when no Supabase project is configured anywhere
  signOut: () => Promise<void>;
  refreshMe: () => Promise<void>;
}

const AuthContext = createContext<AuthState>({
  user: null, me: null, loading: true, enabled: false, signOut: async () => {}, refreshMe: async () => {},
});

export function useAuth() {
  return useContext(AuthContext);
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** Tracks auth config + the Supabase session + the backend's view of the user (role). */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [loading, setLoading] = useState(true);

  const refreshMe = useCallback(async () => {
    try {
      const h = await authHeaders();
      if (!h.Authorization) { setMe(null); return; }
      const r = await fetch(`${API_BASE}/api/v1/me`, { headers: h, cache: "no-store" });
      setMe(r.ok ? await r.json() : null);
    } catch {
      setMe(null);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    let unsub: (() => void) | undefined;
    (async () => {
      const cfg = await loadAuthConfig();
      if (cancelled) return;
      setEnabled(cfg.enabled);
      if (!cfg.enabled) { setLoading(false); return; }
      const c = await getClient();
      if (!c || cancelled) { setLoading(false); return; }
      const { data } = await c.auth.getSession();
      if (cancelled) return;
      setUser(data.session?.user ?? null);
      if (data.session) await refreshMe();
      setLoading(false);
      const { data: sub } = c.auth.onAuthStateChange((_event, session) => {
        setUser(session?.user ?? null);
        if (session) refreshMe(); else setMe(null);
        setLoading(false);
      });
      unsub = () => sub.subscription.unsubscribe();
    })();
    return () => { cancelled = true; unsub?.(); };
  }, [refreshMe]);

  async function signOut() {
    const c = await getClient();
    await c?.auth.signOut();
    setUser(null);
    setMe(null);
  }

  return (
    <AuthContext.Provider value={{ user, me, loading, enabled, signOut, refreshMe }}>
      {children}
    </AuthContext.Provider>
  );
}

/** Gate: renders children only for a signed-in user (or always, when auth is off).
 *  The login page itself is never gated. */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading, enabled } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const isLogin = pathname === "/login";

  useEffect(() => {
    if (loading || !enabled || isLogin) return;
    if (!user) {
      const next = typeof window !== "undefined" ? window.location.pathname + window.location.search : "/";
      router.replace(`/login?next=${encodeURIComponent(next)}`);
    }
  }, [enabled, isLogin, loading, user, router]);

  if (isLogin) return <>{children}</>;
  if (loading || (enabled && !user)) {
    return (
      <div className="h-screen bg-background flex items-center justify-center text-muted-foreground text-sm gap-2">
        <Loader2 className="w-4 h-4 animate-spin" /> {loading ? "Checking your session…" : "Redirecting to sign in…"}
      </div>
    );
  }
  return <>{children}</>;
}
