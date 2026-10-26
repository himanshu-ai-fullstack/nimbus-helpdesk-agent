"""Support metrics for one tenant, computed from conversations, agent events,
feedback, actions and knowledge gaps. Everything runs in a tenant-scoped
transaction, so row-level security keeps each company's numbers separate."""

from datetime import date, timedelta
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from ..config import MODEL_PRICES, cost_usd
from ..db import tenant_conn


def _ratio(num: float, den: float) -> float | None:
    return round(num / den, 4) if den else None


async def _rows(conn: AsyncConnection, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    cur = conn.cursor(row_factory=dict_row)
    await cur.execute(query, params)
    return await cur.fetchall()


async def tenant_analytics(
    pool: AsyncConnectionPool, tenant_id: str, days: int = 30, today: date | None = None
) -> dict[str, Any]:
    today = today or date.today()
    since = today - timedelta(days=days - 1)
    p = {"tenant": tenant_id, "since": since}
    async with tenant_conn(pool, tenant_id) as conn:
        outcomes = await _rows(
            conn,
            "SELECT outcome, count(*) AS n FROM conversations "
            "WHERE tenant_id = %(tenant)s AND started_at >= %(since)s GROUP BY outcome",
            p,
        )
        daily = await _rows(
            conn,
            "SELECT started_at::date AS day, outcome, count(*) AS n FROM conversations "
            "WHERE tenant_id = %(tenant)s AND started_at >= %(since)s GROUP BY 1, 2",
            p,
        )
        feedback = await _rows(
            conn,
            "SELECT rating, count(*) AS n FROM feedback "
            "WHERE tenant_id = %(tenant)s AND created_at >= %(since)s GROUP BY rating",
            p,
        )
        actions = await _rows(
            conn,
            "SELECT kind, status, count(*) AS n FROM actions "
            "WHERE tenant_id = %(tenant)s AND created_at >= %(since)s GROUP BY 1, 2",
            p,
        )
        # One assistant turn can span several model calls and tools; latency is
        # what the person waited for the whole turn.
        [latency] = await _rows(
            conn,
            "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY ms) AS p50, "
            "percentile_cont(0.95) WITHIN GROUP (ORDER BY ms) AS p95, count(*) AS turns "
            "FROM (SELECT message_id, sum(latency_ms) AS ms FROM agent_events "
            "WHERE tenant_id = %(tenant)s AND created_at >= %(since)s GROUP BY message_id) t",
            p,
        )
        usage = await _rows(
            conn,
            "SELECT model, count(*) AS calls, sum(input_tokens) AS input, "
            "sum(output_tokens) AS output, sum(cache_read_tokens) AS cache_read, "
            "sum(cache_write_tokens) AS cache_write FROM agent_events "
            "WHERE tenant_id = %(tenant)s AND kind = 'llm' AND created_at >= %(since)s "
            "GROUP BY model",
            p,
        )
        tools = await _rows(
            conn,
            "SELECT tool_name AS name, count(*) AS calls, "
            "count(*) FILTER (WHERE is_error) AS errors, round(avg(latency_ms)) AS avg_ms "
            "FROM agent_events WHERE tenant_id = %(tenant)s AND kind = 'tool' "
            "AND created_at >= %(since)s GROUP BY 1 ORDER BY 2 DESC",
            p,
        )
        cited = await _rows(
            conn,
            "SELECT part->'data'->>'title' AS title, count(*) AS citations "
            "FROM messages, jsonb_array_elements(parts) AS part "
            "WHERE tenant_id = %(tenant)s AND created_at >= %(since)s "
            "AND part->>'type' = 'data-citation' GROUP BY 1 ORDER BY 2 DESC LIMIT 8",
            p,
        )
        gaps = await _rows(
            conn,
            "SELECT lower(topic) AS topic, count(*) AS n, max(created_at) AS last_seen, "
            "(array_agg(question ORDER BY created_at DESC))[1] AS example "
            "FROM knowledge_gaps WHERE tenant_id = %(tenant)s AND created_at >= %(since)s "
            "GROUP BY 1 ORDER BY 2 DESC, 3 DESC LIMIT 10",
            p,
        )
        thumbs_down = await _rows(
            conn,
            "SELECT f.created_at, f.comment, f.conversation_id, "
            "(SELECT u.parts->0->>'text' FROM messages u WHERE u.conversation_id = m.conversation_id "
            " AND u.role = 'user' AND u.seq < m.seq ORDER BY u.seq DESC LIMIT 1) AS question "
            "FROM feedback f JOIN messages m ON m.id = f.message_id "
            "WHERE f.tenant_id = %(tenant)s AND f.rating = -1 AND f.created_at >= %(since)s "
            "ORDER BY f.created_at DESC LIMIT 10",
            p,
        )
        versions = await _rows(
            conn,
            "SELECT c.config_version AS version, count(*) AS conversations, "
            "count(*) FILTER (WHERE c.outcome = 'escalated') AS escalated, "
            "min(c.started_at) AS first_seen, "
            "(SELECT avg(f.rating) FROM feedback f JOIN conversations c2 "
            " ON c2.id = f.conversation_id WHERE c2.config_version = c.config_version) AS rating "
            "FROM conversations c WHERE c.tenant_id = %(tenant)s AND c.started_at >= %(since)s "
            "GROUP BY 1 ORDER BY 4",
            p,
        )

    by_outcome = {r["outcome"]: r["n"] for r in outcomes}
    total = sum(by_outcome.values())
    escalated = by_outcome.get("escalated", 0)
    ratings = {r["rating"]: r["n"] for r in feedback}
    decided = {s: sum(r["n"] for r in actions if r["status"] == s) for s in ("approved", "denied")}
    pending = sum(r["n"] for r in actions if r["status"] == "pending_approval")

    cost = sum(
        cost_usd(r["model"] or "", r["input"], r["output"], r["cache_read"], r["cache_write"])
        for r in usage
    )
    input_side = sum(r["input"] + r["cache_read"] + r["cache_write"] for r in usage)
    cache_read = sum(r["cache_read"] for r in usage)
    saved = sum(
        r["cache_read"] * MODEL_PRICES.get(r["model"] or "", (0.0, 0.0))[0] * 0.9 / 1_000_000
        for r in usage
    )

    day_counts: dict[str, dict[str, int]] = {
        (since + timedelta(days=i)).isoformat(): {
            "answered": 0,
            "action_proposed": 0,
            "escalated": 0,
        }
        for i in range(days)
    }
    for r in daily:
        day_counts.setdefault(r["day"].isoformat(), {})[r["outcome"]] = r["n"]

    return {
        "tenant": tenant_id,
        "days": days,
        "since": since.isoformat(),
        "conversations": total,
        "outcomes": {k: by_outcome.get(k, 0) for k in ("answered", "action_proposed", "escalated")},
        "containment_rate": _ratio(total - escalated, total),
        "escalation_rate": _ratio(escalated, total),
        "feedback": {"up": ratings.get(1, 0), "down": ratings.get(-1, 0)},
        "helpfulness": _ratio(ratings.get(1, 0), ratings.get(1, 0) + ratings.get(-1, 0)),
        "actions": {
            "approved": decided["approved"],
            "denied": decided["denied"],
            "pending": pending,
            "by_kind": [{"kind": r["kind"], "status": r["status"], "n": r["n"]} for r in actions],
        },
        "approval_rate": _ratio(decided["approved"], decided["approved"] + decided["denied"]),
        "latency_ms": {
            "p50": round(latency["p50"]) if latency["p50"] is not None else None,
            "p95": round(latency["p95"]) if latency["p95"] is not None else None,
            "turns": latency["turns"],
        },
        "cost": {
            "total_usd": round(cost, 4),
            "per_conversation_usd": round(cost / total, 4) if total else None,
            "cache_hit_rate": _ratio(cache_read, input_side),
            "cache_savings_usd": round(saved, 4),
            "by_model": [
                {
                    **r,
                    "cost_usd": round(
                        cost_usd(
                            r["model"] or "",
                            r["input"],
                            r["output"],
                            r["cache_read"],
                            r["cache_write"],
                        ),
                        4,
                    ),
                }
                for r in usage
            ],
        },
        "daily": [{"day": d, **counts} for d, counts in sorted(day_counts.items())],
        "tools": [{**r, "avg_ms": int(r["avg_ms"] or 0)} for r in tools],
        "top_cited": cited,
        "knowledge_gaps": [{**g, "last_seen": g["last_seen"].isoformat()} for g in gaps],
        "thumbs_down": [{**t, "created_at": t["created_at"].isoformat()} for t in thumbs_down],
        "config_versions": [
            {
                "version": v["version"],
                "conversations": v["conversations"],
                "escalation_rate": _ratio(v["escalated"], v["conversations"]),
                "avg_rating": round(float(v["rating"]), 2) if v["rating"] is not None else None,
                "first_seen": v["first_seen"].isoformat(),
            }
            for v in versions
        ],
    }
