"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2, LogIn, Mail, UserPlus, KeyRound } from "lucide-react";
import { getClient } from "@/lib/supabase";
import { useAuth } from "@/lib/auth";

type Mode = "signin" | "signup" | "magic" | "forgot" | "reset";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { user, loading, enabled } = useAuth();
  const next = params.get("next") || "/";

  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // A password-recovery link lands here with a recovery session: show the "set a new password" form
  // instead of bouncing the user into the app.
  useEffect(() => {
    const hash = typeof window !== "undefined" ? window.location.hash : "";
    if (/type=recovery/.test(hash) || params.get("mode") === "reset") setMode("reset");
    let unsub: (() => void) | undefined;
    getClient().then((c) => {
      if (!c) return;
      const { data } = c.auth.onAuthStateChange((event) => { if (event === "PASSWORD_RECOVERY") setMode("reset"); });
      unsub = () => data.subscription.unsubscribe();
    });
    return () => unsub?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Already signed in → go where they were heading (unless they are here to set a new password).
  useEffect(() => {
    if (!loading && user && mode !== "reset") router.replace(next.startsWith("/") ? next : "/");
  }, [user, loading, next, router, mode]);

  if (loading) {
    return <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />;
  }
  if (!enabled) {
    return (
      <div className="max-w-sm text-center text-sm text-muted-foreground space-y-2">
        <p>Sign-in is not available: the backend has no Supabase project configured (<code>APP_SUPABASE_URL</code>) and the frontend build has no <code>NEXT_PUBLIC_SUPABASE_URL</code>.</p>
        <button onClick={() => router.replace("/")} className="text-primary text-xs">Continue without an account</button>
      </div>
    );
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const c = await getClient();
    if (!c || busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (mode === "signin") {
        const { error } = await c.auth.signInWithPassword({ email: email.trim(), password });
        if (error) throw error;
        router.replace(next.startsWith("/") ? next : "/");
      } else if (mode === "signup") {
        const { data, error } = await c.auth.signUp({
          email: email.trim(),
          password,
          options: { emailRedirectTo: `${window.location.origin}/login` },
        });
        if (error) throw error;
        if (data.session) {
          router.replace(next.startsWith("/") ? next : "/");
        } else {
          setNotice("Account created. Check your inbox for a confirmation link, then sign in.");
          setMode("signin");
        }
      } else if (mode === "magic") {
        const { error } = await c.auth.signInWithOtp({
          email: email.trim(),
          options: { emailRedirectTo: `${window.location.origin}${next.startsWith("/") ? next : "/"}` },
        });
        if (error) throw error;
        setNotice("Magic link sent. Open it on this device to sign in.");
      } else if (mode === "forgot") {
        const { error } = await c.auth.resetPasswordForEmail(email.trim(), { redirectTo: `${window.location.origin}/login?mode=reset` });
        if (error) throw error;
        setNotice("Password reset email sent. Open the link, then choose a new password here.");
      } else if (mode === "reset") {
        const { error } = await c.auth.updateUser({ password });
        if (error) throw error;
        setNotice("Password updated. Taking you in…");
        setTimeout(() => router.replace("/"), 800);
      }
    } catch (err: any) {
      const msg: string = err?.message || "Sign-in failed. Please try again.";
      setError(/invalid login credentials/i.test(msg)
        ? "Wrong email or password. If a password manager filled it in, check it is the one you set for this app — or use “Forgot password?” to choose a new one."
        : msg);
    } finally {
      setBusy(false);
    }
  }

  const title = mode === "signin" ? "Sign in" : mode === "signup" ? "Create your account" : mode === "magic" ? "Email me a sign-in link" : mode === "forgot" ? "Reset your password" : "Choose a new password";
  const needsEmail = mode !== "reset";
  const needsPassword = mode === "signin" || mode === "signup" || mode === "reset";

  return (
    <div className="w-full max-w-sm">
      <div className="border border-border rounded-lg p-6 bg-card/30">
        <h1 className="text-base font-semibold text-foreground mb-1 flex items-center gap-2">
          {mode === "signup" ? <UserPlus className="w-4 h-4 text-primary" /> : mode === "magic" || mode === "forgot" ? <Mail className="w-4 h-4 text-primary" /> : mode === "reset" ? <KeyRound className="w-4 h-4 text-primary" /> : <LogIn className="w-4 h-4 text-primary" />}
          {title}
        </h1>
        <p className="text-xs text-muted-foreground mb-5">
          {mode === "signup"
            ? "Your sessions, populations and reports are private to your account. The first account to register becomes the admin."
            : mode === "forgot"
            ? "We’ll email you a link. Open it on this device and you can set a new password."
            : mode === "reset"
            ? "You arrived from a reset link. Pick a new password for your account."
            : "Your sessions, populations and reports are private to your account."}
        </p>

        <form onSubmit={submit} className="space-y-3.5">
          {needsEmail && (
          <div>
            <label className="block text-[10px] text-muted-foreground mb-1.5 uppercase tracking-wide">Email</label>
            <input
              type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)}
              className="w-full bg-muted/50 border border-border rounded-md px-3 py-2 text-foreground placeholder-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/60 text-sm"
              placeholder="you@company.com"
            />
          </div>
          )}
          {needsPassword && (
            <div>
              <label className="block text-[10px] text-muted-foreground mb-1.5 uppercase tracking-wide">{mode === "reset" ? "New password" : "Password"}</label>
              <input
                type="password" autoComplete={mode === "signin" ? "current-password" : "new-password"} required minLength={8}
                value={password} onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-muted/50 border border-border rounded-md px-3 py-2 text-foreground placeholder-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/60 text-sm"
                placeholder={mode === "signin" ? "••••••••" : "At least 8 characters"}
              />
            </div>
          )}

          <button
            type="submit" disabled={busy || (needsEmail && !email.trim()) || (needsPassword && password.length < 8)}
            className="w-full bg-primary hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed text-primary-foreground font-medium py-2.5 rounded-md flex items-center justify-center gap-2 text-sm transition-colors"
          >
            {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {mode === "signin" ? "Sign in" : mode === "signup" ? "Create account" : mode === "reset" ? "Set new password" : mode === "forgot" ? "Send reset link" : "Send link"}
          </button>

          {error && <p className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">{error}</p>}
          {notice && <p className="text-xs text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 rounded px-3 py-2">{notice}</p>}
        </form>

        <div className="mt-5 pt-4 border-t border-border/50 flex flex-col gap-1.5 text-xs text-muted-foreground">
          {mode !== "signin" && <button onClick={() => { setMode("signin"); setError(null); }} className="text-left hover:text-foreground">Have an account? <span className="text-primary">Sign in</span></button>}
          {mode !== "signup" && <button onClick={() => { setMode("signup"); setError(null); }} className="text-left hover:text-foreground">New here? <span className="text-primary">Create an account</span></button>}
          {mode !== "magic" && mode !== "reset" && <button onClick={() => { setMode("magic"); setError(null); }} className="text-left hover:text-foreground">Prefer no password? <span className="text-primary">Email me a link</span></button>}
          {mode === "signin" && <button onClick={() => { setMode("forgot"); setError(null); }} className="text-left hover:text-foreground"><span className="text-primary">Forgot password?</span></button>}
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <div className="h-screen bg-background flex flex-col">
      <header className="px-8 py-3.5 flex items-center justify-between border-b border-border/50 shrink-0">
        <span className="text-base font-semibold text-foreground tracking-tight">11 Minds Population</span>
        <span className="text-xs text-muted-foreground">Multi-agent simulation</span>
      </header>
      <div className="flex-1 flex items-center justify-center px-6">
        <Suspense fallback={<Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />}>
          <LoginForm />
        </Suspense>
      </div>
    </div>
  );
}
