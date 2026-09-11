"use client";

/** Renders an instrument's input panel from its own declaration.
 *
 *  The Lab shell has no idea what a stimulus, an asking price or an attribute level is — it
 *  renders whatever the instrument says it needs. Adding a tool with entirely different
 *  inputs requires no change here. */

import { Instrument, InstrumentInput } from "@/lib/api";

interface Props {
  instrument: Instrument;
  values: Record<string, any>;
  onChange: (key: string, value: any) => void;
}

const CONTROL =
  "w-full bg-input border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary/50";

export default function InstrumentForm({ instrument, values, onChange }: Props) {
  return (
    <div className="space-y-4">
      {instrument.inputs.map((f) => (
        <Field key={f.key} field={f} value={values[f.key]} onChange={(v) => onChange(f.key, v)} />
      ))}
    </div>
  );
}

function Field({ field, value, onChange }: { field: InstrumentInput; value: any; onChange: (v: any) => void }) {
  const label = (
    <label className="text-xs text-muted-foreground block mb-1.5">
      {field.label}
      {field.required && <span className="text-primary/70"> *</span>}
    </label>
  );
  const help = field.help ? <p className="text-[10px] text-muted-foreground/60 mt-1">{field.help}</p> : null;

  if (field.type === "textarea") {
    return (
      <div>
        {label}
        <textarea
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value)}
          rows={6}
          placeholder={field.placeholder}
          className={`${CONTROL} resize-y`}
        />
        {help}
      </div>
    );
  }

  if (field.type === "select") {
    return (
      <div>
        {label}
        <select value={value ?? field.default ?? ""} onChange={(e) => onChange(e.target.value)} className={CONTROL}>
          {field.options.map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>
        {help}
      </div>
    );
  }

  // text · number · money
  return (
    <div>
      {label}
      <input
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        inputMode={field.type === "text" ? undefined : "decimal"}
        placeholder={field.placeholder}
        className={`${CONTROL}${field.type === "text" ? "" : " tabular-nums"}`}
      />
      {help}
    </div>
  );
}

/** Inputs the instrument declared, with `default_from` resolved against session state and
 *  numeric fields coerced — so the spec the API receives already matches the declaration. */
export function initialValues(instrument: Instrument, ctx: { session_query?: string }): Record<string, any> {
  const out: Record<string, any> = {};
  for (const f of instrument.inputs) {
    if (f.default_from === "session_query" && ctx.session_query) out[f.key] = ctx.session_query;
    else if (f.default !== null && f.default !== undefined) out[f.key] = f.default;
    else out[f.key] = "";
  }
  return out;
}

export function toSpec(instrument: Instrument, values: Record<string, any>): Record<string, any> {
  const spec: Record<string, any> = {};
  for (const f of instrument.inputs) {
    const raw = values[f.key];
    if (raw === "" || raw === undefined || raw === null) continue;
    spec[f.key] = f.type === "number" || f.type === "money" ? Number(raw) : raw;
  }
  return spec;
}
