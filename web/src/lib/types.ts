import type { UIMessage } from "ai";

export type Tenant = {
  slug: string;
  name: string;
  industry: string;
  tagline: string;
  brand_color: string;
  persona: string;
  audience: "customers" | "employees";
  greeting: string;
  suggestions: string[];
  // action kind -> label, e.g. { refund: "Refund" }
  actions: Record<string, string>;
  display: {
    account_label: string;
    account_fields: Record<string, string>;
    record_labels: Record<string, string>;
  };
};

export type Account = {
  id: string;
  email: string;
  name: string;
  status: string;
  created_on: string;
  attributes: Record<string, unknown>;
};

export type RecordItem = {
  id: string;
  type: string;
  title: string;
  status: string;
  amount_usd: number | null;
  currency: string;
  date: string;
  attributes: Record<string, unknown>;
};

export type ActionSummary = {
  id: number;
  kind: string;
  record_id: string;
  amount_usd: number | null;
  status: string;
};

export type ProposedAction = ActionSummary & {
  label: string;
  record_title: string;
  reason: string;
  account_name: string;
};

export type Triage = {
  category: string;
  priority: "low" | "medium" | "high" | "urgent";
  sentiment: string;
  summary: string;
  customer_asks: string[];
  suggested_next_step: string;
};

export type Article = {
  id: number;
  document_id: number;
  title: string;
  page: number | null;
  excerpt: string;
  score: number;
};

type ToolError = { error: string };

// Mirrors the tools built in api/app/tools/registry.py.
export type AgentTools = {
  search_knowledge_base: {
    input: { query: string };
    output: { articles: Article[] } | ToolError;
  };
  lookup_account: {
    input: { email: string };
    output:
      | { found: true; account: Account; records: RecordItem[]; actions: ActionSummary[] }
      | { found: false; email: string }
      | ToolError;
  };
  get_record: {
    input: { record_id: string };
    output: { found: true; record: RecordItem } | { found: false; record_id: string; note: string } | ToolError;
  };
  propose_action: {
    input: { kind: string; record_id: string; amount_usd?: number | null; reason: string };
    output:
      | { created: true; action: ProposedAction; note: string }
      | { created: false; policy_violation: string }
      | ToolError;
  };
  escalate_to_human: {
    input: { reason: string; account_email?: string | null };
    output: { ticket_id: number; triage: Triage } | ToolError;
  };
  flag_knowledge_gap: {
    input: { topic: string };
    output: { logged: true; topic: string } | ToolError;
  };
};

export type Citation = { textId: string; source: string; title: string; citedText: string };

export type AgentMessage = UIMessage<never, { citation: Citation }, AgentTools>;

export function isError(output: unknown): output is ToolError {
  return typeof output === "object" && output !== null && "error" in output;
}
