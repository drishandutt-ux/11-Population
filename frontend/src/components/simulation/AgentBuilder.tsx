"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, AgentCharacter, AgentDials, AgentPreset, AuthoredAgentDraft, BuiltProfile, Session } from "@/lib/api";
import { stanceColor } from "@/lib/utils";
import {
  ArrowLeft, Wand2, Loader2, Bookmark, Check, AlertCircle, RotateCcw, UserPlus, Sparkles, MapPin, Brain, Heart,
} from "lucide-react";

/** The 112 dials, grouped — the same schema the backend's spawn prompts use (`agent_factory.DIALS_SCHEMA`). */
const DIAL_KEYS: Record<keyof AgentDials, string[]> = {
  sentiment: ["joy", "sadness", "anger", "fear", "disgust", "surprise", "trust", "anticipation", "pride", "shame", "guilt", "envy", "awe", "nostalgia", "relief", "boredom", "loneliness", "love", "hope", "anxiety", "confusion", "curiosity", "frustration"],
  motivation: ["desire", "urgency", "need_intensity", "aspiration", "self_improvement", "escape", "comfort", "pleasure", "mastery", "autonomy", "status", "belonging", "security", "novelty", "convenience", "control"],
  habit: ["cue_strength", "action_simplicity", "reward_immediacy", "reward_intensity", "repeat_frequency", "environmental_fit", "ritual_potential", "dependency_risk", "switching_cost", "routine_compatibility", "habit_pull"],
  trust: ["credibility", "transparency", "social_proof", "authority", "consistency", "privacy_comfort", "safety", "fairness", "reliability", "reversibility", "guarantee_strength"],
  friction: ["cognitive_load", "time_cost", "money_pain", "ambiguity", "choice_overload", "technical_difficulty", "emotional_resistance", "embarrassment_risk", "social_risk", "regret_risk", "friction"],
  identity: ["self_fit", "tribe_fit", "values_fit", "aesthetic_fit", "cultural_fit", "life_stage_fit", "status_lift", "taste_fit", "belonging_fit", "identity_fit"],
  commercial: ["purchase_intent", "willingness_to_pay", "perceived_value", "premium_justification", "repeat_intent", "referral_intent", "churn_risk", "upgrade_intent", "objection_intensity", "price_pain"],
  product: ["ease", "reward_clarity", "shareability", "delight", "usefulness", "memorability", "clarity", "confidence", "satisfaction", "emotional_fit"],
  composite: ["human_resonance", "product_emotional_fit", "retention_potential", "share_potential", "desire_trust", "habit_potential", "virality_potential", "product_humanity", "emotional_risk", "adoption_readiness"],
};
const GROUPS: { key: keyof AgentDials; label: string; accent: string; text: string; hint: string }[] = [
  { key: "sentiment", label: "Sentiment", accent: "accent-rose-500", text: "text-rose-400", hint: "How they feel about the topic right now" },
  { key: "motivation", label: "Motivation", accent: "accent-amber-500", text: "text-amber-400", hint: "What drives their engagement" },
  { key: "habit", label: "Habit", accent: "accent-emerald-500", text: "text-emerald-400", hint: "Their patterns around this category" },
  { key: "trust", label: "Trust", accent: "accent-blue-500", text: "text-blue-400", hint: "Trust and scepticism" },
  { key: "friction", label: "Friction", accent: "accent-red-500", text: "text-red-400", hint: "The barriers they personally hit" },
  { key: "identity", label: "Identity", accent: "accent-purple-500", text: "text-purple-400", hint: "How far the topic fits who they are" },
  { key: "commercial", label: "Commercial", accent: "accent-teal-500", text: "text-teal-400", hint: "Their commercial relationship with this space" },
  { key: "product", label: "Product experience", accent: "accent-cyan-500", text: "text-cyan-400", hint: "How they experience products and services here" },
  { key: "composite", label: "Composite", accent: "accent-indigo-500", text: "text-indigo-400", hint: "Aggregates the system derives from the rest" },
];
const DIAL_TOTAL = Object.values(DIAL_KEYS).reduce((n, k) => n + k.length, 0);

type CharacterTextKey = Exclude<keyof AgentCharacter, "archetype">;
const CHARACTER_FIELDS: { key: CharacterTextKey; label: string; placeholder: string }[] = [
  { key: "decision_rules", label: "How they decide", placeholder: "The rules of thumb, in order. e.g. Guideline first, then what the local formulary allows, then what the last patient complained about." },
  { key: "behaviour", label: "How they behave", placeholder: "Who they defer to, what they ignore, how fast they change their mind, what they do under pressure." },
  { key: "vocabulary", label: "How they talk", placeholder: "The words and register they use — and the words they never use." },
  { key: "information_diet", label: "Where their information comes from", placeholder: "NICE, the local prescribing lead, reps, peers, patient forums, the Daily Mail…" },
  { key: "failure_modes", label: "Where they go wrong", placeholder: "The predictable mistakes: over-trusting a colleague, misreading a leaflet, dropping a regimen when life gets busy." },
];

function humanityBand(h: number) {
  if (h < 25) return "expert";
  if (h < 50) return "tempered";
  if (h < 60) return "balanced";
  if (h < 72) return "defensive";
  return "reactive";
}
function toLabel(key: string) {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

type Text = {
  name: string; age: string; role: string; background: string; correlation: string; personality: string; debate_style: string;
  stance: "direct" | "indirect" | "neutral";
  gender: string; region: string; income_band: string; education: string; geo_behavior: string;
  character: AgentCharacter;
};
const EMPTY: Text = {
  name: "", age: "", role: "", background: "", correlation: "", personality: "", debate_style: "", stance: "neutral",
  gender: "", region: "", income_band: "", education: "", geo_behavior: "", character: {},
};
type Fixed = Record<string, number>; // "group.key" → value the analyst set by hand

const field = "w-full bg-muted/50 border border-border rounded-lg px-3 py-2 text-sm text-foreground placeholder-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-primary/40";
const label = "text-[11px] font-medium text-muted-foreground";

function Field({ l, children, hint }: { l: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="block space-y-1">
      <span className={label}>{l}{hint && <span className="text-muted-foreground/50 font-normal"> · {hint}</span>}</span>
      {children}
    </label>
  );
}

/** Build your own agent: the person in words on the left, the 112 dials on the right, and a lineup to join at the bottom. */
export default function AgentBuilder({ sessionId }: { sessionId: string }) {
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const [text, setText] = useState<Text>(EMPTY);
  const [humanity, setHumanity] = useState(50);
  const [humanityFixed, setHumanityFixed] = useState(false);
  const [fixed, setFixed] = useState<Fixed>({});
  const [built, setBuilt] = useState<AgentDials | null>(null);
  const [reading, setReading] = useState("");
  const [building, setBuilding] = useState(false);
  const [openGroup, setOpenGroup] = useState<keyof AgentDials>("sentiment");
  const [presets, setPresets] = useState<AgentPreset[]>([]);
  const [target, setTarget] = useState<"new" | "existing">("new");
  const [newName, setNewName] = useState("");
  const [presetId, setPresetId] = useState("");
  const [saving, setSaving] = useState<"" | "building" | "saving">("");
  // Also keep the agent as an archetype: a mould the Studio casts a whole segment from (L3-02).
  const [asArchetype, setAsArchetype] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<{ agent: string; lineup: string; count: number; archetype: boolean } | null>(null);
  // The profile was built from an earlier version of the text.
  const builtFromRef = useRef<string>("");

  useEffect(() => {
    api.sessions.get(sessionId).then((s) => setSession(s as Session)).catch(() => {});
    api.presets.list().then((p) => { setPresets(p); if (p.length && !presetId) setPresetId(p[0].id); }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const set = (patch: Partial<Text>) => setText((t) => ({ ...t, ...patch }));
  const setChar = (k: CharacterTextKey, v: string) => setText((t) => ({ ...t, character: { ...t.character, [k]: v } }));

  const fixedCount = Object.keys(fixed).length;
  const autoCount = DIAL_TOTAL - fixedCount;
  const textKey = JSON.stringify({ text, humanity: humanityFixed ? humanity : null });
  const stale = built !== null && builtFromRef.current !== textKey;
  const ready = text.name.trim() && text.role.trim() && text.background.trim();

  const valueOf = (g: keyof AgentDials, k: string): number | null => {
    const id = `${g}.${k}`;
    if (id in fixed) return fixed[id];
    const v = built?.[g]?.[k];
    return typeof v === "number" ? v : null;
  };
  const fixDial = (g: keyof AgentDials, k: string, v: number) => setFixed((f) => ({ ...f, [`${g}.${k}`]: v }));
  const releaseDial = (g: keyof AgentDials, k: string) => setFixed((f) => { const n = { ...f }; delete n[`${g}.${k}`]; return n; });
  const releaseGroup = (g: keyof AgentDials) => setFixed((f) => Object.fromEntries(Object.entries(f).filter(([id]) => !id.startsWith(`${g}.`))));

  function fixedAsDials(): AgentDials {
    const out: AgentDials = {};
    for (const [id, v] of Object.entries(fixed)) {
      const [g, k] = id.split(".") as [keyof AgentDials, string];
      (out[g] ??= {})[k] = v;
    }
    return out;
  }
  function fullDials(): AgentDials | null {
    const out: AgentDials = {};
    for (const g of GROUPS.map((x) => x.key)) {
      out[g] = {};
      for (const k of DIAL_KEYS[g]) {
        const v = valueOf(g, k);
        if (v === null) return null;
        out[g]![k] = v;
      }
    }
    return out;
  }
  function draft(withDials: AgentDials | null, h: number): AuthoredAgentDraft {
    return {
      name: text.name.trim(), age: text.age ? +text.age : undefined, role: text.role.trim(), background: text.background.trim(),
      stance: text.stance, correlation: text.correlation.trim(), personality: text.personality, debate_style: text.debate_style.trim(),
      humanity: h, humanity_fixed: humanityFixed,
      demographics: { gender: text.gender.trim(), region: text.region.trim(), income_band: text.income_band.trim(), education: text.education.trim(), geo_behavior: text.geo_behavior.trim() },
      character: text.character,
      dials: withDials ?? fixedAsDials(),
    };
  }

  async function build(): Promise<BuiltProfile> {
    setBuilding(true);
    setError(null);
    try {
      const p = await api.agents.buildProfile(sessionId, draft(null, humanity));
      setBuilt(p.dials);
      setReading(p.reading);
      if (!humanityFixed) setHumanity(p.humanity);
      builtFromRef.current = textKey;
      return p;
    } finally {
      setBuilding(false);
    }
  }
  async function onBuild() {
    if (!ready) { setError("Give the agent a name, a job and a description first — the profile is read from them."); return; }
    try { await build(); } catch (e: any) { setError(e.message || "Couldn't build the profile"); }
  }

  async function onSave() {
    if (!ready) { setError("Give the agent a name, a job and a description before saving."); return; }
    if (target === "new" && !newName.trim()) { setError("Name the new lineup."); return; }
    if (target === "existing" && !presetId) { setError("Pick a lineup to add to."); return; }
    setError(null);
    setSaved(null);
    try {
      let dials = fullDials();
      let h = humanity;
      if (dials === null || stale) {
        // Some dials are still the system's to set (or the text moved since the last build): build first.
        setSaving("building");
        const p = await build();
        dials = { ...p.dials };
        for (const [id, v] of Object.entries(fixed)) { const [g, k] = id.split(".") as [keyof AgentDials, string]; (dials[g] ??= {})[k] = v; }
        h = humanityFixed ? humanity : p.humanity;
      }
      setSaving("saving");
      const body = draft(dials, h);
      const preset = target === "new" ? await api.presets.createCustom(newName.trim(), [body], asArchetype) : await api.presets.addAgents(presetId, [body], asArchetype);
      setPresets((prev) => target === "new" ? [preset, ...prev] : prev.map((p) => (p.id === preset.id ? preset : p)));
      setSaved({ agent: body.name, lineup: preset.name, count: preset.agent_count, archetype: asArchetype });
      if (target === "new") { setTarget("existing"); setPresetId(preset.id); setNewName(""); }
    } catch (e: any) {
      setError(e.message || "Couldn't save the agent");
    } finally {
      setSaving("");
    }
  }
  function startAnother() {
    setText(EMPTY); setHumanity(50); setHumanityFixed(false); setFixed({}); setBuilt(null); setReading(""); setSaved(null); setError(null);
    builtFromRef.current = "";
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  const back = () => router.push(`/session/${sessionId}?tab=agents`);
  const busy = building || saving !== "";
  const band = humanityBand(humanity);
  const topSentiments = useMemo(() => DIAL_KEYS.sentiment.map((k) => [k, valueOf("sentiment", k)] as const).filter(([, v]) => v !== null && v >= 6).sort((a, b) => (b[1]! - a[1]!)).slice(0, 3), [fixed, built]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border px-6 py-4 flex items-center gap-4 sticky top-0 bg-background/90 backdrop-blur z-10">
        <button onClick={back} className="text-muted-foreground hover:text-foreground" title="Back to the Agents tab"><ArrowLeft className="w-5 h-5" /></button>
        <div className="flex-1 min-w-0">
          <h1 className="font-semibold text-foreground flex items-center gap-2"><UserPlus className="w-4 h-4 text-primary" /> Build your own agent</h1>
          <p className="text-[11px] text-muted-foreground truncate">Dials are tuned relative to: <span className="text-foreground/80">{session?.query || "…"}</span></p>
        </div>
        <span className="text-[11px] text-muted-foreground tabular-nums">{fixedCount} dials set by hand · {autoCount} by the system</span>
      </header>

      <div className="max-w-6xl mx-auto px-6 py-6 grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_400px] gap-6">
        {/* ── The person, in words ── */}
        <div className="space-y-5">
          <section className="glass rounded-2xl p-5 space-y-4">
            <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Who they are</h2>
            <div className="grid grid-cols-1 sm:grid-cols-[minmax(0,1fr)_90px] gap-3">
              <Field l="Name"><input className={field} value={text.name} onChange={(e) => set({ name: e.target.value })} placeholder="Dr Ann Okafor" /></Field>
              <Field l="Age"><input className={field} type="number" min={16} max={100} value={text.age} onChange={(e) => set({ age: e.target.value })} placeholder="47" /></Field>
            </div>
            <Field l="Job / role"><input className={field} value={text.role} onChange={(e) => set({ role: e.target.value })} placeholder="GP partner in a coastal practice" /></Field>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Field l="Gender"><input className={field} value={text.gender} onChange={(e) => set({ gender: e.target.value })} placeholder="woman" /></Field>
              <Field l="Lives in" hint="a real place"><input className={field} value={text.region} onChange={(e) => set({ region: e.target.value })} placeholder="Blackpool, UK" /></Field>
              <Field l="Household income"><input className={field} value={text.income_band} onChange={(e) => set({ income_band: e.target.value })} placeholder="middle" /></Field>
              <Field l="Education"><input className={field} value={text.education} onChange={(e) => set({ education: e.target.value })} placeholder="medical degree" /></Field>
            </div>
            <Field l="Description" hint="2–3 sentences of background"><textarea className={`${field} min-h-[84px]`} value={text.background} onChange={(e) => set({ background: e.target.value })} placeholder="Twenty years in the same practice; runs a list in one of the most deprived wards in England…" /></Field>
            <Field l="Relationship to the topic"><input className={field} value={text.correlation} onChange={(e) => set({ correlation: e.target.value })} placeholder="Prescribes the drug class in question every week." /></Field>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Field l="Personality" hint="comma-separated"><input className={field} value={text.personality} onChange={(e) => set({ personality: e.target.value })} placeholder="blunt, tired, loyal" /></Field>
              <Field l="Debate style"><input className={field} value={text.debate_style} onChange={(e) => set({ debate_style: e.target.value })} placeholder="Leads with a patient story, then the guideline." /></Field>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Field l="Stance" hint="their stake in the topic">
                <div className="flex gap-1.5">
                  {(["direct", "indirect", "neutral"] as const).map((s) => (
                    <button key={s} type="button" onClick={() => set({ stance: s })} className={`flex-1 text-xs px-2 py-1.5 rounded-lg border transition-colors ${text.stance === s ? stanceColor(s) : "border-border/50 text-muted-foreground hover:text-foreground"}`}>{s}</button>
                  ))}
                </div>
              </Field>
              <Field l="Expert ↔ Reactive" hint={humanityFixed ? `${humanity} · ${band}` : built ? `system: ${humanity} · ${band}` : "left to the system"}>
                <div className="flex items-center gap-2">
                  <Brain className="w-3.5 h-3.5 text-muted-foreground/60 shrink-0" />
                  <input type="range" min={0} max={100} value={humanity} onChange={(e) => { setHumanity(+e.target.value); setHumanityFixed(true); }} className={`flex-1 accent-pink-500 cursor-pointer h-1.5 ${humanityFixed ? "" : "opacity-50"}`} />
                  <Heart className="w-3.5 h-3.5 text-pink-400/70 shrink-0" />
                  {humanityFixed && <button type="button" onClick={() => setHumanityFixed(false)} className="text-[10px] text-muted-foreground hover:text-foreground" title="Leave it to the system">auto</button>}
                </div>
              </Field>
            </div>
            <Field l="How their place shapes them" hint="written to them as “you”"><textarea className={`${field} min-h-[64px]`} value={text.geo_behavior} onChange={(e) => set({ geo_behavior: e.target.value })} placeholder="You see the deprivation daily; you measure any new drug by whether your patients will actually collect it…" /></Field>
          </section>

          <section className="glass rounded-2xl p-5 space-y-4">
            <div>
              <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Character</h2>
              <p className="text-[11px] text-muted-foreground/70 mt-0.5">Optional. These go into the persona&apos;s prompt word for word, as rules it must not contradict.</p>
            </div>
            {CHARACTER_FIELDS.map(({ key, label: l, placeholder }) => (
              <Field key={key} l={l}><textarea className={`${field} min-h-[56px]`} value={text.character[key] || ""} onChange={(e) => setChar(key, e.target.value)} placeholder={placeholder} /></Field>
            ))}
          </section>
        </div>

        {/* ── The dials ── */}
        <div className="space-y-4 lg:sticky lg:top-20 self-start">
          <section className="glass rounded-2xl p-4 space-y-3">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Sentiment profile</h2>
              {fixedCount > 0 && <button type="button" onClick={() => setFixed({})} className="text-[10px] text-muted-foreground hover:text-foreground flex items-center gap-1" title="Leave every dial to the system"><RotateCcw className="w-3 h-3" /> all auto</button>}
            </div>
            <p className="text-[11px] text-muted-foreground/80 leading-relaxed">
              Move a dial to set it by hand; leave the rest to the system. <span className="text-foreground/80">Build sentiment profile</span> reads what you wrote and tunes every dial you left alone.
            </p>
            <button type="button" onClick={onBuild} disabled={busy} className="w-full flex items-center justify-center gap-2 text-sm font-semibold px-4 py-2.5 rounded-xl bg-primary/10 border border-primary/25 text-primary hover:bg-primary/20 disabled:opacity-50 transition-colors">
              {building ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />} {built ? "Rebuild sentiment profile" : "Build sentiment profile"}
            </button>
            {reading && (
              <div className={`text-[11px] leading-relaxed rounded-lg px-3 py-2 border ${stale ? "border-yellow-500/25 bg-yellow-500/5 text-yellow-200/90" : "border-primary/20 bg-primary/5 text-foreground/80"}`}>
                <Sparkles className="w-3 h-3 inline mr-1 -mt-0.5" />{reading}{stale && <span className="block mt-1 text-yellow-300/80">Built before your latest edits — saving rebuilds it.</span>}
              </div>
            )}
            {topSentiments.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {topSentiments.map(([k, v]) => <span key={k} className="text-[10px] px-1.5 py-0.5 rounded border border-rose-500/30 text-rose-300 bg-rose-500/10">{toLabel(k)} {v}</span>)}
              </div>
            )}
          </section>

          <section className="glass rounded-2xl p-2 max-h-[52vh] overflow-y-auto">
            {GROUPS.map((g) => {
              const keys = DIAL_KEYS[g.key];
              const setHere = keys.filter((k) => `${g.key}.${k}` in fixed).length;
              const open = openGroup === g.key;
              return (
                <div key={g.key} className="border-b border-border/30 last:border-0">
                  <button type="button" onClick={() => setOpenGroup(g.key)} className="w-full flex items-center gap-2 px-2 py-2 text-left">
                    <span className={`text-xs font-semibold ${g.text}`}>{g.label}</span>
                    <span className="text-[10px] text-muted-foreground/60 truncate flex-1">{g.hint}</span>
                    <span className="text-[10px] text-muted-foreground tabular-nums">{setHere ? `${setHere} set` : "auto"}</span>
                  </button>
                  {open && (
                    <div className="px-2 pb-2 space-y-1.5">
                      {setHere > 0 && <button type="button" onClick={() => releaseGroup(g.key)} className="text-[10px] text-muted-foreground hover:text-foreground">leave this group to the system</button>}
                      {keys.map((k) => {
                        const id = `${g.key}.${k}`;
                        const isFixed = id in fixed;
                        const v = valueOf(g.key, k);
                        return (
                          <div key={k} className="flex items-center gap-2">
                            <span className="text-[11px] text-muted-foreground w-[132px] truncate" title={toLabel(k)}>{toLabel(k)}</span>
                            <input type="range" min={0} max={10} step={1} value={v ?? 5} onChange={(e) => fixDial(g.key, k, +e.target.value)} className={`flex-1 ${g.accent} cursor-pointer h-1.5 ${isFixed ? "" : v === null ? "opacity-30" : "opacity-60"}`} title={isFixed ? "Set by hand" : v === null ? "Left to the system" : "Set by the system — move it to take over"} />
                            <span className={`text-[10px] w-7 text-right tabular-nums ${isFixed ? "text-foreground font-semibold" : "text-muted-foreground/70"}`}>{v === null ? "auto" : v}</span>
                            <button type="button" onClick={() => releaseDial(g.key, k)} className={`text-[10px] w-7 text-left ${isFixed ? "text-muted-foreground hover:text-foreground" : "invisible"}`} title="Leave this dial to the system">auto</button>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </section>
        </div>
      </div>

      {/* ── Join a lineup ── */}
      <div className="sticky bottom-0 border-t border-border bg-background/95 backdrop-blur px-6 py-4">
        <div className="max-w-6xl mx-auto space-y-2">
          {error && <div className="flex items-center gap-2 text-xs text-red-300 bg-red-500/10 border border-red-500/25 rounded-xl px-3 py-2"><AlertCircle className="w-4 h-4 shrink-0" /> {error}</div>}
          {saved && (
            <div className="flex items-center gap-3 text-xs text-emerald-200 bg-emerald-500/10 border border-emerald-500/25 rounded-xl px-3 py-2">
              <Check className="w-4 h-4 shrink-0" />
              <span className="flex-1"><span className="font-semibold">{saved.agent}</span> joined <span className="font-semibold">{saved.lineup}</span> ({saved.count} agent{saved.count === 1 ? "" : "s"}){saved.archetype ? " and is now an archetype the Studio can cast from" : ""}. Load the lineup from the Agents tab to bring them into this session.</span>
              <button type="button" onClick={startAnother} className="text-emerald-100 hover:text-white underline underline-offset-2">Build another</button>
              <button type="button" onClick={back} className="text-emerald-100 hover:text-white underline underline-offset-2">Back to agents</button>
            </div>
          )}
          <div className="flex flex-col sm:flex-row sm:items-center gap-3">
            <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground"><Bookmark className="w-3.5 h-3.5 text-primary" /> An agent always belongs to a lineup:</div>
            <div className="flex gap-1.5">
              <button type="button" onClick={() => setTarget("new")} className={`text-xs px-2.5 py-1.5 rounded-lg border ${target === "new" ? "border-primary/50 bg-primary/10 text-primary" : "border-border/50 text-muted-foreground hover:text-foreground"}`}>New lineup</button>
              <button type="button" onClick={() => setTarget("existing")} disabled={presets.length === 0} className={`text-xs px-2.5 py-1.5 rounded-lg border disabled:opacity-40 ${target === "existing" ? "border-primary/50 bg-primary/10 text-primary" : "border-border/50 text-muted-foreground hover:text-foreground"}`} title={presets.length === 0 ? "No saved lineups yet" : undefined}>Add to existing</button>
            </div>
            {target === "new" ? (
              <input className={`${field} sm:max-w-xs`} value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Name the new lineup…" />
            ) : (
              <select className={`${field} sm:max-w-xs`} value={presetId} onChange={(e) => setPresetId(e.target.value)}>
                {presets.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.agent_count} agent{p.agent_count === 1 ? "" : "s"}</option>)}
              </select>
            )}
            <button type="button" onClick={onSave} disabled={busy} className="sm:ml-auto flex items-center justify-center gap-2 text-sm font-semibold px-5 py-2.5 rounded-xl bg-primary hover:bg-primary/90 text-primary-foreground disabled:opacity-50 transition-colors">
              {saving === "building" ? <><Loader2 className="w-4 h-4 animate-spin" /> Building profile…</> : saving === "saving" ? <><Loader2 className="w-4 h-4 animate-spin" /> Saving…</> : <><UserPlus className="w-4 h-4" /> {target === "new" ? "Save to new lineup" : "Add to lineup"}</>}
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-pointer" title="The Population Studio matches segments to archetypes by job and casts every persona in the segment from the mould: your character rules, temperament and dials stay, the model writes only names, life stories and places">
              <input type="checkbox" checked={asArchetype} onChange={(e) => setAsArchetype(e.target.checked)} className="accent-primary" />
              Use as an archetype the Studio can cast a segment from
            </label>
            {autoCount > 0 && !built && <p className="text-[10px] text-muted-foreground/60 flex items-center gap-1"><MapPin className="w-3 h-3" /> {autoCount} dial{autoCount === 1 ? "" : "s"} still belong to the system — saving builds the profile first.</p>}
          </div>
        </div>
      </div>
    </div>
  );
}
