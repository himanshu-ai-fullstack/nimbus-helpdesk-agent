import { usd } from "@/lib/api";
import type { Account, ActionSummary, RecordItem, Tenant } from "@/lib/types";
import { Badge, Card, humanize, statusColor } from "./Card";

export function AccountCard({
  tenant,
  account,
  records,
  actions,
}: {
  tenant: Tenant;
  account: Account;
  records: RecordItem[];
  actions: ActionSummary[];
}) {
  const fields = Object.entries(tenant.display.account_fields)
    .filter(([key]) => account.attributes[key] != null)
    .map(([key, label]) => `${label}: ${account.attributes[key]}`);
  return (
    <Card title={`${tenant.display.account_label} account`}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-base font-semibold">{account.name}</div>
          <div className="text-zinc-500">{account.email}</div>
        </div>
        <Badge color={statusColor(account.status)}>{humanize(account.status)}</Badge>
      </div>
      <div className="mt-1 text-xs text-zinc-500">
        {[...fields, `since ${new Date(account.created_on).toLocaleDateString()}`].join(" · ")}
      </div>
      {records.length > 0 && <RecordTable tenant={tenant} records={records} actions={actions} />}
    </Card>
  );
}

export function RecordTable({
  tenant,
  records,
  actions = [],
}: {
  tenant: Tenant;
  records: RecordItem[];
  actions?: ActionSummary[];
}) {
  const showAmount = records.some((r) => r.amount_usd != null);
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead className="text-zinc-500">
          <tr>
            <th className="py-1 pr-2 font-medium">Record</th>
            <th className="py-1 pr-2 font-medium">Date</th>
            <th className="hidden py-1 pr-2 font-medium sm:table-cell">Description</th>
            {showAmount && <th className="py-1 pr-2 text-right font-medium">Amount</th>}
            <th className="py-1 text-right font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {records.map((r) => {
            const open = actions.filter((a) => a.record_id === r.id && a.status !== "denied");
            return (
              <tr key={r.id} className="border-t border-zinc-100 align-top dark:border-zinc-800">
                <td className="py-1.5 pr-2">
                  <div className="font-mono">{r.id}</div>
                  <div className="text-zinc-500">{tenant.display.record_labels[r.type] ?? humanize(r.type)}</div>
                </td>
                <td className="py-1.5 pr-2 whitespace-nowrap">{r.date}</td>
                <td className="hidden py-1.5 pr-2 text-zinc-600 dark:text-zinc-400 sm:table-cell">{r.title}</td>
                {showAmount && (
                  <td className="py-1.5 pr-2 text-right tabular-nums">{r.amount_usd != null ? usd(r.amount_usd) : "—"}</td>
                )}
                <td className="py-1.5 text-right">
                  <Badge color={statusColor(r.status)}>{humanize(r.status)}</Badge>
                  {open.map((a) => (
                    <div key={a.id} className="mt-1 text-[11px] text-zinc-500">
                      {tenant.actions[a.kind] ?? humanize(a.kind)}
                      {a.amount_usd != null && ` ${usd(a.amount_usd)}`}: {humanize(a.status)}
                    </div>
                  ))}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
