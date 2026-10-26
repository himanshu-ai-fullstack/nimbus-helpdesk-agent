from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from ..telemetry.analytics import tenant_analytics
from ..tenants.seed import seed_all
from .deps import Tenant, TenantAdmin, platform_admin

router = APIRouter()


@router.get("/api/tenants")
async def list_tenants(request: Request) -> list[dict[str, Any]]:
    return [t.public() for t in request.app.state.tenants.all()]


@router.get("/api/t/{slug}")
async def get_tenant(t: Tenant) -> dict[str, Any]:
    return t.public()


@router.get("/api/t/{slug}/actions")
async def list_actions(
    request: Request,
    t: TenantAdmin,
    status: Literal["pending_approval", "approved", "denied"] | None = None,
) -> list[dict[str, Any]]:
    rows = await request.app.state.repo.list_actions(t.slug, status)
    return [
        {
            **r,
            "label": t.actions[r["kind"]].label if r["kind"] in t.actions else r["kind"],
            "amount_usd": None if r["amount_cents"] is None else r["amount_cents"] / 100,
        }
        for r in rows
    ]


class Decision(BaseModel):
    approve: bool


@router.post("/api/t/{slug}/actions/{action_id}/decision")
async def decide_action(
    action_id: int, body: Decision, request: Request, t: TenantAdmin
) -> dict[str, Any]:
    row = await request.app.state.repo.decide_action(t.slug, action_id, body.approve)
    if row is None:
        raise HTTPException(409, "action not found or already decided")
    return {"id": row["id"], "status": row["status"]}


@router.get("/api/t/{slug}/tickets")
async def list_tickets(request: Request, t: TenantAdmin) -> list[dict[str, Any]]:
    return await request.app.state.repo.list_tickets(t.slug)


@router.get("/api/t/{slug}/analytics")
async def analytics(
    request: Request, t: TenantAdmin, days: int = Query(30, ge=1, le=90)
) -> dict[str, Any]:
    return await tenant_analytics(request.app.state.pool, t.slug, days)


@router.post("/api/admin/reset", dependencies=[Depends(platform_admin)])
async def reset_demo(request: Request, tenant: str | None = None) -> dict[str, Any]:
    st = request.app.state
    if tenant is not None:
        st.tenants.get(tenant)
    return {"status": "reset", "tenants": await seed_all(st.pool, st.store, st.tenants, tenant)}
