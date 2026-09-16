"use client";

import { useParams } from "next/navigation";
import PopulationStudio from "@/components/population/PopulationStudio";

/** Standalone route for the Population Studio. The Studio is also the Agents tab's first screen;
 *  this page keeps deep links working. */
export default function PopulationStudioPage() {
  const { id } = useParams<{ id: string }>();
  return <PopulationStudio sessionId={id} />;
}
