"use client";

import { useState } from "react";
import { api, SimMode } from "@/lib/api";
import { Pause, Square, Loader2, Play } from "lucide-react";

interface Props {
  sessionId: string;
  status: string;
  intensity: number;
  mode: SimMode;
  onUpdate: () => void;
}

export default function SimulationControls({ sessionId, status, intensity, mode, onUpdate }: Props) {
  const [loading, setLoading] = useState(false);

  async function act(fn: () => Promise<any>) {
    setLoading(true);
    try { await fn(); onUpdate(); } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }

  if (status === "simulating") {
    return (
      <button
        onClick={() => act(() => api.simulation.pause(sessionId))}
        disabled={loading}
        className="flex items-center gap-2 bg-orange-500/20 hover:bg-orange-500/30 border border-orange-500/30 text-orange-400 text-sm font-medium px-4 py-2 rounded-lg transition-all disabled:opacity-50"
      >
        {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Pause className="w-4 h-4" />}
        Pause
      </button>
    );
  }

  if (status === "paused") {
    return (
      <div className="flex items-center gap-2">
        <button
          onClick={() => act(() => api.simulation.start(sessionId, intensity, mode))}
          disabled={loading}
          className="flex items-center gap-2 bg-primary hover:bg-primary/90 disabled:opacity-50 text-primary-foreground text-sm font-medium px-4 py-2 rounded-lg transition-all"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
          Resume
        </button>
        <button
          onClick={() => act(() => api.simulation.stop(sessionId))}
          disabled={loading}
          className="flex items-center gap-2 border border-border text-muted-foreground hover:text-foreground text-sm px-3 py-2 rounded-lg transition-all disabled:opacity-50"
        >
          <Square className="w-4 h-4" />
        </button>
      </div>
    );
  }

  return null;
}
