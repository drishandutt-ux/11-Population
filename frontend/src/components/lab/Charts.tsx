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

// Colours a live dot by whichever answer field looks categorical, so a dot grid can show
// progress for any instrument without knowing its schema.
const ANSWER_COLORS: Record<string, string> = {
  yes: "hsl(var(--primary))", no: "#f87171", unsure: "#fbbf24",
  buy: "hsl(var(--primary))", reject: "#f87171",
};

export function dotColor(answer: Record<string, any>, fallback: string): string {
  for (const v of Object.values(answer || {})) {
    if (typeof v === "string" && ANSWER_COLORS[v.toLowerCase()]) return ANSWER_COLORS[v.toLowerCase()];
  }
  return fallback;
}

/** Format a level (a share, a mean, a price) the way its metric asks. */
export function fmtLevel(v: number, format: "share" | "mean" | "money", currency = ""): string {
  if (format === "share") return pct(v);
  if (format === "money") return money(v, currency || "GBP");
  return `${Math.round(v * 100) / 100}`;
}

/** Format a lift with its sign: "+11 pts", "−4.2", "+£1.20". */
export function fmtLift(v: number, format: "share" | "mean" | "money", currency = ""): string {
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  const a = Math.abs(v);
  if (format === "share") return `${sign}${Math.round(a * 100)} pts`;
  if (format === "money") return `${sign}${money(a, currency || "GBP")}`;
  return `${sign}${Math.round(a * 100) / 100}`;
}

/** A difference between two arms, drawn around zero with its interval. Green when the
 *  interval clears zero upwards, red downwards, grey when it does not — the grey is the
 *  point: a lift whose band crosses zero is not a result. */
export function LiftBar({
  lift, format, currency, scale,
}: {
  lift: { mean: number; low: number; high: number; significant: boolean };
  format: "share" | "mean" | "money";
  currency?: string;
  /** Half-width of the axis in the metric's own units; defaults to the interval's reach. */
  scale?: number;
}) {
  const W = 200, H = 14, MID = W / 2;
  const reach = Math.max(scale || 0, Math.abs(lift.low), Math.abs(lift.high), Math.abs(lift.mean), 1e-9) * 1.1;
  const x = (v: number) => MID + (v / reach) * (MID - 4);
  const color = !lift.significant ? "hsl(var(--muted-foreground))" : lift.mean > 0 ? "hsl(var(--primary))" : "#f87171";
  return (
    <div className="flex items-center gap-2">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-[200px] h-3.5" preserveAspectRatio="none" role="img"
        aria-label={`lift ${fmtLift(lift.mean, format, currency)}`}>
        <rect x="0" y="5" width={W} height="4" rx="2" fill="hsl(var(--muted))" />
        <line x1={MID} y1="0" x2={MID} y2={H} stroke="hsl(var(--border))" strokeWidth="1" />
        <rect x={Math.min(x(lift.low), x(lift.high))} y="5" width={Math.max(1, Math.abs(x(lift.high) - x(lift.low)))} height="4" rx="2" fill={color} opacity="0.3" />
        <rect x={x(lift.mean) - 1} y="1" width="2" height={H - 2} rx="1" fill={color} />
      </svg>
      <span className="text-xs tabular-nums shrink-0 w-20" style={{ color }}>{fmtLift(lift.mean, format, currency)}</span>
    </div>
  );
}

/** A cell of the segment heat-map: lift coloured by sign and size, greyed when thin. */
export function HeatCell({ lift, thin, n, format, currency, maxAbs }: {
  lift: { mean: number; significant: boolean }; thin: boolean; n: number;
  format: "share" | "mean" | "money"; currency?: string; maxAbs: number;
}) {
  const strength = maxAbs > 0 ? Math.min(1, Math.abs(lift.mean) / maxAbs) : 0;
  const bg = lift.mean === 0 ? "transparent" : lift.mean > 0
    ? `hsl(var(--primary) / ${0.12 + strength * 0.5})`
    : `rgba(248, 113, 113, ${0.12 + strength * 0.5})`;
  return (
    <div
      className={`rounded-md px-2 py-1.5 text-center ${thin ? "opacity-40" : ""}`}
      style={{ background: bg }}
      title={thin ? `Only ${n} agents — too few to read confidently` : `${n} agents${lift.significant ? "" : " · interval includes zero"}`}
    >
      <div className={`text-xs tabular-nums ${lift.significant ? "text-foreground" : "text-muted-foreground"}`}>
        {fmtLift(lift.mean, format, currency)}{!lift.significant && !thin ? "" : ""}
      </div>
      <div className="text-[9px] text-muted-foreground/70 tabular-nums">n={n}{lift.significant ? " ✓" : ""}</div>
    </div>
  );
}

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
