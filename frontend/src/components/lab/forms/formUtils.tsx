"use client";

/** Helpers shared by the two Forms surfaces — the pro studio and the simple view: the draft
 *  shape, what a returned form changed, appending without key collisions, and a bold-and-bullets
 *  renderer for the colleague's short replies. */

import { FormQuestion, SurveyQuestion } from "@/lib/api";

export type Draft = { title: string; intro: string; questions: FormQuestion[] };

export function readDraft(values: Record<string, any>): Draft {
  return {
    title: typeof values.title === "string" ? values.title : "",
    intro: typeof values.intro === "string" ? values.intro : "",
    questions: Array.isArray(values.questions) ? values.questions : [],
  };
}

function sig(q: SurveyQuestion): string {
  return JSON.stringify([q.type, q.text, q.options || [], q.rows || [], q.columns || [], q.min ?? null, q.max ?? null, q.min_label || "", q.max_label || "", !!q.primary]);
}

/** Which questions a new form changed against the old one: new keys, or the same key with different content. */
export function changedKeys(prev: Draft, next: Draft): Set<string> {
  const before = new Map(prev.questions.map((q) => [q.key, sig(q)]));
  return new Set(next.questions.filter((q) => before.get(q.key) !== sig(q)).map((q) => q.key));
}

export function appendQuestions(prev: Draft, incoming: FormQuestion[]): FormQuestion[] {
  const used = new Set(prev.questions.map((q) => q.key));
  const out = [...prev.questions];
  for (const q of incoming) {
    let key = q.key || `q${out.length + 1}`;
    let n = 2;
    while (used.has(key)) key = `${q.key || "q"}_${n++}`;
    used.add(key);
    // Only one primary per form; the existing one keeps it.
    out.push({ ...q, key, primary: prev.questions.some((p) => p.primary) ? false : q.primary });
  }
  return out;
}

export function ago(iso: string | null): string {
  if (!iso) return "";
  const t = Date.parse(/[zZ]$|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

/** Bold and bullets, nothing more — the chat writes short lines. */
export function Md({ text }: { text: string }) {
  const lines = text.split(/\r?\n/);
  const blocks: { kind: "p" | "ul"; lines: string[] }[] = [];
  for (const ln of lines) {
    const bullet = /^\s*[-•]\s+/.test(ln);
    const last = blocks[blocks.length - 1];
    if (bullet) {
      if (last && last.kind === "ul") last.lines.push(ln.replace(/^\s*[-•]\s+/, ""));
      else blocks.push({ kind: "ul", lines: [ln.replace(/^\s*[-•]\s+/, "")] });
    } else if (ln.trim()) {
      if (last && last.kind === "p") last.lines.push(ln);
      else blocks.push({ kind: "p", lines: [ln] });
    } else if (last) {
      blocks.push({ kind: "p", lines: [] });
    }
  }
  const inline = (s: string) => s.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i} className="font-semibold text-foreground">{part.slice(2, -2)}</strong> : <span key={i}>{part}</span>);
  return (
    <div className="space-y-1.5">
      {blocks.filter((b) => b.lines.length).map((b, i) => b.kind === "ul"
        ? <ul key={i} className="list-disc pl-4 space-y-0.5">{b.lines.map((l, j) => <li key={j}>{inline(l)}</li>)}</ul>
        : <p key={i}>{b.lines.map((l, j) => <span key={j}>{j > 0 && <br />}{inline(l)}</span>)}</p>)}
    </div>
  );
}
