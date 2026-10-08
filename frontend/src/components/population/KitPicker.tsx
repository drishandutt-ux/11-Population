"use client";

import { useEffect, useState } from "react";
import { api, PopulationKit } from "@/lib/api";
import { Library, Loader2 } from "lucide-react";

interface Props {
  count: number;
  busy: boolean;
  /** Start a build from the kit: it opens at plan review, every segment accepted. */
  onStart: (kitId: string, preset: string | null) => void;
}

/** "Or start from a published segmentation": a kit replaces research and planning — its segments,
 *  their shares and each person's facts and beliefs come from the published study. */
export default function KitPicker({ count, busy, onStart }: Props) {
  const [kits, setKits] = useState<PopulationKit[]>([]);
  const [preset, setPreset] = useState<Record<string, string>>({});
  useEffect(() => { api.population.kits().then((r) => setKits(r.kits || [])).catch(() => {}); }, []);
  if (!kits.length) return null;
  return (
    <div className="surface rounded-xl overflow-hidden animate-fade-in">
      <div className="flex items-center gap-2 px-4 h-11 border-b hairline">
        <Library className="w-3.5 h-3.5 text-muted-foreground" />
        <span className="text-[13px] font-medium text-foreground">Or start from a published segmentation</span>
      </div>
      <div className="divide-y divide-border/40">
        {kits.map((k) => {
          const presets = Object.entries(k.share_presets || {});
          const chosen = preset[k.id] || k.default_preset || presets[0]?.[0] || "";
          return (
            <div key={k.id} className="px-4 py-3 space-y-2">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-[13px] text-foreground">{k.title}</div>
                  <div className="text-[11px] text-muted-foreground leading-snug">{k.description}</div>
                </div>
                <button disabled={busy} onClick={() => onStart(k.id, chosen || null)} className="btn btn-sm btn-secondary shrink-0">
                  {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null} Plan {count} agents
                </button>
              </div>
              <div className="flex flex-wrap gap-1">
                {k.segments.map((s) => (
                  <span key={s.id} title={s.tagline} className="text-[10px] rounded-full border border-border/60 px-2 py-0.5 text-muted-foreground">{s.name}</span>
                ))}
              </div>
              {presets.length > 1 && (
                <label className="flex items-center gap-2 text-[11px] text-muted-foreground">
                  Segment shares
                  <select value={chosen} onChange={(e) => setPreset((p) => ({ ...p, [k.id]: e.target.value }))} className="bg-input border border-border rounded-lg px-2 py-1 text-[11px] text-foreground">
                    {presets.map(([key, v]) => <option key={key} value={key}>{v.label}</option>)}
                  </select>
                </label>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
