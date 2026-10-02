"use client";

/** People being conjured one by one — the decoration on the simple view's "getting everyone
 *  ready" card. Purely an animation: it loops on its own and has nothing to do with the real
 *  build's timing or count. Every face is drawn procedurally (no image assets), so each pass
 *  shows a different crowd. */

import { useEffect, useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import { Face, rng, BG, SKIN, HAIR, GREY, SHIRT, type Look as SharedLook } from "@/components/PersonaAvatar";

const JOBS = [
  "Nurse", "Teacher", "Plumber", "Engineer", "Chef", "Driver", "Pharmacist", "Carer", "Barista", "Farmer",
  "Electrician", "Student", "Accountant", "Shop owner", "Social worker", "Postie", "Mechanic", "Librarian", "GP",
  "Hairdresser", "Retired", "Builder", "Designer", "Journalist", "Cleaner", "Pilot", "Florist", "Lawyer",
  "Warehouse", "Gardener", "Musician", "Dentist", "Tailor", "Coach", "Vet", "Firefighter", "Translator", "Baker",
  "Parent", "Carpenter", "Programmer", "Reception", "Bus driver", "Midwife", "Decorator", "Analyst",
];
type Look = SharedLook;

function crowd(seed: number, n: number): Look[] {
  const r = rng(seed);
  const jobs = [...JOBS].sort(() => r() - 0.5);
  return Array.from({ length: n }, (_, i) => {
    const age = 18 + Math.floor(r() * 60);
    const fem = r() < 0.5;
    const style = fem ? [1, 2, 3][Math.floor(r() * 3)] : age >= 62 && r() < 0.3 ? 5 : [0, 4][Math.floor(r() * 2)];
    const greying = age >= 68 ? 1 : age >= 55 ? 0.6 : age >= 45 ? 0.25 : 0;
    return {
      bg: BG[Math.floor(r() * BG.length)],
      skin: SKIN[Math.floor(r() * SKIN.length)],
      hair: r() < greying ? GREY[Math.floor(r() * GREY.length)] : HAIR[Math.floor(r() * HAIR.length)],
      shirt: SHIRT[Math.floor(r() * SHIRT.length)],
      style,
      glasses: r() < (age >= 60 ? 0.6 : age >= 40 ? 0.3 : 0.12),
      hat: r() < 0.14 ? 1 + Math.floor(r() * 3) : 0,
      smile: Math.floor(r() * 3),
      age,
      earrings: fem && r() < 0.35,
      job: jobs[i % jobs.length],
    };
  });
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
