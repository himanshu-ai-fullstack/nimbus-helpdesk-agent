import type { UIMessage } from "ai";

export type Invoice = {
  id: string;
  amount_usd: number;
  refunded_usd?: number;
  refunded_or_pending_usd?: number;
  status: string;
  description: string;
  issued_on: string;
  customer_name?: string;
  email?: string;
};

export type Customer = {
  id: string;
  name: string;
  email: string;
  plan: "free" | "pro" | "business";
  seats: number;
  status: string;
  created_at: string;
};

export type Triage = {
  category: string;
  priority: "low" | "medium" | "high" | "urgent";
  sentiment: string;
  summary: string;
  customer_asks: string[];
  suggested_next_step: string;
};

export type Refund = {
  id: number;
  invoice_id: string;
  amount_usd: number;
  reason: string;
  status: string;
  customer_name: string;
};

type ToolError = { error: string };

// Mirrors the tools defined in api/app/helpdesk/tools.py.
export type HelpdeskTools = {
  search_help_center: {
    input: { query: string };
    output: { articles: { id: number; title: string; excerpt: string; score: number }[] } | ToolError;
  };
  lookup_customer: {
    input: { email: string };
    output:
      | { found: true; customer: Customer; invoices: Invoice[]; refunds: Pick<Refund, "id" | "invoice_id" | "amount_usd" | "status">[] }
      | { found: false; email: string }
      | ToolError;
  };
  get_invoice: {
    input: { invoice_id: string };
    output: { found: true; invoice: Invoice } | { found: false; invoice_id: string } | ToolError;
  };
  propose_refund: {
    input: { invoice_id: string; amount_usd: number; reason: string };
    output:
      | { created: true; refund: Refund; note: string }
      | { created: false; policy_violation: string }
      | ToolError;
  };
  escalate_to_human: {
    input: { reason: string; customer_email?: string };
    output: { ticket_id: number; triage: Triage } | ToolError;
  };
};

export type HelpdeskMessage = UIMessage<never, never, HelpdeskTools>;

export function isError(output: unknown): output is ToolError {
  return typeof output === "object" && output !== null && "error" in output;
}
