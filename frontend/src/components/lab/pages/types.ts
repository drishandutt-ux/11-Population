import { Instrument, Probe, ProbeAnswerRow } from "@/lib/api";

/** What every instrument results page receives. The shell owns running, streaming, cost,
 *  export and provenance; the page owns everything that is specific to the tool — its
 *  charts, its KPIs, its way of reading its own aggregates. */
export interface InstrumentPageProps {
  instrument: Instrument;
  probe: Probe & { answers?: ProbeAnswerRow[] };
}
