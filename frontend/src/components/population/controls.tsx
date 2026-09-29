"use client";

import { ReactNode } from "react";

/** Small, shared controls for the Studio: a filled range slider, a switch, a segmented control,
 *  a section heading. Purely presentational — every value and handler is the caller's. */

export function Range({ value, min, max, step = 1, onChange, disabled, fill }: { value: number; min: number; max: number; step?: number; onChange: (v: number) => void; disabled?: boolean; fill?: string }) {
  const pct = Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100));
  return (
    <input
      type="range"
      min={min}
      max={max}
      step={step}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(+e.target.value)}
      style={{ "--range-pct": `${pct}%`, ...(fill ? { "--range-fill": fill } : {}) } as React.CSSProperties}
    />
  );
}

export function Switch({ on, onChange, disabled, label }: { on: boolean; onChange: (v: boolean) => void; disabled?: boolean; label?: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} data-on={on} onClick={() => onChange(!on)} className="switch">
      <span className="switch-thumb" />
    </button>
  );
}

export function SwitchRow({ on, onChange, disabled, title, hint }: { on: boolean; onChange: (v: boolean) => void; disabled?: boolean; title: string; hint?: ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <div className="pt-0.5"><Switch on={on} onChange={onChange} disabled={disabled} label={title} /></div>
      <div className="min-w-0 flex-1">
        <p className="text-xs text-foreground/90 leading-snug">{title}</p>
        {hint && <p className="hint mt-0.5">{hint}</p>}
      </div>
    </div>
  );
}

export function Seg<T extends string>({ value, onChange, options, disabled, className = "" }: { value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode; title?: string }[]; disabled?: boolean; className?: string }) {
  return (
    <div className={`seg ${className}`} role="tablist">
      {options.map((o) => (
        <button key={o.value} type="button" role="tab" title={o.title} disabled={disabled} data-on={value === o.value} onClick={() => onChange(o.value)} className="seg-item flex-1 justify-center whitespace-nowrap px-2">
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Section({ title, aside, children, className = "" }: { title: ReactNode; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`space-y-3 ${className}`}>
      <div className="flex items-baseline gap-2">
        <h3 className="section-title">{title}</h3>
        {aside && <span className="ml-auto text-[11px] text-muted-foreground/70">{aside}</span>}
      </div>
      {children}
    </section>
  );
}

export function Divider() {
  return <div className="h-px w-full hairline border-t" />;
}
