"use client";

/** 11 Minds City — the living town and its dashboard (2026-11-05).
 *
 *  The 3D engine (engine.ts, loaded client-side only) draws the plan; the simulation (sim.ts)
 *  runs the twins' own answers forward. The dashboard is plain React over the canvas, in the
 *  world-builder "sketch" style: paper cards, ink borders, a handwritten title face.
 *
 *  Before Launch the town just lives. Launch starts a run from Monday morning with the levers
 *  ticked; "Test instantly" runs the same days off-screen for the baseline, each lever alone and
 *  all together, so the effect of each one can be compared like for like. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CityPlan, ProbeAnswerRow } from "@/lib/api";
import { City, Resident, RunSummary, THRESHOLD } from "./sim";
import type { CityEngine, Pick } from "./engine";
import type { Lot } from "./layout";

const SIM_PER_SEC = 2; // sim minutes per real second at 1×
const SPEEDS: [string, number][] = [["⏸", 0], ["▶", 1], ["⏩", 4], ["⏭", 16], ["⚡", 60]];
const LEVER_ICON: Record<string, string> = { poster: "📣", tv: "📺", social: "📱", radio: "📻", leaflet: "✉️", advice: "🩺", event: "🎪", price: "🏷️", hours: "🕘", word_of_mouth: "🗣️" };
const KIND_ICON: Record<string, string> = {
  hospital: "🏥", gp: "🩺", pharmacy: "💊", clinic: "⚕️", supermarket: "🛒", shop: "🛍️", pub: "🍺", cafe: "☕", restaurant: "🍽️",
  takeaway: "🍟", office: "🏢", factory: "🏭", school: "🏫", college: "🎓", park: "🌳", church: "⛪", gym: "🏋️", community: "🏛️",
  station: "🚉", bank: "🏦", salon: "💇", betting: "🎰", house: "🏠", flats: "🏢",
};
const pct = (a: number, b: number) => (b ? Math.round((a / b) * 100) : 0);

type Props = { plan: CityPlan; answers: ProbeAnswerRow[]; seed: number; onBack: () => void; note?: string };

export default function CityWorld({ plan, answers, seed, onBack, note }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const engineRef = useRef<CityEngine | null>(null);
  const city = useMemo(() => new City(plan, answers, seed || 1), [plan, answers, seed]);
  const [, setTick] = useState(0);
  const [speed, setSpeed] = useState(4);
  const speedRef = useRef(speed); speedRef.current = speed;
  const [selected, setSelected] = useState<Pick>(null);
  const [hover, setHover] = useState<{ p: Pick; x: number; y: number } | null>(null);
  const [levers, setLevers] = useState<string[]>(() => plan.levers.map((l) => l.id));
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [testing, setTesting] = useState(false);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [panel, setPanel] = useState<"levers" | "results">("levers");
  const accent = "#E8452C";
  const finishedRef = useRef(false);

  // Fonts for the sketch style (falls back to a cursive face if blocked).
  useEffect(() => {
    if (document.getElementById("city-fonts")) return;
    const l = document.createElement("link");
    l.id = "city-fonts"; l.rel = "stylesheet";
    l.href = "https://fonts.googleapis.com/css2?family=Pangolin&display=swap";
    document.head.appendChild(l);
  }, []);

  // The engine and the loop.
  useEffect(() => {
    let raf = 0, alive = true, last = performance.now(), ui = 0;
    (async () => {
      try {
        const { CityEngine } = await import("./engine");
        if (!alive || !host.current) return;
        const eng = new CityEngine(host.current, city, accent, {
          onHover: (p, x, y) => setHover(p ? { p, x, y } : null),
          onSelect: (p) => setSelected(p),
        });
        engineRef.current = eng;
        if (process.env.NODE_ENV !== "production") (window as any).__city = { city, eng };
        const loop = (now: number) => {
          const real = (now - last) / 1000; last = now;
          const rdt = Math.min(0.05, real);
          const sp = speedRef.current;
          // The clock keeps time on a slow machine (up to a quarter-second per frame); drawing is clamped separately.
          if (sp > 0) city.step(Math.min(0.25, real) * SIM_PER_SEC * sp);
          eng.frame(rdt);
          ui += rdt;
          if (ui > 0.25) { ui = 0; setTick((t) => t + 1); }
          raf = requestAnimationFrame(loop);
        };
        raf = requestAnimationFrame(loop);
      } catch (e: any) {
        setLoadErr(e?.message || "The 3D view could not start on this device.");
      }
    })();
    return () => { alive = false; cancelAnimationFrame(raf); engineRef.current?.dispose(); engineRef.current = null; };
  }, [city]);

  // A watched run that reaches its last day is recorded with the others.
  useEffect(() => {
    if (city.finished && !finishedRef.current) {
      finishedRef.current = true;
      const s = city.summary(labelFor(plan, Array.from(city.levers)) + " (watched)");
      setRuns((r) => [s, ...r.filter((x) => x.label !== s.label)]);
      setPanel("results");
    }
  });

  const select = useCallback((p: Pick) => { setSelected(p); engineRef.current?.select(p); }, []);
  // Keys: + / − zoom, 0 sees everything, Esc lets go of whoever is selected.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest?.("input,textarea")) return;
      const eng = engineRef.current; if (!eng) return;
      if (e.key === "+" || e.key === "=") eng.zoomBy(0.6);
      else if (e.key === "-" || e.key === "_") eng.zoomBy(1.6);
      else if (e.key === "0") { select(null); eng.flyToAll(); }
      else if (e.key === "Escape") select(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [select]);
  const launch = () => {
    finishedRef.current = false;
    city.launch(levers);
    setSelected(null);
    if (speed === 0) setSpeed(4);
  };
  /** Baseline, each lever alone, and all together — off-screen, same seed, same days. */
  const testAll = async () => {
    setTesting(true);
    await new Promise((r) => setTimeout(r, 30));
    const combos: string[][] = [[], ...plan.levers.map((l) => [l.id])];
    if (plan.levers.length > 1) combos.push(plan.levers.map((l) => l.id));
    if (levers.length && levers.length < plan.levers.length && levers.length > 1) combos.push(levers);
    const out: RunSummary[] = [];
    for (const c of combos) {
      const sim = new City(plan, answers, seed || 1);
      sim.launch(c);
      sim.fastForward();
      out.push(sim.summary(labelFor(plan, c)));
      await new Promise((r) => setTimeout(r, 0));
    }
    setRuns((prev) => [...out, ...prev.filter((p) => p.label.endsWith("(watched)"))]);
    setTesting(false);
    setPanel("results");
  };

  const n = city.residents.length;
  const done = city.acts.length;
  const out = city.residents.filter((r) => r.activity === "walking" || r.activity === "at").length;
  const heard = city.residents.filter((r) => r.heard.size > 0).length;
  const mood = n ? Math.round(city.residents.reduce((a, r) => a + r.mood, 0) / n) : 0;
  const f = city.funnel();
  const day = city.runDay();

  return (
    <div className="city-root fixed inset-0 z-50">
      <div ref={host} className="absolute inset-0" />
      {loadErr && <div className="absolute inset-0 grid place-items-center"><div className="city-card p-6 max-w-sm text-center"><div className="city-title">The city could not open</div><p className="mt-2 text-[13px]">{loadErr}</p><button className="city-btn mt-4" onClick={onBack}>Back</button></div></div>}

      {/* Top bar */}
      <div className="city-card city-topbar">
        <button className="city-btn city-btn-quiet" onClick={onBack} title="Back to the Lab">←</button>
        <div className="city-logo" />
        <div className="min-w-0">
          <div className="city-title truncate">{plan.title}</div>
          <div className="text-[11px] city-muted truncate">11 Minds City · {n} people · {plan.outcome_label}</div>
        </div>
        <div className="flex-1" />
        <div className="hidden md:flex gap-1">
          {city.towns.length > 1 && <button className="city-pill" onClick={() => { setSelected(null); engineRef.current?.flyToAll(); }}>All</button>}
          {city.towns.map((t) => <button key={t.id} className="city-pill" onClick={() => { setSelected(null); engineRef.current?.flyToTown(t.id); }}>{t.name}</button>)}
        </div>
        <div className="hidden sm:flex gap-1">
          {SPEEDS.map(([icon, s]) => <button key={s} className={`city-pill ${speed === s ? "on" : ""}`} onClick={() => setSpeed(s)} title={s ? `${s}×` : "Pause"}>{icon}</button>)}
        </div>
        <div className="city-clock">{city.launched ? `Day ${Math.min(day, plan.days)}/${plan.days} · ` : ""}{city.clock()}</div>
        <button className={`city-pill ${city.weather === "rain" ? "on" : ""}`} onClick={() => { city.weather = city.weather === "rain" ? "clear" : "rain"; setTick((t) => t + 1); }} title="Weather">{city.weather === "rain" ? "🌧" : "☀︎"}</button>
      </div>

      {/* KPIs */}
      <div className="city-kpis">
        <Kpi icon="✅" label={`Have ${plan.outcome_label}`} value={`${done}`} sub={city.launched ? `${pct(done, n)}% of ${n}` : "launch to start counting"} />
        <Kpi icon="🚶" label="Out and about" value={`${out}`} sub={`${pct(out, n)}% right now`} />
        <Kpi icon="👂" label="Heard of it" value={`${heard}`} sub={city.launched ? `${pct(heard, n)}% met a lever` : "nothing launched"} />
        <Kpi icon="🙂" label="Average mood" value={`${mood}`} sub="0 low · 100 great" />
      </div>

      {/* Feed */}
      <div className="city-feed hidden lg:flex">
        {city.feed.slice(0, 4).map((it, i) => {
          const r = it.who ? city.byId[it.who] : null;
          return (
            <div key={`${it.t}-${i}`} className="city-card city-post">
              <div className="city-av" style={{ background: r?.color || "#ddd" }}>{r ? initials(r.name) : "🏙"}</div>
              <div className="min-w-0">
                <div className="flex justify-between gap-2 text-[11px] font-semibold"><span className="truncate">{r ? r.name : "City"}</span><span className="city-muted font-normal shrink-0">{city.clock(it.t)}</span></div>
                <p className="text-[12.5px] leading-snug">{it.text}</p>
                {r && <button className="city-link text-[11px]" onClick={() => select({ type: "resident", resident: r })}>📍 show</button>}
              </div>
            </div>
          );
        })}
      </div>

      {/* Right panel: a twin, a place, or the levers and results */}
      <div className="city-card city-side">
        {selected?.type === "resident" ? (
          <ResidentCard r={selected.resident} city={city} onClose={() => select(null)} onPlace={(lot) => select({ type: "lot", lot })} />
        ) : selected?.type === "lot" ? (
          <LotCard lot={selected.lot} city={city} onClose={() => select(null)} onResident={(r) => select({ type: "resident", resident: r })} />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-1 mb-3">
              <button className={`city-pill justify-center ${panel === "levers" ? "on" : ""}`} onClick={() => setPanel("levers")}>Levers</button>
              <button className={`city-pill justify-center ${panel === "results" ? "on" : ""}`} onClick={() => setPanel("results")}>Results{runs.length ? ` (${runs.length})` : ""}</button>
            </div>
            {panel === "levers" ? (
              <div className="space-y-3">
                <div>
                  <div className="city-title">What to try</div>
                  <p className="text-[12px] city-muted mt-0.5">Tick the levers, then launch. The town goes back to Monday morning and runs {plan.days} days.</p>
                </div>
                <div className="space-y-2">
                  {plan.levers.map((lv) => (
                    <label key={lv.id} className={`city-lever ${levers.includes(lv.id) ? "on" : ""}`}>
                      <input type="checkbox" checked={levers.includes(lv.id)} onChange={(e) => setLevers((ls) => (e.target.checked ? [...ls, lv.id] : ls.filter((x) => x !== lv.id)))} />
                      <div className="min-w-0">
                        <div className="text-[13px] font-semibold">{LEVER_ICON[lv.kind] || "•"} {lv.label}</div>
                        {lv.detail && <div className="text-[11.5px] leading-snug mt-0.5">{lv.detail}</div>}
                        {lv.why && <div className="text-[11px] city-muted leading-snug mt-0.5">Why: {lv.why}</div>}
                      </div>
                    </label>
                  ))}
                </div>
                <button className="city-cta" onClick={launch}>🚀 {city.launched ? "Launch again" : "Launch"} and watch</button>
                <button className="city-btn w-full" onClick={testAll} disabled={testing}>{testing ? "Running the days…" : "⚡ Test each lever instantly"}</button>
                <p className="text-[10.5px] city-muted leading-snug">{note || "A model, not a fresh poll: each person answered once about their week and each lever; the town runs those answers forward. Same seed every run, so runs compare like for like."}</p>
              </div>
            ) : (
              <Results runs={runs} plan={plan} towns={city.towns.map((t) => ({ id: t.id, name: t.name }))} />
            )}
          </>
        )}
      </div>

      {/* Zoom */}
      <div className="city-zoom">
        <button className="city-pill" onClick={() => engineRef.current?.zoomBy(0.6)} title="Zoom in (+)">＋</button>
        <button className="city-pill" onClick={() => engineRef.current?.zoomBy(1.6)} title="Zoom out (−)">－</button>
        <button className="city-pill" onClick={() => { select(null); engineRef.current?.flyToAll(); }} title="See everything (0)">⤢</button>
      </div>

      {/* Funnel */}
      <div className="city-card city-funnel hidden md:block">
        <div className="flex justify-between items-center"><span className="city-title text-[15px]">On the way to {plan.outcome_label}</span><span className="text-[11px] city-muted">{city.launched ? (city.finished ? "run finished" : "live") : "not launched"}</span></div>
        <div className="city-steps">
          {[["Not heard", f.unaware, "#B9B0A3"], ["Heard", f.heard, "#6A9BCC"], ["Keen", f.keen, "#E0A93B"], ["Going", f.going, "#A67DC9"], ["Done", f.done, accent], ["Put off", f.off, "#7D6B5D"]].map(([label, v, c]) => (
            <div key={label as string} className="city-step">
              <div className="city-step-bar"><i style={{ height: `${pct(v as number, n)}%`, background: c as string }} /></div>
              <b className="tabular-nums">{v as number}</b>
              <span>{label as string}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Hover tooltip */}
      {hover?.p && (
        <div className="city-card city-tip" style={{ left: hover.x + 14, top: hover.y + 14 }}>
          {hover.p.type === "resident" ? (
            <>
              <div className="font-semibold text-[12.5px]">{hover.p.resident.name}</div>
              <div className="text-[11px] city-muted">{hover.p.resident.doing}</div>
              <MiniBars r={hover.p.resident} />
            </>
          ) : (
            <>
              <div className="font-semibold text-[12.5px]">{KIND_ICON[hover.p.lot.kind] || "📍"} {hover.p.lot.name}</div>
              <div className="text-[11px] city-muted">{inside(city, hover.p.lot).length} inside now{hover.p.lot.capacity ? ` · ${hover.p.lot.residents.length} live here` : ""}</div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function labelFor(plan: CityPlan, ids: string[]) {
  if (!ids.length) return "Nothing changes";
  if (ids.length === plan.levers.length && ids.length > 1) return "All levers together";
  return plan.levers.filter((l) => ids.includes(l.id)).map((l) => l.label).join(" + ");
}

function initials(name: string) { return name.split(/\s+/).map((p) => p[0]).join("").slice(0, 2).toUpperCase(); }
function inside(city: City, lot: Lot) { return city.residents.filter((r) => (r.activity === "at" && r.at === lot) || ((r.activity === "home" || r.activity === "asleep") && r.home === lot)); }

function Kpi({ icon, label, value, sub }: { icon: string; label: string; value: string; sub: string }) {
  return (
    <div className="city-card city-kpi">
      <div className="city-kpi-ico">{icon}</div>
      <div className="min-w-0">
        <div className="text-[11px] city-muted truncate">{label}</div>
        <div className="text-[20px] font-bold tabular-nums leading-tight">{value}</div>
        <div className="text-[10.5px] city-muted truncate">{sub}</div>
      </div>
    </div>
  );
}

function Meter({ label, value, max = 100, color, text, mark }: { label: string; value: number; max?: number; color: string; text: string; mark?: number }) {
  return (
    <div className="city-row">
      <span>{label}</span>
      <span className="flex items-center gap-2 justify-end">
        <span className="city-meter" style={{ ["--c" as any]: color }}>
          <i style={{ width: `${Math.max(0, Math.min(100, (value / max) * 100))}%` }} />
          {mark != null && <em style={{ left: `${(mark / max) * 100}%` }} />}
        </span>
        <b className="tabular-nums w-12 text-right">{text}</b>
      </span>
    </div>
  );
}

function MiniBars({ r }: { r: Resident }) {
  return (
    <div className="mt-1.5 space-y-0.5 text-[10.5px]">
      {[["Hunger", r.hunger, "#E0A93B"], ["Mood", r.mood, "#7FB069"], ["Company", r.social, "#6A9BCC"], ["Interest", r.interest, "#E8452C"]].map(([k, v, c]) => (
        <div key={k as string} className="flex items-center gap-1.5"><span className="w-14 city-muted">{k as string}</span><span className="city-meter city-meter-sm" style={{ ["--c" as any]: c }}><i style={{ width: `${v}%` }} /></span></div>
      ))}
      <div className="flex items-center gap-1.5"><span className="w-14 city-muted">Money</span><b>£{Math.round(r.money)}</b></div>
    </div>
  );
}

function ResidentCard({ r, city, onClose, onPlace }: { r: Resident; city: City; onClose: () => void; onPlace: (l: Lot) => void }) {
  const [why, setWhy] = useState(false);
  const plan = city.plan;
  const status = r.acted ? `Done — ${city.clock(r.actedAt!)}` : r.wantsTo ? (r.blocked ? `Wants to, but: ${r.blocked.toLowerCase()}` : "Decided — going when they can") : r.putOff ? "Put off" : r.interest >= 50 ? "Keen, not decided" : r.heard.size ? "Heard of it" : "Hasn't heard of it";
  const credit = r.credit ? (r.credit === "already_keen" ? "already keen before anything changed" : r.credit === "word_of_mouth" ? "someone told them" : plan.levers.find((l) => l.id === r.credit)?.label) : null;
  const w = city.willingness(r);
  return (
    <div className="space-y-3">
      <div className="flex gap-3 items-start">
        <div className="city-av city-av-lg" style={{ background: r.color }}>{initials(r.name)}</div>
        <div className="min-w-0 flex-1">
          <div className="city-title text-[19px] leading-tight">{r.name}</div>
          <div className="text-[11.5px] city-muted">{r.role}</div>
          <div className="flex flex-wrap gap-1 mt-1">
            <span className="city-chip-sm">{city.townById[r.town]?.name}</span>
            <span className="city-chip-sm">{r.a.daytime?.replace(/_/g, " ")}</span>
            <span className="city-chip-sm">{r.doing}</span>
          </div>
        </div>
        <button className="city-x" onClick={onClose}>✕</button>
      </div>
      <div className={`city-status ${r.acted ? "ok" : r.blocked ? "warn" : ""}`}>{status}{credit ? <span className="city-muted"> · pushed by {credit}</span> : null}</div>
      <div>
        <Meter label="Interest" value={r.interest} color="#E8452C" text={`${Math.round(r.interest)}`} mark={THRESHOLD} />
        <Meter label="Hunger" value={r.hunger} color="#E0A93B" text={`${Math.round(r.hunger)}`} />
        <Meter label="Mood" value={r.mood} color="#7FB069" text={`${Math.round(r.mood)}`} />
        <Meter label="Wants company" value={r.social} color="#6A9BCC" text={`${Math.round(r.social)}`} />
        <Meter label="Energy" value={r.energy} color="#A67DC9" text={`${Math.round(r.energy)}`} />
        <Meter label="Up for going out" value={w} color="#4E8A36" text={`${Math.round(w)}`} />
        <Meter label="Money" value={r.money} max={Math.max(50, r.a.spare_cash_week)} color="#C98A1B" text={`£${Math.round(r.money)}`} />
      </div>
      <div className="grid grid-cols-2 gap-1.5 text-[11.5px]">
        <button className="city-tile text-left" onClick={() => onPlace(r.home)}><span className="city-muted">Lives</span><b className="block truncate">{r.home.name}</b></button>
        <button className="city-tile text-left" disabled={!r.work} onClick={() => r.work && onPlace(r.work)}><span className="city-muted">Days</span><b className="block truncate">{r.work ? r.work.name : r.a.daytime?.replace(/_/g, " ")}</b></button>
      </div>
      {plan.levers.length > 0 && (
        <div className="text-[11.5px]">
          <div className="city-muted mb-1">How each lever lands with them (their own answer)</div>
          {plan.levers.map((lv) => {
            const pull = Number(r.a[`pull_${lv.id}`] || 0), meet = Number(r.a[`meet_${lv.id}`] || 0);
            return (
              <div key={lv.id} className="flex items-center gap-2 py-0.5">
                <span className="flex-1 truncate">{r.heard.has(lv.id) ? "✓ " : ""}{lv.label}</span>
                <span className="city-muted tabular-nums">meets {meet}%</span>
                <b className={`tabular-nums w-10 text-right ${pull < 0 ? "text-[#B8463B]" : ""}`}>{pull > 0 ? "+" : ""}{pull}</b>
              </div>
            );
          })}
        </div>
      )}
      {r.a.quote && <p className="city-quote">“{r.a.quote}”</p>}
      {r.a.barrier && <p className="text-[11.5px]"><span className="city-muted">What stops them: </span>{r.a.barrier}</p>}
      {r.reasoning && <button className="city-link text-[11.5px]" onClick={() => setWhy((v) => !v)}>{why ? "Hide" : "Their week, in their words"}</button>}
      {why && <p className="text-[11.5px] leading-snug">{r.reasoning}</p>}
    </div>
  );
}

function LotCard({ lot, city, onClose, onResident }: { lot: Lot; city: City; onClose: () => void; onResident: (r: Resident) => void }) {
  const people = inside(city, lot);
  const isOutcome = lot.kind === city.plan.outcome_building;
  const levers = city.plan.levers.filter((l) => l.building === lot.kind);
  const done = city.acts.filter((a) => a.place === lot);
  return (
    <div className="space-y-3">
      <div className="flex gap-3 items-start">
        <div className="text-[30px] leading-none">{KIND_ICON[lot.kind] || "📍"}</div>
        <div className="min-w-0 flex-1">
          <div className="city-title text-[19px] leading-tight">{lot.name}</div>
          <div className="text-[11.5px] city-muted">{city.townById[lot.town]?.name} · {lot.kind === "flats" ? "flats" : lot.kind}</div>
        </div>
        <button className="city-x" onClick={onClose}>✕</button>
      </div>
      {isOutcome && (
        <div className="city-tile">
          <div className="text-[12px]"><b>{city.plan.outcome_label}</b> happens here · £{city.outcomePrice()} · open {city.plan.open_from}:00–{city.plan.open_to}:00{city.plan.levers.some((l) => l.kind === "hours" && city.levers.has(l.id) && city.launched) ? " (longer hours on)" : ""}</div>
          <div className="text-[12px] mt-1">{city.launched ? `${done.length} have done it here` : "Launch from the Levers panel to start."}</div>
        </div>
      )}
      {levers.length > 0 && <div className="text-[11.5px]"><span className="city-muted">Levers here: </span>{levers.map((l) => l.label).join(", ")}</div>}
      <div>
        <div className="text-[11.5px] city-muted mb-1">{lot.capacity ? `${lot.residents.length} live here · ${people.length} in now` : `${people.length} here now`}</div>
        <div className="flex flex-wrap gap-1">
          {(lot.capacity ? lot.residents.map((id) => city.byId[id]).filter(Boolean) : people).slice(0, 30).map((r) => (
            <button key={r.id} className="city-chip-sm" onClick={() => onResident(r)}><span className="inline-block w-2 h-2 rounded-full mr-1" style={{ background: r.color }} />{r.name.split(" ")[0]}{lot.capacity && people.includes(r) ? " · in" : ""}</button>
          ))}
          {!people.length && !lot.capacity && <span className="text-[12px] city-muted">Nobody right now.</span>}
        </div>
      </div>
    </div>
  );
}

function Results({ runs, plan, towns }: { runs: RunSummary[]; plan: CityPlan; towns: { id: string; name: string }[] }) {
  if (!runs.length) return <p className="text-[12.5px] city-muted">Launch a run and let it finish, or test each lever instantly, and the results land here side by side.</p>;
  const base = runs.find((r) => r.key === "baseline");
  const best = runs.reduce((a, b) => (b.acted > a.acted ? b : a), runs[0]);
  const lever = (id: string) => (id === "already_keen" ? "Already keen" : id === "word_of_mouth" ? "Someone told them" : plan.levers.find((l) => l.id === id)?.label || id);
  return (
    <div className="space-y-4">
      <div>
        <div className="city-title">Who did it, run by run</div>
        <p className="text-[11px] city-muted">{plan.days} days each, the same people and the same seed.</p>
      </div>
      <div className="space-y-1.5">
        {runs.map((r, i) => {
          const share = pct(r.acted, r.n);
          const lift = base && r !== base ? r.acted - base.acted : null;
          return (
            <div key={`${r.label}-${i}`} className="city-runrow">
              <div className="flex justify-between gap-2 text-[12px]"><span className="truncate font-semibold">{r.label}</span><span className="tabular-nums shrink-0">{r.acted}/{r.n} · {share}%{lift != null ? <span className={lift >= 0 ? "text-[#4E8A36]" : "text-[#B8463B]"}> ({lift >= 0 ? "+" : ""}{lift})</span> : null}</span></div>
              <div className="city-meter mt-1" style={{ ["--c" as any]: r === best ? "#E8452C" : "#6A9BCC" }}><i style={{ width: `${share}%` }} /></div>
              {towns.length > 1 && <div className="flex gap-3 text-[10.5px] city-muted mt-0.5">{towns.map((t) => <span key={t.id}>{t.name}: {r.byTown[t.id]?.acted || 0}/{r.byTown[t.id]?.n || 0} ({pct(r.byTown[t.id]?.acted || 0, r.byTown[t.id]?.n || 0)}%)</span>)}</div>}
            </div>
          );
        })}
      </div>
      <div>
        <div className="text-[12px] font-semibold">{best.label}: what pushed them</div>
        {Object.entries(best.credit).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
          <div key={k} className="flex justify-between text-[11.5px]"><span>{lever(k)}</span><b className="tabular-nums">{v}</b></div>
        ))}
        {!Object.keys(best.credit).length && <p className="text-[11.5px] city-muted">Nobody did it.</p>}
      </div>
      <div>
        <div className="text-[12px] font-semibold">When they went</div>
        <div className="city-hours">{best.byHour.map((v, h) => <i key={h} title={`${h}:00 — ${v}`} style={{ height: `${(v / Math.max(1, ...best.byHour)) * 100}%` }} />)}</div>
        <div className="flex justify-between text-[10px] city-muted"><span>00</span><span>06</span><span>12</span><span>18</span><span>24</span></div>
      </div>
      {Object.keys(best.blocked).length > 0 && (
        <div>
          <div className="text-[12px] font-semibold">Wanted to, but didn't</div>
          {Object.entries(best.blocked).sort((a, b) => b[1] - a[1]).map(([k, v]) => <div key={k} className="flex justify-between text-[11.5px]"><span>{k}</span><b className="tabular-nums">{v}</b></div>)}
        </div>
      )}
      <p className="text-[10.5px] city-muted leading-snug">Heard of it: {best.heard} · put off: {best.putOff}. A model built from each person's one answer, run forward; not a fresh poll.</p>
    </div>
  );
}

