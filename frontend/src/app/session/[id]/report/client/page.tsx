"use client";

/** The client-facing report (brief L6-06): a clean, print-ready page with none of the working
 *  controls — the synthetic-population statement at the top and the bottom (brief L6-07, generated
 *  server-side so it cannot be edited out), the direct answer with its computed confidence, the
 *  outcome records with intervals and equity, what's in the way, the narrative with every
 *  citation resolved to a name or a figure with its source class, and the caveats. */

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, ClientReport } from "@/lib/api";

function esc(t: string): string { return t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }

/** The document arrives as markdown from the same builder that writes report.md in the export; a
 *  small renderer keeps the two identical. */
function renderMarkdown(md: string): string {
  const inline = (t: string) => esc(t).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/(^|[^*])\*([^*\s][^*]*?)\*(?!\*)/g, "$1<em>$2</em>");
  const out: string[] = [];
  let list: string[] = []; let listType = ""; let quote: string[] = [];
  const flush = () => {
    if (list.length) { out.push(`<${listType}>${list.map((l) => `<li>${l}</li>`).join("")}</${listType}>`); list = []; listType = ""; }
    if (quote.length) { out.push(`<blockquote>${quote.join("<br/>")}</blockquote>`); quote = []; }
  };
  for (const raw of md.split("\n")) {
    const line = raw.trimEnd();
    if (!line.trim()) { flush(); continue; }
    if (line.startsWith("> ")) { if (list.length) flush(); quote.push(inline(line.slice(2))); continue; }
    if (/^#{1,3} /.test(line)) { flush(); const lvl = line.match(/^#+/)![0].length; out.push(`<h${lvl}>${inline(line.replace(/^#+ /, ""))}</h${lvl}>`); continue; }
    if (line === "---") { flush(); out.push("<hr/>"); continue; }
    const ul = line.match(/^- (.*)$/); const ol = line.match(/^\d+\. (.*)$/);
    if (ul || ol) { const t = ul ? "ul" : "ol"; if (listType && listType !== t) flush(); listType = t; list.push(inline((ul || ol)![1])); continue; }
    flush(); out.push(`<p>${inline(line)}</p>`);
  }
  flush();
  return out.join("\n");
}

export default function ClientReportPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<ClientReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.report.client(id).then(setData).catch((e) => setError(e?.message || "Could not load")); }, [id]);

  return (
    <div className="client-report min-h-screen" style={{ background: "#ffffff", color: "#111827" }}>
      <style>{`
        .client-report { font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
        .client-report .doc { max-width: 52rem; margin: 0 auto; padding: 3rem 2.5rem 4rem; line-height: 1.55; font-size: 14px; }
        .client-report h1 { font-size: 26px; font-weight: 700; margin: 0 0 1rem; color: #111827; }
        .client-report h2 { font-size: 13px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: #0f766e; margin: 2rem 0 .6rem; padding-bottom: .3rem; border-bottom: 1px solid #e5e7eb; }
        .client-report h3 { font-size: 14px; font-weight: 600; margin: 1.2rem 0 .4rem; }
        .client-report p { margin: .5rem 0; color: #1f2937; }
        .client-report ul, .client-report ol { margin: .4rem 0 .8rem 1.4rem; color: #1f2937; }
        .client-report li { margin: .25rem 0; }
        .client-report blockquote { margin: 1rem 0; padding: .9rem 1.1rem; border: 1px solid #fcd34d; background: #fffbeb; color: #78350f; font-size: 12.5px; border-radius: .5rem; }
        .client-report hr { border: 0; border-top: 1px solid #e5e7eb; margin: 2rem 0; }
        .client-report strong { color: #111827; }
        .client-report .bar { display: flex; gap: .75rem; align-items: center; justify-content: space-between; padding: .75rem 2.5rem; border-bottom: 1px solid #e5e7eb; font-size: 12px; color: #6b7280; }
        .client-report .bar button { border: 1px solid #d1d5db; background: #fff; color: #111827; padding: .35rem .7rem; border-radius: .4rem; font-size: 12px; cursor: pointer; }
        @media print { .client-report .bar { display: none; } .client-report .doc { padding: 0; max-width: none; } }
      `}</style>
      <div className="bar no-print">
        <span>Client report · generated from the synthetic population · {data?.run?.generated_at ? new Date(data.run.generated_at).toLocaleString() : ""}</span>
        <button type="button" onClick={() => window.print()}>Print / save as PDF</button>
      </div>
      <div className="doc">
        {error && <p style={{ color: "#b91c1c" }}>{error}</p>}
        {!data && !error && <p>Preparing the document…</p>}
        {data && !data.report && (
          <>
            <h1>{data.run.title || "Population report"}</h1>
            <blockquote>{data.statement}</blockquote>
            <p>No report has been generated for this session yet. Generate the report in the app, then open this page again.</p>
          </>
        )}
        {data && data.report && <div dangerouslySetInnerHTML={{ __html: renderMarkdown(data.markdown) }} />}
      </div>
    </div>
  );
}
