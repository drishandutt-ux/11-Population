"use client";

/** A twin's portrait, drawn in code from what the record says about them: gender picks the hair,
 *  age greys it and adds glasses and lines, the job can add a hard hat or a chef's toque, and the
 *  twin's own avatar colour becomes the shirt and the tint behind them so they stay recognisable
 *  next to the dots and chips that already use that colour. Everything else (skin, smile, which
 *  cut) is drawn from a hash of the id, so the same person always looks the same. */

import { useMemo } from "react";
import type { Agent } from "@/lib/api";

export type Look = { bg: string; skin: string; hair: string; shirt: string; style: number; glasses: boolean; hat: number; smile: number; age: number; earrings: boolean; job?: string };

export const BG = ["#dff3ec", "#e3ecfb", "#fde7e2", "#fbf0d6", "#ece5fa", "#e2f3f8", "#f6e3ef", "#e9f1dc"];
export const SKIN = ["#f6d4b8", "#e8b894", "#c98f66", "#a7704b", "#7a4b2d", "#f1c8a9", "#d9a27c", "#5b3a24"];
export const HAIR = ["#2b2118", "#5a3a22", "#b5742f", "#e3c27e", "#8a8a8a", "#1f1f1f", "#a33f2a", "#4a3728"];
export const GREY = ["#d8d8d8", "#bdbdbd", "#efefef", "#a9a9a9"];
export const SHIRT = ["#2f8f7a", "#3b6fd1", "#d9663f", "#c2962a", "#7a5bd1", "#2a8fb0", "#c74b8a", "#5f9a2e"];

/** Hair cuts: 0 short, 1 long, 2 bun, 3 fringe, 4 cropped, 5 bald/thin (older men). */
const FEMININE = [1, 2, 3];
const MASCULINE = [0, 4];

export function rng(seed: number) {
  let t = seed >>> 0;
  return () => { t = (t + 0x6d2b79f5) >>> 0; let r = Math.imul(t ^ (t >>> 15), 1 | t); r ^= r + Math.imul(r ^ (r >>> 7), 61 | r); return ((r ^ (r >>> 14)) >>> 0) / 4294967296; };
}

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

/** Mix a hex colour towards white (t = 0 keeps it, 1 is white). */
function tint(hex: string, t: number): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return "#e7eef5";
  const n = parseInt(m[1], 16);
  const ch = (v: number) => Math.round(v + (255 - v) * t);
  const r = ch((n >> 16) & 255), g = ch((n >> 8) & 255), b = ch(n & 255);
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, "0")}`;
}

const HARD_HAT = /\b(builder|construction|electrician|plumber|scaffold|site manager|labourer|laborer|roofer|bricklayer|civil engineer|surveyor|foreman|groundwork)/i;
const TOQUE = /\b(chef|cook|baker|pastry|kitchen|caterer)\b/i;

/** The look a twin's record implies. */
export function lookFor(agent: Pick<Agent, "id" | "name" | "age" | "role" | "avatar_color"> & { demographics?: { gender?: string } | null }): Look {
  const r = rng(hash(agent.id || agent.name || "x"));
  const g = (agent.demographics?.gender || "").toLowerCase();
  const fem = g.startsWith("f") || g.startsWith("w");
  const masc = g.startsWith("m");
  const age = Number(agent.age) || 40;
  const pool = fem ? FEMININE : masc ? MASCULINE : [...FEMININE, ...MASCULINE];
  let style = pool[Math.floor(r() * pool.length)];
  if (masc && age >= 62 && r() < 0.35) style = 5;
  const greying = age >= 68 ? 1 : age >= 55 ? 0.6 : age >= 45 ? 0.25 : 0;
  const hair = r() < greying ? GREY[Math.floor(r() * GREY.length)] : HAIR[Math.floor(r() * HAIR.length)];
  const glasses = r() < (age >= 60 ? 0.6 : age >= 40 ? 0.3 : 0.12);
  const role = agent.role || "";
  const hat = HARD_HAT.test(role) ? 1 : TOQUE.test(role) ? 3 : 0;
  return {
    bg: tint(agent.avatar_color, 0.8),
    skin: SKIN[Math.floor(r() * SKIN.length)],
    hair,
    shirt: agent.avatar_color || SHIRT[Math.floor(r() * SHIRT.length)],
    style, glasses, hat,
    smile: Math.floor(r() * 3),
    age,
    earrings: fem && r() < 0.35,
  };
}

/** A small, friendly face. */
export function Face({ look, size = 56, className }: { look: Look; size?: number; className?: string }) {
  const id = useMemo(() => `c${Math.random().toString(36).slice(2, 8)}`, []);
  const hair = (() => {
    switch (look.style) {
      case 0: return <path d="M19 27 q13 -16 26 0 v-3 q-13 -12 -26 0z M19 27 q0 -14 13 -14 q13 0 13 14 q-13 -7 -26 0z" fill={look.hair} />;
      case 1: return <path d="M18 30 q0 -18 14 -18 q14 0 14 18 v8 q-3 -4 -3 -10 q-11 -6 -22 0 q0 6 -3 10z" fill={look.hair} />;
      case 2: return <><path d="M19 27 q13 -16 26 0 q-13 -7 -26 0z" fill={look.hair} /><circle cx="32" cy="12" r="5" fill={look.hair} /></>;
      case 3: return <path d="M18 28 q2 -16 14 -16 q12 0 14 16 q-4 -5 -8 -4 q-6 -5 -12 0 q-4 -1 -8 4z" fill={look.hair} />;
      case 5: return <><path d="M19 28 q1 -6 4 -8 q-1 4 0 8z" fill={look.hair} /><path d="M45 28 q-1 -6 -4 -8 q1 4 0 8z" fill={look.hair} /></>;
      default: return <path d="M20 26 q12 -10 24 0 q-12 -4 -24 0z" fill={look.hair} opacity="0.9" />;
    }
  })();
  const smile = look.smile === 0 ? "M27 34 q5 4 10 0" : look.smile === 1 ? "M28 34 q4 2 8 0" : "M27 33 q5 6 10 0";
  const old = look.age >= 60;
  const veryOld = look.age >= 72;
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} className={className} aria-hidden="true">
      <defs><clipPath id={id}><circle cx="32" cy="32" r="31" /></clipPath></defs>
      <circle cx="32" cy="32" r="31" fill={look.bg} />
      <g clipPath={`url(#${id})`}>
        <path d="M12 66 q0 -20 20 -20 q20 0 20 20z" fill={look.shirt} />
        <rect x="28" y="38" width="8" height="8" rx="3" fill={look.skin} />
        <circle cx="32" cy="28" r="13" fill={look.skin} />
        {hair}
        {look.earrings && <><circle cx="19.5" cy="32" r="1.1" fill="#d4a017" /><circle cx="44.5" cy="32" r="1.1" fill="#d4a017" /></>}
        <circle cx="27" cy="29" r="1.6" fill="#2b2118" />
        <circle cx="37" cy="29" r="1.6" fill="#2b2118" />
        <path d={smile} stroke="#8a4b3a" strokeWidth="1.6" fill="none" strokeLinecap="round" />
        {old && <g stroke="#2b2118" strokeWidth="0.9" fill="none" opacity="0.35" strokeLinecap="round"><path d="M23.5 34 q1 1.5 2.5 1.5" /><path d="M40.5 34 q-1 1.5 -2.5 1.5" />{veryOld && <><path d="M25 24 h4" /><path d="M35 24 h4" /></>}</g>}
        {look.glasses && <g stroke="#3b3b3b" strokeWidth="1.4" fill="none"><circle cx="27" cy="29" r="4" /><circle cx="37" cy="29" r="4" /><path d="M31 29 h2" /></g>}
        {look.hat === 1 && <path d="M18 22 q14 -14 28 0 l0 2 l-28 0z" fill="#f2b632" />}
        {look.hat === 2 && <><rect x="19" y="18" width="26" height="5" rx="2" fill="#2e3a59" /><path d="M23 18 q9 -10 18 0z" fill="#2e3a59" /></>}
        {look.hat === 3 && <><rect x="21" y="18" width="22" height="5" rx="1.5" fill="#ffffff" stroke="#d9d9d9" strokeWidth="0.8" /><path d="M21 18 q-3 -10 6 -9 q2 -6 8 -3 q6 -3 8 3 q9 -1 6 9z" fill="#ffffff" stroke="#d9d9d9" strokeWidth="0.8" /></>}
      </g>
    </svg>
  );
}

/** The portrait for a real twin. `shape` rounds it like the app's existing avatar boxes. */
export default function PersonaAvatar({ agent, size = 32, shape = "circle", className }: { agent: Parameters<typeof lookFor>[0]; size?: number; shape?: "circle" | "rounded"; className?: string }) {
  const look = useMemo(() => lookFor(agent), [agent]);
  if (shape === "rounded") {
    return (
      <span className={className} style={{ width: size, height: size, display: "inline-flex", borderRadius: Math.max(6, size * 0.28), overflow: "hidden", flexShrink: 0, background: look.bg }}>
        <Face look={look} size={size} />
      </span>
    );
  }
  return <Face look={look} size={size} className={className} />;
}
