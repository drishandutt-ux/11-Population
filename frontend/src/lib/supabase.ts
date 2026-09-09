"use client";

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const BUILD_URL = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
const BUILD_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";

export interface AuthConfig {
  enabled: boolean;
  url: string;
  key: string;
}

let _configPromise: Promise<AuthConfig> | null = null;
let _client: SupabaseClient | null = null;

/** Where the Supabase project comes from, in order: build-time env vars, then the backend's
 *  public `/config` endpoint (so the frontend works wherever it is hosted without a rebuild),
 *  else auth is off. Resolved once per page load. */
export function loadAuthConfig(): Promise<AuthConfig> {
  if (!_configPromise) {
    _configPromise = (async () => {
      if (BUILD_URL && BUILD_KEY) return { enabled: true, url: BUILD_URL, key: BUILD_KEY };
      try {
        const r = await fetch(`${API_BASE}/api/v1/config`, { cache: "no-store" });
        if (r.ok) {
          const j = await r.json();
          if (j?.auth?.enabled && j.auth.supabase_url && j.auth.anon_key) {
            return { enabled: true, url: j.auth.supabase_url, key: j.auth.anon_key };
          }
        }
      } catch {
        // backend unreachable: fall through to "auth off" so the UI still renders
      }
      return { enabled: false, url: "", key: "" };
    })();
  }
  return _configPromise;
}

/** The Supabase client, or null when auth is off. */
export async function getClient(): Promise<SupabaseClient | null> {
  const cfg = await loadAuthConfig();
  if (!cfg.enabled) return null;
  if (!_client) {
    _client = createClient(cfg.url, cfg.key, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
    });
  }
  return _client;
}

/** The current user's access token (refreshed automatically by supabase-js), or null. */
export async function getAccessToken(): Promise<string | null> {
  const c = await getClient();
  if (!c) return null;
  const { data } = await c.auth.getSession();
  return data.session?.access_token ?? null;
}

/** Headers to attach to every backend call. */
export async function authHeaders(): Promise<Record<string, string>> {
  const token = await getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Send the user to the login page, remembering where they were. */
export function redirectToLogin() {
  if (typeof window === "undefined") return;
  if (window.location.pathname === "/login") return;
  const next = window.location.pathname + window.location.search;
  window.location.assign(`/login?next=${encodeURIComponent(next)}`);
}
