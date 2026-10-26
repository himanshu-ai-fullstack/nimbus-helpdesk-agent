"use client";

import { useEffect, useState } from "react";
import { Badge, humanize, statusColor } from "@/components/cards/Card";
import { AdminGate, useTenant } from "@/components/tenant";
import { api } from "@/lib/api";
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
  const { tenant } = useTenant();
  return (
    <AdminGate
      title="Ticket queue"
      description={`Conversations ${tenant.persona} escalated. Each was triaged by Claude into ${tenant.name}'s categories (plus priority, sentiment and asks), so the queue sorts and routes itself.`}
    >
      <TicketList />
    </AdminGate>
  );
}

function TicketList() {
  const { tenant, token } = useTenant();
  const [tickets, setTickets] = useState<Ticket[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Ticket[]>(`/api/t/${tenant.slug}/tickets`, { token })
      .then((t) => setTickets([...t].sort((a, b) => PRIORITY_ORDER[a.triage.priority] - PRIORITY_ORDER[b.triage.priority])))
      .catch((e) => setError(e.message));
  }, [tenant.slug, token]);

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!tickets) return <p className="text-sm text-zinc-500">Loading…</p>;
  if (tickets.length === 0) return <p className="text-sm text-zinc-500">No tickets yet. Ask {tenant.persona} for a human to create one.</p>;

  return (
    <div className="space-y-3">
      {tickets.map((t) => (
        <div key={t.id} className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm text-zinc-500">#{t.id}</span>
            <Badge color={statusColor(t.triage.priority)}>{t.triage.priority}</Badge>
            <Badge color="indigo">{humanize(t.triage.category)}</Badge>
            <Badge>{t.triage.sentiment}</Badge>
            <span className="ml-auto text-xs text-zinc-500">
              {t.customer_name ?? `Unknown ${tenant.display.account_label.toLowerCase()}`} · {new Date(t.created_at).toLocaleString()}
            </span>
          </div>
          <p className="mt-2 text-sm">{t.triage.summary}</p>
          <p className="mt-1 text-xs text-zinc-500">Next step: {t.triage.suggested_next_step}</p>
        </div>
      ))}
    </div>
  );
}
