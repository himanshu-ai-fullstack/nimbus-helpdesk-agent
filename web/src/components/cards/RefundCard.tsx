"use client";

import { useState } from "react";
import { API_URL, usd } from "@/lib/api";
import type { Refund } from "@/lib/types";
import { Badge, Card, statusColor } from "./Card";

export function RefundCard({ refund }: { refund: Refund }) {
  const [status, setStatus] = useState(refund.status);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function decide(approve: boolean) {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/api/refunds/${refund.id}/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approve }),
      });
      if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText);
      setStatus((await res.json()).status);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  const pending = status === "pending_approval";
  return (
    <Card title={`Refund request #${refund.id}`} tone={pending ? "warn" : status === "approved" ? "success" : "default"}>
      <div className="flex items-baseline justify-between">
        <div className="text-2xl font-semibold tabular-nums">{usd(refund.amount_usd)}</div>
        <Badge color={statusColor(status)}>{status.replace("_", " ")}</Badge>
      </div>
      <div className="mt-1 text-zinc-500">
        {refund.customer_name} · invoice <span className="font-mono">{refund.invoice_id}</span>
      </div>
      <p className="mt-2">{refund.reason}</p>
      {pending && (
        <div className="mt-4 rounded-lg bg-amber-50 dark:bg-amber-950/40 p-3">
          <div className="text-xs text-amber-800 dark:text-amber-300 mb-2">
            Human in the loop: the agent can only propose refunds. A support lead approves them here.
          </div>
          <div className="flex gap-2">
            <button disabled={busy} onClick={() => decide(true)}
              className="rounded-lg bg-emerald-600 px-3 py-1.5 text-white text-sm font-medium hover:bg-emerald-700 disabled:opacity-50">
              Approve refund
            </button>
            <button disabled={busy} onClick={() => decide(false)}
              className="rounded-lg border border-zinc-300 dark:border-zinc-700 px-3 py-1.5 text-sm font-medium hover:bg-zinc-50 dark:hover:bg-zinc-800 disabled:opacity-50">
              Deny
            </button>
          </div>
        </div>
      )}
      {error && <div className="mt-2 text-xs text-red-600">{error}</div>}
    </Card>
  );
}
