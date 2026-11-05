/** 11 Minds City — the 3D engine (2026-11-05). One reusable engine that draws ANY city plan in
 *  the world-builder "sketch" style: soft clay buildings with ink outlines, a low-FOV isometric
 *  camera, lit windows and warm lamp pools at night, slanted rain. People are two instanced
 *  meshes (body + head) coloured by their avatar colour; at home they are indoors (hidden), out
 *  and about they walk the roads, and at a place they gather round its door.
 *
 *  The engine draws; `City` (sim.ts) decides. Loaded client-side only (dynamic import). */

import * as THREE from "three";
import { MapControls } from "three/examples/jsm/controls/MapControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";
import type { City, Resident } from "./sim";
import { BLOCK, nodePos, ROAD } from "./layout";
import type { Lot, TownLayout } from "./layout";

export const KIND_ICON: Record<string, string> = {
  hospital: "🏥", gp: "🩺", pharmacy: "💊", clinic: "⚕️", supermarket: "🛒", shop: "🛍️", pub: "🍺", cafe: "☕", restaurant: "🍽️",
  takeaway: "🍟", office: "🏢", factory: "🏭", school: "🏫", college: "🎓", park: "🌳", church: "⛪", gym: "🏋️", community: "🏛️",
  station: "🚉", bank: "🏦", salon: "💇", betting: "🎰", house: "🏠", flats: "🏢",
};

export type Pick = { type: "resident"; resident: Resident } | { type: "lot"; lot: Lot } | null;

type Hooks = {
  onHover: (p: Pick, x: number, y: number) => void;
  onSelect: (p: Pick) => void;
};

const INK = "#2B2522";
const CHAR_GROUND: Record<string, string> = {
  seaside: "#E9DFC9", historic: "#E6DDCC", university: "#DDE3D0", industrial: "#D9D6D0", market: "#E6DFD2",
  suburban: "#DCE5CF", inner_city: "#D8D6D2", rural: "#D3E0C2",
};
const WALLS = ["#F7F3EC", "#EFE6D6", "#E9DCC6", "#F2E9DC", "#D9CBB5", "#E8D5C4"];
const ROOFS = ["#C8664A", "#6B7A8F", "#5E8C61", "#A65E46", "#7D6B5D", "#B4573E"];

export class CityEngine {
  city: City;
  private el: HTMLElement;
  private hooks: Hooks;
  private accent: string;
  renderer: THREE.WebGLRenderer;
  private labels: CSS2DRenderer;
  scene = new THREE.Scene();
  camera: THREE.PerspectiveCamera;
  controls: MapControls;
  private hemi: THREE.HemisphereLight;
  private sun: THREE.DirectionalLight;
  private matCache: Record<string, THREE.MeshStandardMaterial> = {};
  private outlineMat: THREE.MeshBasicMaterial;
  private edgeMat = new THREE.LineBasicMaterial({ color: INK });
  private nightMats: { m: THREE.MeshStandardMaterial; max: number }[] = [];
  private poolMat: THREE.MeshBasicMaterial;
  private pickables: THREE.Object3D[] = [];
  private bodies!: THREE.InstancedMesh;
  private heads!: THREE.InstancedMesh;
  private bodyHull!: THREE.InstancedMesh;
  private ring: THREE.Mesh;
  private pin: CSS2DObject;
  private outcomePins: { obj: CSS2DObject; el: HTMLDivElement; lot: Lot }[] = [];
  private billboardFaces: { mesh: THREE.Mesh; lever: () => string | null; label: CSS2DObject; el: HTMLDivElement }[] = [];
  private bubbles: { obj: CSS2DObject; until: number }[] = [];
  private bursts: { pts: THREE.Points; t: number }[] = [];
  private seenActs = 0;
  private seenTalks = 0;
  private precip: THREE.LineSegments;
  private pgeo: THREE.BufferGeometry;
  private ground: THREE.Mesh;
  selected: Pick = null;
  private glide: null | { t: number; dur: number; fromP: THREE.Vector3; fromT: THREE.Vector3; toP: THREE.Vector3; toT: THREE.Vector3 } = null;
  private ray = new THREE.Raycaster();
  private ptr = new THREE.Vector2();
  private down: [number, number] | null = null;
  private disposed = false;
  private flash = 0;
  private mobile: boolean;
  private _o = new THREE.Object3D();
  private _c = new THREE.Color();
  private dayC = new THREE.Color();
  private nightSky = new THREE.Color("#1B2235");
  private skyDay = new THREE.Color("#E9E2D6");
  private skyRain = new THREE.Color("#9AA3AD");
  private winPools = { lit: [] as THREE.Matrix4[], dark: [] as THREE.Matrix4[] };

  constructor(el: HTMLElement, city: City, accent: string, hooks: Hooks) {
    this.el = el; this.city = city; this.accent = accent; this.hooks = hooks;
    this.mobile = matchMedia("(max-width:760px)").matches;
    const w = el.clientWidth, h = el.clientHeight;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, this.mobile ? 1.5 : 2));
    this.renderer.setSize(w, h);
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    el.appendChild(this.renderer.domElement);
    this.labels = new CSS2DRenderer();
    this.labels.setSize(w, h);
    Object.assign(this.labels.domElement.style, { position: "absolute", inset: "0", pointerEvents: "none", zIndex: "1" });
    el.appendChild(this.labels.domElement);

    this.scene.background = new THREE.Color("#E9E2D6");
    this.scene.fog = new THREE.Fog("#E9E2D6", 160, 420);
    this.camera = new THREE.PerspectiveCamera(32, w / h, 0.5, 1500);
    this.controls = new MapControls(this.camera, this.renderer.domElement);
    Object.assign(this.controls, { enableDamping: true, dampingFactor: 0.08, screenSpacePanning: false, minDistance: 8, maxDistance: 1200, zoomSpeed: 1.6, zoomToCursor: true, maxPolarAngle: Math.PI * 0.42, minPolarAngle: Math.PI * 0.12 });
    this.hemi = new THREE.HemisphereLight("#fff6ea", "#b9a58a", 0.9);
    this.scene.add(this.hemi);
    this.sun = new THREE.DirectionalLight("#fff1dc", 2.2);
    this.sun.castShadow = true;
    const SM = this.mobile ? 1024 : 2048;
    this.sun.shadow.mapSize.set(SM, SM);
    this.sun.shadow.bias = -0.0004;
    this.sun.shadow.normalBias = 0.02;
    this.scene.add(this.sun, this.sun.target);

    this.outlineMat = new THREE.MeshBasicMaterial({ color: INK, side: THREE.BackSide });
    this.outlineMat.onBeforeCompile = (s) => { s.vertexShader = s.vertexShader.replace("#include <begin_vertex>", "vec3 transformed = position + normal * 0.085;"); };
    this.poolMat = new THREE.MeshBasicMaterial({ map: this.poolTexture(), transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, opacity: 0 });

    this.ground = this.mesh(new THREE.PlaneGeometry(4000, 4000), this.clay("#E6DFD2"), 0, -0.02, 0, this.scene, { outline: false, cast: false });
    this.ground.rotation.x = -Math.PI / 2;
    for (const t of city.towns) this.buildTown(t);
    this.flushWindows();
    this.flushTreesAndLamps();
    this.buildPeople();

    this.ring = new THREE.Mesh(new THREE.RingGeometry(1.4, 1.8, 40), new THREE.MeshBasicMaterial({ color: accent, transparent: true, depthWrite: false }));
    this.ring.rotation.x = -Math.PI / 2; this.ring.visible = false; this.scene.add(this.ring);
    const pinEl = document.createElement("div");
    pinEl.innerHTML = `<svg class="city-pin" width="30" height="40" viewBox="0 0 34 44"><path d="M17 42C17 42 3 26 3 16a14 14 0 0 1 28 0c0 10-14 26-14 26z" fill="${accent}" stroke="${INK}" stroke-width="2.4"/><circle cx="17" cy="16" r="6" fill="#fff" stroke="${INK}" stroke-width="2"/></svg>`;
    this.pin = new CSS2DObject(pinEl); this.pin.visible = false; this.scene.add(this.pin);

    const N = this.mobile ? 1500 : 3500;
    const pp = new Float32Array(N * 6);
    for (let i = 0; i < N; i++) { const x = (Math.random() - 0.5) * 220, y = Math.random() * 70, z = (Math.random() - 0.5) * 220; pp.set([x, y, z, x, y, z], i * 6); }
    this.pgeo = new THREE.BufferGeometry(); this.pgeo.setAttribute("position", new THREE.BufferAttribute(pp, 3));
    this.precip = new THREE.LineSegments(this.pgeo, new THREE.LineBasicMaterial({ color: "#c9d8e8", transparent: true, opacity: 0.55, depthWrite: false }));
    this.precip.frustumCulled = false; this.precip.visible = false; this.scene.add(this.precip);

    const first = city.towns[0];
    const allSpan = city.towns.length ? city.towns[city.towns.length - 1].ox + city.towns[city.towns.length - 1].span - first.ox : 100;
    const cx = first ? first.ox + allSpan / 2 : 0;
    this.camera.position.set(cx + allSpan * 0.55, allSpan * 0.75 + 60, allSpan * 0.75 + 60);
    // Far enough out to see every town at once, whatever the plan.
    this.controls.maxDistance = Math.max(400, allSpan * 2.2 + 200);
    // The reader takes the camera back the moment they scroll, drag or pinch: no glide fighting them.
    this.controls.addEventListener("start", () => { this.glide = null; });
    this.controls.target.set(cx, 0, 0);
    this.camera.lookAt(this.controls.target);

    const dom = this.renderer.domElement;
    dom.addEventListener("pointerdown", this.onDown);
    dom.addEventListener("pointerup", this.onUp);
    dom.addEventListener("pointermove", this.onMove);
    dom.addEventListener("pointerleave", this.onLeave);
    window.addEventListener("resize", this.onResize);
  }

  // ── the clay kit ─────────────────────────────────────────────────────────────
  private clay(c: string, o: THREE.MeshStandardMaterialParameters = {}) {
    const k = c + JSON.stringify(o);
    return (this.matCache[k] ??= new THREE.MeshStandardMaterial({ color: c, roughness: 0.82, metalness: 0, ...o }));
  }
  private mesh(geo: THREE.BufferGeometry, mat: THREE.Material, x = 0, y = 0, z = 0, parent: THREE.Object3D = this.scene, o: { outline?: boolean; cast?: boolean } = {}) {
    const m = new THREE.Mesh(geo, mat);
    m.position.set(x, y, z);
    m.castShadow = o.cast ?? true; m.receiveShadow = true;
    parent.add(m);
    if (o.outline !== false) {
      const flat = (mat as THREE.MeshStandardMaterial).flatShading || !geo.index;
      if (flat) { const e = new THREE.LineSegments(new THREE.EdgesGeometry(geo, 28), this.edgeMat); e.raycast = () => {}; m.add(e); }
      else { const h = new THREE.Mesh(geo, this.outlineMat); h.raycast = () => {}; m.add(h); }
    }
    return m;
  }
  private rbox(w: number, h: number, d: number, r = 0.3) { return new RoundedBoxGeometry(w, h, d, 2, Math.min(r, w / 2, h / 2, d / 2)); }
  private poolTexture() {
    const c = document.createElement("canvas"); c.width = c.height = 128;
    const x = c.getContext("2d")!; const g = x.createRadialGradient(64, 64, 0, 64, 64, 64);
    g.addColorStop(0, "rgba(255,165,70,.9)"); g.addColorStop(0.45, "rgba(240,130,50,.35)"); g.addColorStop(1, "rgba(220,110,40,0)");
    x.fillStyle = g; x.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);
  }
  private winLitMat = new THREE.MeshStandardMaterial({ color: "#9FB3C8", emissive: "#FFC874", emissiveIntensity: 0, roughness: 0.35 });
  private winDarkMat = new THREE.MeshStandardMaterial({ color: "#9FB3C8", roughness: 0.35 });
  private addWindows(gx: number, gz: number, w: number, h: number, d: number, rand: () => number) {
    for (const [nx, nz, len, rotY] of [[0, 1, w, 0], [0, -1, w, Math.PI], [1, 0, d, Math.PI / 2], [-1, 0, d, -Math.PI / 2]]) {
      const cols = Math.max(1, Math.floor((len - 1) / 1.4));
      for (let y = 1.4; y < h - 0.6; y += 1.7) for (let c = 0; c < cols; c++) {
        const t = (c - (cols - 1) / 2) * 1.4;
        this._o.position.set(gx + nx * (w / 2 + 0.02) + (nz ? t : 0), y, gz + nz * (d / 2 + 0.02) + (nx ? t : 0));
        this._o.rotation.set(0, rotY, 0); this._o.updateMatrix();
        (rand() < 0.45 ? this.winPools.lit : this.winPools.dark).push(this._o.matrix.clone());
      }
    }
  }
  private flushWindows() {
    this.nightMats.push({ m: this.winLitMat, max: 1.8 });
    const geo = new THREE.BoxGeometry(0.7, 0.9, 0.08);
    for (const [arr, mat] of [[this.winPools.lit, this.winLitMat], [this.winPools.dark, this.winDarkMat]] as const) {
      if (!arr.length) continue;
      const im = new THREE.InstancedMesh(geo, mat, arr.length);
      arr.forEach((m, i) => im.setMatrixAt(i, m));
      im.raycast = () => {};
      this.scene.add(im);
    }
  }
  private hipRoof(g: THREE.Object3D, w: number, d: number, y: number, color: string) {
    const r = this.mesh(new THREE.ConeGeometry(Math.hypot(w, d) / 2 * 1.02, 2.2, 4, 1), this.clay(color, { flatShading: true }), 0, y + 1.1, 0, g);
    r.rotation.y = Math.PI / 4;
    r.scale.set(w / Math.hypot(w, d) * 1.42, 1, d / Math.hypot(w, d) * 1.42);
  }
  private sign(g: THREE.Object3D, text: string, y: number, z: number, color: string) {
    // A flat coloured band with a cross / icon shape is enough at this scale; the floating chip names it.
    this.mesh(new THREE.BoxGeometry(text.length ? 3.2 : 1.2, 0.9, 0.2), this.clay(color), 0, y, z, g, { cast: false });
  }
  private cross(g: THREE.Object3D, y: number, z: number, color: string) {
    this.mesh(new THREE.BoxGeometry(1.6, 0.5, 0.25), this.clay(color), 0, y, z, g, { outline: false, cast: false });
    this.mesh(new THREE.BoxGeometry(0.5, 1.6, 0.25), this.clay(color), 0, y, z, g, { outline: false, cast: false });
  }
  /** Trees and lamps are collected and drawn as instanced meshes (one draw call per part). */
  private trees: { x: number; z: number; s: number; c: string }[] = [];
  private lamps: { x: number; z: number }[] = [];
  private tree(x: number, z: number, s = 1, parent?: THREE.Object3D) {
    if (parent && parent !== this.scene) {
      // A tree inside a rotated group (a park): place it in world space.
      const v = new THREE.Vector3(x, 0, z); parent.updateMatrixWorld(); v.applyMatrix4(parent.matrixWorld);
      x = v.x; z = v.z;
    }
    this.trees.push({ x, z, s, c: Math.random() < 0.5 ? "#7BAF6A" : "#6E9F5E" });
  }
  private flushTreesAndLamps() {
    const n = this.trees.length;
    if (n) {
      const trunk = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.15, 0.2, 1.2, 6), this.clay("#8a6a4f"), n);
      const crownGeo = new THREE.SphereGeometry(0.95, 10, 8);
      const crown = new THREE.InstancedMesh(crownGeo, new THREE.MeshStandardMaterial({ roughness: 0.82 }), n);
      const hull = new THREE.InstancedMesh(crownGeo, this.outlineMat, n);
      this.trees.forEach((tr, i) => {
        this._o.rotation.set(0, 0, 0); this._o.scale.setScalar(tr.s);
        this._o.position.set(tr.x, 0.6 * tr.s, tr.z); this._o.updateMatrix(); trunk.setMatrixAt(i, this._o.matrix);
        this._o.position.set(tr.x, 1.8 * tr.s, tr.z); this._o.updateMatrix(); crown.setMatrixAt(i, this._o.matrix); hull.setMatrixAt(i, this._o.matrix);
        crown.setColorAt(i, this._c.set(tr.c));
      });
      for (const m of [trunk, crown, hull]) { m.castShadow = m !== hull; m.receiveShadow = true; m.raycast = () => {}; this.scene.add(m); }
    }
    const L = this.lamps.length;
    if (L) {
      const pole = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.06, 0.08, 3, 6), this.clay("#2f3640"), L);
      const bulb = new THREE.InstancedMesh(new THREE.SphereGeometry(0.22, 8, 6), this.bulbMat, L);
      const pool = new THREE.InstancedMesh(new THREE.PlaneGeometry(10, 10).rotateX(-Math.PI / 2), this.poolMat, L);
      this._o.rotation.set(0, 0, 0); this._o.scale.setScalar(1);
      this.lamps.forEach((l, i) => {
        this._o.position.set(l.x, 1.5, l.z); this._o.updateMatrix(); pole.setMatrixAt(i, this._o.matrix);
        this._o.position.set(l.x, 3.05, l.z); this._o.updateMatrix(); bulb.setMatrixAt(i, this._o.matrix);
        this._o.position.set(l.x, 0.05, l.z); this._o.updateMatrix(); pool.setMatrixAt(i, this._o.matrix);
      });
      for (const m of [pole, bulb, pool]) { m.raycast = () => {}; this.scene.add(m); }
    }
  }
  private bulbMat = new THREE.MeshStandardMaterial({ color: "#fff4d6", emissive: "#FFC874", emissiveIntensity: 0 });
  private lamp(x: number, z: number) { this.lamps.push({ x, z }); }

  // ── a town ───────────────────────────────────────────────────────────────────
  private buildTown(t: TownLayout) {
    const rand = mulberry(t.ox * 7 + 13);
    const groundCol = CHAR_GROUND[t.character] || "#E6DFD2";
    const pad = this.mesh(new THREE.BoxGeometry(t.span + 24, 0.2, t.span + 24), this.clay(groundCol), t.ox + t.span / 2, -0.08, t.oz + t.span / 2, this.scene, { outline: false, cast: false });
    pad.receiveShadow = true;
    if (t.character === "seaside") {
      const sea = this.mesh(new THREE.BoxGeometry(t.span + 60, 0.1, 50), this.clay("#7FB3C8", { roughness: 0.3 }), t.ox + t.span / 2, -0.05, t.oz + t.span + 40, this.scene, { outline: false, cast: false });
      sea.receiveShadow = true;
      this.mesh(new THREE.BoxGeometry(t.span + 60, 0.12, 10), this.clay("#EADBB4"), t.ox + t.span / 2, -0.03, t.oz + t.span + 13, this.scene, { outline: false, cast: false });
      // A pier.
      this.mesh(new THREE.BoxGeometry(4, 0.6, 34), this.clay("#9B7B5B"), t.ox + t.span * 0.6, 0.3, t.oz + t.span + 30, this.scene);
    }
    // Roads.
    const roadMat = this.clay("#5b5f66");
    for (let k = 0; k <= t.n; k++) {
      this.mesh(new THREE.BoxGeometry(t.span + ROAD, 0.06, ROAD), roadMat, t.ox + t.span / 2, 0.02, t.oz + k * t.step, this.scene, { outline: false, cast: false });
      this.mesh(new THREE.BoxGeometry(ROAD, 0.07, t.span + ROAD), roadMat, t.ox + k * t.step, 0.025, t.oz + t.span / 2, this.scene, { outline: false, cast: false });
    }
    for (let c = 0; c <= t.n; c++) for (let r = 0; r <= t.n; r++) {
      const p = nodePos(t, c, r);
      if ((c + r) % 2 === 0) this.lamp(p.x + ROAD / 2 + 0.6, p.z + ROAD / 2 + 0.6);
    }
    // Lots.
    for (const lot of t.lots) this.buildLot(lot, rand);
    // Green verges on empty quarter-lots.
    const taken = new Set(t.lots.map((l) => `${Math.round(l.x)},${Math.round(l.z)}`));
    for (let bc = 0; bc < t.n; bc++) for (let br = 0; br < t.n; br++) for (const [qx, qz] of [[0, 0], [1, 0], [0, 1], [1, 1]]) {
      const x = t.ox + bc * t.step + ROAD / 2 + qx * BLOCK / 2 + BLOCK / 4, z = t.oz + br * t.step + ROAD / 2 + qz * BLOCK / 2 + BLOCK / 4;
      if (taken.has(`${Math.round(x)},${Math.round(z)}`)) continue;
      if (t.lots.some((l) => l.park && Math.abs(l.x - x) < BLOCK / 2 && Math.abs(l.z - z) < BLOCK / 2)) continue;
      // Most spare plots get a house nobody on the panel lives in, so the town reads as a town.
      if (rand() < 0.72) this.backgroundHouse(x, z, qz === 1, rand);
      else this.tree(x + (rand() - 0.5) * 4, z + (rand() - 0.5) * 4, 0.9 + rand() * 0.5);
    }
    // Edge trees.
    for (let k = 0; k < t.n * 6; k++) {
      const side = k % 4, u = rand() * t.span;
      const x = side < 2 ? t.ox + u : (side === 2 ? t.ox - 8 : t.ox + t.span + 8);
      const z = side >= 2 ? t.oz + u : (side === 0 ? t.oz - 8 : t.oz + t.span + 8);
      if (t.character === "seaside" && side === 1) continue;
      this.tree(x, z, 0.8 + rand() * 0.7);
    }
    // Billboards.
    for (const b of t.billboards) {
      const g = new THREE.Group(); g.position.set(b.x, 0, b.z); g.rotation.y = b.rotY; this.scene.add(g);
      this.mesh(new THREE.CylinderGeometry(0.1, 0.1, 3, 6), this.clay("#3a4350"), -1.3, 1.5, 0, g, { outline: false });
      this.mesh(new THREE.CylinderGeometry(0.1, 0.1, 3, 6), this.clay("#3a4350"), 1.3, 1.5, 0, g, { outline: false });
      const face = this.mesh(new THREE.BoxGeometry(3.6, 2, 0.25), new THREE.MeshStandardMaterial({ color: "#D8CFC0", roughness: 0.6, emissive: "#000000" }), 0, 3.6, 0, g);
      const el = document.createElement("div"); el.className = "city-chip city-chip-ad"; el.style.display = "none";
      const label = new CSS2DObject(el); label.position.set(0, 5.4, 0); g.add(label);
      this.billboardFaces.push({ mesh: face, lever: () => b.lever, label, el });
    }
    // The town's name, floating over its middle.
    const name = document.createElement("div"); name.className = "city-townname"; name.textContent = t.name;
    const nl = new CSS2DObject(name); nl.position.set(t.centre.x, 26, t.oz - 6); this.scene.add(nl);
  }

  /** A house or a small terrace in a spare plot: drawn, not lived in by anyone on the panel, not clickable. */
  private backgroundHouse(x: number, z: number, south: boolean, rand: () => number) {
    const g = new THREE.Group(); g.position.set(x, 0, z); g.rotation.y = south ? 0 : Math.PI; this.scene.add(g);
    const wall = WALLS[Math.floor(rand() * WALLS.length)], roof = ROOFS[Math.floor(rand() * ROOFS.length)];
    if (rand() < 0.55) {
      for (const dx of [-3, 3]) {
        const w = 5, d = 6, h = 3.6 + rand() * 1.4;
        this.mesh(this.rbox(w, h, d, 0.25), this.clay(wall), dx, h / 2, 0, g);
        const sub = new THREE.Group(); sub.position.x = dx; g.add(sub); this.hipRoof(sub, w, d, h, roof);
        this.addWindows(x + dx * (south ? 1 : -1), z, w, h, d, rand);
      }
    } else {
      const w = 8.5, d = 7.5, h = 4 + rand() * 2;
      this.mesh(this.rbox(w, h, d, 0.25), this.clay(wall), 0, h / 2, 0, g);
      this.hipRoof(g, w, d, h, roof);
      this.addWindows(x, z, w, h, d, rand);
    }
  }

  private buildLot(lot: Lot, rand: () => number) {
    const g = new THREE.Group(); g.position.set(lot.x, 0, lot.z);
    // Face the door: the door is on the north (-z) or south (+z) edge.
    const south = lot.door.z > lot.z;
    g.rotation.y = south ? 0 : Math.PI;
    g.userData.pick = { type: "lot", lot } as Pick;
    this.scene.add(g); this.pickables.push(g);
    const w = lot.w, d = lot.d;
    const wall = WALLS[Math.floor(rand() * WALLS.length)];
    const roof = ROOFS[Math.floor(rand() * ROOFS.length)];
    const front = d / 2 + 0.15;
    const civic = lot.kind !== "house" && lot.kind !== "flats";
    const k = lot.kind;
    const box = (bw: number, bh: number, bd: number, col: string, y = bh / 2, x = 0, z = 0, r = 0.25) => this.mesh(this.rbox(bw, bh, bd, r), this.clay(col), x, y, z, g);
    const win = (bw: number, bh: number, bd: number) => this.addWindows(lot.x, lot.z, bw, bh, bd, rand);
    if (k === "park") {
      this.mesh(new THREE.BoxGeometry(w - 1, 0.12, d - 1), this.clay("#9CC48A"), 0, 0.03, 0, g, { outline: false, cast: false });
      this.mesh(new THREE.CylinderGeometry(3, 3, 0.1, 24), this.clay("#7FB3C8", { roughness: 0.3 }), w * 0.18, 0.1, -d * 0.15, g, { outline: false, cast: false });
      for (let i = 0; i < 9; i++) this.tree((rand() - 0.5) * (w - 6), (rand() - 0.5) * (d - 6), 0.9 + rand() * 0.7, g);
      box(2.2, 0.5, 0.7, "#9B7B5B", 0.45, -w * 0.2, d * 0.25, 0.1);
    } else if (k === "house") {
      const h = 4 + rand() * 1.5;
      box(w, h, d, wall); this.hipRoof(g, w, d, h, roof); win(w, h, d);
      box(1.2, 2, 0.3, "#7D5A44", 1, 0, front - 0.05, 0.08);
    } else if (k === "flats") {
      const h = 9 + Math.floor(rand() * 3) * 2;
      box(w, h, d, wall); box(w + 0.4, 0.5, d + 0.4, "#8E8478", h + 0.25); win(w, h, d);
      box(2, 2.4, 0.3, "#5E4B3C", 1.2, 0, front - 0.05, 0.08);
    } else if (k === "hospital") {
      const h = 8;
      box(w, h, d, "#F8F8F4"); box(w * 0.55, 4, d * 0.5, "#F8F8F4", h + 2, 0, 0); box(w + 0.3, 0.8, d + 0.3, this.accent, h - 1.5);
      this.cross(g, h + 2.4, d * 0.25 + 0.2, "#D9443A"); win(w, h, d);
      box(4, 0.3, 2.4, "#9AA6B2", 3, 0, front + 1, 0.05);
    } else if (k === "gp" || k === "clinic" || k === "pharmacy") {
      const h = 4.5;
      box(w, h, d, "#F4F1EA"); box(w + 0.3, 0.6, d + 0.3, k === "pharmacy" ? "#3E9A5B" : "#5B8DC9", h + 0.3);
      this.cross(g, h - 1.4, front + 0.05, k === "pharmacy" ? "#3E9A5B" : "#2F6DB5"); win(w, h, d);
    } else if (k === "supermarket") {
      const h = 5;
      box(w, h, d, "#EDE6DA"); box(w + 0.4, 1.2, 0.6, "#E2A13B", h - 0.8, 0, front);
      box(w * 0.8, 2.2, 0.15, "#A9C5D6", 1.4, 0, front + 0.05, 0.05);
    } else if (k === "shop" || k === "cafe" || k === "takeaway" || k === "salon" || k === "betting" || k === "restaurant") {
      const h = 4.5;
      const awn = { shop: "#E07A5F", cafe: "#81B29A", takeaway: "#F2CC8F", salon: "#C38EB4", betting: "#3D405B", restaurant: "#B5533C" }[k] || "#E07A5F";
      box(w, h, d, wall); this.hipRoof(g, w, d, h, roof);
      box(w - 1, 0.25, 1.6, awn, 2.9, 0, front + 0.7, 0.08);
      box(w * 0.6, 1.6, 0.15, "#A9C5D6", 1.4, 0, front + 0.05, 0.05);
      if (k === "cafe" || k === "restaurant") for (const x of [-2, 2]) this.mesh(new THREE.CylinderGeometry(0.5, 0.5, 0.8, 10), this.clay("#F7F3EC"), x, 0.4, front + 2.2, g, { outline: false });
    } else if (k === "pub") {
      const h = 5;
      box(w, h, d, "#A65E46"); this.hipRoof(g, w, d, h, "#4B5563"); win(w, h, d);
      box(1.6, 1.2, 0.2, "#F2CC8F", 3.4, w / 2 - 1, front + 0.4, 0.05);
    } else if (k === "office" || k === "bank") {
      const h = k === "bank" ? 6 : 12 + Math.floor(rand() * 3) * 2;
      box(w, h, d, k === "bank" ? "#E8E2D6" : "#B9C6D3"); win(w, h, d);
      if (k === "bank") for (const x of [-2.4, -0.8, 0.8, 2.4]) this.mesh(new THREE.CylinderGeometry(0.3, 0.3, 4.5, 10), this.clay("#F7F3EC"), x, 2.25, front + 0.6, g, { outline: false });
    } else if (k === "factory") {
      const h = 6;
      box(w, h, d, "#C9C2B6"); box(w * 0.8, 1.2, d * 0.8, "#8E8478", h + 0.6);
      this.mesh(new THREE.CylinderGeometry(0.8, 1, 9, 12), this.clay("#9B5A44"), w / 2 - 2, 4.5 + h / 2, -d / 4, g);
    } else if (k === "school" || k === "college" || k === "community") {
      const h = k === "college" ? 9 : 6;
      box(w, h, d, k === "college" ? "#E2D4BC" : wall); this.hipRoof(g, w, d, h, k === "college" ? "#5E6A7D" : roof); win(w, h, d);
      if (k === "college") { box(2.4, 5, 2.4, "#E2D4BC", h + 2.5, 0, 0); this.hipRoof(g, 2.4, 2.4, h + 5, "#5E6A7D"); }
    } else if (k === "church") {
      const h = 6;
      box(w * 0.7, h, d, "#D9CBB5"); this.hipRoof(g, w * 0.7, d, h, "#6B7A8F");
      box(2.6, 11, 2.6, "#D9CBB5", 5.5, 0, d / 2 - 1.4);
      const sp = this.mesh(new THREE.ConeGeometry(1.9, 5, 4, 1), this.clay("#6B7A8F", { flatShading: true }), 0, 13.5, d / 2 - 1.4, g); sp.rotation.y = Math.PI / 4;
    } else if (k === "gym") {
      const h = 5;
      box(w, h, d, "#3D405B"); box(w * 0.6, 1, 0.3, this.accent, h - 1, 0, front);
    } else if (k === "station") {
      box(w, 1, d, "#B8B2A6", 0.5); box(w, 0.4, d * 0.6, "#C8664A", 4.5);
      for (const x of [-w / 3, 0, w / 3]) this.mesh(new THREE.CylinderGeometry(0.2, 0.2, 4, 8), this.clay("#3a4350"), x, 2.5, 0, g, { outline: false });
    } else {
      const h = 5;
      box(w, h, d, wall); this.hipRoof(g, w, d, h, roof); win(w, h, d);
    }
    if (civic) {
      const el = document.createElement("div");
      el.className = "city-chip";
      el.innerHTML = `<span>${KIND_ICON[k] || "📍"}</span>${escapeHtml(lot.name)}`;
      const obj = new CSS2DObject(el);
      obj.position.set(lot.x, k === "park" ? 4 : k === "office" ? 16 : 11, lot.z);
      this.scene.add(obj);
      if (k === this.city.plan.outcome_building) {
        el.classList.add("city-chip-outcome");
        this.outcomePins.push({ obj, el, lot });
        const halo = new THREE.Mesh(new THREE.RingGeometry(w * 0.75, w * 0.75 + 0.8, 48), new THREE.MeshBasicMaterial({ color: this.accent, transparent: true, opacity: 0.7, depthWrite: false }));
        halo.rotation.x = -Math.PI / 2; halo.position.set(lot.x, 0.08, lot.z); halo.raycast = () => {}; this.scene.add(halo);
      }
    }
  }

  // ── people ───────────────────────────────────────────────────────────────────
  private buildPeople() {
    const n = Math.max(1, this.city.residents.length);
    const bodyGeo = new THREE.CapsuleGeometry(0.42, 0.75, 4, 10);
    const headGeo = new THREE.SphereGeometry(0.36, 12, 10);
    this.bodies = new THREE.InstancedMesh(bodyGeo, new THREE.MeshStandardMaterial({ roughness: 0.7 }), n);
    this.heads = new THREE.InstancedMesh(headGeo, this.clay("#F1D3B5"), n);
    const hullMat = new THREE.MeshBasicMaterial({ color: INK, side: THREE.BackSide });
    hullMat.onBeforeCompile = (s) => { s.vertexShader = s.vertexShader.replace("#include <begin_vertex>", "vec3 transformed = position + normal * 0.07;"); };
    this.bodyHull = new THREE.InstancedMesh(bodyGeo, hullMat, n);
    this.bodyHull.raycast = () => {};
    this.heads.raycast = () => {};
    for (const m of [this.bodies, this.heads, this.bodyHull]) { m.castShadow = m !== this.bodyHull; m.frustumCulled = false; this.scene.add(m); }
    this.city.residents.forEach((r, i) => this.bodies.setColorAt(i, this._c.set(r.color)));
    if (this.bodies.instanceColor) this.bodies.instanceColor.needsUpdate = true;
  }

  private placePeople(now: number) {
    const crowd = new Map<Lot, number>();
    this.city.residents.forEach((r, i) => {
      let visible = true, x = r.pos.x, z = r.pos.z, yaw = Math.atan2(r.dir.x, r.dir.z), bob = 0;
      if (r.activity === "walking") {
        bob = Math.abs(Math.sin(now * 0.012 + i)) * 0.12;
      } else if (r.activity === "at" && r.at && r.at.kind !== "house" && r.at.kind !== "flats") {
        const k = crowd.get(r.at) || 0; crowd.set(r.at, k + 1);
        const ang = k * 2.39996, rad = 1.6 + Math.sqrt(k) * 0.9;
        const out = r.at.door.z > r.at.z ? 1 : -1;
        x = r.at.door.x + Math.cos(ang) * rad; z = r.at.door.z + out * (2 + Math.abs(Math.sin(ang)) * rad);
        if (r.at.park) { x = r.at.x + Math.cos(ang) * rad * 2; z = r.at.z + Math.sin(ang) * rad * 2; }
        yaw = ang + Math.PI;
      } else {
        visible = false;
      }
      const s = visible ? 1 : 0;
      this._o.position.set(x, 0.85 + bob, z); this._o.rotation.set(0, yaw, 0); this._o.scale.setScalar(s); this._o.updateMatrix();
      this.bodies.setMatrixAt(i, this._o.matrix); this.bodyHull.setMatrixAt(i, this._o.matrix);
      this._o.position.y = 1.95 + bob; this._o.updateMatrix();
      this.heads.setMatrixAt(i, this._o.matrix);
    });
    this.bodies.instanceMatrix.needsUpdate = true; this.heads.instanceMatrix.needsUpdate = true; this.bodyHull.instanceMatrix.needsUpdate = true;
    this.bodies.computeBoundingSphere();
  }

  /** Where a resident is drawn right now (their crowd spot when at a place). */
  residentPosition(r: Resident): THREE.Vector3 {
    const i = this.city.residents.indexOf(r);
    const m = new THREE.Matrix4(); this.bodies.getMatrixAt(i, m);
    const p = new THREE.Vector3().setFromMatrixPosition(m);
    if (r.activity === "home" || r.activity === "asleep") return new THREE.Vector3(r.home.x, 0, r.home.z);
    return p.setY(0);
  }

  // ── picking and the camera ───────────────────────────────────────────────────
  private pickAt(cx: number, cy: number): Pick {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.ptr.set(((cx - rect.left) / rect.width) * 2 - 1, -((cy - rect.top) / rect.height) * 2 + 1);
    this.ray.setFromCamera(this.ptr, this.camera);
    const hp = this.ray.intersectObject(this.bodies, false)[0];
    if (hp && hp.instanceId != null) return { type: "resident", resident: this.city.residents[hp.instanceId] };
    let o: THREE.Object3D | null | undefined = this.ray.intersectObjects(this.pickables, true)[0]?.object;
    while (o && !o.userData.pick) o = o.parent;
    return (o?.userData.pick as Pick) || null;
  }
  private onDown = (e: PointerEvent) => { this.down = [e.clientX, e.clientY]; };
  private onUp = (e: PointerEvent) => {
    if (!this.down || Math.hypot(e.clientX - this.down[0], e.clientY - this.down[1]) > 5) return;
    const p = this.pickAt(e.clientX, e.clientY);
    this.select(p);
    this.hooks.onSelect(p);
  };
  private hoverT = 0;
  private onMove = (e: PointerEvent) => {
    const now = performance.now();
    if (now - this.hoverT < 60) return;
    this.hoverT = now;
    const p = this.pickAt(e.clientX, e.clientY);
    this.renderer.domElement.style.cursor = p ? "pointer" : "grab";
    const rect = this.el.getBoundingClientRect();
    this.hooks.onHover(p, e.clientX - rect.left, e.clientY - rect.top);
  };
  private onLeave = () => this.hooks.onHover(null, 0, 0);

  select(p: Pick) {
    this.selected = p;
    if (!p) return;
    const target = p.type === "resident" ? this.residentPosition(p.resident) : new THREE.Vector3(p.lot.x, 0, p.lot.z);
    this.flyTo(target, p.type === "resident" ? 34 : 48);
  }

  flyTo(target: THREE.Vector3, dist = 60, dur = 1.2) {
    const dir = this.camera.position.clone().sub(this.controls.target).normalize();
    this.glide = { t: 0, dur, fromP: this.camera.position.clone(), fromT: this.controls.target.clone(), toT: target.clone(), toP: target.clone().add(dir.multiplyScalar(dist)) };
  }

  /** Zoom by a factor toward the current target (buttons and keys): < 1 closer, > 1 further. */
  zoomBy(factor: number) {
    const dir = this.camera.position.clone().sub(this.controls.target);
    const d = Math.max(this.controls.minDistance, Math.min(this.controls.maxDistance, dir.length() * factor));
    const to = this.controls.target.clone().add(dir.setLength(d));
    this.glide = { t: 0, dur: 0.35, fromP: this.camera.position.clone(), fromT: this.controls.target.clone(), toT: this.controls.target.clone(), toP: to };
  }

  flyToTown(id: string) {
    const t = this.city.townById[id];
    if (t) { this.selected = null; this.flyTo(new THREE.Vector3(t.centre.x, 0, t.centre.z), t.span * 1.5 + 40); }
  }

  flyToAll() {
    const ts = this.city.towns; if (!ts.length) return;
    const a = ts[0].ox, b = ts[ts.length - 1].ox + ts[ts.length - 1].span;
    this.selected = null;
    this.flyTo(new THREE.Vector3((a + b) / 2, 0, 0), (b - a) * 1.1 + 60);
  }

  // ── a frame ──────────────────────────────────────────────────────────────────
  frame(rdt: number) {
    if (this.disposed) return;
    const now = performance.now();
    this.placePeople(now);

    if (this.glide) {
      const g = this.glide; g.t += rdt / g.dur;
      const k = ease(Math.min(1, g.t));
      this.camera.position.lerpVectors(g.fromP, g.toP, k); this.controls.target.lerpVectors(g.fromT, g.toT, k);
      if (g.t >= 1) this.glide = null;
    } else if (this.selected?.type === "resident") {
      const p = this.residentPosition(this.selected.resident);
      const d = p.sub(this.controls.target).multiplyScalar(0.08);
      this.controls.target.add(d); this.camera.position.add(d);
    }
    const sel = this.selected;
    const selPos = sel ? (sel.type === "resident" ? this.residentPosition(sel.resident) : new THREE.Vector3(sel.lot.x, 0, sel.lot.z)) : null;
    const showRing = !!selPos && !(sel?.type === "resident" && (sel.resident.activity === "home" || sel.resident.activity === "asleep"));
    this.ring.visible = showRing; this.pin.visible = !!selPos;
    if (selPos) {
      const s = (sel?.type === "lot" ? 4 : 1) * (1 + Math.sin(now * 0.006) * 0.12);
      this.ring.position.copy(selPos).setY(0.08); this.ring.scale.setScalar(s);
      (this.ring.material as THREE.MeshBasicMaterial).opacity = 0.55 + Math.sin(now * 0.006) * 0.3;
      this.pin.position.copy(selPos).setY(sel?.type === "lot" ? 14 : 3.4);
    }

    // Billboards show the posters that are up.
    for (const b of this.billboardFaces) {
      const id = b.lever();
      const lv = id ? this.city.plan.levers.find((l) => l.id === id) : null;
      const mat = b.mesh.material as THREE.MeshStandardMaterial;
      mat.color.set(lv && this.city.launched ? this.accent : "#D8CFC0");
      b.el.style.display = lv && this.city.launched ? "" : "none";
      if (lv && b.el.textContent !== `📣 ${lv.label}`) b.el.textContent = `📣 ${lv.label}`;
    }
    // Outcome pins: a count once launched.
    for (const o of this.outcomePins) {
      const done = this.city.acts.filter((a) => a.place === o.lot).length;
      const label = this.city.launched ? `${KIND_ICON[o.lot.kind] || "📍"} ${o.lot.name} · ${done} done` : `${KIND_ICON[o.lot.kind] || "📍"} ${o.lot.name} · launch here`;
      if (o.el.dataset.l !== label) { o.el.dataset.l = label; o.el.textContent = label; }
    }
    // New acts burst; new conversations get a bubble.
    while (this.seenActs < this.city.acts.length) { this.burst(this.city.acts[this.seenActs].place); this.seenActs++; }
    if (this.city.acts.length < this.seenActs) this.seenActs = this.city.acts.length;
    const talks = this.city.talks, total = this.city.talkCount;
    if (total < this.seenTalks) this.seenTalks = total;          // a new run started
    const fresh = Math.min(total - this.seenTalks, talks.length);
    for (const tk of talks.slice(talks.length - fresh)) {
      const r = this.city.byId[tk.a];
      if (r && this.bubbles.length < 10) this.bubble(r, now);
    }
    this.seenTalks = total;
    this.bubbles = this.bubbles.filter((b) => { if (now > b.until) { this.scene.remove(b.obj); b.obj.element.remove(); return false; } return true; });
    this.bursts = this.bursts.filter((b) => {
      b.t += rdt; const s = 1 + b.t * 6; b.pts.scale.set(s, 1 + b.t * 2, s);
      (b.pts.material as THREE.PointsMaterial).opacity = Math.max(0, 1 - b.t / 1.4);
      if (b.t > 1.4) { this.scene.remove(b.pts); b.pts.geometry.dispose(); return false; }
      return true;
    });

    this.environment(rdt);
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this.labels.render(this.scene, this.camera);
  }

  private burst(lot: Lot) {
    const N = 40, pos = new Float32Array(N * 3);
    for (let i = 0; i < N; i++) { const a = (i / N) * Math.PI * 2; pos.set([Math.cos(a), 0.5 + Math.random() * 1.5, Math.sin(a)], i * 3); }
    const geo = new THREE.BufferGeometry(); geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    const pts = new THREE.Points(geo, new THREE.PointsMaterial({ color: this.accent, size: 0.9, transparent: true, depthWrite: false }));
    pts.position.set(lot.door.x, 0.5, lot.door.z); this.scene.add(pts);
    this.bursts.push({ pts, t: 0 });
  }

  private bubble(r: Resident, now: number) {
    if (r.activity !== "at") return;
    const el = document.createElement("div"); el.className = "city-bubble"; el.textContent = "💬";
    const obj = new CSS2DObject(el); obj.position.copy(this.residentPosition(r)).setY(3.4);
    this.scene.add(obj); this.bubbles.push({ obj, until: now + 1800 });
  }

  private environment(rdt: number) {
    const city = this.city;
    const h = city.minuteOfDay() / 60;
    const daylight = THREE.MathUtils.smoothstep(Math.sin(((h - 6) / 12) * Math.PI), -0.15, 0.35);
    const rain = city.weather === "rain";
    this.dayC.copy(rain ? this.skyRain : this.skyDay).lerp(this.nightSky, 1 - daylight);
    (this.scene.background as THREE.Color).copy(this.dayC);
    const fog = this.scene.fog as THREE.Fog;
    fog.color.copy(this.dayC);
    const near = rain ? 90 : 220, far = rain ? 380 : 700;
    fog.near += (near - fog.near) * rdt * 2; fog.far += (far - fog.far) * rdt * 2;
    const ang = ((h - 6) / 12) * Math.PI;
    const tgt = this.controls.target;
    this.sun.position.set(tgt.x + Math.cos(ang) * 120, Math.max(10, Math.sin(ang) * 120), tgt.z + 40);
    this.sun.target.position.copy(tgt);
    const cam = this.sun.shadow.camera; const R = 140;
    if (cam.right !== R) { Object.assign(cam, { left: -R, right: R, top: R, bottom: -R, far: 400 }); cam.updateProjectionMatrix(); }
    this.sun.intensity = (rain ? 0.8 : 2.2) * daylight + 0.04;
    this.hemi.intensity = 0.22 + 0.68 * daylight;
    this.hemi.color.set(daylight > 0.5 ? "#fff6ea" : "#9fb0d8");
    const night = 1 - daylight;
    this.nightMats.forEach(({ m, max }) => (m.emissiveIntensity = night * max));
    this.bulbMat.emissiveIntensity = night * 3;
    this.poolMat.opacity = night * 0.7;
    if (rain && Math.random() < rdt * 0.12) this.flash = 1;
    this.flash = Math.max(0, this.flash - rdt * 4);
    this.hemi.intensity += this.flash * 3;
    (this.ground.material as THREE.MeshStandardMaterial).roughness = rain ? 0.35 : 0.82;
    this.precip.visible = rain;
    if (rain) {
      const a = this.pgeo.attributes.position.array as Float32Array;
      const N = a.length / 6, fall = 38;
      for (let i = 0; i < N; i++) {
        const o = i * 6; let x = a[o] + rdt * 4, y = a[o + 1] - fall * rdt, z = a[o + 2];
        if (y < 0) { y = 70; x = (Math.random() - 0.5) * 220 + tgt.x; z = (Math.random() - 0.5) * 220 + tgt.z; }
        a[o] = x; a[o + 1] = y; a[o + 2] = z; a[o + 3] = x - 0.24; a[o + 4] = y + 1.6; a[o + 5] = z;
      }
      this.pgeo.attributes.position.needsUpdate = true;
    }
  }

  private onResize = () => {
    const w = this.el.clientWidth, h = this.el.clientHeight;
    if (!w || !h) return;
    this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h); this.labels.setSize(w, h);
  };
  resize() { this.onResize(); }

  dispose() {
    this.disposed = true;
    const dom = this.renderer.domElement;
    dom.removeEventListener("pointerdown", this.onDown);
    dom.removeEventListener("pointerup", this.onUp);
    dom.removeEventListener("pointermove", this.onMove);
    dom.removeEventListener("pointerleave", this.onLeave);
    window.removeEventListener("resize", this.onResize);
    this.controls.dispose();
    this.scene.traverse((o) => {
      const m = o as THREE.Mesh;
      if (m.geometry) m.geometry.dispose();
    });
    Object.values(this.matCache).forEach((m) => m.dispose());
    this.renderer.dispose();
    dom.remove();
    this.labels.domElement.remove();
  }
}

function ease(t: number) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }
function mulberry(seed: number) {
  let a = seed >>> 0;
  return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
function escapeHtml(s: string) { return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!)); }
