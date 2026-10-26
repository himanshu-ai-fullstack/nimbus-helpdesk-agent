"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge, humanize, statusColor } from "@/components/cards/Card";
import { AdminGate, useTenant } from "@/components/tenant";
import { api, usd } from "@/lib/api";

type Action = {
  id: number;
  kind: string;
  label: string;
  record_id: string;
  account_name: string;
  amount_usd: number | null;
  reason: string;
  status: string;
  created_at: string;
  decided_at: string | null;
};

export default function ApprovalsPage() {
  const { tenant } = useTenant();
  return (
    <AdminGate
      title="Approvals"
      description={`Actions ${tenant.persona} requested. The agent can only propose them, and only within ${tenant.name}'s policy; nothing happens until someone here approves.`}
    >
      <ActionQueue />
    </AdminGate>
  );
}

function ActionQueue() {
  const { tenant, token } = useTenant();
  const [actions, setActions] = useState<Action[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Action[]>(`/api/t/${tenant.slug}/actions`, { token })
      .then(setActions)
      .catch((e) => setError(e.message));
  }, [tenant.slug, token]);

  useEffect(load, [load]);

  async function decide(id: number, approve: boolean) {
    try {
      await api(`/api/t/${tenant.slug}/actions/${id}/decision`, { method: "POST", body: JSON.stringify({ approve }), token });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    }
    load();
  }

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!actions) return <p className="text-sm text-zinc-500">Loading…</p>;
  if (actions.length === 0) {
    return <p className="text-sm text-zinc-500">Nothing yet. Ask {tenant.persona} for something that needs approval.</p>;
  }
  const pending = actions.filter((a) => a.status === "pending_approval");
  const decided = actions.filter((a) => a.status !== "pending_approval");

  return (
    <div className="space-y-8">
      <section>
        <h2 className="text-sm font-medium text-zinc-500">Waiting for approval ({pending.length})</h2>
        <div className="mt-3 space-y-3">
          {pending.map((a) => (
            <Row key={a.id} action={a}>
              <div className="flex gap-2">
                <button onClick={() => decide(a.id, true)} className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700">
                  Approve
                </button>
                <button onClick={() => decide(a.id, false)} className="rounded-lg border border-zinc-300 px-3 py-1.5 text-sm font-medium dark:border-zinc-700">
                  Deny
                </button>
              </div>
            </Row>
          ))}
          {pending.length === 0 && <p className="text-sm text-zinc-500">All caught up.</p>}
        </div>
      </section>
      {decided.length > 0 && (
        <section>
          <h2 className="text-sm font-medium text-zinc-500">Decided</h2>
          <div className="mt-3 space-y-3">
            {decided.map((a) => (
              <Row key={a.id} action={a}>
                <Badge color={statusColor(a.status)}>{humanize(a.status)}</Badge>
              </Row>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function Row({ action: a, children }: { action: Action; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm text-zinc-500">#{a.id}</span>
          <span className="font-medium">{a.label}</span>
          {a.amount_usd != null && <span className="tabular-nums">{usd(a.amount_usd)}</span>}
          <span className="text-sm text-zinc-500">
            · {a.account_name} · <span className="font-mono">{a.record_id}</span>
          </span>
        </div>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">{a.reason}</p>
        <p className="mt-1 text-xs text-zinc-400">Requested {new Date(a.created_at).toLocaleString()}</p>
      </div>
      {children}
    </div>
  );
}
