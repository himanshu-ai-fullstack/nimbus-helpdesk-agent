"use client";

import Link from "next/link";
import { useState } from "react";
import { api, usd } from "@/lib/api";
import type { ProposedAction } from "@/lib/types";
import { useTenant } from "../tenant";
import { Badge, Card, humanize, statusColor } from "./Card";

/** An action the agent proposed. Approving needs this tenant's admin token: the
 * agent can only ever create a pending request. */
export function ActionCard({ action }: { action: ProposedAction }) {
  const { tenant, token } = useTenant();
  const [status, setStatus] = useState(action.status);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function decide(approve: boolean) {
    setBusy(true);
    setError(null);
    try {
      const res = await api<{ status: string }>(`/api/t/${tenant.slug}/actions/${action.id}/decision`, {
        method: "POST",
        body: JSON.stringify({ approve }),
        token,
      });
      setStatus(res.status);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  const pending = status === "pending_approval";
  return (
    <Card title={`${action.label} request #${action.id}`} tone={pending ? "warn" : status === "approved" ? "success" : "default"}>
      <div className="flex items-baseline justify-between gap-3">
        <div className="text-lg font-semibold">
          {action.amount_usd != null ? <span className="tabular-nums">{usd(action.amount_usd)}</span> : action.record_title}
        </div>
        <Badge color={statusColor(status)}>{humanize(status)}</Badge>
      </div>
      <div className="mt-1 text-zinc-500">
        {action.account_name} · <span className="font-mono">{action.record_id}</span>
        {action.amount_usd != null && <> · {action.record_title}</>}
      </div>
      <p className="mt-2">{action.reason}</p>
      {pending && (
        <div className="mt-4 rounded-lg bg-amber-50 p-3 dark:bg-amber-950/40">
          <div className="mb-2 text-xs text-amber-800 dark:text-amber-300">
            Human in the loop: the agent can only request this. {tenant.name} staff approve it.
          </div>
          {token ? (
            <div className="flex gap-2">
              <button
                disabled={busy}
                onClick={() => decide(true)}
                className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
              >
                Approve
              </button>
              <button
                disabled={busy}
                onClick={() => decide(false)}
                className="rounded-lg border border-zinc-300 px-3 py-1.5 text-sm font-medium hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
              >
                Deny
              </button>
            </div>
          ) : (
            <Link href={`/t/${tenant.slug}/approvals`} className="text-xs font-medium text-amber-900 underline dark:text-amber-200">
              Open the approvals queue (staff sign-in)
            </Link>
          )}
        </div>
      )}
      {error && <div className="mt-2 text-xs text-red-600">{error}</div>}
    </Card>
  );
}
