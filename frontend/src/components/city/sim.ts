/** 11 Minds City — the simulation (2026-11-05). Pure TypeScript, no Three.js, no model calls.
 *
 *  Every twin answered ONCE (the `city` instrument): where they live, their day, how much they
 *  go out, their spare money, how impulsive and sociable they are, how inclined they already are
 *  to the outcome, and for each lever how likely they are to meet it and how far it would move
 *  them. This file runs those answers forward in time:
 *
 *  - bars: hunger, money, mood (the "dopamine" bar — eating out, buying and company lift it,
 *    and a low mood makes impulse buys likelier), need for company, energy, and willingness to
 *    go out (a mix of the twin's own answer, mood, company, energy and the weather);
 *  - a day: sleep → up → work / errands → home → maybe out for the evening → sleep;
 *  - levers (after Launch): a poster is met by walking past it, TV in the evening, the radio in
 *    the morning, social media during the day, a leaflet once, a professional's advice by visiting
 *    their building, an event by going to it, a price cut or longer hours by hearing of them.
 *    Meeting one moves interest by the twin's own pull (it can push them away);
 *  - conversation: two people at the same place may talk; an interested one may pass it on;
 *  - acting: interest over the threshold → the twin plans a trip to the outcome building when it
 *    is open, they are free, they can afford it and they feel like going out.
 *
 *  Deterministic for a given seed and lever set, so two launches compare like for like. */

import type { CityPlan, ProbeAnswerRow } from "@/lib/api";
import { hash, layoutTowns, pathLength, pointAt, rng, route } from "./layout";
import type { Lot, TownLayout, Vec } from "./layout";

export const WALK = 6;           // metres per sim minute (a toy town: the walk takes a believable time)
export const THRESHOLD = 70;     // interest at which a twin decides to do it
export const DAY = 1440;
const TICK = 5;                  // the bars and decisions move every 5 sim minutes; walking moves every minute
const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export type Activity = "asleep" | "home" | "walking" | "at";
export type Credit = string; // a lever id, "word_of_mouth", or "already_keen"

export type Resident = {
  id: string; name: string; role: string; color: string; town: string;
  a: Record<string, any>; reasoning: string;
  home: Lot; work: Lot | null;
  lane: number;
  // bars, 0-100 except money (£)
  hunger: number; money: number; mood: number; social: number; energy: number; interest: number;
  baseMood: number; startInterest: number;
  // where they are
  activity: Activity; at: Lot | null; pos: Vec; dir: Vec;
  path: Vec[] | null; pathS: number; pathLen: number; dest: Lot | null;
  agenda: { start: number; place: Lot; stay: number; why: string }[];
  leaveAt: number;               // when to leave the current place
  stay: number; why: string;     // the stay and reason of the walk in progress
  week: number;                  // the week the money was last topped up
  phoneAt: number;               // the minute of the day they scroll their phone
  doing: string;                 // in words, for the card
  // the outcome
  heard: Set<string>; lastPush: Credit | null; putOff: boolean;
  gains: Record<string, number>;  // how much interest each source added: the biggest gets the credit
  toldBy: Set<string>;            // who has already passed it on to them
  wantsTo: boolean; acted: boolean; actedAt: number | null; credit: Credit | null;
  blocked: string | null;        // why they have not gone yet, in words
  retryDay: number;
};

export type FeedItem = { t: number; who: string; town: string; text: string; kind: "heard" | "acted" | "blocked" | "talk" | "life" | "off" };
export type ActEvent = { id: string; town: string; t: number; credit: Credit; place: Lot };

export type RunSummary = {
  key: string; label: string; levers: string[]; days: number; n: number;
  acted: number; byTown: Record<string, { n: number; acted: number }>;
  credit: Record<string, number>; byHour: number[]; blocked: Record<string, number>; heard: number; putOff: number;
};

export type Weather = "clear" | "rain";

export class City {
  plan: CityPlan;
  towns: TownLayout[];
  townById: Record<string, TownLayout> = {};
  residents: Resident[] = [];
  byId: Record<string, Resident> = {};
  t = 6 * 60;                    // sim minutes since Monday 00:00 of day 1
  launched = false;
  launchAt = 0;
  levers = new Set<string>();
  weather: Weather = "clear";
  feed: FeedItem[] = [];
  acts: ActEvent[] = [];
  talks: { a: string; b: string; t: number }[] = [];
  talkCount = 0;                 // every conversation ever, so the engine knows which are new
  finished = false;
  private rand: () => number;
  private seed: number;
  private lastMinute = -1;
  private answers: ProbeAnswerRow[];

  constructor(plan: CityPlan, answers: ProbeAnswerRow[], seed = 1) {
    this.plan = plan;
    this.answers = answers;
    this.seed = seed;
    this.rand = rng(seed);
    const usable = answers.filter((r) => r.answer && r.answer.home);
    const homeCounts: Record<string, { house: number; flat: number }> = {};
    const townIds = new Set(plan.cities.map((c) => c.id));
    const homeOf = (r: ProbeAnswerRow) => (townIds.has(r.answer.home) ? r.answer.home : plan.cities[0]?.id);
    for (const r of usable) {
      const h = homeOf(r);
      homeCounts[h] = homeCounts[h] || { house: 0, flat: 0 };
      homeCounts[h][r.answer.home_type === "flat" ? "flat" : "house"]++;
    }
    this.towns = layoutTowns(plan, homeCounts);
    for (const t of this.towns) this.townById[t.id] = t;
    this.placeResidents(usable, homeOf);
  }

  // ── setting up ──────────────────────────────────────────────────────────────
  private placeResidents(rows: ProbeAnswerRow[], homeOf: (r: ProbeAnswerRow) => string) {
    const r0 = rng(this.seed ^ 0x9e3779b9);
    for (const row of rows) {
      const a = row.answer;
      const town = this.townById[homeOf(row)];
      if (!town) continue;
      const kind = a.home_type === "flat" ? "flats" : "house";
      const home = town.lots.find((l) => l.kind === kind && l.residents.length < l.capacity)
        || town.lots.find((l) => (l.kind === "house" || l.kind === "flats") && l.residents.length < l.capacity);
      if (!home) continue;
      home.residents.push(row.agent_id);
      const num = (k: string, d: number, lo = 0, hi = 100) => Math.max(lo, Math.min(hi, Number.isFinite(+a[k]) ? +a[k] : d));
      const res: Resident = {
        id: row.agent_id, name: row.name || "Someone", role: row.role || "", color: row.avatar_color || "#6366f1", town: town.id,
        a: { ...a,
          wake_hour: Math.round(num("wake_hour", 7, 4, 12)), leave_hour: Math.round(num("leave_hour", 8, 5, 14)), back_hour: Math.round(num("back_hour", 17, 10, 23)),
          go_out: num("go_out", 50), spare_cash_week: num("spare_cash_week", 40, 0, 2000), impulse: num("impulse", 40),
          sociable: num("sociable", 50), eats_out: num("eats_out", 2, 0, 14), mood: num("mood", 55), start_interest: num("start_interest", 20),
          word_of_mouth: num("word_of_mouth", 30) },
        reasoning: row.reasoning || a.reasoning || "",
        home, work: null, lane: (r0() - 0.5) * 4.2,
        hunger: 20 + r0() * 30, money: 0, mood: 0, social: 30 + r0() * 30, energy: 80, interest: 0,
        baseMood: 0, startInterest: 0,
        activity: "asleep", at: home, pos: { ...home.door }, dir: { x: 0, z: 1 },
        path: null, pathS: 0, pathLen: 0, dest: null, agenda: [], leaveAt: 0, stay: 0, why: "", week: 0, phoneAt: 13 * 60 + (hash(row.agent_id) % 300), doing: "Asleep",
        heard: new Set(), lastPush: null, putOff: false, gains: {}, toldBy: new Set(), wantsTo: false, acted: false, actedAt: null, credit: null, blocked: null, retryDay: 0,
      };
      res.money = res.a.spare_cash_week;
      res.baseMood = res.a.mood; res.mood = res.a.mood;
      res.startInterest = res.a.start_interest; res.interest = res.a.start_interest;
      res.work = this.workplaceFor(res, town);
      this.residents.push(res);
      this.byId[res.id] = res;
    }
    const day0 = Math.floor(this.t / DAY);
    for (const r of this.residents) this.planDay(r, day0);
  }

  private lotsOf(town: TownLayout, kinds: string[]): Lot[] {
    return town.lots.filter((l) => kinds.includes(l.kind));
  }

  private pick<T>(xs: T[], rand = this.rand): T | null {
    return xs.length ? xs[Math.floor(rand() * xs.length)] : null;
  }

  private workplaceFor(r: Resident, town: TownLayout): Lot | null {
    const d = r.a.daytime;
    const rr = rng(hash(r.id));
    if (d === "study") return this.pick(this.lotsOf(town, ["college", "school"]), rr) || this.pick(this.lotsOf(town, ["office"]), rr);
    if (d !== "work_away") return null;
    const role = (r.role || "").toLowerCase();
    const byRole: [RegExp, string[]][] = [
      [/nurse|doctor|clinic|consultant|health|care assistant|midwife|paramedic/, ["hospital", "gp", "clinic"]],
      [/pharmac/, ["pharmacy"]], [/teach|lectur|school/, ["school", "college"]],
      [/shop|retail|cashier|till|sales assist/, ["supermarket", "shop"]], [/bar|pub|chef|cook|wait|hospitality/, ["pub", "restaurant", "cafe"]],
      [/factory|warehouse|operat|engineer|mechanic|labour|driver|manufactur/, ["factory", "station"]],
    ];
    for (const [re, kinds] of byRole) if (re.test(role)) { const l = this.pick(this.lotsOf(town, kinds), rr); if (l) return l; }
    return this.pick(this.lotsOf(town, ["office", "factory", "supermarket", "shop", "hospital", "school", "bank"]), rr);
  }

  // ── a day ───────────────────────────────────────────────────────────────────
  dayOf(t = this.t) { return Math.floor(t / DAY); }
  minuteOfDay(t = this.t) { return ((t % DAY) + DAY) % DAY; }
  weekday(t = this.t) { return this.dayOf(t) % 7; }
  clock(t = this.t) {
    const m = this.minuteOfDay(t);
    return `${DAY_NAMES[this.weekday(t)]} ${String(Math.floor(m / 60)).padStart(2, "0")}:${String(Math.floor(m % 60)).padStart(2, "0")}`;
  }
  /** Days since launch, counting the launch day as 1. */
  runDay() { return this.launched ? Math.floor((this.t - this.launchAt) / DAY) + 1 : 0; }

  willingness(r: Resident): number {
    let w = r.a.go_out + (r.social - 50) * 0.3 + (r.mood - 50) * 0.2;
    if (this.weather === "rain") w -= 15;
    if (r.energy < 30) w -= 20;
    if (r.hunger > 80) w += 5;
    return Math.max(0, Math.min(100, w));
  }

  private eveningPlace(r: Resident, town: TownLayout): Lot | null {
    const map: Record<string, string[]> = {
      pub: ["pub"], eat_out: ["restaurant", "cafe", "takeaway", "pub"], gym: ["gym", "park"], shops: ["supermarket", "shop"],
      walk: ["park"], church_or_club: ["church", "community"],
    };
    if (r.a.evening === "friends") {
      const friends = this.residents.filter((o) => o.town === r.town && o.id !== r.id && o.home !== r.home);
      const f = this.pick(friends);
      return f ? f.home : null;
    }
    return this.pick(this.lotsOf(town, map[r.a.evening] || ["pub", "cafe", "park"]));
  }

  private errand(r: Resident, town: TownLayout): Lot | null {
    const kinds = ["supermarket", "shop", "cafe", "park", "pharmacy", "community", "salon", "bank", "betting"];
    return this.pick(this.lotsOf(town, kinds));
  }

  /** The day's agenda, written at wake-up. */
  private planDay(r: Resident, day: number) {
    const town = this.townById[r.town];
    const base = day * DAY;
    const wd = day % 7;
    const weekend = wd >= 5;
    const agenda: Resident["agenda"] = [];
    const jitter = () => (this.rand() - 0.5) * 30;
    const w = this.willingness(r);
    if (r.work && !weekend) {
      const start = base + r.a.leave_hour * 60 + jitter();
      const end = base + Math.max(r.a.leave_hour + 4, r.a.back_hour) * 60 + jitter();
      agenda.push({ start, place: r.work, stay: Math.max(120, end - start), why: r.a.daytime === "study" ? "Studying" : "At work" });
    } else {
      const errands = weekend ? 2 : 1;
      for (let k = 0; k < errands; k++) {
        if (this.rand() * 100 < w * 0.9) {
          const p = this.errand(r, town);
          if (p) agenda.push({ start: base + (10 + k * 3) * 60 + this.rand() * 120, place: p, stay: 30 + this.rand() * 60, why: "Out on an errand" });
        }
      }
    }
    // Levers that are reached by going somewhere: a professional's advice, an event.
    if (this.launched) {
      for (const lv of this.plan.levers) {
        if (!this.levers.has(lv.id) || (lv.kind !== "advice" && lv.kind !== "event")) continue;
        const meet = Number(r.a[`meet_${lv.id}`] || 0) / 100;
        const pDay = 1 - Math.pow(1 - Math.min(0.99, meet), 1 / 7);
        if (this.rand() < pDay) {
          const place = this.pick(this.lotsOf(town, [lv.building]));
          if (place) {
            const hour = lv.kind === "event" ? 18.5 : (r.work && !weekend ? Math.max(r.a.back_hour, 16) - 0.5 : 11 + this.rand() * 4);
            agenda.push({ start: base + hour * 60, place, stay: lv.kind === "event" ? 90 : 25, why: lv.kind === "event" ? `At ${lv.label}` : `Seeing someone at the ${place.name}` });
          }
        }
      }
    }
    // Evening out.
    const evening = r.a.evening !== "stay_in" ? (weekend ? 0.75 : 0.45) : 0.12;
    if (this.rand() * 100 < w * evening * 1.6) {
      const p = this.eveningPlace(r, town);
      if (p) agenda.push({ start: base + Math.max(18.5, r.a.back_hour + 1) * 60 + this.rand() * 60, place: p, stay: 60 + this.rand() * 100, why: p.kind === "house" || p.kind === "flats" ? "At a friend's" : `At the ${p.name}` });
    }
    // The outcome, when they have decided.
    if (r.wantsTo && !r.acted) this.planTheTrip(r, day, agenda);
    agenda.sort((x, y) => x.start - y.start);
    // Drop clashes: a later item that starts before the previous one ends is pushed after it.
    for (let k = 1; k < agenda.length; k++) {
      const prev = agenda[k - 1];
      if (agenda[k].start < prev.start + prev.stay + 15) agenda[k].start = prev.start + prev.stay + 15;
    }
    r.agenda = agenda.filter((x) => x.start < base + 23.5 * 60);
  }

  private openHours(day: number): [number, number] | null {
    const hoursLever = this.plan.levers.find((l) => l.kind === "hours" && this.levers.has(l.id) && this.launched);
    const weekend = day % 7 >= 5;
    if (hoursLever) return [Math.min(this.plan.open_from, 8), Math.max(this.plan.open_to, 21)];
    if (weekend) return null;
    return [this.plan.open_from, this.plan.open_to];
  }

  outcomePrice(): number {
    const priceLever = this.plan.levers.find((l) => l.kind === "price" && this.levers.has(l.id) && this.launched);
    if (!priceLever) return this.plan.outcome_price;
    const m = /£\s*(\d+(?:\.\d+)?)/.exec(priceLever.detail || "");
    if (/free/i.test(priceLever.detail || "")) return 0;
    return m ? Math.min(this.plan.outcome_price, Number(m[1])) : Math.round(this.plan.outcome_price * 0.5);
  }

  /** Fit a trip to the outcome building into the day, or say why it cannot happen. */
  private planTheTrip(r: Resident, day: number, agenda: Resident["agenda"]) {
    if (day < r.retryDay) return;
    const town = this.townById[r.town];
    const place = this.pick(this.lotsOf(town, [this.plan.outcome_building]));
    if (!place) { r.blocked = "There is nowhere to do it in town"; return; }
    const price = this.outcomePrice();
    if (price > r.money) { this.block(r, "Can't afford it this week", day + 1); return; }
    const hours = this.openHours(day);
    if (!hours) { this.block(r, "Closed when I'm free", day + 1); return; }
    const busy = agenda.filter((x) => x.place === r.work);
    let hour = hours[0] + 1 + this.rand() * 2;
    if (busy.length) {
      const free = r.a.back_hour + 0.5;
      if (free < hours[1] - 0.5) hour = free;
      else if (this.rand() < 0.25) hour = 12.5;    // a lunch-break dash, sometimes
      else { this.block(r, "Closed when I'm free", day + 1); return; }
    }
    if (this.rand() * 100 > this.willingness(r) + 25) { this.block(r, "Didn't get round to it", day + 1); return; }
    r.blocked = null;
    agenda.push({ start: day * DAY + hour * 60, place, stay: 30, why: `Going to ${this.plan.outcome_label}` });
  }

  private block(r: Resident, why: string, retry: number) {
    if (r.blocked !== why && why !== "Didn't get round to it") this.post(r, why === "Can't afford it this week" ? `Want to ${this.plan.outcome_label} but it's not in the budget this week.` : why === "Closed when I'm free" ? `Wanted to ${this.plan.outcome_label} — closed by the time I'm free.` : `Meant to ${this.plan.outcome_label} today. Didn't get round to it.`, "blocked");
    r.blocked = why;
    r.retryDay = retry;
  }

  // ── levers ──────────────────────────────────────────────────────────────────
  setLevers(ids: string[]) { this.levers = new Set(ids); for (const t of this.towns) this.assignBillboards(t); }

  private assignBillboards(t: TownLayout) {
    const posters = this.plan.levers.filter((l) => l.kind === "poster" && this.levers.has(l.id));
    t.billboards.forEach((b, k) => { b.lever = posters.length ? posters[k % posters.length].id : null; });
  }

  /** Start a run: the clock goes back to Monday morning, everyone starts from their own answer. */
  launch(ids: string[]) {
    this.reset(this.seed + hash(ids.slice().sort().join(",")));
    this.setLevers(ids);
    this.launched = true;
    this.launchAt = this.t;
    // A price cut or longer hours is news: people hear of it over the week (morningChannels).
    for (const r of this.residents) {
      if (r.interest >= THRESHOLD && !r.wantsTo) { r.wantsTo = true; if (!r.lastPush) r.lastPush = "already_keen"; }
      this.planDay(r, this.dayOf());
    }
    this.post(null, `Launched: ${ids.length ? this.plan.levers.filter((l) => ids.includes(l.id)).map((l) => l.label).join(", ") : "nothing changes (the baseline)"}.`, "life");
  }

  reset(seed = this.seed) {
    this.rand = rng(seed);
    this.t = 6 * 60;
    this.lastMinute = -1;
    this.launched = false;
    this.finished = false;
    this.feed = [];
    this.acts = [];
    this.talks = [];
    this.talkCount = 0;
    this.passed.clear();
    const r0 = rng(seed ^ 0x51ed27);
    for (const r of this.residents) {
      Object.assign(r, {
        hunger: 20 + r0() * 30, money: r.a.spare_cash_week, mood: r.baseMood, social: 30 + r0() * 30, energy: 80, interest: r.startInterest,
        activity: "asleep", at: r.home, pos: { ...r.home.door }, path: null, dest: null, agenda: [], leaveAt: 0, stay: 0, why: "", week: 0, doing: "Asleep",
        heard: new Set(), lastPush: null, putOff: false, gains: {}, toldBy: new Set(), wantsTo: false, acted: false, actedAt: null, credit: null, blocked: null, retryDay: 0,
      });
    }
    for (const r of this.residents) this.planDay(r, this.dayOf());
  }

  private expose(r: Resident, leverId: string, say = true) {
    const lv = this.plan.levers.find((l) => l.id === leverId);
    if (!lv) return;
    const first = !r.heard.has(leverId);
    r.heard.add(leverId);
    const pull = Number(r.a[`pull_${leverId}`] || 0);
    // The first time counts fully; seeing it again adds a little more (repetition), never the whole pull again.
    const k = first ? 0.6 : 0.12;
    const before = r.interest;
    r.interest = Math.max(0, Math.min(100, r.interest + pull * k));
    if (r.interest > before) r.gains[leverId] = (r.gains[leverId] || 0) + (r.interest - before);
    if (pull > 0) r.lastPush = leverId;
    if (pull < -10 && first) { r.putOff = true; if (say) this.post(r, `Saw "${lv.label}". Not for me.`, "off"); }
    else if (first && say && pull > 25) this.post(r, `${lv.label} — ${r.a.quote ? r.a.quote : "might look into it."}`, "heard");
    this.maybeDecide(r);
  }

  private maybeDecide(r: Resident) {
    if (!r.wantsTo && !r.acted && r.interest >= THRESHOLD) {
      r.wantsTo = true;
      r.retryDay = 0;
      this.planTheTripToday(r);
    }
  }

  private planTheTripToday(r: Resident) {
    const day = this.dayOf();
    const before = r.agenda.length;
    this.planTheTrip(r, day, r.agenda);
    if (r.agenda.length > before) {
      const trip = r.agenda[r.agenda.length - 1];
      if (trip.start < this.t + 20) trip.start = this.t + 20 + this.rand() * 60;
      r.agenda.sort((x, y) => x.start - y.start);
    }
  }

  // ── the clock ───────────────────────────────────────────────────────────────
  /** Advance by `dt` sim minutes (any size; walking moves each minute, the rest every TICK). */
  step(dt: number) {
    const end = this.t + dt;
    while (this.t < end) {
      const h = Math.min(1, end - this.t);
      this.move(h);
      this.t += h;
      const tick = Math.floor(this.t / TICK);
      if (tick !== this.lastMinute) { this.lastMinute = tick; this.everyTick(); }
    }
  }

  /** Is minute-of-day `m` the tick that contains `at`? (Things that happen "at 20:00".) */
  private at(m: number, at: number) { return m <= at && at < m + TICK; }

  private everyTick() {
    const m = Math.floor(this.minuteOfDay() / TICK) * TICK;
    const k = TICK / 60;           // hours per tick
    const day = this.dayOf();
    if (this.launched && !this.finished && this.t - this.launchAt >= this.plan.days * DAY) { this.finished = true; this.post(null, `${this.plan.days} days are up. See the results.`, "life"); }
    this.countOccupancy();
    for (const r of this.residents) {
      // Bars drift every minute.
      const awake = r.activity !== "asleep";
      r.hunger = Math.min(100, r.hunger + (awake ? 5.5 : 1.5) * k);
      r.energy = Math.max(0, Math.min(100, r.energy + (awake ? -4.2 : 9) * k));
      const company = r.activity === "at" && r.at && this.presentAt(r.at) > 1;
      r.social = Math.max(0, Math.min(100, r.social + (company ? -16 : 2.5 * (r.a.sociable / 50)) * k));
      r.mood += (r.baseMood - r.mood) * 0.04 * k;
      if (r.hunger > 80) r.mood -= 3 * k;
      if (company) r.mood += (r.a.sociable / 100) * 6 * k;
      r.mood = Math.max(0, Math.min(100, r.mood));
      if (this.launched) r.interest += (r.startInterest - r.interest) * 0.02 * TICK / DAY;

      // Wake up, go to bed.
      const wake = r.a.wake_hour * 60;
      const bed = Math.min(23.75 * 60, Math.max(22 * 60, (r.a.back_hour + 5) * 60));
      if (r.activity === "asleep" && m >= wake && m < bed) {
        r.activity = "home"; r.doing = "At home";
        if (Math.floor(day / 7) !== r.week) { r.week = Math.floor(day / 7); r.money = r.a.spare_cash_week + r.money * 0.2; } // the week's money
        this.planDay(r, day);
        this.morningChannels(r);
      }
      if (r.activity === "home" && (m >= bed || m < wake) && !r.agenda.some((x) => x.start <= this.t + 30)) { r.activity = "asleep"; r.doing = "Asleep"; }

      // Eat at home when hungry.
      if (r.activity === "home" && r.hunger > 55) { r.hunger = 8; r.doing = "Having something to eat"; }
      // Out and hungry: maybe buy food.
      if (r.activity === "at" && r.at && r.hunger > 65 && ["cafe", "restaurant", "takeaway", "pub"].includes(r.at.kind) && r.money >= 6) {
        const cost = r.at.kind === "restaurant" ? 18 : r.at.kind === "pub" ? 12 : 7;
        r.money -= cost; r.hunger = 10; r.mood = Math.min(100, r.mood + 8);
      }

      // Leave when the stay is over; set off when the next agenda item starts.
      if (r.activity === "at" && this.t >= r.leaveAt) this.walkTo(r, r.home, "Heading home");
      const next = r.agenda[0];
      if (next && this.t >= next.start - this.walkMinutes(r, next.place) && (r.activity === "home" || r.activity === "at")) {
        r.agenda.shift();
        if (r.activity === "home" || r.at !== next.place) this.walkTo(r, next.place, next.why, next.stay);
      }

      // Evening channels at home.
      if (this.launched && r.activity === "home" && this.at(m, 20 * 60)) this.channel(r, "tv");
      if (this.launched && r.activity !== "asleep" && this.at(m, r.phoneAt)) this.channel(r, "social");
    }
    this.conversations();
  }

  private morningChannels(r: Resident) {
    if (!this.launched) return;
    this.channel(r, "radio");
    this.channel(r, "price");
    this.channel(r, "hours");
    if (this.runDay() === 1) this.channel(r, "leaflet", true);
  }

  /** A broadcast channel: once a day (once ever for a leaflet), with the twin's own weekly chance. */
  private channel(r: Resident, kind: string, once = false) {
    for (const lv of this.plan.levers) {
      if (lv.kind !== kind || !this.levers.has(lv.id)) continue;
      const meet = Math.min(0.99, Number(r.a[`meet_${lv.id}`] || 0) / 100);
      const p = once ? meet : 1 - Math.pow(1 - meet, 1 / 7);
      if (this.rand() < p) this.expose(r, lv.id);
    }
  }

  private walkMinutes(r: Resident, to: Lot) {
    const from = r.at || r.home;
    return (Math.abs(from.x - to.x) + Math.abs(from.z - to.z) + 20) / WALK;
  }

  private walkTo(r: Resident, to: Lot, why: string, stay = 0) {
    const town = this.townById[r.town];
    const from = r.at || r.home;
    r.path = route(town, from, to, r.lane);
    r.pathLen = pathLength(r.path);
    r.pathS = 0;
    r.dest = to;
    r.activity = "walking";
    r.at = null;
    r.doing = why === "Heading home" ? "Walking home" : `On the way: ${why.toLowerCase()}`;
    r.stay = stay;
    r.why = why;
  }

  private move(dt: number) {
    for (const r of this.residents) {
      if (r.activity !== "walking" || !r.path) continue;
      const before = r.pathS;
      r.pathS = Math.min(r.pathLen, r.pathS + WALK * dt);
      const { p, dir } = pointAt(r.path, r.pathS);
      r.pos = p; r.dir = dir;
      if (this.launched && Math.floor(before / 10) !== Math.floor(r.pathS / 10)) this.passBillboards(r);
      if (r.pathS >= r.pathLen) this.arrive(r);
    }
  }

  private passed: Map<string, number> = new Map();
  private passBillboards(r: Resident) {
    const town = this.townById[r.town];
    for (const b of town.billboards) {
      if (!b.lever || Math.hypot(b.x - r.pos.x, b.z - r.pos.z) > 10) continue;
      const key = `${r.id}:${b.lever}:${this.dayOf()}`;
      if (this.passed.has(key)) continue;
      this.passed.set(key, 1);
      const meet = Math.min(0.99, Number(r.a[`meet_${b.lever}`] || 0) / 100);
      // Passing a poster is not seeing it: spread the week's chance over a few passes.
      if (this.rand() < 1 - Math.pow(1 - meet, 1 / 4)) this.expose(r, b.lever);
    }
  }

  private arrive(r: Resident) {
    const to = r.dest!;
    const stay = r.stay;
    const why = r.why;
    r.path = null; r.dest = null;
    if (to === r.home) { r.activity = "home"; r.at = r.home; r.doing = "At home"; r.pos = { ...to.door }; return; }
    r.activity = "at"; r.at = to; r.leaveAt = this.t + (stay || 30); r.doing = why;
    // Spending: a venue costs something, impulse buys at shops.
    const spend: Record<string, number> = { pub: 10, cafe: 5, restaurant: 18, takeaway: 8, gym: 5, salon: 15, betting: 10 };
    if (spend[to.kind] && r.money >= spend[to.kind]) { r.money -= spend[to.kind]; r.mood = Math.min(100, r.mood + 6); }
    if (["shop", "supermarket"].includes(to.kind)) {
      const urge = r.a.impulse + Math.max(0, r.baseMood - r.mood) * 0.8; // a low mood makes the impulse buy likelier
      if (this.rand() * 100 < urge && r.money > 8) { const c = 5 + this.rand() * 20; r.money -= c; r.mood = Math.min(100, r.mood + 7); }
    }
    // Levers reached by being here.
    if (this.launched) for (const lv of this.plan.levers) {
      if (!this.levers.has(lv.id) || (lv.kind !== "advice" && lv.kind !== "event") || lv.building !== to.kind) continue;
      this.expose(r, lv.id);
    }
    // The outcome.
    if (to.kind === this.plan.outcome_building && r.wantsTo && !r.acted && this.launched && !this.finished) {
      const price = this.outcomePrice();
      const hours = this.openHours(this.dayOf());
      const hour = this.minuteOfDay() / 60;
      if (!hours || hour < hours[0] || hour >= hours[1]) { this.block(r, "Closed when I'm free", this.dayOf() + 1); return; }
      if (price > r.money) { this.block(r, "Can't afford it this week", this.dayOf() + 1); return; }
      r.money -= price; r.acted = true; r.actedAt = this.t; r.credit = this.creditFor(r); r.blocked = null;
      r.doing = `Did it: ${this.plan.outcome_label}`;
      r.mood = Math.min(100, r.mood + 5);
      this.acts.push({ id: r.id, town: r.town, t: this.t, credit: r.credit, place: to });
      this.post(r, r.a.quote || `Done — ${this.plan.outcome_label}.`, "acted");
    }
  }

  private occupancy = new Map<Lot, number>();
  presentAt(l: Lot): number { return this.occupancy.get(l) || 0; }
  private countOccupancy() {
    this.occupancy.clear();
    for (const r of this.residents) if (r.activity === "at" && r.at) this.occupancy.set(r.at, (this.occupancy.get(r.at) || 0) + 1);
  }

  /** What gets the credit: already keen before anything changed, or the source that added most interest. */
  creditFor(r: Resident): Credit {
    if (r.startInterest >= THRESHOLD) return "already_keen";
    let best: string | null = null, v = 0;
    for (const [k, g] of Object.entries(r.gains)) if (g > v) { v = g; best = k; }
    return best || r.lastPush || "already_keen";
  }

  /** People at the same place may talk; someone keen may pass it on. */
  private conversations() {
    const groups = new Map<Lot, Resident[]>();
    for (const r of this.residents) if (r.activity === "at" && r.at) { const g = groups.get(r.at) || []; g.push(r); groups.set(r.at, g); }
    const wom = this.plan.levers.find((l) => l.kind === "word_of_mouth" && this.levers.has(l.id));
    groups.forEach((g) => {
      if (g.length < 2) return;
      for (const a of g) {
        if (this.rand() * 100 > a.a.sociable * 0.08) continue;
        const b = g[Math.floor(this.rand() * g.length)];
        if (b === a) continue;
        this.talks.push({ a: a.id, b: b.id, t: this.t });
        this.talkCount++;
        if (this.talks.length > 40) this.talks.shift();
        a.social = Math.max(0, a.social - 6); b.social = Math.max(0, b.social - 6);
        a.mood = Math.min(100, a.mood + 2); b.mood = Math.min(100, b.mood + 2);
        if (!this.launched) continue;
        const keen = a.acted || a.interest >= 60;
        // Each person passes it on to each other person once; hearsay alone can only add so much.
        if (keen && !b.toldBy.has(a.id) && this.rand() * 100 < a.a.word_of_mouth) {
          b.toldBy.add(a.id);
          const src = wom ? wom.id : "word_of_mouth";
          const pull = wom ? Number(b.a[`pull_${wom.id}`] || 0) : 20;
          const cap = wom ? 40 : 25;
          const before = b.interest;
          const room = Math.max(0, cap - (b.gains[src] || 0));
          const delta = Math.max(Math.min(room, pull * (a.acted ? 0.25 : 0.15)), Math.min(0, pull * 0.15));
          b.interest = Math.max(0, Math.min(100, b.interest + delta));
          b.heard.add("word_of_mouth");
          if (b.interest > before) { b.lastPush = src; b.gains[src] = (b.gains[src] || 0) + (b.interest - before); }
          if (this.rand() < 0.3) this.post(a, `Told ${b.name.split(" ")[0]} about it.`, "talk");
          this.maybeDecide(b);
        }
      }
    });
  }

  private post(r: Resident | null, text: string, kind: FeedItem["kind"]) {
    this.feed.unshift({ t: this.t, who: r ? r.id : "", town: r ? r.town : "", text, kind });
    if (this.feed.length > 60) this.feed.pop();
  }

  // ── what happened ───────────────────────────────────────────────────────────
  summary(label: string): RunSummary {
    const byTown: RunSummary["byTown"] = {};
    for (const t of this.towns) byTown[t.id] = { n: 0, acted: 0 };
    const credit: Record<string, number> = {};
    const blocked: Record<string, number> = {};
    const byHour = new Array(24).fill(0);
    let heard = 0, putOff = 0;
    for (const r of this.residents) {
      byTown[r.town].n++;
      if (r.heard.size) heard++;
      if (r.putOff) putOff++;
      if (r.acted) {
        byTown[r.town].acted++;
        credit[r.credit || "already_keen"] = (credit[r.credit || "already_keen"] || 0) + 1;
        byHour[Math.floor(this.minuteOfDay(r.actedAt!) / 60)]++;
      } else if (r.wantsTo && r.blocked) blocked[r.blocked] = (blocked[r.blocked] || 0) + 1;
    }
    const levers = Array.from(this.levers);
    return { key: levers.slice().sort().join(",") || "baseline", label, levers, days: this.plan.days, n: this.residents.length,
             acted: this.acts.length, byTown, credit, byHour, blocked, heard, putOff };
  }

  /** Run the rest of the period at once (no drawing) and return what happened. */
  fastForward(): void {
    const end = this.launchAt + this.plan.days * DAY;
    while (this.t < end) this.step(Math.min(60, end - this.t));
  }

  /** Where each person stands on the way to the outcome, for the funnel. */
  funnel() {
    let unaware = 0, heard = 0, keen = 0, going = 0, done = 0, off = 0;
    for (const r of this.residents) {
      if (r.acted) done++;
      else if (r.wantsTo) going++;
      else if (r.putOff && r.interest < 40) off++;
      else if (r.interest >= 50) keen++;
      else if (r.heard.size) heard++;
      else unaware++;
    }
    return { unaware, heard, keen, going, done, off };
  }
}
