"use client";

import { useParams } from "next/navigation";
import AgentBuilder from "@/components/simulation/AgentBuilder";

/** Build your own agent: one hand-authored twin at a time, saved into a lineup. Reached from the Agents tab. */
export default function AgentBuilderPage() {
  const { id } = useParams<{ id: string }>();
  return <AgentBuilder sessionId={id} />;
}
