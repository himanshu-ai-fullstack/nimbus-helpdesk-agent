import { Suspense } from "react";
import { Badge, statusColor } from "@/components/cards/Card";
import { API_URL } from "@/lib/api";
import type { Triage } from "@/lib/types";

type Ticket = {
  id: number;
  customer_name: string | null;
  triage: Triage;
  status: string;
  created_at: string;
};

const PRIORITY_ORDER = { urgent: 0, high: 1, medium: 2, low: 3 } as const;

export default function TicketsPage() {
  return (
    <main className="mx-auto w-full max-w-5xl flex-1 overflow-y-auto px-4 py-8">
      <h1 className="text-xl font-semibold">Ticket queue</h1>
      <p className="mt-1 text-sm text-zinc-500">
        Conversations the agent escalated. Each one was triaged by Claude into a validated schema
        (category, priority, sentiment, asks), so the queue can sort and route without a human reading every chat.
      </p>
      <Suspense fallback={<p className="mt-6 text-sm text-zinc-500">Loading tickets…</p>}>
        <TicketList />
      </Suspense>
    </main>
  );
}

async function TicketList() {
  let tickets: Ticket[] = [];
  let failed = false;
  try {
    const res = await fetch(`${API_URL}/api/tickets`, { cache: "no-store" });
    tickets = await res.json();
  } catch {
    failed = true;
  }
  tickets.sort((a, b) => PRIORITY_ORDER[a.triage.priority] - PRIORITY_ORDER[b.triage.priority]);

  return (
    <>
      {failed && <p className="mt-6 text-sm text-red-600">Couldn&apos;t reach the API.</p>}
      {!failed && tickets.length === 0 && (
        <p className="mt-6 text-sm text-zinc-500">No tickets yet. Ask the agent for a human to create one.</p>
      )}
      <div className="mt-6 space-y-3">
        {tickets.map((t) => (
          <div key={t.id} className="rounded-xl border border-zinc-200 dark:border-zinc-800 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-sm text-zinc-500">#{t.id}</span>
              <Badge color={statusColor(t.triage.priority)}>{t.triage.priority}</Badge>
              <Badge color="indigo">{t.triage.category.replace("_", " ")}</Badge>
              <Badge>{t.triage.sentiment}</Badge>
              <span className="ml-auto text-xs text-zinc-500">
                {t.customer_name ?? "Unknown customer"} · {new Date(t.created_at).toLocaleString()}
              </span>
            </div>
            <p className="mt-2 text-sm">{t.triage.summary}</p>
            <p className="mt-1 text-xs text-zinc-500">Next step: {t.triage.suggested_next_step}</p>
          </div>
        ))}
      </div>
    </>
  );
}
