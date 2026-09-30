"use client";

import { PopulationConstraints, SimMode } from "@/lib/api";
import { Divider, Range, Seg, Section, SwitchRow } from "./controls";

export const DEFAULT_CONSTRAINTS: PopulationConstraints = {
  stance: { direct: 33, indirect: 33, neutral: 34, follow_plan: true },
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

const FOR = "hsl(160 60% 45%)";
const AGAINST = "hsl(0 70% 60%)";

/** Marks a dial the detect stage set from the research. Compact form is a dot, for tight labels. */
function FromResearch({ basis, compact }: { basis?: string; compact?: boolean }) {
  if (!basis) return null;
  if (compact) return <span className="dot bg-emerald-400 ml-1.5" title={`Set from the research: ${basis}`} />;
  return <span className="chip chip-ok h-[18px] px-1.5 text-[10px] ml-1.5" title={basis}>research</span>;
}

function Row({ label, value, children, muted, basis }: { label: string; value: string; children: React.ReactNode; muted?: boolean; basis?: string }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground inline-flex items-center">{label}<FromResearch basis={basis} /></span>
        <span className={`tabular-nums ${muted ? "text-muted-foreground/60" : "text-foreground font-medium"}`}>{value}</span>
      </div>
      {children}
    </div>
  );
}

function Dial({ label, value, onChange, lo, hi, disabled, basis }: { label: string; value: number; onChange: (v: number) => void; lo: string; hi: string; disabled?: boolean; basis?: string }) {
  const moved = value !== 5;
  return (
    <Row label={label} value={moved ? `${value} / 10` : "auto"} muted={!moved} basis={basis}>
      <Range min={0} max={10} value={value} onChange={onChange} disabled={disabled} />
      <div className="flex justify-between text-[10px] text-muted-foreground/50 -mt-0.5"><span>{lo}</span><span>{hi}</span></div>
    </Row>
  );
}

function Select({ value, onChange, options, disabled }: { value: string; onChange: (v: string) => void; options: [string, string][]; disabled?: boolean }) {
  return (
    <select value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)} className="field field-sm">
      {options.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
    </select>
  );
}

export default function DialsPanel({ constraints, onChange, count, onCount, mode, onMode, disabled }: Props) {
  const c = constraints;
  const st = c.stance ?? DEFAULT_CONSTRAINTS.stance!;
  const demo = c.demographics ?? DEFAULT_CONSTRAINTS.demographics!;
  const sent = c.sentiment ?? DEFAULT_CONSTRAINTS.sentiment!;
  const voice = c.voice ?? { auto: true, value: 50 };
  const neutral = Math.max(0, 100 - st.direct - st.indirect);
  const gender = demo.gender ?? { female: 50, male: 48, other: 2 };

  const set = (patch: Partial<PopulationConstraints>) => onChange({ ...c, ...patch });
  const setDemo = (patch: Partial<NonNullable<PopulationConstraints["demographics"]>>) => set({ demographics: { ...demo, ...patch } });
  const setSent = (patch: Partial<NonNullable<PopulationConstraints["sentiment"]>>) => set({ sentiment: { ...sent, ...patch } });
  const mood = sent.mood ?? { for: 40, against: 35, mixed: 25 };
  const from = c.derived_from_research ?? {};

  return (
    <div className="space-y-6">
      {/* Size + model */}
      <Section title="Population">
        <div className="flex items-end justify-between gap-3">
          <div>
            <input type="number" min={1} max={1000} value={count} disabled={disabled} onChange={(e) => onCount(Math.max(1, Math.min(1000, +e.target.value || 0)))} className="w-24 text-3xl font-semibold text-foreground bg-transparent focus:outline-none tabular-nums tracking-tight leading-none" />
            <p className="text-[11px] text-muted-foreground mt-0.5">agents</p>
          </div>
          <div className="flex gap-1">
            {[20, 50, 100, 250, 500].map((n) => (
              <button key={n} type="button" disabled={disabled} onClick={() => onCount(n)} className={`chip transition-colors disabled:opacity-50 ${count === n ? "chip-on" : "hover:text-foreground"}`}>{n}</button>
            ))}
          </div>
        </div>
        <Range min={5} max={500} step={5} value={Math.min(count, 500)} onChange={onCount} disabled={disabled} />
        <Seg<SimMode>
          value={mode}
          onChange={onMode}
          disabled={disabled}
          options={[
            { value: "fast", label: "Fast", title: "Quick personas from the smaller model — about a minute for 50 twins" },
            { value: "pro", label: "Pro", title: "Richer personas from the larger model — a few minutes, and costlier" },
          ]}
        />
        <p className="hint -mt-1">{mode === "pro" ? "Pro: richer personas from the larger model — a few minutes for 50 twins, and costlier." : "Fast: quick personas — about a minute for 50 twins."}</p>
      </Section>

      <Divider />

      {/* Demographics */}
      <Section title="Who they are">
        <Row label="Age range" value={`${demo.age_min ?? 18} – ${demo.age_max ?? 75}`} basis={from.age_range || from.age_skew}>
          <div className="flex items-center gap-2">
            <input type="number" min={10} max={100} value={demo.age_min ?? 18} disabled={disabled} onChange={(e) => setDemo({ age_min: Math.min(+e.target.value || 10, (demo.age_max ?? 75) - 1) })} className="field field-sm w-14 text-center tabular-nums" />
            <Range min={10} max={100} value={demo.age_max ?? 75} onChange={(v) => setDemo({ age_max: Math.max(v, (demo.age_min ?? 18) + 1) })} disabled={disabled} />
            <input type="number" min={10} max={100} value={demo.age_max ?? 75} disabled={disabled} onChange={(e) => setDemo({ age_max: Math.max(+e.target.value || 100, (demo.age_min ?? 18) + 1) })} className="field field-sm w-14 text-center tabular-nums" />
          </div>
          <Seg
            value={(demo.age_skew ?? "even") as "even" | "younger" | "older"}
            onChange={(k) => setDemo({ age_skew: k })}
            disabled={disabled}
            options={[{ value: "even", label: "even spread" }, { value: "younger", label: "younger" }, { value: "older", label: "older" }]}
          />
        </Row>
        <Row label="Women" value={`${gender.female}%`} basis={from.gender}>
          <Range min={0} max={100} step={5} value={gender.female} onChange={(f) => { const other = gender.other; setDemo({ gender: { female: f, male: Math.max(0, 100 - f - other), other } }); }} disabled={disabled} />
          <div className="flex justify-between text-[10px] text-muted-foreground/50 -mt-0.5"><span>men {gender.male}%</span><span>non-binary {gender.other}%</span></div>
        </Row>
        <Row label="Where they live" value={demo.regions?.length ? `${demo.regions.length} place${demo.regions.length > 1 ? "s" : ""}` : "from the evidence"} muted={!demo.regions?.length} basis={from.regions}>
          <input
            value={(demo.regions ?? []).join(", ")}
            disabled={disabled}
            onChange={(e) => setDemo({ regions: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
            placeholder="Greater Manchester, Leeds — comma separated"
            className="field field-sm"
          />
        </Row>
        <div className="grid grid-cols-3 gap-2">
          <div><p className="eyebrow mb-1 inline-flex items-center">Settlement<FromResearch basis={from.urban_rural} compact /></p><Select disabled={disabled} value={demo.urban_rural ?? "mixed"} onChange={(v) => setDemo({ urban_rural: v as any })} options={[["mixed", "mixed"], ["urban", "urban"], ["suburban", "suburban"], ["rural", "rural"]]} /></div>
          <div><p className="eyebrow mb-1 inline-flex items-center">Income<FromResearch basis={from.income} compact /></p><Select disabled={disabled} value={demo.income ?? "mixed"} onChange={(v) => setDemo({ income: v as any })} options={[["mixed", "mixed"], ["low", "low"], ["middle", "middle"], ["high", "high"]]} /></div>
          <div><p className="eyebrow mb-1 inline-flex items-center">Education<FromResearch basis={from.education} compact /></p><Select disabled={disabled} value={demo.education ?? "mixed"} onChange={(v) => setDemo({ education: v as any })} options={[["mixed", "mixed"], ["secondary", "secondary"], ["degree", "degree"], ["postgraduate", "postgrad"]]} /></div>
        </div>
        <input value={demo.notes ?? ""} disabled={disabled} onChange={(e) => setDemo({ notes: e.target.value })} placeholder="Anything else about who they are" className="field field-sm" />
      </Section>

      <Divider />

      {/* Sentiment */}
      <Section title="How they feel">
        <SwitchRow
          on={sent.follow_evidence !== false}
          onChange={(v) => setSent({ follow_evidence: v })}
          disabled={disabled}
          title="Follow the evidence"
          hint={<>The observed for / against split sets the mood. Turn off to impose your own.{from.mood && <FromResearch basis={from.mood} />}</>}
        />
        {sent.follow_evidence === false && (
          <div className="space-y-2.5 pl-1 animate-fade-in">
            <Row label="For" value={`${mood.for}%`}>
              <Range min={0} max={100} step={5} value={mood.for} fill={FOR} onChange={(f) => { const ag = Math.min(mood.against, 100 - f); setSent({ mood: { for: f, against: ag, mixed: 100 - f - ag } }); }} disabled={disabled} />
            </Row>
            <Row label="Against" value={`${mood.against}%`}>
              <Range min={0} max={100} step={5} value={mood.against} fill={AGAINST} onChange={(ag) => { const f = Math.min(mood.for, 100 - ag); setSent({ mood: { for: f, against: ag, mixed: 100 - f - ag } }); }} disabled={disabled} />
            </Row>
            <div className="flex justify-between text-xs"><span className="text-muted-foreground">Mixed / undecided</span><span className="text-muted-foreground/70 tabular-nums">{mood.mixed}% auto</span></div>
          </div>
        )}
        <Dial label="Emotional temperature" value={sent.temperature ?? 5} onChange={(v) => setSent({ temperature: v })} lo="calm" hi="heated" disabled={disabled} basis={from.temperature} />
        <Dial label="Trust in institutions" value={sent.trust_in_institutions ?? 5} onChange={(v) => setSent({ trust_in_institutions: v })} lo="cynical" hi="trusting" disabled={disabled} basis={from.trust_in_institutions} />
        <Dial label="Price sensitivity" value={sent.price_sensitivity ?? 5} onChange={(v) => setSent({ price_sensitivity: v })} lo="price-blind" hi="every penny" disabled={disabled} basis={from.price_sensitivity} />
        <Dial label="Comfort with technology" value={sent.tech_savviness ?? 5} onChange={(v) => setSent({ tech_savviness: v })} lo="wary" hi="early adopter" disabled={disabled} basis={from.tech_savviness} />
        <Dial label="Openness to change" value={sent.openness_to_change ?? 5} onChange={(v) => setSent({ openness_to_change: v })} lo="set in their ways" hi="restless" disabled={disabled} basis={from.openness_to_change} />
      </Section>

      <Divider />

      {/* Stance */}
      <Section title="Stance mix">
        <SwitchRow
          on={st.follow_plan !== false}
          onChange={(v) => set({ stance: { ...st, follow_plan: v } })}
          disabled={disabled}
          title="Let the segments decide"
          hint="Stance follows each group's real relationship to the topic. Turn off to target a mix."
        />
        {st.follow_plan === false && (
          <div className="space-y-2.5 pl-1 animate-fade-in">
            <Row label="Direct" value={`${st.direct}%`}>
              <Range min={0} max={100} step={5} value={st.direct} onChange={(d) => { const i = Math.min(st.indirect, 100 - d); set({ stance: { ...st, direct: d, indirect: i, neutral: 100 - d - i } }); }} disabled={disabled} />
            </Row>
            <Row label="Indirect" value={`${st.indirect}%`}>
              <Range min={0} max={100} step={5} value={st.indirect} onChange={(i) => { const d = Math.min(st.direct, 100 - i); set({ stance: { ...st, direct: d, indirect: i, neutral: 100 - d - i } }); }} disabled={disabled} />
            </Row>
            <div className="flex justify-between text-xs"><span className="text-muted-foreground">Neutral</span><span className="text-muted-foreground/70 tabular-nums">{neutral}% auto</span></div>
          </div>
        )}
      </Section>

      <Divider />

      {/* Voice */}
      <Section title="Expert ↔ Reactive" aside={voice.auto ? "auto" : `${voice.value}`}>
        <SwitchRow
          on={voice.auto}
          onChange={(v) => set({ voice: { ...voice, auto: v } })}
          disabled={disabled}
          title="Let the system decide"
          hint="From the question: how measured or feeling-led the voices should be."
        />
        <div className={voice.auto ? "opacity-50" : ""}>
          <Range min={0} max={100} step={5} value={voice.value} onChange={(v) => set({ voice: { auto: false, value: v } })} disabled={disabled || voice.auto} />
          <div className="flex justify-between text-[10px] text-muted-foreground/60 -mt-0.5"><span>expert</span><span>natural</span><span>reactive</span></div>
        </div>
        <p className="hint">
          Shapes how the personas feel and speak — never who is in the population.{" "}
          {voice.auto
            ? "The plan chooses a value from the question and says why; set it yourself and re-plan to override."
            : voice.value >= 40 && voice.value <= 60
              ? "In the middle nothing is imposed: each group speaks in its natural register."
              : voice.value < 40
                ? "Toward expert: cooler sentiment, higher credibility, measured evidence-led descriptions."
                : "Toward reactive: hotter sentiment, lower credibility, people reacting from their own jobs, money and lives."}
        </p>
      </Section>
    </div>
  );
}
