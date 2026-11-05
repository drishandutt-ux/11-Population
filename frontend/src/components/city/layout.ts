/** 11 Minds City — the town layout (2026-11-05). Pure geometry, no Three.js: the simulation
 *  walks people along it and the engine draws it, so both always agree.
 *
 *  Each town is a grid of blocks separated by roads. Lots sit inside blocks (four to a block);
 *  every lot has a door on the road side. A walk from one door to another goes out to the road,
 *  along the grid (an L through the intersections), and in at the other door — always on a road,
 *  so nobody cuts through a building. Towns sit side by side along x. */

import type { CityPlan } from "@/lib/api";

export type Vec = { x: number; z: number };
export type LotKind = string; // a building kind from the plan, or "house" | "flats"

export type Lot = {
  id: string;
  town: string;
  kind: LotKind;
  name: string;
  x: number; z: number;          // centre
  w: number; d: number;          // footprint
  door: Vec;                     // on the road edge
  node: { c: number; r: number }; // nearest intersection to the door
  roadPoint: Vec;                // where the door meets the road
  capacity: number;              // homes: how many people live here
  residents: string[];           // homes: who lives here
  park?: boolean;
};

export type Billboard = { id: string; town: string; x: number; z: number; rotY: number; lever: string | null };

export type TownLayout = {
  id: string; name: string; character: string;
  ox: number; oz: number;        // the town's corner (intersection 0,0)
  n: number;                     // blocks per side
  step: number;                  // block + road
  span: number;                  // total width
  centre: Vec;
  lots: Lot[];
  billboards: Billboard[];
};

export const BLOCK = 26;
export const ROAD = 7;
export const STEP = BLOCK + ROAD;
const TOWN_GAP = 70;
const HOUSE_CAP = 3;
const FLATS_CAP = 10;

export function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

const SIZE_N: Record<string, number> = { small: 3, medium: 4, large: 5 };
/** Big civic buildings take a whole block's quarter but look larger; parks take a whole block. */
const BIG = new Set(["hospital", "supermarket", "factory", "college", "school", "station"]);

export function nodePos(t: { ox: number; oz: number; step: number }, c: number, r: number): Vec {
  return { x: t.ox + c * t.step, z: t.oz + r * t.step };
}

/** Lay out every town in the plan; `homeCounts` is residents per town by home type. */
export function layoutTowns(plan: CityPlan, homeCounts: Record<string, { house: number; flat: number }>): TownLayout[] {
  const towns: TownLayout[] = [];
  let cursor = 0;
  for (const c of plan.cities) {
    const rand = rng(hash(c.id + plan.title));
    const counts = homeCounts[c.id] || { house: 0, flat: 0 };
    const houseLots = Math.ceil(counts.house / HOUSE_CAP);
    const flatLots = Math.ceil(counts.flat / FLATS_CAP);
    const parks = c.places.filter((p) => p.kind === "park").length;
    const civic = c.places.filter((p) => p.kind !== "park").length;
    const lotsNeeded = houseLots + flatLots + civic + parks * 4 + 3; // a little slack for trees/greens
    let n = SIZE_N[c.size] || 4;
    while (n * n * 4 < lotsNeeded) n++;
    const span = n * STEP;
    const t: TownLayout = { id: c.id, name: c.name, character: c.character, ox: cursor, oz: -span / 2, n, step: STEP, span, centre: { x: cursor + span / 2, z: 0 }, lots: [], billboards: [] };
    cursor += span + TOWN_GAP;

    // Blocks, nearest the centre first: civic places go in the middle, homes around them.
    const blocks: { c: number; r: number; dist: number }[] = [];
    for (let bc = 0; bc < n; bc++) for (let br = 0; br < n; br++) {
      blocks.push({ c: bc, r: br, dist: Math.hypot(bc + 0.5 - n / 2, br + 0.5 - n / 2) + rand() * 0.3 });
    }
    blocks.sort((a, b) => a.dist - b.dist);
    // Parks claim whole blocks a little way out.
    const parkBlocks = new Set<string>();
    const parkPlaces = c.places.filter((p) => p.kind === "park");
    const ring = blocks.filter((b) => b.dist > 0.8);
    parkPlaces.forEach((p, k) => {
      const b = ring[Math.min(ring.length - 1, k * 3 + 1)] || blocks[blocks.length - 1];
      if (parkBlocks.has(`${b.c},${b.r}`)) return;
      parkBlocks.add(`${b.c},${b.r}`);
      const x = t.ox + b.c * STEP + ROAD / 2 + BLOCK / 2, z = t.oz + b.r * STEP + ROAD / 2 + BLOCK / 2;
      // Door on the north edge road.
      const door = { x, z: t.oz + b.r * STEP + ROAD / 2 };
      t.lots.push({ id: `${c.id}:park${k}`, town: c.id, kind: "park", name: p.name, x, z, w: BLOCK, d: BLOCK, door, roadPoint: { x, z: t.oz + b.r * STEP }, node: { c: b.c + (rand() < 0.5 ? 0 : 1), r: b.r }, capacity: 0, residents: [], park: true });
    });

    // Quarter-lots: (qx,qz) in {0,1}²; each quarter's door faces its outer road.
    // One quarter per block first, then the second quarter of every block, and so on: civic
    // places spread across the middle instead of piling into one block (their labels collide).
    const slots: { b: { c: number; r: number }; q: [number, number] }[] = [];
    const quarters: [number, number][] = [[0, 0], [1, 1], [1, 0], [0, 1]];
    for (let round = 0; round < 4; round++) for (const b of blocks) {
      if (parkBlocks.has(`${b.c},${b.r}`)) continue;
      slots.push({ b, q: quarters[(round + b.c + b.r) % 4] });
    }
    const half = BLOCK / 2;
    const makeLot = (slot: (typeof slots)[number], kind: string, name: string, id: string, capacity = 0): Lot => {
      const bx = t.ox + slot.b.c * STEP + ROAD / 2, bz = t.oz + slot.b.r * STEP + ROAD / 2;
      const x = bx + slot.q[0] * half + half / 2, z = bz + slot.q[1] * half + half / 2;
      // Door on the north or south edge (the road outside this quarter).
      const south = slot.q[1] === 1;
      const edgeZ = south ? bz + BLOCK : bz;
      const roadZ = south ? edgeZ + ROAD / 2 : edgeZ - ROAD / 2;
      const nodeC = slot.b.c + slot.q[0];
      const nodeR = slot.b.r + (south ? 1 : 0);
      const big = BIG.has(kind);
      return { id, town: c.id, kind, name, x, z, w: big ? half - 2 : half - 4.5, d: big ? half - 2 : half - 4.5, door: { x, z: edgeZ }, roadPoint: { x, z: roadZ }, node: { c: nodeC, r: nodeR }, capacity, residents: [] };
    };
    let si = 0;
    c.places.filter((p) => p.kind !== "park").forEach((p, k) => {
      if (si < slots.length) t.lots.push(makeLot(slots[si++], p.kind, p.name, `${c.id}:${p.kind}${k}`));
    });
    // Homes: flats nearer the middle, houses outside.
    for (let k = 0; k < flatLots && si < slots.length; k++) t.lots.push(makeLot(slots[si++], "flats", `Flats ${k + 1}`, `${c.id}:flats${k}`, FLATS_CAP));
    for (let k = 0; k < houseLots && si < slots.length; k++) t.lots.push(makeLot(slots[si++], "house", `House ${k + 1}`, `${c.id}:house${k}`, HOUSE_CAP));

    // Billboards on the roads nearest the centre, facing along the road.
    const mid = Math.floor(n / 2);
    const spots: Vec[] = [];
    for (let k = 0; k <= n; k++) {
      spots.push({ x: t.ox + k * STEP, z: t.oz + mid * STEP + STEP / 2 });
      spots.push({ x: t.ox + mid * STEP + STEP / 2, z: t.oz + k * STEP });
    }
    spots.sort((a, b) => Math.hypot(a.x - t.centre.x, a.z - t.centre.z) - Math.hypot(b.x - t.centre.x, b.z - t.centre.z));
    spots.slice(0, Math.min(6, spots.length)).forEach((s, k) => {
      const alongX = Math.abs((s.z - t.oz) % STEP) < 0.01; // on an east-west road
      t.billboards.push({ id: `${c.id}:bb${k}`, town: c.id, x: s.x + (alongX ? 0 : ROAD / 2 + 0.8), z: s.z + (alongX ? ROAD / 2 + 0.8 : 0), rotY: alongX ? 0 : Math.PI / 2, lever: null });
    });
    towns.push(t);
  }
  return towns;
}

/** A walk from one lot to another, along the roads. Each person keeps a lane offset so a crowd
 *  spreads across the street instead of walking in single file. */
export function route(t: TownLayout, from: Lot, to: Lot, lane: number): Vec[] {
  const a = nodePos(t, from.node.c, from.node.r);
  const b = nodePos(t, to.node.c, to.node.r);
  const pts: Vec[] = [from.door, from.roadPoint, { x: a.x, z: from.roadPoint.z }, a];
  if (a.x !== b.x && a.z !== b.z) pts.push({ x: b.x, z: a.z });
  pts.push(b, { x: b.x, z: to.roadPoint.z }, to.roadPoint, to.door);
  // De-duplicate and offset by lane, perpendicular to each leg.
  const out: Vec[] = [];
  for (const p of pts) {
    const last = out[out.length - 1];
    if (last && Math.abs(last.x - p.x) < 0.01 && Math.abs(last.z - p.z) < 0.01) continue;
    out.push({ ...p });
  }
  return out.map((p, i) => {
    const q = out[Math.min(out.length - 1, i + 1)], o = out[Math.max(0, i - 1)];
    const dx = q.x - o.x, dz = q.z - o.z, len = Math.hypot(dx, dz) || 1;
    return i === 0 || i === out.length - 1 ? p : { x: p.x + (-dz / len) * lane, z: p.z + (dx / len) * lane };
  });
}

export function pathLength(pts: Vec[]): number {
  let L = 0;
  for (let i = 1; i < pts.length; i++) L += Math.hypot(pts[i].x - pts[i - 1].x, pts[i].z - pts[i - 1].z);
  return L;
}

export function pointAt(pts: Vec[], s: number): { p: Vec; dir: Vec } {
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i];
    const L = Math.hypot(b.x - a.x, b.z - a.z);
    if (s <= L || i === pts.length - 1) {
      const k = L ? Math.min(1, s / L) : 1;
      return { p: { x: a.x + (b.x - a.x) * k, z: a.z + (b.z - a.z) * k }, dir: { x: (b.x - a.x) / (L || 1), z: (b.z - a.z) / (L || 1) } };
    }
    s -= L;
  }
  const last = pts[pts.length - 1];
  return { p: last, dir: { x: 0, z: 1 } };
}
