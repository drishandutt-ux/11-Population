"use client";

/** The way back to the simple view from anywhere in the full portal: one pill, bottom-left,
 *  on every pro page. It returns to the same session's simple screen (the report view when the
 *  pro Report tab is open), or to the simple home, and remembers the choice. */

import { usePathname, useRouter } from "next/navigation";
import { Sparkles } from "lucide-react";
import { setUiMode } from "@/lib/lite";

export default function SimpleViewPill() {
  const pathname = usePathname() || "";
  const router = useRouter();
  // Not on the simple pages themselves, not on the login gate, not on the landing (it has the switch).
  if (pathname.startsWith("/lite") || pathname.startsWith("/login") || pathname === "/") return null;

  function go() {
    setUiMode("simple");
    const m = pathname.match(/^\/session\/([^/]+)/);
    if (!m) { router.push("/"); return; }
    const tab = new URLSearchParams(window.location.search).get("tab");
    const view = tab === "report" ? "?view=report" : tab === "lab" ? "?view=lab" : "";
    router.push(`/lite/${m[1]}${view}`);
  }

  return (
    <button
      type="button"
      onClick={go}
      title="Back to the simple view: one step at a time, only what matters"
      className="fixed bottom-4 left-4 z-50 inline-flex items-center gap-1.5 h-9 pl-3 pr-3.5 rounded-full bg-primary text-primary-foreground text-[12.5px] font-semibold shadow-lg shadow-primary/20 hover:brightness-110 transition-all"
    >
      <Sparkles className="w-3.5 h-3.5" /> Simple view
    </button>
  );
}
