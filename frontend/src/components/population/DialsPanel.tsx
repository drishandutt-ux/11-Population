"use client";

import { PopulationConstraints, SimMode } from "@/lib/api";
import { Brain, Rocket, Heart, Users, SlidersHorizontal, MapPin, Thermometer } from "lucide-react";

/** Humanity register bands (mirrors backend agent_runner._humanity_band). */
export function humanityBand(h: number): { label: string; desc: string; color: string } {
  if (h >= 70) return { label: "Reactive", desc: "pure gut — judges and reacts, logic ignored", color: "text-rose-400" };
  if (h >= 60) return { label: "Defensive", desc: "defends their feelings with logic at any cost", color: "text-orange-400" };
  if (h >= 50) return { label: "Balanced", desc: "50 / 50 feeling and logic", color: "text-amber-400" };
  if (h >= 20) return { label: "Tempered", desc: "a bit sentimental, logic stays in control", color: "text-teal-400" };
  if (h > 0) return { label: "Mostly logical", desc: "barely sentimental", color: "text-sky-400" };
  return { label: "Off", desc: "pure analytical experts", color: "text-muted-foreground" };
}

export const DEFAULT_CONSTRAINTS: PopulationConstraints = {
  stance: { direct: 33, indirect: 33, neutral: 34, follow_plan: true },
  humanity: 50,
  humanity_coverage: 60,
  demographics: { age_min: 18, age_max: 75, age_skew: "even", gender: { female: 50, male: 48, other: 2 }, regions: [], urban_rural: "mixed", income: "mixed", education: "mixed", notes: "" },
  sentiment: { follow_evidence: true, mood: { for: 40, against: 35, mixed: 25 }, temperature: 5, trust_in_institutions: 5, price_sensitivity: 5, tech_savviness: 5, openness_to_change: 5 },
  profile_query: "",
  doc_context: "",
  skip_questions: false,
};

interface Props {
  constraints: PopulationConstraints;
  onChange: (c: PopulationConstraints) => void;
  count: number;
  onCount: (n: number) => void;
  mode: SimMode;
  onMode: (m: SimMode) => void;
  disabled?: boolean;
}

function Row({ label, value, children, color = "text-foreground" }: { label: string; value: string; children: React.ReactNode; color?: string }) {
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[11px]">
        <span className="text-muted-foreground">{label}</span>
        <span className={`font-semibold tabular-nums ${color}`}>{value}</span>
      </div>
      {children}
    </div>
  );
}

function Dial({ label, value, onChange, lo, hi, color, disabled }: { label: string; value: number; onChange: (v: number) => void; lo: string; hi: string; color: string; disabled?: boolean }) {
  const moved = value !== 5;
  return (
    <Row label={label} value={moved ? `${value}/10` : "auto"} color={moved ? color : "text-muted-foreground/60"}>
      <input type="range" min={0} max={10} step={1} value={value} disabled={disabled} onChange={(e) => onChange(+e.target.value)} className={`w-full ${color.replace("text-", "accent-")} cursor-pointer h-1.5`} />
      <div className="flex justify-between text-[9px] text-muted-foreground/50"><span>{lo}</span><span>{hi}</span></div>
    </Row>
  );
}

function Select({ value, onChange, options, disabled }: { value: string; onChange: (v: string) => void; options: [string, string][]; disabled?: boolean }) {
  return (
    <select value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)} className="w-full bg-muted/50 border border-border rounded-lg px-2 py-1.5 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50">
      {options.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
    </select>
  );
}

export default function DialsPanel({ constraints, onChange, count, onCount, mode, onMode, disabled }: Props) {
  const c = constraints;
  const st = c.stance ?? DEFAULT_CONSTRAINTS.stance!;
  const demo = c.demographics ?? DEFAULT_CONSTRAINTS.demographics!;
  const sent = c.sentiment ?? DEFAULT_CONSTRAINTS.sentiment!;
  const humanity = c.humanity ?? 50;
  const coverage = c.humanity_coverage ?? 60;
  const hBand = humanityBand(humanity);
  const neutral = Math.max(0, 100 - st.direct - st.indirect);
  const gender = demo.gender ?? { female: 50, male: 48, other: 2 };

  const set = (patch: Partial<PopulationConstraints>) => onChange({ ...c, ...patch });
  const setDemo = (patch: Partial<NonNullable<PopulationConstraints["demographics"]>>) => set({ demographics: { ...demo, ...patch } });
  const setSent = (patch: Partial<NonNullable<PopulationConstraints["sentiment"]>>) => set({ sentiment: { ...sent, ...patch } });
  const mood = sent.mood ?? { for: 40, against: 35, mixed: 25 };

  return (
    <div className="space-y-4">
      {/* Size + model */}
      <div className="glass rounded-2xl p-4 space-y-3">
        <div className="flex items-center gap-2">
          <Users className="w-3.5 h-3.5 text-primary" />
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Population</span>
          <input type="number" min={1} max={1000} value={count} disabled={disabled} onChange={(e) => onCount(Math.max(1, Math.min(1000, +e.target.value || 0)))} className="ml-auto w-20 text-right text-2xl font-bold text-primary bg-transparent focus:outline-none tabular-nums" />
        </div>
        <input type="range" min={5} max={500} step={5} value={Math.min(count, 500)} disabled={disabled} onChange={(e) => onCount(+e.target.value)} className="w-full accent-purple-500 cursor-pointer" />
        <div className="flex gap-1.5 flex-wrap">
          {[20, 50, 100, 250, 500].map((n) => (
            <button key={n} disabled={disabled} onClick={() => onCount(n)} className={`text-[11px] px-2 py-0.5 rounded-lg border transition-colors ${count === n ? "border-primary/50 bg-primary/10 text-primary" : "border-border/50 text-muted-foreground hover:text-foreground"}`}>{n}</button>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-1.5">
          {([["fast", "Fast", "Haiku writes the personas", <Rocket key="r" className="w-3.5 h-3.5" />], ["pro", "Pro", "Sonnet · richer, slower, pricier", <Brain key="b" className="w-3.5 h-3.5" />]] as [SimMode, string, string, React.ReactNode][]).map(([k, l, d, icon]) => (
            <button key={k} disabled={disabled} onClick={() => onMode(k)} className={`text-left rounded-xl border px-3 py-2 transition-all ${mode === k ? "border-primary/60 bg-primary/10 ring-1 ring-primary/30" : "border-border/50 bg-muted/30 hover:border-border"}`}>
              <div className="flex items-center gap-1.5"><span className={mode === k ? "text-primary" : "text-muted-foreground"}>{icon}</span><span className={`text-xs font-semibold ${mode === k ? "text-foreground" : "text-muted-foreground"}`}>{l}</span></div>
              <p className="text-[10px] text-muted-foreground/70 mt-0.5 leading-snug">{d}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Demographics */}
      <div className="glass rounded-2xl p-4 space-y-3">
        <div className="flex items-center gap-2">
          <MapPin className="w-3.5 h-3.5 text-sky-400" />
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Demographics</span>
          <span className="text-[10px] text-muted-foreground/50 ml-auto">who they are</span>
        </div>
        <Row label="Age range" value={`${demo.age_min ?? 18} – ${demo.age_max ?? 75}`} color="text-sky-400">
          <div className="flex items-center gap-2">
            <input type="number" min={10} max={100} value={demo.age_min ?? 18} disabled={disabled} onChange={(e) => setDemo({ age_min: Math.min(+e.target.value || 10, (demo.age_max ?? 75) - 1) })} className="w-14 bg-muted/50 border border-border rounded-lg px-2 py-1 text-[11px] text-foreground focus:outline-none" />
            <input type="range" min={10} max={100} value={demo.age_max ?? 75} disabled={disabled} onChange={(e) => setDemo({ age_max: Math.max(+e.target.value, (demo.age_min ?? 18) + 1) })} className="flex-1 accent-sky-500 cursor-pointer h-1.5" />
            <input type="number" min={10} max={100} value={demo.age_max ?? 75} disabled={disabled} onChange={(e) => setDemo({ age_max: Math.max(+e.target.value || 100, (demo.age_min ?? 18) + 1) })} className="w-14 bg-muted/50 border border-border rounded-lg px-2 py-1 text-[11px] text-foreground focus:outline-none" />
          </div>
          <div className="flex gap-1">
            {(["even", "younger", "older"] as const).map((k) => (
              <button key={k} disabled={disabled} onClick={() => setDemo({ age_skew: k })} className={`flex-1 text-[10px] py-1 rounded-lg border ${(demo.age_skew ?? "even") === k ? "border-sky-500/50 bg-sky-500/10 text-sky-300" : "border-border/50 text-muted-foreground"}`}>{k === "even" ? "even spread" : `skew ${k}`}</button>
            ))}
          </div>
        </Row>
        <Row label="Women" value={`${gender.female}%`} color="text-pink-400">
          <input type="range" min={0} max={100} step={5} value={gender.female} disabled={disabled} onChange={(e) => { const f = +e.target.value; const other = gender.other; setDemo({ gender: { female: f, male: Math.max(0, 100 - f - other), other } }); }} className="w-full accent-pink-500 cursor-pointer h-1.5" />
          <div className="flex justify-between text-[9px] text-muted-foreground/50"><span>men {gender.male}%</span><span>non-binary {gender.other}%</span></div>
        </Row>
        <Row label="Where they live" value={demo.regions?.length ? `${demo.regions.length} place${demo.regions.length > 1 ? "s" : ""}` : "from the evidence"} color={demo.regions?.length ? "text-sky-400" : "text-muted-foreground/60"}>
          <input
            value={(demo.regions ?? []).join(", ")}
            disabled={disabled}
            onChange={(e) => setDemo({ regions: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
            placeholder="e.g. Greater Manchester, Leeds — comma separated"
            className="w-full bg-muted/50 border border-border rounded-lg px-2 py-1.5 text-[11px] text-foreground placeholder-muted-foreground/40 focus:outline-none focus:ring-1 focus:ring-primary/50"
          />
        </Row>
        <div className="grid grid-cols-3 gap-1.5">
          <div><p className="text-[10px] text-muted-foreground mb-1">Settlement</p><Select disabled={disabled} value={demo.urban_rural ?? "mixed"} onChange={(v) => setDemo({ urban_rural: v as any })} options={[["mixed", "mixed"], ["urban", "urban"], ["suburban", "suburban"], ["rural", "rural"]]} /></div>
          <div><p className="text-[10px] text-muted-foreground mb-1">Income</p><Select disabled={disabled} value={demo.income ?? "mixed"} onChange={(v) => setDemo({ income: v as any })} options={[["mixed", "mixed"], ["low", "low"], ["middle", "middle"], ["high", "high"]]} /></div>
          <div><p className="text-[10px] text-muted-foreground mb-1">Education</p><Select disabled={disabled} value={demo.education ?? "mixed"} onChange={(v) => setDemo({ education: v as any })} options={[["mixed", "mixed"], ["secondary", "secondary"], ["degree", "degree"], ["postgraduate", "postgrad"]]} /></div>
        </div>
        <input value={demo.notes ?? ""} disabled={disabled} onChange={(e) => setDemo({ notes: e.target.value })} placeholder="Anything else about who they are (optional)" className="w-full bg-muted/50 border border-border rounded-lg px-2 py-1.5 text-[11px] text-foreground placeholder-muted-foreground/40 focus:outline-none focus:ring-1 focus:ring-primary/50" />
      </div>

      {/* Sentiment */}
      <div className="glass rounded-2xl p-4 space-y-3">
        <div className="flex items-center gap-2">
          <Thermometer className="w-3.5 h-3.5 text-rose-400" />
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Sentiment</span>
          <span className="text-[10px] text-muted-foreground/50 ml-auto">how they feel</span>
        </div>
        <label className="flex items-start gap-2 cursor-pointer">
          <input type="checkbox" checked={sent.follow_evidence !== false} disabled={disabled} onChange={(e) => setSent({ follow_evidence: e.target.checked })} className="mt-0.5 accent-[hsl(var(--primary))]" />
          <span className="text-[10px] text-muted-foreground leading-relaxed"><span className="text-foreground/80">Follow the evidence.</span> Let the observed for / against split set the mood. Untick to impose your own.</span>
        </label>
        {sent.follow_evidence === false && (
          <div className="space-y-2 pl-1">
            <Row label="For" value={`${mood.for}%`} color="text-emerald-400">
              <input type="range" min={0} max={100} step={5} value={mood.for} disabled={disabled} onChange={(e) => { const f = +e.target.value; const ag = Math.min(mood.against, 100 - f); setSent({ mood: { for: f, against: ag, mixed: 100 - f - ag } }); }} className="w-full accent-emerald-500 cursor-pointer h-1.5" />
            </Row>
            <Row label="Against" value={`${mood.against}%`} color="text-red-400">
              <input type="range" min={0} max={100} step={5} value={mood.against} disabled={disabled} onChange={(e) => { const ag = +e.target.value; const f = Math.min(mood.for, 100 - ag); setSent({ mood: { for: f, against: ag, mixed: 100 - f - ag } }); }} className="w-full accent-red-500 cursor-pointer h-1.5" />
            </Row>
            <div className="flex justify-between text-[11px]"><span className="text-muted-foreground">Mixed / undecided</span><span className="text-slate-400 font-semibold">{mood.mixed}% (auto)</span></div>
          </div>
        )}
        <Dial label="Emotional temperature" value={sent.temperature ?? 5} onChange={(v) => setSent({ temperature: v })} lo="calm" hi="heated" color="text-rose-400" disabled={disabled} />
        <Dial label="Trust in institutions" value={sent.trust_in_institutions ?? 5} onChange={(v) => setSent({ trust_in_institutions: v })} lo="cynical" hi="trusting" color="text-blue-400" disabled={disabled} />
        <Dial label="Price sensitivity" value={sent.price_sensitivity ?? 5} onChange={(v) => setSent({ price_sensitivity: v })} lo="price-blind" hi="every penny" color="text-teal-400" disabled={disabled} />
        <Dial label="Comfort with technology" value={sent.tech_savviness ?? 5} onChange={(v) => setSent({ tech_savviness: v })} lo="wary" hi="early adopter" color="text-cyan-400" disabled={disabled} />
        <Dial label="Openness to change" value={sent.openness_to_change ?? 5} onChange={(v) => setSent({ openness_to_change: v })} lo="set in their ways" hi="restless" color="text-amber-400" disabled={disabled} />
      </div>

      {/* Stance + humanity */}
      <div className="glass rounded-2xl p-4 space-y-3">
        <div className="flex items-center gap-2">
          <SlidersHorizontal className="w-3.5 h-3.5 text-purple-400" />
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Stance mix</span>
        </div>
        <label className="flex items-start gap-2 cursor-pointer">
          <input type="checkbox" checked={st.follow_plan !== false} disabled={disabled} onChange={(e) => set({ stance: { ...st, follow_plan: e.target.checked } })} className="mt-0.5 accent-[hsl(var(--primary))]" />
          <span className="text-[10px] text-muted-foreground leading-relaxed"><span className="text-foreground/80">Let the segments decide.</span> Stance follows each group's real relationship to the topic. Untick to target a mix.</span>
        </label>
        {st.follow_plan === false && (
          <div className="space-y-2">
            <Row label="Direct" value={`${st.direct}%`} color="text-blue-400">
              <input type="range" min={0} max={100} step={5} value={st.direct} disabled={disabled} onChange={(e) => { const d = +e.target.value; const i = Math.min(st.indirect, 100 - d); set({ stance: { ...st, direct: d, indirect: i, neutral: 100 - d - i } }); }} className="w-full accent-blue-500 cursor-pointer h-1.5" />
            </Row>
            <Row label="Indirect" value={`${st.indirect}%`} color="text-purple-400">
              <input type="range" min={0} max={100} step={5} value={st.indirect} disabled={disabled} onChange={(e) => { const i = +e.target.value; const d = Math.min(st.direct, 100 - i); set({ stance: { ...st, direct: d, indirect: i, neutral: 100 - d - i } }); }} className="w-full accent-purple-500 cursor-pointer h-1.5" />
            </Row>
            <div className="flex justify-between text-[11px]"><span className="text-muted-foreground">Neutral</span><span className="text-slate-400 font-semibold">{neutral}% (auto)</span></div>
          </div>
        )}
        <div className="border-t border-border/40 pt-3 space-y-2">
          <div className="flex items-center gap-2">
            <Heart className="w-3.5 h-3.5 text-pink-400" />
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Humanity</span>
            <span className="text-[10px] text-muted-foreground/50 ml-auto">feeling over logic</span>
          </div>
          <Row label="Intensity" value={humanity === 0 ? "Off" : `${humanity}% · ${hBand.label}`} color={hBand.color}>
            <input type="range" min={0} max={100} step={5} value={humanity} disabled={disabled} onChange={(e) => set({ humanity: +e.target.value })} className="w-full accent-pink-500 cursor-pointer h-1.5" />
            {humanity > 0 && <p className="text-[10px] text-muted-foreground/70">{hBand.desc}</p>}
          </Row>
          <Row label="Coverage" value={`${coverage}% of agents`} color="text-pink-300">
            <input type="range" min={0} max={100} step={5} value={coverage} disabled={disabled || humanity === 0} onChange={(e) => set({ humanity_coverage: +e.target.value })} className="w-full accent-pink-400 cursor-pointer h-1.5" />
          </Row>
        </div>
      </div>
    </div>
  );
}
