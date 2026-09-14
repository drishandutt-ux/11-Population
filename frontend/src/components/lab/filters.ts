/** "Who answers" filters shared by every Lab tool. Values are the runner's segment keys. */
export const SEGMENT_FILTERS: { key: string; label: string; options: string[] }[] = [
  { key: "stance", label: "Stance", options: ["direct", "indirect", "neutral"] },
  { key: "age_band", label: "Age", options: ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"] },
];
