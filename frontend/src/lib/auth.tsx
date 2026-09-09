"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import type { User } from "@supabase/supabase-js";
import { authEnabled, supabase } from "./supabase";
import { Loader2 } from "lucide-react";

interface AuthState {
  user: User | null;
  loading: boolean;
  enabled: boolean;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState>({ user: null, loading: false, enabled: false, signOut: async () => {} });

export function useAuth() {
  return useContext(AuthContext);
}

/** Tracks the Supabase session for the whole app. When auth is not configured it is a no-op provider. */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(authEnabled);

  useEffect(() => {
    const c = supabase();
    if (!c) return;
    let cancelled = false;
    c.auth.getSession().then(({ data }) => {
      if (cancelled) return;
      setUser(data.session?.user ?? null);
      setLoading(false);
    });
    const { data: sub } = c.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null);
      setLoading(false);
    });
    return () => { cancelled = true; sub.subscription.unsubscribe(); };
  }, []);

  async function signOut() {
    await supabase()?.auth.signOut();
    setUser(null);
  }

  return <AuthContext.Provider value={{ user, loading, enabled: authEnabled, signOut }}>{children}</AuthContext.Provider>;
}

/** Gate: renders children only for a signed-in user (or always, when auth is off).
 *  The login page itself is never gated. */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading, enabled } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const isLogin = pathname === "/login";

  useEffect(() => {
    if (!enabled || isLogin || loading) return;
    if (!user) {
      const next = typeof window !== "undefined" ? window.location.pathname + window.location.search : "/";
      router.replace(`/login?next=${encodeURIComponent(next)}`);
    }
  }, [enabled, isLogin, loading, user, router]);

  if (!enabled || isLogin) return <>{children}</>;
  if (loading || !user) {
    return (
      <div className="h-screen bg-background flex items-center justify-center text-muted-foreground text-sm gap-2">
        <Loader2 className="w-4 h-4 animate-spin" /> {loading ? "Checking your session…" : "Redirecting to sign in…"}
      </div>
    );
  }
  return <>{children}</>;
}
