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
        className="btn btn-sm text-amber-300 bg-amber-500/10 hover:bg-amber-500/15"
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
          className="btn btn-sm btn-primary"
        >
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
          Resume
        </button>
        <button
          onClick={() => act(() => api.simulation.stop(sessionId))}
          disabled={loading}
          className="btn btn-sm btn-ghost px-2"
        >
          <Square className="w-4 h-4" />
        </button>
      </div>
    );
  }

  return null;
}
