import type { Triage } from "@/lib/types";
import { Badge, Card, humanize, statusColor } from "./Card";

export function TicketCard({ ticketId, triage }: { ticketId: number; triage: Triage }) {
  return (
    <Card title={`Escalated · ticket #${ticketId}`}>
      <div className="flex flex-wrap gap-1.5">
        <Badge color={statusColor(triage.priority)}>{triage.priority} priority</Badge>
        <Badge color="indigo">{humanize(triage.category)}</Badge>
        <Badge>{triage.sentiment}</Badge>
      </div>
      <p className="mt-3">{triage.summary}</p>
      {triage.customer_asks.length > 0 && (
        <ul className="mt-2 list-disc pl-5 text-zinc-600 dark:text-zinc-400">
          {triage.customer_asks.map((a) => <li key={a}>{a}</li>)}
        </ul>
      )}
      <div className="mt-3 text-xs text-zinc-500">
        <span className="font-medium">Suggested next step:</span> {triage.suggested_next_step}
      </div>
    </Card>
  );
}
