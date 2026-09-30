import { ComponentType } from "react";
import { Instrument } from "@/lib/api";
import InstrumentForm from "../InstrumentForm";
import SurveyBuilder from "./SurveyBuilder";
import JourneyBuilder from "./JourneyBuilder";

export interface InstrumentFormProps {
  instrument: Instrument;
  values: Record<string, any>;
  onChange: (key: string, value: any) => void;
  /** The session the tool runs in — a builder that asks the backend to propose its inputs needs it. */
  sessionId?: string;
  /** What this tool has been run on before in the session, so a builder can warn when a new run would not compare. */
  context?: { pastOutcomes?: string[] };
}

/** The backend's `form` key → a bespoke input panel. Anything else renders its declared
 *  inputs through the generic InstrumentForm. The shell never branches on instrument keys. */
const FORMS: Record<string, ComponentType<InstrumentFormProps>> = {
  survey: SurveyBuilder,
  journey: JourneyBuilder,
};

export function formFor(key: string): ComponentType<InstrumentFormProps> {
  return FORMS[key] || InstrumentForm;
}
