import { ComponentType } from "react";
import { Instrument } from "@/lib/api";
import InstrumentForm from "../InstrumentForm";
import SurveyBuilder from "./SurveyBuilder";

export interface InstrumentFormProps {
  instrument: Instrument;
  values: Record<string, any>;
  onChange: (key: string, value: any) => void;
}

/** The backend's `form` key → a bespoke input panel. Anything else renders its declared
 *  inputs through the generic InstrumentForm. The shell never branches on instrument keys. */
const FORMS: Record<string, ComponentType<InstrumentFormProps>> = {
  survey: SurveyBuilder,
};

export function formFor(key: string): ComponentType<InstrumentFormProps> {
  return FORMS[key] || InstrumentForm;
}
