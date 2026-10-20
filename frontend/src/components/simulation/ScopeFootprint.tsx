"use client";

import { Post, PostFootprint, ScopeBreach } from "@/lib/api";
import { AlertTriangle, Fingerprint } from "lucide-react";

/** Standing-based scoping, made visible where the words are (2026-10-20): every debate post
 *  says what its author spoke from, how much knowledge it was given and how much was kept
 *  back, and carries the scope check's flags where it stepped outside its standing. */

export const SPOKE_LABEL: Record<PostFootprint["spoke_from"], string> = {
  lived: "lived experience",
  carer: "a carer's view",
  professional: "professional training",
  public: "a member of the public",
};

const SPOKE_COLOR: Record<PostFootprint["spoke_from"], string> = {
  lived: "border-emerald-500/30 text-emerald-300 bg-emerald-500/10",
  carer: "border-teal-500/30 text-teal-300 bg-teal-500/10",
  professional: "border-sky-500/30 text-sky-300 bg-sky-500/10",
  public: "border-zinc-500/30 text-zinc-300 bg-zinc-500/10",
};

const DIM_WORD: Record<string, string> = {
  geography: "about another place", role: "written for another role", register: "too specialist", channel: "on a channel they do not use",
  time: "after their date", condition: "about another condition", stage: "about another stage", segment: "about another group", provenance: "by source",
  project: "another project", licence: "licence", arm: "another arm",
};

function withheldText(fp: PostFootprint): string {
  const by = Object.entries(fp.withheld_by || {}).sort((a, b) => b[1] - a[1]).slice(0, 4);
  if (!by.length) return "";
  return by.map(([d, n]) => `${n} ${DIM_WORD[d] || d}`).join(", ");
}

function standingText(fp: PostFootprint): string {
  const st = fp.standing || ({} as PostFootprint["standing"]);
  const lived = { yes: "lives with it", past: "lived with it before", carer: "cares for someone with it", no: "no lived experience" }[st.lived as "yes" | "past" | "carer" | "no"] || "no lived experience";
  const prof = st.professional ? `trained as ${st.professional}` : "no training in it";
  const home = st.home ? ` · lives in ${st.home.split(",")[0]}` : "";
  const basis = st.basis === "inferred" ? " (standing inferred from the record)" : st.basis === "set" ? " (standing set by the analyst)" : "";
  return `${lived} · ${prof} · ${st.expertise || "lay"} working knowledge${home}${basis}`;
}

/** The chip in a post's meta row: "spoke from lived experience · knew 6 · 38 kept back". */
export function FootprintChip({ fp }: { fp: PostFootprint | null | undefined }) {
  if (!fp) return null;
  const kept = withheldText(fp);
  const title = fp.scoped
    ? `Spoke from ${SPOKE_LABEL[fp.spoke_from]}: ${standingText(fp)}.\nGiven ${fp.used} item${fp.used === 1 ? "" : "s"} of the session's knowledge${fp.routes.length ? ` (${fp.routes.slice(0, 3).join("; ")})` : ""}; ${fp.withheld} kept back${kept ? ` — ${kept}` : ""}.`
    : `Spoke from ${SPOKE_LABEL[fp.spoke_from]}: ${standingText(fp)}.\nThis session's knowledge was not scoped when the post was written, so every twin saw the same material.`;
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded border leading-none ${SPOKE_COLOR[fp.spoke_from] || SPOKE_COLOR.public}`}
    >
      <Fingerprint className="w-2.5 h-2.5" />
      {SPOKE_LABEL[fp.spoke_from]}
      {fp.scoped ? <span className="opacity-70">· knew {fp.used} · {fp.withheld} kept back</span> : <span className="opacity-70">· shared knowledge</span>}
    </span>
  );
}

/** The scope check's flags on a post, one chip per kind of breach. */
export function BreachFlags({ fp }: { fp: PostFootprint | null | undefined }) {
  const breaches = fp?.check?.breaches || [];
  if (!breaches.length) return null;
  const byKind = new Map<string, ScopeBreach[]>();
  for (const b of breaches) byKind.set(b.kind, [...(byKind.get(b.kind) || []), b]);
  return (
    <>
      {Array.from(byKind.entries()).map(([kind, list]) => (
        <span
          key={kind}
          title={`Out of scope — ${list[0].label}.\n${list.map((b) => `“${b.quote}” — ${b.why}`).join("\n")}`}
          className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded border leading-none border-amber-500/40 text-amber-300 bg-amber-500/10"
        >
          <AlertTriangle className="w-2.5 h-2.5" /> {list[0].label}
        </span>
      ))}
    </>
  );
}

type Group = { n: number; used: number; withheld: number; flags: number; checked: number };

/** How differently each kind of voice answered: posts, knowledge given and kept back, flags —
 *  computed from the footprints already on the client, grouped by what the author spoke from. */
export function ScopeEffects({ posts }: { posts: Post[] }) {
  const groups: Record<string, Group> = {};
  let any = 0;
  for (const p of posts) {
    const fp = p.footprint;
    if (!fp || p.type === "like" || !p.content) continue;
    any += 1;
    const g = (groups[fp.spoke_from] ||= { n: 0, used: 0, withheld: 0, flags: 0, checked: 0 });
    g.n += 1;
    g.used += fp.used || 0;
    g.withheld += fp.withheld || 0;
    if (fp.check) {
      g.checked += 1;
      g.flags += fp.check.breaches?.length ? 1 : 0;
    }
  }
  if (!any) return null;
  const order: PostFootprint["spoke_from"][] = ["lived", "carer", "professional", "public"];
  return (
    <div
      className="px-5 py-1.5 border-b border-border/30 flex items-center gap-3 flex-wrap text-[10.5px] text-muted-foreground/70 shrink-0"
      title="Scoping effects: for each kind of voice, how many posts, how much of the session's knowledge they were given on average, how much was kept back from them, and how many posts the scope check flagged for stepping outside their standing."
    >
      <span className="inline-flex items-center gap-1 text-muted-foreground"><Fingerprint className="w-3 h-3" /> Scoping effects</span>
      {order.filter((k) => groups[k]).map((k) => {
        const g = groups[k];
        return (
          <span key={k} className="inline-flex items-center gap-1.5">
            <span className={`px-1.5 py-0.5 rounded border leading-none ${SPOKE_COLOR[k]}`}>{SPOKE_LABEL[k]}</span>
            <span>{g.n} post{g.n === 1 ? "" : "s"} · knew {(g.used / g.n).toFixed(1)} · {(g.withheld / g.n).toFixed(0)} kept back</span>
            {g.checked > 0 && (
              <span className={g.flags ? "text-amber-300/90" : "text-emerald-300/70"}>· {g.flags ? `${g.flags} flagged` : "none flagged"}</span>
            )}
          </span>
        );
      })}
    </div>
  );
}
