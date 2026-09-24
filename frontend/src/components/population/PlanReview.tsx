"use client";

import { useState } from "react";
import { Archetype, PopulationBuild, PopulationSegment } from "@/lib/api";
import { stanceColor } from "@/lib/utils";
import { Check, X, Pencil, Loader2, Users, MapPin, Thermometer, Quote, Lightbulb, RotateCcw, Save, UserPlus } from "lucide-react";

interface Props {
  build: PopulationBuild;
  onDecide: (segmentId: string, body: { decision: "accept" | "reject" | "edit"; edits?: Partial<PopulationSegment>; reason?: string }) => Promise<void>;
  busyIds: Set<string>;
  readOnly?: boolean;
  /** The analyst's archetypes (Build your own agent → "use as an archetype"); a segment cast from one takes its rules, the model writes texture only. */
  archetypes?: Archetype[];
}

/** Which mould a segment is cast from — auto-matched by job at plan time, changeable here. */
function ArchetypePicker({ seg, archetypes, busy, readOnly, onPick }: { seg: PopulationSegment; archetypes: Archetype[]; busy: boolean; readOnly?: boolean; onPick: (id: string) => void }) {
  const cast = !!seg.archetype_id;
  const known = archetypes.some((a) => a.id === seg.archetype_id);
  return (
    <div className="mt-2 flex items-center gap-2 flex-wrap text-[10px]">
      <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border ${cast ? "border-primary/40 text-primary bg-primary/10" : "border-border/50 text-muted-foreground/70"}`}
            title={cast ? "Every persona in this segment is cast from this archetype: its decision rules, temperament and dials are kept; the model writes only names, life stories and places" : "No archetype matches this segment — the model invents each persona's psychology"}>
        <UserPlus className="w-3 h-3" /> {cast ? `cast from ${seg.archetype_name || "an archetype"}${known ? "" : " (deleted)"}` : "model invents"}
      </span>
      {!readOnly && archetypes.length > 0 && (
        <select disabled={busy} value={known ? seg.archetype_id : ""} onChange={(e) => onPick(e.target.value)} className="bg-muted/50 border border-border rounded-md px-1.5 py-0.5 text-[10px] text-foreground focus:outline-none">
          <option value="">model invents</option>
          {archetypes.map((a) => <option key={a.id} value={a.id}>cast from {a.name} · {a.role}</option>)}
        </select>
      )}
      {!readOnly && archetypes.length === 0 && <span className="text-muted-foreground/50">no archetypes yet — author one in Build your own agent</span>}
    </div>
  );
}

const MOOD: Record<string, string> = { for: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30", against: "bg-red-500/15 text-red-300 border-red-500/30", mixed: "bg-amber-500/15 text-amber-300 border-amber-500/30", uncertain: "bg-slate-500/15 text-slate-300 border-slate-500/30" };

/** The segment's register — how its agents argue. Mirrors backend HINT_HUMANITY_BANDS. */
const REGISTER: Record<string, { desc: string; cls: string }> = {
  expert: { desc: "analytical, evidence-first", cls: "bg-sky-500/15 text-sky-300 border-sky-500/30" },
  tempered: { desc: "logic leads, feeling colours it", cls: "bg-teal-500/15 text-teal-300 border-teal-500/30" },
  balanced: { desc: "gut and reason 50/50", cls: "bg-amber-500/15 text-amber-300 border-amber-500/30" },
  defensive: { desc: "feeling decides, logic defends it", cls: "bg-orange-500/15 text-orange-300 border-orange-500/30" },
  reactive: { desc: "pure gut — snap judgments", cls: "bg-rose-500/15 text-rose-300 border-rose-500/30" },
};

function toLabel(s: string) { return s.replace(/_/g, " "); }

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
  const inp = "w-full bg-muted/50 border border-border rounded-lg px-2 py-1.5 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50";
  const lab = "text-[10px] text-muted-foreground mb-0.5 block";
  return (
    <div className="mt-3 border-t border-border/40 pt-3 space-y-2.5">
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
        <div><label className={lab}>Temperature {temp}/10</label><input type="range" min={0} max={10} value={temp} onChange={(e) => setTemp(+e.target.value)} className="w-full accent-rose-500 h-1.5 mt-2" /></div>
      </div>
      <div>
        <label className={lab}>Register — how this group argues</label>
        <select className={inp} value={register} onChange={(e) => setRegister(e.target.value)}>
          {Object.entries(REGISTER).map(([k, r]) => <option key={k} value={k}>{k} — {r.desc}</option>)}
        </select>
      </div>
      <div><label className={lab}>Where they live (comma separated)</label><input className={inp} value={regions} onChange={(e) => setRegions(e.target.value)} /></div>
      <div className="flex gap-2 justify-end">
        <button disabled={busy} onClick={onCancel} className="text-[11px] px-3 py-1.5 rounded-lg border border-border/60 text-muted-foreground hover:text-foreground">Cancel</button>
        <button disabled={busy} onClick={() => onSave({ name, description: desc, share_pct: share, stance, humanity_hint: register, demographics: { age_min: Math.min(ageMin, ageMax), age_max: Math.max(ageMin, ageMax), gender_female_pct: female, regions: regions.split(",").map((s) => s.trim()).filter(Boolean), income_band: income, education }, sentiment: { mood, temperature: temp, top_emotions: se.top_emotions || [] } })} className="flex items-center gap-1 text-[11px] font-semibold px-3 py-1.5 rounded-lg bg-primary/15 border border-primary/40 text-primary hover:bg-primary/25 disabled:opacity-40">
          {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />} Save &amp; accept
        </button>
      </div>
    </div>
  );
}

function SegmentCard({ seg, onDecide, busy, readOnly, archetypes }: { seg: PopulationSegment; onDecide: Props["onDecide"]; busy: boolean; readOnly?: boolean; archetypes: Archetype[] }) {
  const [editing, setEditing] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [open, setOpen] = useState(false);
  const d = seg.demographics || {};
  const se = seg.sentiment || { mood: "mixed", temperature: 5, top_emotions: [] };
  const rejected = seg.decision === "rejected";
  const accepted = seg.decision === "accepted" || seg.decision === "edited";
  const ring = rejected ? "border-red-500/30 opacity-60" : accepted ? "border-emerald-500/40 ring-1 ring-emerald-500/20" : "border-border/50";
  return (
    <div className={`glass rounded-2xl p-4 border transition-all ${ring}`}>
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-foreground">{seg.name}</span>
            <span className={`inline-flex text-[10px] px-1.5 py-0.5 rounded border ${stanceColor(seg.stance)}`}>{seg.stance}</span>
            <span className={`inline-flex text-[10px] px-1.5 py-0.5 rounded border ${MOOD[se.mood] || MOOD.mixed}`}>{se.mood}</span>
            <span className={`inline-flex text-[10px] px-1.5 py-0.5 rounded border ${(REGISTER[seg.humanity_hint || "tempered"] || REGISTER.tempered).cls}`} title={`Register: how this group argues — ${(REGISTER[seg.humanity_hint || "tempered"] || REGISTER.tempered).desc}`}>{seg.humanity_hint || "tempered"}</span>
            {rejected && <span className="text-[10px] px-1.5 py-0.5 rounded border border-red-500/30 text-red-300">{busy ? "regenerating…" : "rejected"}</span>}
            {accepted && <span className="text-[10px] px-1.5 py-0.5 rounded border border-emerald-500/30 text-emerald-300">{seg.decision}</span>}
            {seg.replaced && !rejected && <span className="text-[10px] text-muted-foreground/60">replaces “{seg.replaced}”</span>}
          </div>
          <p className="text-[11px] text-muted-foreground leading-snug mt-1">{seg.description}</p>
        </div>
        <div className="text-right shrink-0">
          <div className="text-2xl font-bold text-primary tabular-nums leading-none">{seg.share_pct}%</div>
          <div className="text-[10px] text-muted-foreground flex items-center gap-1 justify-end mt-1"><Users className="w-3 h-3" /> {seg.count ?? 0} agents</div>
        </div>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2.5 text-[10px] text-muted-foreground/85">
        <span>ages <span className="text-foreground/80">{d.age_min}–{d.age_max}</span></span>
        <span><span className="text-foreground/80">{d.gender_female_pct}%</span> women</span>
        {d.regions?.length ? <span className="flex items-center gap-1"><MapPin className="w-3 h-3" /><span className="text-foreground/80">{d.regions.join(", ")}</span></span> : null}
        <span>income <span className="text-foreground/80">{d.income_band}</span></span>
        <span>education <span className="text-foreground/80">{d.education}</span></span>
        <span className="flex items-center gap-1"><Thermometer className="w-3 h-3 text-rose-400" /><span className="text-foreground/80">{se.temperature}/10</span>{se.top_emotions?.length ? <span className="text-rose-300/80"> · {se.top_emotions.slice(0, 3).map(toLabel).join(", ")}</span> : null}</span>
      </div>
      {d.occupations?.length ? <p className="text-[10px] text-muted-foreground/70 mt-1">typically: {d.occupations.slice(0, 5).join(" · ")}</p> : null}
      {!rejected && <ArchetypePicker seg={seg} archetypes={archetypes} busy={busy} readOnly={readOnly} onPick={(id) => onDecide(seg.id, { decision: "edit", edits: { archetype_id: id } })} />}

      <div className="mt-2.5 rounded-lg bg-muted/25 border border-border/30 px-3 py-2">
        <p className="text-[10px] text-muted-foreground/60 uppercase tracking-wide flex items-center gap-1 mb-0.5"><Lightbulb className="w-3 h-3 text-amber-300" /> why this segment, at this share</p>
        <p className="text-[11px] text-foreground/85 leading-snug">{seg.rationale}</p>
      </div>

      {(seg.arguments?.length || seg.evidence?.length) ? (
        <button onClick={() => setOpen(!open)} className="text-[10px] text-muted-foreground/70 hover:text-foreground mt-2">{open ? "hide" : "show"} what they say &amp; the evidence</button>
      ) : null}
      {open && (
        <div className="mt-1.5 grid md:grid-cols-2 gap-3">
          {seg.arguments?.length ? (
            <div>
              <p className="text-[10px] text-muted-foreground/60 uppercase tracking-wide mb-1 flex items-center gap-1"><Quote className="w-3 h-3" /> in their words</p>
              <ul className="space-y-1">{seg.arguments.map((a, k) => <li key={k} className="text-[11px] text-foreground/80 leading-snug">“{a}”</li>)}</ul>
            </div>
          ) : null}
          <div>
            <p className="text-[10px] text-muted-foreground/60 uppercase tracking-wide mb-1">evidence</p>
            {seg.evidence?.length ? <ul className="space-y-1">{seg.evidence.map((e, k) => <li key={k} className="text-[11px] text-muted-foreground/85 leading-snug">• {e}</li>)}</ul> : <p className="text-[11px] text-yellow-400/80">Assumed — no evidence cited for this segment.</p>}
          </div>
        </div>
      )}

      {!readOnly && !editing && !rejecting && (
        <div className="flex gap-2 mt-3">
          <button disabled={busy || accepted} onClick={() => onDecide(seg.id, { decision: "accept" })} className={`flex items-center gap-1 text-[11px] font-medium px-3 py-1.5 rounded-lg border transition-colors disabled:opacity-40 ${accepted ? "border-emerald-500/40 text-emerald-300 bg-emerald-500/10" : "border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/10"}`}>
            <Check className="w-3.5 h-3.5" /> {accepted ? "Accepted" : "Accept"}
          </button>
          <button disabled={busy} onClick={() => setEditing(true)} className="flex items-center gap-1 text-[11px] font-medium px-3 py-1.5 rounded-lg border border-border/60 text-muted-foreground hover:text-foreground disabled:opacity-40"><Pencil className="w-3.5 h-3.5" /> Edit</button>
          <button disabled={busy} onClick={() => setRejecting(true)} className="flex items-center gap-1 text-[11px] font-medium px-3 py-1.5 rounded-lg border border-red-500/30 text-red-300 hover:bg-red-500/10 disabled:opacity-40 ml-auto">
            {busy && rejected ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : rejected ? <RotateCcw className="w-3.5 h-3.5" /> : <X className="w-3.5 h-3.5" />} {rejected ? "Reject again" : "Reject"}
          </button>
        </div>
      )}
      {rejecting && (
        <div className="mt-3 border-t border-border/40 pt-3 space-y-2">
          <p className="text-[11px] text-foreground/85">Why doesn&apos;t this segment belong? The replacement is written from your reason.</p>
          <input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Too affluent — this product is aimed at renters; or: this group doesn't exist in Scotland" className="w-full bg-muted/50 border border-border rounded-lg px-2.5 py-1.5 text-[11px] text-foreground placeholder-muted-foreground/40 focus:outline-none focus:ring-1 focus:ring-red-500/40" onKeyDown={(e) => { if (e.key === "Enter") { onDecide(seg.id, { decision: "reject", reason }); setRejecting(false); } if (e.key === "Escape") setRejecting(false); }} />
          <div className="flex gap-2 justify-end">
            <button onClick={() => setRejecting(false)} className="text-[11px] px-3 py-1.5 rounded-lg border border-border/60 text-muted-foreground hover:text-foreground">Cancel</button>
            <button onClick={() => { onDecide(seg.id, { decision: "reject", reason }); setRejecting(false); setReason(""); }} className="flex items-center gap-1 text-[11px] font-semibold px-3 py-1.5 rounded-lg bg-red-500/15 border border-red-500/40 text-red-200 hover:bg-red-500/25"><X className="w-3 h-3" /> Reject &amp; replace</button>
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
  return (
    <div className="space-y-3">
      <div className="glass rounded-2xl p-4 space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-semibold text-foreground">Proposed population</span>
          <span className="text-[11px] text-muted-foreground">{kept.length} segment{kept.length === 1 ? "" : "s"} · {total} agents</span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded border ${castCount ? "border-primary/40 text-primary" : "border-border/50 text-muted-foreground/70"}`} title="Segments cast from a hand-authored archetype keep its rules and dials; the rest are invented by the model">{castCount} of {kept.length} cast from archetypes</span>
          <span className="text-[10px] text-muted-foreground/60 ml-auto">{reviewed}/{segs.length} reviewed</span>
        </div>
        <p className="text-[11px] text-foreground/85 leading-snug">{plan.rationale}</p>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-muted-foreground">
          <span className="text-blue-300">direct {total ? Math.round(100 * byStance.direct / total) : 0}%</span>
          <span className="text-purple-300">indirect {total ? Math.round(100 * byStance.indirect / total) : 0}%</span>
          <span className="text-slate-300">neutral {total ? Math.round(100 * byStance.neutral / total) : 0}%</span>
          {plan.evidence_coverage && <span className="text-muted-foreground/70">· {plan.evidence_coverage}</span>}
        </div>
        {plan.assumptions?.length ? (
          <details className="text-[10px] text-muted-foreground/80">
            <summary className="cursor-pointer text-yellow-400/80">{plan.assumptions.length} assumption{plan.assumptions.length === 1 ? "" : "s"} made</summary>
            <ul className="mt-1 pl-3 space-y-0.5">{plan.assumptions.map((a, k) => <li key={k}>• {a}</li>)}</ul>
          </details>
        ) : null}
      </div>
      {segs.map((seg) => <SegmentCard key={seg.id} seg={seg} onDecide={onDecide} busy={busyIds.has(seg.id)} readOnly={readOnly} archetypes={archetypes} />)}
    </div>
  );
}
