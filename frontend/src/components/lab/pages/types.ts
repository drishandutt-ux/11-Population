import { Agent, DynamicDial, Instrument, Probe, ProbeAnswerRow } from "@/lib/api";

/** What every instrument results page receives. The shell owns running, streaming, cost,
 *  export and provenance; the page owns everything that is specific to the tool — its
 *  charts, its KPIs, its way of reading its own aggregates. */
export interface InstrumentPageProps {
  instrument: Instrument;
  probe: Probe & { answers?: ProbeAnswerRow[] };
  /** The question's own dials (brief L3-04) — so a split reads as the dial's own name. */
  dynamicDials?: DynamicDial[];
  /** The roster by id, so an answer can carry its twin's confidence score (brief L3-05). */
  agentsById?: Record<string, Agent>;
  /** Open another tool (or this one afresh) from a results page, with inputs prefilled and, for the
   *  Visuals studio, images pre-ticked for Compare — how "Show it to the population" and "Compare it
   *  with the original" hand a new version straight back into the loop (the Visual Lab, step 4). */
  onOpenTool?: (key: string, seed?: { values?: Record<string, any>; compare?: string[] }) => void;
}
