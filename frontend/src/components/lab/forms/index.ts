import { ComponentType, ReactNode } from "react";
import { Instrument } from "@/lib/api";
import InstrumentForm from "../InstrumentForm";
import FormsStudio from "./FormsStudio";
import JourneyBuilder from "./JourneyBuilder";

export interface InstrumentFormProps {
  instrument: Instrument;
  values: Record<string, any>;
  onChange: (key: string, value: any) => void;
  /** The session the tool runs in — a builder that asks the backend to propose its inputs needs it. */
  sessionId?: string;
  /** What this tool has been run on before in the session, so a builder can warn when a new run would not compare. */
  context?: { pastOutcomes?: string[] };
  /** Full-width builders only: the shell's run controls (who answers, model, estimate, Run) to place where the builder wants them. */
  controls?: ReactNode;
  /** Full-width builders only: the shell's list of this tool's past runs. */
  aside?: ReactNode;
  /** Full-width builders only: back to the tool picker. */
  onBack?: () => void;
}

/** The backend's `form` key → a bespoke input panel. Anything else renders its declared
 *  inputs through the generic InstrumentForm. The shell never branches on instrument keys. */
const FORMS: Record<string, ComponentType<InstrumentFormProps>> = {
  survey: FormsStudio,
  journey: JourneyBuilder,
};

/** How a builder wants the screen while a run is being composed: `side` is the Lab's usual
 *  340px input column beside the results pane; `full` hands the builder the whole tab and the
 *  shell's run controls to place itself (the Forms studio). */
const LAYOUT: Record<string, "side" | "full"> = {
  survey: "full",
};

export function formFor(key: string): ComponentType<InstrumentFormProps> {
  return FORMS[key] || InstrumentForm;
}

export function formLayout(key: string): "side" | "full" {
  return LAYOUT[key] || "side";
}
