import { ComponentType } from "react";
import GenericPage from "./GenericPage";
import PurchaseIntentPage from "./PurchaseIntentPage";
import { InstrumentPageProps } from "./types";

/** Instrument key (the backend's `page` field) → its own results page.
 *
 *  An instrument with no entry here renders through GenericPage, so the backend can ship a
 *  tool before its bespoke UI exists. The shell never branches on instrument keys itself. */
const PAGES: Record<string, ComponentType<InstrumentPageProps>> = {
  purchase_intent: PurchaseIntentPage,
};

export function pageFor(key: string): ComponentType<InstrumentPageProps> {
  return PAGES[key] || GenericPage;
}

export type { InstrumentPageProps };
