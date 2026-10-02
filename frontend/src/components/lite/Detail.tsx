"use client";

/** "See in detail": wrap anything in the simple view and a small pill appears on hover (or
 *  keyboard focus) that opens the pro page where the same thing is analysed in full. */

import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";

type Props = {
  href: string;
  label?: string;
  /** Where the pill sits relative to the wrapped content. */
  at?: "top-right" | "top-left" | "bottom-right" | "inline";
  className?: string;
  children: React.ReactNode;
};

const POS: Record<NonNullable<Props["at"]>, string> = {
  "top-right": "top-2 right-2",
  "top-left": "top-2 left-2",
  "bottom-right": "bottom-2 right-2",
  inline: "top-1/2 -translate-y-1/2 right-0",
};

export default function Detail({ href, label = "See in detail", at = "top-right", className, children }: Props) {
  return (
    <div className={cn("relative group", className)}>
      {children}
      <Link href={href} className={cn("detail-pill", POS[at])} title="Open this in the full portal" onClick={(e) => e.stopPropagation()}>
        {label} <ArrowUpRight className="w-3 h-3" />
      </Link>
    </div>
  );
}

/** The same idea as a plain small link, for places where a pill cannot float (a sentence, a header). */
export function DetailLink({ href, label = "See in detail", className }: { href: string; label?: string; className?: string }) {
  return (
    <Link href={href} className={cn("inline-flex items-center gap-1 text-[12px] font-medium text-muted-foreground hover:text-primary transition-colors", className)} title="Open this in the full portal">
      {label} <ArrowUpRight className="w-3 h-3" />
    </Link>
  );
}
