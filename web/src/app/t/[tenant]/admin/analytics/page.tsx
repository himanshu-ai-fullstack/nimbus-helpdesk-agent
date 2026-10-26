"use client";

import { useEffect, useState } from "react";
import { humanize } from "@/components/cards/Card";
import { AdminGate, useTenant } from "@/components/tenant";
import { api, usd } from "@/lib/api";

type Outcome = "answered" | "action_proposed" | "escalated";
type Day = { day: string } & Record<Outcome, number>;

type Analytics = {
  days: number;
  conversations: number;
  outcomes: Record<Outcome, number>;
  containment_rate: number | null;
  escalation_rate: number | null;
  feedback: { up: number; down: number };
  helpfulness: number | null;
  actions: { approved: number; denied: number; pending: number };
  approval_rate: number | null;
  latency_ms: { p50: number | null; p95: number | null; turns: number };
  cost: { total_usd: number; per_conversation_usd: number | null; cache_hit_rate: number | null; cache_savings_usd: number };
  daily: Day[];
  tools: { name: string; calls: number; errors: number; avg_ms: number }[];
  top_cited: { title: string; citations: number }[];
  knowledge_gaps: { topic: string; n: number; last_seen: string; example: string | null }[];
  thumbs_down: { created_at: string; comment: string | null; question: string | null }[];
  config_versions: { version: string; conversations: number; escalation_rate: number | null; avg_rating: number | null; first_seen: string }[];
};

const SERIES: { key: Outcome; label: string; color: string }[] = [
  { key: "answered", label: "Answered", color: "var(--series-1)" },
  { key: "action_proposed", label: "Action requested", color: "var(--series-2)" },
  { key: "escalated", label: "Escalated", color: "var(--series-3)" },
];

const pct = (v: number | null) => (v == null ? "—" : `${Math.round(v * 100)}%`);
const secs = (ms: number | null) => (ms == null ? "—" : `${(ms / 1000).toFixed(1)}s`);

export default function AnalyticsPage() {
  const { tenant } = useTenant();
  return (
    <AdminGate
      title="Analytics"
      description={`How ${tenant.persona} is doing for ${tenant.name}: how many conversations it resolves without a person, whether answers help, what it costs, and what the knowledge base is missing.`}
    >
      <Dashboard />
    </AdminGate>
  );
}

function Dashboard() {
  const { tenant, token } = useTenant();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<Analytics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api<Analytics>(`/api/t/${tenant.slug}/analytics?days=${days}`, { token })
      .then((d) => live && setData(d))
      .catch((e) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [tenant.slug, token, days]);

  if (error) return <p className="text-sm text-red-600">{error}</p>;

  return (
    <div className="viz-root space-y-6">
      <div className="flex items-center gap-1 text-sm" role="group" aria-label="Date range">
        {[7, 30, 90].map((d) => (
          <button
            key={d}
            onClick={() => setDays(d)}
            aria-pressed={days === d}
            className={`rounded-lg px-3 py-1 ${days === d ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900" : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"}`}
          >
            Last {d} days
          </button>
        ))}
      </div>

      {!data ? (
        <p className="text-sm text-zinc-500">Loading…</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Tile label="Conversations" value={String(data.conversations)} note={`${data.latency_ms.turns} agent turns`} />
            <Tile label="Containment" value={pct(data.containment_rate)} note="resolved without a person" />
            <Tile
              label="Helpful answers"
              value={pct(data.helpfulness)}
              note={`${data.feedback.up} 👍 · ${data.feedback.down} 👎`}
            />
            <Tile label="Escalation rate" value={pct(data.escalation_rate)} note={`${data.outcomes.escalated} ticket${data.outcomes.escalated === 1 ? "" : "s"}`} />
            <Tile
              label="Actions approved"
              value={pct(data.approval_rate)}
              note={`${data.actions.approved} approved · ${data.actions.denied} denied · ${data.actions.pending} pending`}
            />
            <Tile label="Response time" value={secs(data.latency_ms.p50)} note={`median · p95 ${secs(data.latency_ms.p95)}`} />
            <Tile
              label="Cost per conversation"
              value={data.cost.per_conversation_usd == null ? "—" : usd(data.cost.per_conversation_usd)}
              note={`${usd(data.cost.total_usd)} total`}
            />
            <Tile
              label="Prompt cache hits"
              value={pct(data.cost.cache_hit_rate)}
              note={`of input tokens · saved ${usd(data.cost.cache_savings_usd)}`}
            />
          </div>

          <Panel title="Conversations per day, by outcome">
            <DailyVolume daily={data.daily} />
          </Panel>

          <div className="grid gap-6 md:grid-cols-2">
            <Panel title="Tool calls">
              <BarList
                rows={data.tools.map((t) => ({
                  label: t.name,
                  value: t.calls,
                  note: `${t.avg_ms} ms avg${t.errors ? ` · ${t.errors} failed` : ""}`,
                }))}
                empty="No tool calls yet."
              />
            </Panel>
            <Panel title="Most cited sources">
              <BarList rows={data.top_cited.map((c) => ({ label: c.title, value: c.citations }))} empty="No citations yet." />
            </Panel>
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            <Panel title="Knowledge gaps" hint={`Questions ${tenant.persona} couldn't answer from the knowledge base. Write these articles next.`}>
              {data.knowledge_gaps.length === 0 ? (
                <p className="text-sm text-zinc-500">None flagged.</p>
              ) : (
                <ul className="divide-y divide-zinc-100 text-sm dark:divide-zinc-800">
                  {data.knowledge_gaps.map((g) => (
                    <li key={g.topic} className="py-2">
                      <div className="flex justify-between gap-3">
                        <span className="font-medium">{g.topic}</span>
                        <span className="tabular-nums text-zinc-500">{g.n}×</span>
                      </div>
                      {g.example && <p className="mt-0.5 truncate text-xs text-zinc-500">“{g.example}”</p>}
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
            <Panel title="Answers rated unhelpful">
              {data.thumbs_down.length === 0 ? (
                <p className="text-sm text-zinc-500">None yet.</p>
              ) : (
                <ul className="divide-y divide-zinc-100 text-sm dark:divide-zinc-800">
                  {data.thumbs_down.map((t) => (
                    <li key={t.created_at} className="py-2">
                      <p className="truncate">“{t.question ?? "(question unavailable)"}”</p>
                      <p className="text-xs text-zinc-500">
                        {new Date(t.created_at).toLocaleString()}
                        {t.comment && ` · ${t.comment}`}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>

          {data.config_versions.length > 0 && (
            <Panel title="By config version" hint="Each change to the company's prompt or policies gets a new version, so you can compare them.">
              <table className="w-full text-left text-sm">
                <thead className="text-xs text-zinc-500">
                  <tr>
                    <th className="py-1 font-medium">Version</th>
                    <th className="py-1 font-medium">First seen</th>
                    <th className="py-1 text-right font-medium">Conversations</th>
                    <th className="py-1 text-right font-medium">Escalated</th>
                    <th className="py-1 text-right font-medium">Helpful</th>
                  </tr>
                </thead>
                <tbody>
                  {data.config_versions.map((v) => (
                    <tr key={v.version} className="border-t border-zinc-100 dark:border-zinc-800">
                      <td className="py-1.5 font-mono text-xs">{v.version}</td>
                      <td className="py-1.5">{new Date(v.first_seen).toLocaleDateString()}</td>
                      <td className="py-1.5 text-right tabular-nums">{v.conversations}</td>
                      <td className="py-1.5 text-right tabular-nums">{pct(v.escalation_rate)}</td>
                      <td className="py-1.5 text-right tabular-nums">{/* ratings are +1/-1, so the share of thumbs-up is (avg + 1) / 2 */}
                        {v.avg_rating == null ? "—" : pct((v.avg_rating + 1) / 2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          )}
        </>
      )}
    </div>
  );
}

function Tile({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      <div className="mt-1 text-xs text-zinc-500">{note}</div>
    </div>
  );
}

function Panel({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <h2 className="text-sm font-medium">{title}</h2>
      {hint && <p className="mt-0.5 text-xs text-zinc-500">{hint}</p>}
      <div className="mt-3">{children}</div>
    </section>
  );
}

/** Rect with only the top corners rounded, so stacks and bars sit flat on the baseline. */
function topRounded(x: number, y: number, w: number, h: number, r = 4) {
  const rr = Math.max(0, Math.min(r, h, w / 2));
  return `M${x},${y + h}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h}Z`;
}

/** A round, even axis maximum, so the midpoint tick is a whole number too. */
function niceMax(n: number) {
  if (n <= 4) return 4;
  const step = 10 ** Math.floor(Math.log10(n));
  const max = Math.ceil(n / step) * step;
  return max % 2 === 0 ? max : max + step;
}

function DailyVolume({ daily }: { daily: Day[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  const W = 720;
  const H = 220;
  const pad = { l: 28, r: 8, t: 8, b: 22 };
  const totals = daily.map((d) => d.answered + d.action_proposed + d.escalated);
  const max = niceMax(Math.max(0, ...totals));
  const slot = (W - pad.l - pad.r) / daily.length;
  const barW = Math.max(2, Math.min(18, slot * 0.6));
  const y = (v: number) => pad.t + (H - pad.t - pad.b) * (1 - v / max);
  const ticks = [0, max / 2, max];
  const labelEvery = Math.ceil(daily.length / 6);
  const sums = Object.fromEntries(SERIES.map((s) => [s.key, daily.reduce((a, d) => a + d[s.key], 0)]));

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--viz-muted)]">
        {SERIES.map((s) => (
          <span key={s.key} className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: s.color }} />
            <span className="text-[var(--viz-text)]">{s.label}</span> {sums[s.key]}
          </span>
        ))}
        <button onClick={() => setTable(!table)} className="ml-auto underline hover:text-[var(--viz-text)]">
          {table ? "Show chart" : "Show table"}
        </button>
      </div>
      {table ? (
        <div className="max-h-72 overflow-y-auto">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-[var(--viz-surface)] text-[var(--viz-muted)]">
              <tr>
                <th className="py-1 font-medium">Day</th>
                {SERIES.map((s) => (
                  <th key={s.key} className="py-1 text-right font-medium">{s.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {daily.map((d) => (
                <tr key={d.day} className="border-t border-zinc-100 dark:border-zinc-800">
                  <td className="py-1">{d.day}</td>
                  {SERIES.map((s) => (
                    <td key={s.key} className="py-1 text-right tabular-nums">{d[s.key]}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="-mx-1 overflow-x-auto px-1">
        <div className="relative min-w-[560px]">
          <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="Stacked bar chart of conversations per day by outcome">
            {ticks.map((t) => (
              <g key={t}>
                <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} stroke="var(--viz-grid)" strokeWidth={1} />
                <text x={pad.l - 6} y={y(t) + 3} textAnchor="end" fontSize={10} fill="var(--viz-muted)">
                  {t}
                </text>
              </g>
            ))}
            {daily.map((d, i) => {
              const x = pad.l + i * slot + (slot - barW) / 2;
              let base = 0;
              const present = SERIES.filter((s) => d[s.key] > 0);
              return (
                <g key={d.day}>
                  {present.map((s, j) => {
                    const top = base + d[s.key];
                    const y0 = y(base);
                    const y1 = y(top);
                    base = top;
                    // 2px surface gap between stacked segments
                    const h = Math.max(0, y0 - y1 - (j > 0 ? 2 : 0));
                    const isTop = j === present.length - 1;
                    return isTop ? (
                      <path key={s.key} d={topRounded(x, y1, barW, h)} fill={s.color} opacity={hover === null || hover === i ? 1 : 0.45} />
                    ) : (
                      <rect key={s.key} x={x} y={y1} width={barW} height={h} fill={s.color} opacity={hover === null || hover === i ? 1 : 0.45} />
                    );
                  })}
                  {i % labelEvery === 0 && (
                    <text x={x + barW / 2} y={H - 6} textAnchor="middle" fontSize={10} fill="var(--viz-muted)">
                      {d.day.slice(5)}
                    </text>
                  )}
                  {/* Hit target wider and taller than the mark */}
                  <rect
                    x={pad.l + i * slot}
                    y={pad.t}
                    width={slot}
                    height={H - pad.t - pad.b}
                    fill="transparent"
                    onMouseEnter={() => setHover(i)}
                    onMouseLeave={() => setHover(null)}
                  />
                </g>
              );
            })}
          </svg>
          {hover !== null && (
            <div
              className="pointer-events-none absolute top-0 z-10 rounded-lg border border-zinc-200 bg-[var(--viz-surface)] px-3 py-2 text-xs shadow-md dark:border-zinc-700"
              style={{
                left: `${((pad.l + hover * slot + slot / 2) / W) * 100}%`,
                transform: hover > daily.length / 2 ? "translateX(calc(-100% - 8px))" : "translateX(8px)",
              }}
            >
              <div className="font-medium text-[var(--viz-text)]">{daily[hover].day}</div>
              {SERIES.map((s) => (
                <div key={s.key} className="mt-0.5 flex items-center gap-2 whitespace-nowrap text-[var(--viz-muted)]">
                  <span className="h-2 w-2 rounded-sm" style={{ background: s.color }} />
                  <span className="text-[var(--viz-text)]">{s.label}</span>
                  <span className="ml-auto pl-3 tabular-nums text-[var(--viz-text)]">{daily[hover][s.key]}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        </div>
      )}
    </div>
  );
}

/** Horizontal bars for one measure; the label and value are text, the bar is the mark. */
function BarList({ rows, empty }: { rows: { label: string; value: number; note?: string }[]; empty: string }) {
  if (rows.length === 0) return <p className="text-sm text-zinc-500">{empty}</p>;
  const max = Math.max(...rows.map((r) => r.value));
  return (
    <ul className="space-y-2.5">
      {rows.map((r) => (
        <li key={r.label} title={`${r.label}: ${r.value}`}>
          <div className="flex justify-between gap-3 text-xs">
            <span className="truncate text-[var(--viz-text)]">{humanize(r.label)}</span>
            <span className="shrink-0 tabular-nums text-[var(--viz-muted)]">
              {r.value}
              {r.note && ` · ${r.note}`}
            </span>
          </div>
          <div className="mt-1 h-2 w-full">
            <div className="h-2 rounded-r" style={{ width: `${(r.value / max) * 100}%`, background: "var(--series-1)" }} />
          </div>
        </li>
      ))}
    </ul>
  );
}
