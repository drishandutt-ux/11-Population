"use client";

/** Inline SVG charts for the Lab. No chart library: every result is a share, a distribution
 *  or a curve, and each one gets a plain-language sentence under it that the report generator
 *  can quote verbatim. */

import { Interval, MeanInterval } from "@/lib/api";

export const pct = (v: number) => `${Math.round(v * 100)}%`;
export const money = (v: number, currency = "GBP") =>
  `${({ GBP: "£", USD: "$", EUR: "€" } as Record<string, string>)[currency] ?? ""}${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

/** A share with its confidence interval drawn as a band around the point estimate.
 *  The band is the honest part — a 42% from 50 agents is not a 42% from 1,000. */
export function ShareBar({ value, label, accent = "hsl(var(--primary))" }: { value: Interval; label: string; accent?: string }) {
  const w = 100;
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1.5">
        <span className="text-xs text-muted-foreground">{label}</span>
        <span className="text-xs tabular-nums text-muted-foreground">
          {value.successes}/{value.n}
        </span>
      </div>
      <div className="flex items-baseline gap-2 mb-2">
        <span className="text-3xl font-semibold tabular-nums" style={{ color: accent }}>{pct(value.share)}</span>
        <span className="text-xs text-muted-foreground tabular-nums">
          95% CI {pct(value.low)}–{pct(value.high)}
        </span>
      </div>
      <svg viewBox={`0 0 ${w} 10`} className="w-full h-2.5" preserveAspectRatio="none" role="img" aria-label={`${label}: ${pct(value.share)}`}>
        <rect x="0" y="3" width={w} height="4" rx="2" fill="hsl(var(--muted))" />
        <rect x={value.low * w} y="3" width={Math.max(0.5, (value.high - value.low) * w)} height="4" rx="2" fill={accent} opacity="0.28" />
        <rect x={Math.min(w - 1, value.share * w) - 0.5} y="0.5" width="1.5" height="9" rx="0.75" fill={accent} />
      </svg>
    </div>
  );
}

const CAT_COLORS: Record<string, string> = {
  yes: "hsl(var(--primary))",
  no: "#f87171",
  unsure: "#fbbf24",
};

export function CategoryBars({ rows, title }: { rows: { value: string; count: number; share: number }[]; title: string }) {
  if (!rows?.length) return null;
  return (
    <div>
      <div className="text-xs text-muted-foreground mb-2">{title}</div>
      <div className="space-y-1.5">
        {rows.map((r) => (
          <div key={r.value} className="flex items-center gap-2">
            <span className="w-24 shrink-0 text-xs text-foreground/80 truncate capitalize">{r.value || "—"}</span>
            <div className="flex-1 h-4 bg-muted rounded-sm overflow-hidden">
              <div
                className="h-full rounded-sm transition-all"
                style={{ width: `${Math.max(1, r.share * 100)}%`, background: CAT_COLORS[r.value] ?? "hsl(var(--primary))", opacity: CAT_COLORS[r.value] ? 0.85 : 0.55 }}
              />
            </div>
            <span className="w-14 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
              {pct(r.share)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Demand curve from each agent's own walk-away price: the share still buying at every price.
 *  Elicited once, so dragging along it costs nothing. */
export function DemandCurve({
  curve,
  currency = "GBP",
  askingPrice,
  optimal,
}: {
  curve: { price: number; share: number; low: number; high: number; revenue_index: number }[];
  currency?: string;
  askingPrice?: number | null;
  optimal?: { price: number; share: number } | null;
}) {
  if (!curve?.length) return null;
  const W = 320, H = 140, PAD = 26;
  const maxP = curve[curve.length - 1].price || 1;
  const x = (p: number) => PAD + (p / maxP) * (W - PAD - 6);
  const y = (s: number) => H - PAD - s * (H - PAD - 8);
  const line = curve.map((p, i) => `${i ? "L" : "M"}${x(p.price).toFixed(1)},${y(p.share).toFixed(1)}`).join(" ");
  const band =
    curve.map((p, i) => `${i ? "L" : "M"}${x(p.price).toFixed(1)},${y(p.high).toFixed(1)}`).join(" ") +
    " " +
    [...curve].reverse().map((p) => `L${x(p.price).toFixed(1)},${y(p.low).toFixed(1)}`).join(" ") +
    " Z";

  return (
    <div>
      <div className="text-xs text-muted-foreground mb-2">Demand curve — share who would still buy at each price</div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Demand curve">
        {[0, 0.5, 1].map((s) => (
          <g key={s}>
            <line x1={PAD} y1={y(s)} x2={W - 6} y2={y(s)} stroke="hsl(var(--border))" strokeWidth="1" />
            <text x={PAD - 4} y={y(s) + 3} textAnchor="end" fontSize="7" fill="hsl(var(--muted-foreground))">{pct(s)}</text>
          </g>
        ))}
        <path d={band} fill="hsl(var(--primary))" opacity="0.13" />
        <path d={line} fill="none" stroke="hsl(var(--primary))" strokeWidth="1.8" />
        {optimal && optimal.price > 0 && (
          <g>
            <circle cx={x(optimal.price)} cy={y(optimal.share)} r="3" fill="hsl(var(--primary))" />
            <text x={x(optimal.price)} y={y(optimal.share) - 6} textAnchor="middle" fontSize="7" fill="hsl(var(--primary))">
              peak revenue {money(optimal.price, currency)}
            </text>
          </g>
        )}
        {askingPrice ? (
          <g>
            <line x1={x(askingPrice)} y1={8} x2={x(askingPrice)} y2={H - PAD} stroke="#fbbf24" strokeWidth="1" strokeDasharray="3 2" />
            <text x={x(askingPrice) + 3} y={14} fontSize="7" fill="#fbbf24">asking {money(askingPrice, currency)}</text>
          </g>
        ) : null}
        <text x={W - 6} y={H - 8} textAnchor="end" fontSize="7" fill="hsl(var(--muted-foreground))">{money(maxP, currency)}</text>
        <text x={PAD} y={H - 8} fontSize="7" fill="hsl(var(--muted-foreground))">{money(0, currency)}</text>
      </svg>
    </div>
  );
}

/** One dot per agent, filling in as answers land — the population, not a progress bar. */
export function DotGrid({ dots, total }: { dots: { color: string; title: string }[]; total: number }) {
  const empty = Math.max(0, total - dots.length);
  return (
    <div className="flex flex-wrap gap-[3px]">
      {dots.map((d, i) => (
        <span key={i} title={d.title} className="w-2.5 h-2.5 rounded-[2px]" style={{ background: d.color }} />
      ))}
      {Array.from({ length: empty }).map((_, i) => (
        <span key={`e${i}`} className="w-2.5 h-2.5 rounded-[2px] bg-muted animate-pulse" />
      ))}
    </div>
  );
}

export function MeanStat({ label, value, suffix = "", currency }: { label: string; value: MeanInterval; suffix?: string; currency?: string }) {
  const fmt = (v: number) => (currency ? money(v, currency) : `${Math.round(v * 10) / 10}${suffix}`);
  return (
    <div className="rounded-lg border border-border/60 bg-card/40 px-3 py-2">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="text-lg font-semibold tabular-nums text-foreground">{fmt(value.mean)}</div>
      <div className="text-[10px] text-muted-foreground tabular-nums">
        CI {fmt(value.low)}–{fmt(value.high)} · median {fmt(value.median)}
      </div>
    </div>
  );
}

export function SegmentTable({ title, rows }: { title: string; rows: { value: string; n: number; thin: boolean; share: number; low: number; high: number }[] }) {
  if (!rows?.length) return null;
  return (
    <div>
      <div className="text-xs text-muted-foreground mb-1.5 capitalize">{title.replace(/_/g, " ")}</div>
      <div className="space-y-1">
        {rows.map((r) => (
          <div key={r.value} className={`flex items-center gap-2 ${r.thin ? "opacity-45" : ""}`} title={r.thin ? "Too few agents to read confidently" : undefined}>
            <span className="w-24 shrink-0 text-xs text-foreground/80 truncate">{r.value}</span>
            <div className="flex-1 h-3.5 bg-muted rounded-sm relative overflow-hidden">
              <div className="absolute inset-y-0 bg-primary/25" style={{ left: `${r.low * 100}%`, width: `${Math.max(1, (r.high - r.low) * 100)}%` }} />
              <div className="absolute inset-y-0 w-[2px] bg-primary" style={{ left: `${r.share * 100}%` }} />
            </div>
            <span className="w-16 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
              {pct(r.share)} <span className="opacity-60">n={r.n}</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
