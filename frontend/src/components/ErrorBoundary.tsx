"use client";

import React from "react";
import { AlertTriangle } from "lucide-react";

interface Props {
  label?: string;
  children: React.ReactNode;
}
interface State {
  error: Error | null;
}

/** Keeps one broken panel from blanking the whole app ("Application error: a client-side
 *  exception has occurred"). The failing subtree is replaced by an inline notice with the
 *  message; everything else keeps working. */
export default class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error(`[${this.props.label || "panel"}] render failed:`, error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="rounded-lg border border-red-500/30 bg-red-500/5 px-4 py-3 text-xs text-red-300 flex items-start gap-2">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">{this.props.label || "This panel"} couldn&apos;t be displayed.</p>
            <p className="text-red-300/70 mt-0.5 break-words">{this.state.error.message}</p>
            <button onClick={() => this.setState({ error: null })} className="mt-1.5 text-[11px] underline text-red-200/80 hover:text-red-100">Try again</button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
