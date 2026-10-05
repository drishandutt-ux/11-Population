"use client";

/** Waiting for a report the server is still writing.
 *
 *  The report proper can take several minutes (it may run a verdict probe over the whole
 *  roster first). The HTTP call carries a long timeout, but when it does give up — a proxy
 *  limit, a dropped connection, a tab put to sleep — the server carries on and saves the
 *  report to the session's history. So instead of failing, the page polls the history for a
 *  report it has not seen before and shows that. A marker in localStorage remembers that a
 *  report was asked for, so a page reopened mid-write resumes waiting instead of offering to
 *  start another one. */

import { api, OutcomeRecord, ReportStructure } from "./api";

export type ReportRow = { id: string; question: string; answer: string; sources: string | null; structure: ReportStructure | null; created_at?: string | null };

/** A server timestamp (naive UTC) as epoch ms; null when missing or unreadable. */
export function serverTime(ts: string | null | undefined): number | null {
  if (!ts) return null;
  const v = Date.parse(/Z$|[+-]\d\d:\d\d$/.test(ts) ? ts : ts + "Z");
  return Number.isFinite(v) ? v : null;
}

/** The ids of every report row on file right now — call before `generate`, so a report that
 *  lands after a timeout can be told apart from the ones already there. */
export async function snapshotReportIds(sessionId: string): Promise<Set<string>> {
  try {
    const rows = (await api.report.history(sessionId)) as ReportRow[];
    return new Set((Array.isArray(rows) ? rows : []).map((r) => r.id));
  } catch {
    return new Set();
  }
}

/** Polls the history until a report proper (one with `structure`) appears that is not in
 *  `known`, or until `maxMs` has passed. Returns the row and the records it was built from. */
export async function waitForNewReport(
  sessionId: string,
  known: Set<string>,
  opts: { everyMs?: number; maxMs?: number; signal?: { stopped: boolean } } = {},
): Promise<{ row: ReportRow; records: OutcomeRecord[] } | null> {
  const every = opts.everyMs ?? 10_000;
  const until = Date.now() + (opts.maxMs ?? 12 * 60_000);
  while (Date.now() < until) {
    if (opts.signal?.stopped) return null;
    try {
      const rows = (await api.report.history(sessionId)) as ReportRow[];
      const fresh = [...(Array.isArray(rows) ? rows : [])].reverse().find((r) => r.structure && !known.has(r.id));
      if (fresh) {
        let records: OutcomeRecord[] = [];
        try { records = (await api.records.list(sessionId)).records || []; } catch {}
        return { row: fresh, records };
      }
    } catch {}
    await new Promise((r) => setTimeout(r, every));
  }
  return null;
}

/** Looks like the call was cut off rather than refused: the server is probably still writing. */
export function isCutOff(e: unknown): boolean {
  const m = String((e as any)?.message || e || "");
  return /timed out|Couldn't reach the server|Failed to fetch|NetworkError|502|503|504/i.test(m);
}

const PENDING_KEY = (sessionId: string) => `report_pending_${sessionId}`;
const PENDING_MAX_MS = 15 * 60_000;

export function markReportPending(sessionId: string) {
  try { localStorage.setItem(PENDING_KEY(sessionId), String(Date.now())); } catch {}
}
export function clearReportPending(sessionId: string) {
  try { localStorage.removeItem(PENDING_KEY(sessionId)); } catch {}
}
/** When a report was asked for recently (and may still be being written), its start time. */
export function reportPendingSince(sessionId: string): number | null {
  try {
    const v = Number(localStorage.getItem(PENDING_KEY(sessionId)) || 0);
    if (!v) return null;
    if (Date.now() - v > PENDING_MAX_MS) { clearReportPending(sessionId); return null; }
    return v;
  } catch { return null; }
}
