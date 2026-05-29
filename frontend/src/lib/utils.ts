import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function stanceColor(stance: string): string {
  switch (stance) {
    case "direct": return "bg-blue-500/20 text-blue-300 border-blue-500/30";
    case "indirect": return "bg-purple-500/20 text-purple-300 border-purple-500/30";
    case "neutral": return "bg-slate-500/20 text-slate-300 border-slate-500/30";
    default: return "bg-slate-500/20 text-slate-300";
  }
}

export function postTypeColor(type: string): string {
  switch (type) {
    case "debate": return "border-l-red-500";
    case "reply": return "border-l-blue-500";
    case "comment": return "border-l-purple-500";
    default: return "border-l-slate-500";
  }
}

export function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return `${h}h ago`;
}
