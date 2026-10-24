import { isError, type HelpdeskMessage } from "@/lib/types";
import { Card, Skeleton } from "./cards/Card";
import { CustomerCard, InvoiceTable } from "./cards/CustomerCard";
import { RefundCard } from "./cards/RefundCard";
import { Sources } from "./cards/Sources";
import { TicketCard } from "./cards/TicketCard";

type Part = HelpdeskMessage["parts"][number];

const PENDING_LABEL: Record<string, string> = {
  search_help_center: "Searching the help center…",
  lookup_customer: "Looking up the account…",
  get_invoice: "Fetching the invoice…",
  propose_refund: "Preparing a refund request…",
  escalate_to_human: "Triaging and creating a ticket…",
};

/** Generative UI: each tool call renders as its own component as it streams. */
export function ToolPart({ part }: { part: Part }) {
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
    case "tool-search_help_center":
      if ("articles" in p.output) return <Sources query={p.input.query} articles={p.output.articles} />;
      return null;
    case "tool-lookup_customer":
      if ("found" in p.output && p.output.found) {
        return <CustomerCard customer={p.output.customer} invoices={p.output.invoices} />;
      }
      return <Card title="Customer account" tone="warn">No account found for {p.input.email}</Card>;
    case "tool-get_invoice":
      if ("found" in p.output && p.output.found) {
        return <Card title="Invoice"><InvoiceTable invoices={[p.output.invoice]} /></Card>;
      }
      return <Card title="Invoice" tone="warn">Invoice {p.input.invoice_id} not found</Card>;
    case "tool-propose_refund":
      if ("created" in p.output && p.output.created) return <RefundCard refund={p.output.refund} />;
      if ("policy_violation" in p.output) {
        return (
          <Card title="Refund blocked by policy" tone="warn">
            {p.output.policy_violation}
          </Card>
        );
      }
      return null;
    case "tool-escalate_to_human":
      if ("ticket_id" in p.output) return <TicketCard ticketId={p.output.ticket_id} triage={p.output.triage} />;
      return null;
  }
  return null;
}
