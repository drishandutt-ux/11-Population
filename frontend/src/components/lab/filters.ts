import { DynamicDial } from "@/lib/api";

/** "Who answers" filters shared by every Lab tool. Values are the runner's segment keys. */
export const SEGMENT_FILTERS: { key: string; label: string; options: string[] }[] = [
  { key: "stance", label: "Stance", options: ["direct", "indirect", "neutral"] },
  { key: "age_band", label: "Age", options: ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"] },
];

/** The runner namespaces a dynamic-dial split so a dial called "region" cannot collide with one. */
export const DYNAMIC_PREFIX = "dyn:";

/** The question's own dials (brief L3-04) as filters: each one low / mid / high. */
export function dynamicFilters(dials: DynamicDial[] = []) {
  return dials.map((d) => ({ key: `${DYNAMIC_PREFIX}${d.key}`, label: d.label, options: ["low", "mid", "high"], title: d.why }));
}

/** A split's heading: a dynamic dial reads as its own name, everything else as before. */
export function segmentLabel(key: string, dials: DynamicDial[] = []): string {
  if (!key.startsWith(DYNAMIC_PREFIX)) return key.replace(/_/g, " ");
  const k = key.slice(DYNAMIC_PREFIX.length);
  return dials.find((d) => d.key === k)?.label || k.replace(/_/g, " ");
}
