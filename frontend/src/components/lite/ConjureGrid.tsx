"use client";

/** People being conjured one by one — the decoration on the simple view's "getting everyone
 *  ready" card. Purely an animation: it loops on its own and has nothing to do with the real
 *  build's timing or count. Every face is drawn procedurally (no image assets), so each pass
 *  shows a different crowd. */

import { useEffect, useMemo, useState } from "react";
import { cn } from "@/lib/utils";

const JOBS = [
  "Nurse", "Teacher", "Plumber", "Engineer", "Chef", "Driver", "Pharmacist", "Carer", "Barista", "Farmer",
  "Electrician", "Student", "Accountant", "Shop owner", "Social worker", "Postie", "Mechanic", "Librarian", "GP",
  "Hairdresser", "Retired", "Builder", "Designer", "Journalist", "Cleaner", "Pilot", "Florist", "Lawyer",
  "Warehouse", "Gardener", "Musician", "Dentist", "Tailor", "Coach", "Vet", "Firefighter", "Translator", "Baker",
  "Parent", "Carpenter", "Programmer", "Reception", "Bus driver", "Midwife", "Decorator", "Analyst",
];
const BG = ["#dff3ec", "#e3ecfb", "#fde7e2", "#fbf0d6", "#ece5fa", "#e2f3f8", "#f6e3ef", "#e9f1dc"];
const SKIN = ["#f6d4b8", "#e8b894", "#c98f66", "#a7704b", "#7a4b2d", "#f1c8a9", "#d9a27c", "#5b3a24"];
const HAIR = ["#2b2118", "#5a3a22", "#b5742f", "#e3c27e", "#8a8a8a", "#1f1f1f", "#a33f2a", "#4a3728"];
const SHIRT = ["#2f8f7a", "#3b6fd1", "#d9663f", "#c2962a", "#7a5bd1", "#2a8fb0", "#c74b8a", "#5f9a2e"];

type Look = { bg: string; skin: string; hair: string; shirt: string; style: number; glasses: boolean; hat: number; job: string; smile: number };

function rng(seed: number) {
  let t = seed >>> 0;
  return () => { t = (t + 0x6d2b79f5) >>> 0; let r = Math.imul(t ^ (t >>> 15), 1 | t); r ^= r + Math.imul(r ^ (r >>> 7), 61 | r); return ((r ^ (r >>> 14)) >>> 0) / 4294967296; };
}

function crowd(seed: number, n: number): Look[] {
  const r = rng(seed);
  const jobs = [...JOBS].sort(() => r() - 0.5);
  return Array.from({ length: n }, (_, i) => ({
    bg: BG[Math.floor(r() * BG.length)],
    skin: SKIN[Math.floor(r() * SKIN.length)],
    hair: HAIR[Math.floor(r() * HAIR.length)],
    shirt: SHIRT[Math.floor(r() * SHIRT.length)],
    style: Math.floor(r() * 5),
    glasses: r() < 0.22,
    hat: r() < 0.18 ? 1 + Math.floor(r() * 2) : 0,
    smile: Math.floor(r() * 3),
    job: jobs[i % jobs.length],
  }));
}

/** A small, friendly face: head, hair in one of five cuts, shoulders, optional glasses or hat. */
export function Face({ look, size = 56 }: { look: Look; size?: number }) {
  const id = useMemo(() => `c${Math.random().toString(36).slice(2, 8)}`, []);
  const hair = (() => {
    switch (look.style) {
      case 0: return <path d="M19 27 q13 -16 26 0 v-3 q-13 -12 -26 0z M19 27 q0 -14 13 -14 q13 0 13 14 q-13 -7 -26 0z" fill={look.hair} />;                // short
      case 1: return <path d="M18 30 q0 -18 14 -18 q14 0 14 18 v8 q-3 -4 -3 -10 q-11 -6 -22 0 q0 6 -3 10z" fill={look.hair} />;                         // long
      case 2: return <><path d="M19 27 q13 -16 26 0 q-13 -7 -26 0z" fill={look.hair} /><circle cx="32" cy="12" r="5" fill={look.hair} /></>;        // bun
      case 3: return <path d="M18 28 q2 -16 14 -16 q12 0 14 16 q-4 -5 -8 -4 q-6 -5 -12 0 q-4 -1 -8 4z" fill={look.hair} />;                              // fringe
      default: return <path d="M20 26 q12 -10 24 0 q-12 -4 -24 0z" fill={look.hair} opacity="0.9" />;                                                 // cropped
    }
  })();
  const smile = look.smile === 0 ? "M27 34 q5 4 10 0" : look.smile === 1 ? "M28 34 q4 2 8 0" : "M27 33 q5 6 10 0";
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} aria-hidden="true">
      <defs><clipPath id={id}><circle cx="32" cy="32" r="31" /></clipPath></defs>
      <circle cx="32" cy="32" r="31" fill={look.bg} />
      <g clipPath={`url(#${id})`}>
        <path d="M12 66 q0 -20 20 -20 q20 0 20 20z" fill={look.shirt} />
        <rect x="28" y="38" width="8" height="8" rx="3" fill={look.skin} />
        <circle cx="32" cy="28" r="13" fill={look.skin} />
        {hair}
        <circle cx="27" cy="29" r="1.6" fill="#2b2118" />
        <circle cx="37" cy="29" r="1.6" fill="#2b2118" />
        <path d={smile} stroke="#8a4b3a" strokeWidth="1.6" fill="none" strokeLinecap="round" />
        {look.glasses && <g stroke="#3b3b3b" strokeWidth="1.4" fill="none"><circle cx="27" cy="29" r="4" /><circle cx="37" cy="29" r="4" /><path d="M31 29 h2" /></g>}
        {look.hat === 1 && <path d="M18 22 q14 -14 28 0 l0 2 l-28 0z" fill="#f2b632" />}
        {look.hat === 2 && <><rect x="19" y="18" width="26" height="5" rx="2" fill="#2e3a59" /><path d="M23 18 q9 -10 18 0z" fill="#2e3a59" /></>}
      </g>
    </svg>
  );
}

type Props = { count?: number; cols?: number; tick?: number; className?: string };

export default function ConjureGrid({ count = 24, cols = 8, tick = 420, className }: Props) {
  const [seed, setSeed] = useState(1);
  const [shown, setShown] = useState(0);
  const [fading, setFading] = useState(false);
  const looks = useMemo(() => crowd(seed, count), [seed, count]);

  useEffect(() => {
    const reduced = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduced) { setShown(count); return; }
    let t: ReturnType<typeof setTimeout>;
    if (shown < count) t = setTimeout(() => setShown((n) => n + 1), shown === 0 ? 300 : tick);
    else if (!fading) t = setTimeout(() => setFading(true), 1800);
    else t = setTimeout(() => { setFading(false); setShown(0); setSeed((s) => s + 1); }, 700);
    return () => clearTimeout(t);
  }, [shown, fading, count, tick]);

  return (
    <div className={cn("grid gap-x-2 gap-y-3 justify-items-center transition-opacity duration-700", fading ? "opacity-0" : "opacity-100", className)} style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }} aria-hidden="true">
      {looks.map((look, i) => (
        <div key={`${seed}-${i}`} className="flex flex-col items-center w-14">
          {i < shown ? (
            <>
              <div className="conjure-pop relative">
                <Face look={look} size={48} />
                <span className="conjure-ring" />
              </div>
              <span className="conjure-label text-[10px] text-muted-foreground mt-1 truncate max-w-full">{look.job}</span>
            </>
          ) : (
            <>
              <div className="w-12 h-12 rounded-full border border-dashed border-border" />
              <span className="h-[15px] mt-1" />
            </>
          )}
        </div>
      ))}
    </div>
  );
}
