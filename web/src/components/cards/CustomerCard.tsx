import { usd } from "@/lib/api";
import type { Customer, Invoice } from "@/lib/types";
import { Badge, Card, statusColor } from "./Card";

export function CustomerCard({ customer, invoices }: { customer: Customer; invoices: Invoice[] }) {
  return (
    <Card title="Customer account">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-base font-semibold">{customer.name}</div>
          <div className="text-zinc-500">{customer.email}</div>
        </div>
        <div className="flex gap-1.5">
          <Badge color="indigo">{customer.plan}</Badge>
          <Badge color={statusColor(customer.status)}>{customer.status.replace("_", " ")}</Badge>
        </div>
      </div>
      <div className="mt-1 text-xs text-zinc-500">
        {customer.seats} seats · customer since {new Date(customer.created_at).toLocaleDateString()}
      </div>
      {invoices.length > 0 && <InvoiceTable invoices={invoices} />}
    </Card>
  );
}

export function InvoiceTable({ invoices }: { invoices: Invoice[] }) {
  return (
    <table className="mt-3 w-full text-left text-xs">
      <thead className="text-zinc-500">
        <tr>
          <th className="py-1 font-medium">Invoice</th>
          <th className="py-1 font-medium">Date</th>
          <th className="py-1 font-medium hidden sm:table-cell">Description</th>
          <th className="py-1 font-medium text-right">Amount</th>
          <th className="py-1 font-medium text-right">Status</th>
        </tr>
      </thead>
      <tbody>
        {invoices.map((i) => (
          <tr key={i.id} className="border-t border-zinc-100 dark:border-zinc-800">
            <td className="py-1.5 font-mono">{i.id}</td>
            <td className="py-1.5">{i.issued_on}</td>
            <td className="py-1.5 hidden sm:table-cell text-zinc-600 dark:text-zinc-400">{i.description}</td>
            <td className="py-1.5 text-right tabular-nums">
              {usd(i.amount_usd)}
              {!!i.refunded_usd && <div className="text-emerald-600">−{usd(i.refunded_usd)}</div>}
            </td>
            <td className="py-1.5 text-right"><Badge color={statusColor(i.status)}>{i.status}</Badge></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
