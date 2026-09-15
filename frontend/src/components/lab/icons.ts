import { Beaker, ClipboardList, FlaskConical, LucideIcon, MessageCircleQuestion, ShoppingCart } from "lucide-react";

/** Instrument key → the icon that stands for it in the picker and in past runs.
 *
 *  A registry like `pages/` and `forms/`: a tool with no entry here gets the Lab's own beaker,
 *  so the backend can ship an instrument before its icon exists. The shell never branches on
 *  instrument keys itself. */
const ICONS: Record<string, LucideIcon> = {
  purchase_intent: ShoppingCart,
  survey: ClipboardList,
  ask: MessageCircleQuestion,
};

/** The A/B test is the shell's own second primitive, not an instrument. */
export const EXPERIMENT_ICON: LucideIcon = FlaskConical;

export function iconFor(key: string): LucideIcon {
  return ICONS[key] || Beaker;
}
