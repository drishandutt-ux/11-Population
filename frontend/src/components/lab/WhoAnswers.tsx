"use client";

/** "Who answers" — the same narrowing for every Lab tool and the A/B test: stance and age,
 *  then the population's own demographics and geography (read off the twins, so a build with
 *  no gender has no gender filter), then the question's own dials folded under "more". */

import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { api, DynamicDial, PopulationFilter } from "@/lib/api";
import { DYNAMIC_PREFIX, FilterDef, SEGMENT_FILTERS, dynamicFilters, populationFilters } from "./filters";

interface Props {
  sessionId: string;
  filters: Record<string, string>;
  setFilters: (fn: (prev: Record<string, string>) => Record<string, string>) => void;
  dynamicDials?: DynamicDial[];
  /** Re-read the population's filters when it changes (a respawn, a new build). */
  agentCount: number;
  hint?: boolean;
}

export default function WhoAnswers({ sessionId, filters, setFilters, dynamicDials = [], agentCount, hint = true }: Props) {
  const [population, setPopulation] = useState<PopulationFilter[]>([]);
  const [moreFilters, setMoreFilters] = useState(false);

  useEffect(() => {
    if (!agentCount) { setPopulation([]); return; }
    api.lab.filters(sessionId).then((r) => setPopulation(r.filters || [])).catch(() => setPopulation([]));
  }, [sessionId, agentCount]);

  const { demographics, geography } = populationFilters(population);

  const select = (f: FilterDef) => (
    <select
      key={f.key}
      value={filters[f.key] || ""}
      onChange={(e) => setFilters((prev) => ({ ...prev, [f.key]: e.target.value }))}
      title={f.title}
      className="w-full bg-input border border-border rounded-lg px-3 py-2 text-xs"
    >
      <option value="">{f.label}: everyone</option>
      {f.options.map((o) => (
        <option key={o} value={o}>{f.label}: {o}{f.counts?.[o] != null ? ` · ${f.counts[o]}` : ""}</option>
      ))}
    </select>
  );

  const group = (title: string, defs: FilterDef[]) => defs.length > 0 && (
    <div className="space-y-2 pt-1">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground/70">{title}</div>
      {defs.map(select)}
    </div>
  );

  return (
    <div>
      <label className="text-xs text-muted-foreground block mb-1.5">
        Who answers{hint && <span className="text-muted-foreground/50"> · everyone unless you narrow it</span>}
      </label>
      <div className="space-y-2">
        {SEGMENT_FILTERS.map(select)}
        {group("Demographics", demographics)}
        {group("Geography", geography)}
        {dynamicDials.length > 0 && (
          <button type="button" onClick={() => setMoreFilters((v) => !v)} className="text-[11px] text-muted-foreground hover:text-foreground inline-flex items-center gap-1">
            {moreFilters ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            {moreFilters ? "Fewer filters" : `More filters · ${dynamicDials.length} traits this question turns on`}
            {Object.entries(filters).some(([k, v]) => v && k.startsWith(DYNAMIC_PREFIX)) && <span className="text-primary">· in use</span>}
          </button>
        )}
        {moreFilters && dynamicFilters(dynamicDials).map(select)}
      </div>
    </div>
  );
}
