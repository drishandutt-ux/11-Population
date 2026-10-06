"use client";

/** The frame every simple-view page sits in: the light skin, one quiet header (back, title,
 *  where we are, the way into the full portal) and the content. */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { useLiteRoot } from "@/lib/lite";

export type LiteStep = "ask" | "people" | "debate" | "report" | "tools";
const STEPS: { key: LiteStep; label: string }[] = [
  { key: "ask", label: "Ask" },
  { key: "people", label: "People" },
  { key: "debate", label: "Conversation" },
  { key: "report", label: "Report" },
  { key: "tools", label: "Tools" },
];

type Props = {
  title?: string;
  backHref?: string;
  /** The current step; steps before it are shown as done. */
  step?: LiteStep;
  /** The pro page for this screen. */
  proHref?: string;
  /** When given, the steps are buttons the reader can move between. */
  onStep?: (step: LiteStep) => void;
  right?: React.ReactNode;
  /** `page` scrolls as a document; `app` fills the viewport (for the live conversation). */
  layout?: "page" | "app";
  children: React.ReactNode;
};

export default function LiteShell({ title, backHref = "/", step, proHref, onStep, right, layout = "page", children }: Props) {
  useLiteRoot();
  const router = useRouter();
  const idx = step ? STEPS.findIndex((s) => s.key === step) : -1;
  return (
    <div className={cn("lite lite-bg text-foreground flex flex-col", layout === "app" ? "h-screen overflow-hidden" : "min-h-screen")}>
      <header className="shrink-0 h-14 px-4 sm:px-6 flex items-center gap-3">
        <button type="button" onClick={() => router.push(backHref)} className="w-9 h-9 rounded-full inline-flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-foreground/5 transition-colors" title="Back">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <span className="text-[14px] font-medium text-foreground truncate max-w-[36vw]">{title || ""}</span>
        {step && (
          <nav className="mx-auto hidden sm:flex items-center gap-1.5" aria-label="Where you are">
            {STEPS.map((s, i) => {
              const cls = cn("inline-flex items-center gap-1.5 text-[12px] font-medium px-2.5 h-7 rounded-full transition-colors",
                i === idx ? "bg-foreground text-background" : i < idx ? "text-foreground/70" : "text-muted-foreground/60",
                onStep && i !== idx && "hover:bg-foreground/5 hover:text-foreground");
              const dot = <span className={cn("w-1.5 h-1.5 rounded-full", i === idx ? "bg-background" : i < idx ? "bg-primary" : "bg-muted-foreground/40")} />;
              return onStep ? (
                <button key={s.key} type="button" onClick={() => onStep(s.key)} className={cls} title={`Go to ${s.label}`}>{dot}{s.label}</button>
              ) : (
                <span key={s.key} className={cls}>{dot}{s.label}</span>
              );
            })}
          </nav>
        )}
        <div className={cn("flex items-center gap-2", !step && "ml-auto")}>
          {right}
          {proHref && (
            <Link href={proHref} className="lite-pill hover:text-primary hover:border-primary/40 transition-colors" title="Open the full portal, where everything is analysed in detail">
              Full portal <ArrowUpRight className="w-3.5 h-3.5" />
            </Link>
          )}
        </div>
      </header>
      <div className={cn(layout === "app" ? "flex-1 min-h-0 flex flex-col" : "flex-1")}>{children}</div>
    </div>
  );
}
