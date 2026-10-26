"use client";

import { isError, type AgentMessage } from "@/lib/types";
import { AccountCard, RecordTable } from "./cards/AccountCard";
import { ActionCard } from "./cards/ActionCard";
import { Card, Skeleton } from "./cards/Card";
import { Sources } from "./cards/Sources";
import { TicketCard } from "./cards/TicketCard";
import { useTenant } from "./tenant";

type Part = AgentMessage["parts"][number];

const PENDING_LABEL: Record<string, string> = {
  search_knowledge_base: "Searching the knowledge base…",
  lookup_account: "Looking up the account…",
  get_record: "Fetching the record…",
  propose_action: "Preparing a request for approval…",
  escalate_to_human: "Triaging and creating a ticket…",
  flag_knowledge_gap: "Noting a gap in the knowledge base…",
};

/** Generative UI: each tool call renders as its own component as it streams. */
export function ToolPart({ part }: { part: Part }) {
  const { tenant } = useTenant();
  if (!part.type.startsWith("tool-")) return null;
  const p = part as Extract<Part, { type: `tool-${string}` }>;
  const name = p.type.slice("tool-".length);

  if (p.state === "input-streaming" || p.state === "input-available") {
    return <Skeleton label={PENDING_LABEL[name] ?? `Running ${name}…`} />;
  }
  if (p.state === "output-error") {
    return <Card title={name} tone="warn">Tool failed: {p.errorText}</Card>;
  }
  if (p.state !== "output-available") return null;
  if (isError(p.output)) {
    return <Card title={name} tone="warn">{p.output.error}</Card>;
  }

  switch (p.type) {
    case "tool-search_knowledge_base":
      if ("articles" in p.output) return <Sources query={p.input.query} articles={p.output.articles} />;
      return null;
    case "tool-lookup_account":
      if ("found" in p.output && p.output.found) {
        return <AccountCard tenant={tenant} account={p.output.account} records={p.output.records} actions={p.output.actions} />;
      }
      return <Card title={`${tenant.display.account_label} account`} tone="warn">No account found for {p.input.email}</Card>;
    case "tool-get_record":
      if ("found" in p.output && p.output.found) {
        return <Card title="Record"><RecordTable tenant={tenant} records={[p.output.record]} /></Card>;
      }
      return <Card title="Record" tone="warn">{p.input.record_id} not found</Card>;
    case "tool-propose_action":
      if ("created" in p.output && p.output.created) return <ActionCard action={p.output.action} />;
      if ("policy_violation" in p.output) {
        const label = tenant.actions[p.input.kind] ?? p.input.kind;
        return <Card title={`${label} blocked by policy`} tone="warn">{p.output.policy_violation}</Card>;
      }
      return null;
    case "tool-escalate_to_human":
      if ("ticket_id" in p.output) return <TicketCard ticketId={p.output.ticket_id} triage={p.output.triage} />;
      return null;
    case "tool-flag_knowledge_gap":
      return (
        <div className="my-1 text-xs text-zinc-500">📝 Flagged a knowledge-base gap for {tenant.name}: “{p.input.topic}”</div>
      );
  }
  return null;
}
