"use client";

import { useState } from "react";
import { Archetype, PopulationBuild, PopulationSegment } from "@/lib/api";
import { Check, X, Pencil, Loader2, MapPin, RotateCcw, Save, UserPlus, ChevronDown } from "lucide-react";

interface Props {
  build: PopulationBuild;
  onDecide: (segmentId: string, body: { decision: "accept" | "reject" | "edit"; edits?: Partial<PopulationSegment>; reason?: string }) => Promise<void>;
  busyIds: Set<string>;
  readOnly?: boolean;
  /** The analyst's archetypes (Build your own agent → "use as an archetype"); a segment cast from one takes its rules, the model writes texture only. */
  archetypes?: Archetype[];
}

/** One hue per segment, shared by the share bar and the card's rule so the eye links them. */
const PALETTE = ["hsl(170 62% 52%)", "hsl(212 70% 62%)", "hsl(268 58% 66%)", "hsl(36 80% 60%)", "hsl(340 65% 64%)", "hsl(150 52% 50%)", "hsl(196 55% 56%)", "hsl(18 72% 60%)"];

const STANCE_CHIP: Record<string, string> = { direct: "chip-info", indirect: "chip-violet", neutral: "" };
const MOOD_CHIP: Record<string, string> = { for: "chip-ok", against: "chip-bad", mixed: "chip-warn", uncertain: "" };

/** The segment's register — how its agents argue. Mirrors backend HINT_HUMANITY_BANDS. */
const REGISTER: Record<string, { desc: string }> = {
  expert: { desc: "analytical, evidence-first" },
  tempered: { desc: "logic leads, feeling colours it" },
  balanced: { desc: "gut and reason 50/50" },
  defensive: { desc: "feeling decides, logic defends it" },
  reactive: { desc: "pure gut — snap judgments" },
};

function toLabel(s: string) { return s.replace(/_/g, " "); }

/** Which mould a segment is cast from — auto-matched by job at plan time, changeable here. */
function ArchetypePicker({ seg, archetypes, busy, readOnly, onPick }: { seg: PopulationSegment; archetypes: Archetype[]; busy: boolean; readOnly?: boolean; onPick: (id: string) => void }) {
  const cast = !!seg.archetype_id;
  const known = archetypes.some((a) => a.id === seg.archetype_id);
  return (
    <div className="flex items-center gap-2 flex-wrap text-[11px]">
      <span className={`chip ${cast ? "chip-on" : ""}`}
            title={cast ? "Every persona in this segment is cast from this archetype: its decision rules, temperament and dials are kept; the model writes only names, life stories and places" : "No archetype matches this segment — the model invents each persona's psychology"}>
        <UserPlus className="w-3 h-3" /> {cast ? `cast from ${seg.archetype_name || "an archetype"}${known ? "" : " (deleted)"}` : "model invents"}
      </span>
      {!readOnly && archetypes.length > 0 && (
        <select disabled={busy} value={known ? seg.archetype_id : ""} onChange={(e) => onPick(e.target.value)} className="field field-sm w-auto py-0.5 text-[11px]">
          <option value="">model invents</option>
          {archetypes.map((a) => <option key={a.id} value={a.id}>cast from {a.name} · {a.role}</option>)}
        </select>
      )}
      {!readOnly && archetypes.length === 0 && <span className="text-muted-foreground/50">no archetypes yet — author one in Build your own agent</span>}
    </div>
  );
}

function EditForm({ seg, onSave, onCancel, busy }: { seg: PopulationSegment; onSave: (edits: Partial<PopulationSegment>) => void; onCancel: () => void; busy: boolean }) {
  const d = seg.demographics || {};
  const se = seg.sentiment || { mood: "mixed", temperature: 5, top_emotions: [] };
  const [name, setName] = useState(seg.name);
  const [share, setShare] = useState(seg.share_pct);
  const [stance, setStance] = useState(seg.stance);
  const [ageMin, setAgeMin] = useState(d.age_min ?? 18);
  const [ageMax, setAgeMax] = useState(d.age_max ?? 75);
  const [female, setFemale] = useState(d.gender_female_pct ?? 50);
  const [regions, setRegions] = useState((d.regions || []).join(", "));
  const [income, setIncome] = useState(d.income_band || "mixed");
  const [education, setEducation] = useState(d.education || "mixed");
  const [mood, setMood] = useState(se.mood);
  const [temp, setTemp] = useState(se.temperature ?? 5);
  const [register, setRegister] = useState(seg.humanity_hint || "tempered");
  const [desc, setDesc] = useState(seg.description);
  const inp = "field field-sm";
  const lab = "eyebrow mb-1 block";
  return (
    <div className="mt-4 border-t hairline pt-4 space-y-3 animate-fade-in">
      <div><label className={lab}>Name</label><input className={inp} value={name} onChange={(e) => setName(e.target.value)} /></div>
      <div><label className={lab}>Who they are</label><textarea className={`${inp} resize-none`} rows={2} value={desc} onChange={(e) => setDesc(e.target.value)} /></div>
      <div className="grid grid-cols-3 gap-2">
        <div><label className={lab}>Share %</label><input type="number" min={0} max={100} className={inp} value={share} onChange={(e) => setShare(+e.target.value)} /></div>
        <div><label className={lab}>Stance</label><select className={inp} value={stance} onChange={(e) => setStance(e.target.value as any)}><option value="direct">direct</option><option value="indirect">indirect</option><option value="neutral">neutral</option></select></div>
        <div><label className={lab}>Women %</label><input type="number" min={0} max={100} className={inp} value={female} onChange={(e) => setFemale(+e.target.value)} /></div>
        <div><label className={lab}>Age from</label><input type="number" min={10} max={100} className={inp} value={ageMin} onChange={(e) => setAgeMin(+e.target.value)} /></div>
        <div><label className={lab}>Age to</label><input type="number" min={10} max={100} className={inp} value={ageMax} onChange={(e) => setAgeMax(+e.target.value)} /></div>
        <div><label className={lab}>Mood</label><select className={inp} value={mood} onChange={(e) => setMood(e.target.value as any)}><option value="for">for</option><option value="against">against</option><option value="mixed">mixed</option><option value="uncertain">uncertain</option></select></div>
        <div><label className={lab}>Income</label><select className={inp} value={income} onChange={(e) => setIncome(e.target.value)}>{["low", "lower-middle", "middle", "upper-middle", "high", "mixed"].map((o) => <option key={o} value={o}>{o}</option>)}</select></div>
        <div><label className={lab}>Education</label><select className={inp} value={education} onChange={(e) => setEducation(e.target.value)}>{["secondary", "some college", "degree", "postgraduate", "mixed"].map((o) => <option key={o} value={o}>{o}</option>)}</select></div>
        <div><label className={lab}>Temperature {temp}/10</label><input type="range" min={0} max={10} value={temp} onChange={(e) => setTemp(+e.target.value)} style={{ "--range-pct": `${temp * 10}%` } as React.CSSProperties} className="mt-1.5" /></div>
      </div>
      <div>
        <label className={lab}>Register — how this group argues</label>
        <select className={inp} value={register} onChange={(e) => setRegister(e.target.value)}>
          {Object.entries(REGISTER).map(([k, r]) => <option key={k} value={k}>{k} — {r.desc}</option>)}
        </select>
      </div>
      <div><label className={lab}>Where they live (comma separated)</label><input className={inp} value={regions} onChange={(e) => setRegions(e.target.value)} /></div>
      <div className="flex gap-2 justify-end">
        <button disabled={busy} onClick={onCancel} className="btn btn-sm btn-ghost">Cancel</button>
        <button disabled={busy} onClick={() => onSave({ name, description: desc, share_pct: share, stance, humanity_hint: register, demographics: { age_min: Math.min(ageMin, ageMax), age_max: Math.max(ageMin, ageMax), gender_female_pct: female, regions: regions.split(",").map((s) => s.trim()).filter(Boolean), income_band: income, education }, sentiment: { mood, temperature: temp, top_emotions: se.top_emotions || [] } })} className="btn btn-sm btn-primary">
          {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />} Save &amp; accept
        </button>
      </div>
    </div>
  );
}

function SegmentCard({ seg, color, onDecide, busy, readOnly, archetypes }: { seg: PopulationSegment; color: string; onDecide: Props["onDecide"]; busy: boolean; readOnly?: boolean; archetypes: Archetype[] }) {
  const [editing, setEditing] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [open, setOpen] = useState(false);
  const d = seg.demographics || {};
  const se = seg.sentiment || { mood: "mixed", temperature: 5, top_emotions: [] };
  const rejected = seg.decision === "rejected";
  const accepted = seg.decision === "accepted" || seg.decision === "edited";
  const register = REGISTER[seg.humanity_hint || "tempered"] ? (seg.humanity_hint || "tempered") : "tempered";
  return (
    <div className={`surface rounded-xl p-5 relative overflow-hidden transition-all ${rejected ? "opacity-55" : ""} ${accepted ? "ring-1 ring-emerald-500/25" : ""}`}>
      <span className="absolute left-0 top-4 bottom-4 w-[3px] rounded-r" style={{ background: rejected ? "hsl(var(--border))" : color }} />
      <div className="flex items-start gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h4 className="text-[15px] font-semibold text-foreground tracking-tight leading-tight">{seg.name}</h4>
            {accepted && <span className="chip chip-ok"><Check className="w-3 h-3" /> {seg.decision}</span>}
            {rejected && <span className="chip chip-bad">{busy ? "regenerating…" : "rejected"}</span>}
          </div>
          <p className="text-xs text-muted-foreground leading-relaxed mt-1">{seg.description}</p>
        </div>
        <div className="text-right shrink-0">
          <div className="text-2xl font-semibold text-foreground tabular-nums leading-none tracking-tight">{seg.share_pct}<span className="text-sm text-muted-foreground font-medium">%</span></div>
          <div className="text-[11px] text-muted-foreground mt-1 tabular-nums">{seg.count ?? 0} agents</div>
        </div>
      </div>

      <div className="flex items-center gap-1.5 flex-wrap mt-3">
        <span className={`chip ${STANCE_CHIP[seg.stance] || ""}`}>{seg.stance}</span>
        <span className={`chip ${MOOD_CHIP[se.mood] || ""}`}>{se.mood}</span>
        <span className="chip" title={`Register: how this group argues — ${REGISTER[register].desc}`}>{register}</span>
        <span className="chip" title="Emotional temperature">{se.temperature}/10 heat</span>
        {seg.replaced && !rejected && <span className="text-[11px] text-muted-foreground/60 ml-1">replaces “{seg.replaced}”</span>}
      </div>

      <dl className="flex flex-wrap gap-x-4 gap-y-1 mt-3 text-[11.5px] text-muted-foreground">
        <span>ages <span className="text-foreground/85">{d.age_min}–{d.age_max}</span></span>
        <span><span className="text-foreground/85">{d.gender_female_pct}%</span> women</span>
        {d.regions?.length ? <span className="inline-flex items-center gap-1"><MapPin className="w-3 h-3" /><span className="text-foreground/85">{d.regions.join(", ")}</span></span> : null}
        <span>income <span className="text-foreground/85">{d.income_band}</span></span>
        <span>education <span className="text-foreground/85">{d.education}</span></span>
        {se.top_emotions?.length ? <span>feels <span className="text-foreground/85">{se.top_emotions.slice(0, 3).map(toLabel).join(", ")}</span></span> : null}
      </dl>
      {d.occupations?.length ? <p className="text-[11.5px] text-muted-foreground/70 mt-1">typically {d.occupations.slice(0, 5).join(" · ")}</p> : null}

      <blockquote className="mt-3 pl-3 border-l-2 hairline text-xs text-foreground/80 leading-relaxed">
        <span className="eyebrow block mb-0.5">Why this segment, at this share</span>
        {seg.rationale}
      </blockquote>

      {!rejected && <div className="mt-3"><ArchetypePicker seg={seg} archetypes={archetypes} busy={busy} readOnly={readOnly} onPick={(id) => onDecide(seg.id, { decision: "edit", edits: { archetype_id: id } })} /></div>}

      {(seg.arguments?.length || seg.evidence?.length) ? (
        <button onClick={() => setOpen(!open)} className="mt-3 inline-flex items-center gap-1 text-[11.5px] text-muted-foreground hover:text-foreground">
          <ChevronDown className={`w-3 h-3 transition-transform ${open ? "rotate-180" : ""}`} /> What they say &amp; the evidence
        </button>
      ) : null}
      {open && (
        <div className="mt-2 grid md:grid-cols-2 gap-4 animate-fade-in">
          {seg.arguments?.length ? (
            <div>
              <p className="eyebrow mb-1">In their words</p>
              <ul className="space-y-1">{seg.arguments.map((a, k) => <li key={k} className="text-xs text-foreground/80 leading-snug">“{a}”</li>)}</ul>
            </div>
          ) : null}
          <div>
            <p className="eyebrow mb-1">Evidence</p>
            {seg.evidence?.length ? <ul className="space-y-1">{seg.evidence.map((e, k) => <li key={k} className="text-xs text-muted-foreground leading-snug">• {e}</li>)}</ul> : <p className="text-xs text-amber-300/90">Assumed — no evidence cited for this segment.</p>}
          </div>
        </div>
      )}

      {!readOnly && !editing && !rejecting && (
        <div className="flex gap-1.5 mt-4">
          <button disabled={busy || accepted} onClick={() => onDecide(seg.id, { decision: "accept" })} className={`btn btn-sm ${accepted ? "btn-ghost text-emerald-300" : "btn-secondary"}`}>
            <Check className="w-3.5 h-3.5" /> {accepted ? "Accepted" : "Accept"}
          </button>
          <button disabled={busy} onClick={() => setEditing(true)} className="btn btn-sm btn-ghost"><Pencil className="w-3.5 h-3.5" /> Edit</button>
          <button disabled={busy} onClick={() => setRejecting(true)} className="btn btn-sm btn-ghost btn-danger ml-auto">
            {busy && rejected ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : rejected ? <RotateCcw className="w-3.5 h-3.5" /> : <X className="w-3.5 h-3.5" />} {rejected ? "Reject again" : "Reject"}
          </button>
        </div>
      )}
      {rejecting && (
        <div className="mt-4 border-t hairline pt-4 space-y-2 animate-fade-in">
          <p className="text-xs text-foreground/85">Why doesn&apos;t this segment belong? The replacement is written from your reason.</p>
          <input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Too affluent — this product is aimed at renters; or: this group doesn't exist in Scotland" className="field field-sm" onKeyDown={(e) => { if (e.key === "Enter") { onDecide(seg.id, { decision: "reject", reason }); setRejecting(false); } if (e.key === "Escape") setRejecting(false); }} />
          <div className="flex gap-2 justify-end">
            <button onClick={() => setRejecting(false)} className="btn btn-sm btn-ghost">Cancel</button>
            <button onClick={() => { onDecide(seg.id, { decision: "reject", reason }); setRejecting(false); setReason(""); }} className="btn btn-sm bg-red-500/15 text-red-200 hover:bg-red-500/25"><X className="w-3 h-3" /> Reject &amp; replace</button>
          </div>
        </div>
      )}
      {editing && <EditForm seg={seg} busy={busy} onCancel={() => setEditing(false)} onSave={async (edits) => { await onDecide(seg.id, { decision: "edit", edits }); setEditing(false); }} />}
    </div>
  );
}

export default function PlanReview({ build, onDecide, busyIds, readOnly, archetypes = [] }: Props) {
  const plan = build.plan;
  if (!plan) return null;
  const segs = plan.segments || [];
  const kept = segs.filter((s) => s.decision !== "rejected");
  const castCount = kept.filter((s) => s.archetype_id).length;
  const total = kept.reduce((n, s) => n + (s.count || 0), 0);
  const reviewed = segs.filter((s) => s.decision !== "proposed").length;
  const byStance = { direct: 0, indirect: 0, neutral: 0 } as Record<string, number>;
  for (const s of kept) byStance[s.stance] = (byStance[s.stance] || 0) + (s.count || 0);
  const shareTotal = kept.reduce((n, s) => n + (s.share_pct || 0), 0) || 1;
  const colorOf = (id: string) => PALETTE[Math.max(0, segs.findIndex((s) => s.id === id)) % PALETTE.length];
  return (
    <div className="space-y-3 animate-fade-in">
      <div className="surface rounded-xl p-5 space-y-3">
        <div className="flex items-baseline gap-2 flex-wrap">
          <h3 className="text-[15px] font-semibold text-foreground tracking-tight">Proposed population</h3>
          <span className="text-xs text-muted-foreground">{kept.length} segment{kept.length === 1 ? "" : "s"} · {total} agents</span>
          <span className="ml-auto text-[11px] text-muted-foreground/70 tabular-nums">{reviewed}/{segs.length} reviewed</span>
        </div>
        {/* the composition at a glance */}
        <div className="flex h-2 w-full rounded-full overflow-hidden gap-px">
          {kept.map((s) => (
            <span key={s.id} title={`${s.name} · ${s.share_pct}%`} style={{ width: `${(100 * (s.share_pct || 0)) / shareTotal}%`, background: colorOf(s.id) }} className="h-full transition-all" />
          ))}
        </div>
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          {kept.map((s) => (
            <span key={s.id} className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground min-w-0"><span className="dot" style={{ background: colorOf(s.id) }} /><span className="truncate max-w-[220px]">{s.name}</span><span className="tabular-nums text-foreground/80">{s.share_pct}%</span></span>
          ))}
        </div>
        <p className="text-xs text-foreground/85 leading-relaxed">{plan.rationale}</p>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
          <span>direct <span className="text-foreground/80 tabular-nums">{total ? Math.round(100 * byStance.direct / total) : 0}%</span></span>
          <span>indirect <span className="text-foreground/80 tabular-nums">{total ? Math.round(100 * byStance.indirect / total) : 0}%</span></span>
          <span>neutral <span className="text-foreground/80 tabular-nums">{total ? Math.round(100 * byStance.neutral / total) : 0}%</span></span>
          <span className={`chip ${castCount ? "chip-on" : ""}`} title="Segments cast from a hand-authored archetype keep its rules and dials; the rest are invented by the model">{castCount} of {kept.length} cast from archetypes</span>
          {plan.evidence_coverage && <span className="text-muted-foreground/70 basis-full">{plan.evidence_coverage}</span>}
        </div>
        {plan.assumptions?.length ? (
          <details className="group text-[11.5px] text-muted-foreground">
            <summary className="cursor-pointer text-amber-300/90 inline-flex items-center gap-1 select-none"><ChevronDown className="w-3 h-3 transition-transform group-open:rotate-180" /> {plan.assumptions.length} assumption{plan.assumptions.length === 1 ? "" : "s"} made</summary>
            <ul className="mt-1.5 pl-4 space-y-0.5">{plan.assumptions.map((a, k) => <li key={k}>• {a}</li>)}</ul>
          </details>
        ) : null}
      </div>
      {segs.map((seg) => <SegmentCard key={seg.id} seg={seg} color={colorOf(seg.id)} onDecide={onDecide} busy={busyIds.has(seg.id)} readOnly={readOnly} archetypes={archetypes} />)}
    </div>
  );
}
