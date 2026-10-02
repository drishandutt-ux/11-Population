"use client";

/** Helpers for the simple view (Lite): a thin wrapper over the same sessions, API and sockets
 *  as the pro portal. Nothing here analyses anything — it only decides what to show and where
 *  "See in detail" should send the reader. */

import { useEffect, useState } from "react";
import { api, Agent, Session } from "@/lib/api";

export type UiMode = "simple" | "pro";
const MODE_KEY = "ui_mode";

export function getUiMode(): UiMode {
  try { return localStorage.getItem(MODE_KEY) === "simple" ? "simple" : "pro"; } catch { return "pro"; }
}
export function setUiMode(mode: UiMode) {
  try { localStorage.setItem(MODE_KEY, mode); } catch {}
}
/** The remembered view. `null` until mounted so the server render never guesses wrong. */
export function useUiMode(): [UiMode | null, (m: UiMode) => void] {
  const [mode, setMode] = useState<UiMode | null>(null);
  useEffect(() => { setMode(getUiMode()); }, []);
  return [mode, (m) => { setUiMode(m); setMode(m); }];
}

/** Marks the document as a simple page while mounted so the html/body background is light too. */
export function useLiteRoot() {
  useEffect(() => {
    document.documentElement.classList.add("lite-root");
    return () => { document.documentElement.classList.remove("lite-root"); };
  }, []);
}

/** Hidden defaults the simple view runs with. Shown only in the explanation lines. */
export const LITE_DEFAULTS = { count: 40, mode: "fast" as const, intensity: 2 };

/** Something the reader dropped into "Add anything". */
export type Dropped =
  | { id: string; kind: "file"; file: File; label: string }
  | { id: string; kind: "youtube"; url: string; label: string }
  | { id: string; kind: "url"; url: string; label: string }
  | { id: string; kind: "text"; text: string; label: string };

const uid = () => Math.random().toString(36).slice(2, 9);

export function classifyText(raw: string): Dropped | null {
  const text = raw.trim();
  if (!text) return null;
  const single = /^https?:\/\/\S+$/i.test(text);
  if (single) {
    const yt = /(youtube\.com|youtu\.be)\//i.test(text);
    let host = text;
    try { host = new URL(text).hostname.replace(/^www\./, ""); } catch {}
    return yt
      ? { id: uid(), kind: "youtube", url: text, label: `YouTube · ${host}` }
      : { id: uid(), kind: "url", url: text, label: `Web page · ${host}` };
  }
  const words = text.split(/\s+/).length;
  return { id: uid(), kind: "text", text, label: `Text · ${words} word${words === 1 ? "" : "s"}` };
}

export function fromFile(file: File): Dropped {
  return { id: uid(), kind: "file", file, label: file.name };
}

export async function ingestDropped(sessionId: string, item: Dropped): Promise<void> {
  if (item.kind === "file") await api.ingest.document(sessionId, item.file);
  else if (item.kind === "youtube") await api.ingest.youtube(sessionId, item.url);
  else if (item.kind === "url") await api.ingest.url(sessionId, item.url);
  else await api.ingest.text(sessionId, item.text);
}

/** A short name for the session, taken from the question. */
export function autoTitle(question: string): string {
  const clean = question.replace(/\s+/g, " ").trim().replace(/[?.!,;:]+$/g, "");
  if (!clean) return "";
  const words = clean.split(" ");
  const cut = words.slice(0, 7).join(" ");
  const t = words.length > 7 ? `${cut}…` : cut;
  return t.charAt(0).toUpperCase() + t.slice(1);
}

/** Where a session is, in plain words. */
export function friendlyStatus(s: Pick<Session, "status" | "agent_count">, hasReport = false): { text: string; tone: "quiet" | "live" | "done" } {
  if (hasReport) return { text: "Report ready", tone: "done" };
  switch (s.status) {
    case "ingesting": return { text: "Reading your material", tone: "live" };
    case "simulating": return { text: "Talking it through", tone: "live" };
    case "paused": return { text: "Paused", tone: "quiet" };
    case "complete": return { text: "Conversation finished", tone: "done" };
    case "error": return { text: "Something went wrong", tone: "quiet" };
    default:
      return s.agent_count > 0 ? { text: "People ready", tone: "quiet" } : { text: "Just started", tone: "quiet" };
  }
}

/** The pro page for a thing in the simple view. */
export const proLinks = {
  session: (id: string) => `/session/${id}`,
  sources: (id: string) => `/session/${id}?tab=ingest`,
  people: (id: string) => `/session/${id}?tab=agents`,
  studio: (id: string) => `/session/${id}/population`,
  debate: (id: string) => `/session/${id}?tab=simulation`,
  knowledge: (id: string) => `/session/${id}?tab=kg`,
  lab: (id: string) => `/session/${id}?tab=lab`,
  report: (id: string) => `/session/${id}?tab=report`,
  person: (id: string, agentId: string) => `/session/${id}/agents/${agentId}`,
};

/** Stance in words a reader without the glossary understands. */
export function stanceWords(stance: Agent["stance"] | string): string {
  switch (stance) {
    case "direct": return "Directly affected";
    case "indirect": return "Affected indirectly";
    case "neutral": return "Looking on";
    default: return String(stance || "");
  }
}

/** First sentence or so of a longer text. */
export function firstSentence(text: string | null | undefined, max = 140): string {
  if (!text) return "";
  const clean = text.replace(/\s+/g, " ").replace(/[*_`#>]/g, "").trim();
  const m = clean.match(/^.{20,}?[.!?](\s|$)/);
  const out = (m ? m[0] : clean).trim();
  return out.length > max ? out.slice(0, max - 1).trimEnd() + "…" : out;
}
