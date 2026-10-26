import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Path, Request

from ..config import get_settings
from ..tenants.loader import TenantNotFound
from ..tenants.models import TenantConfig


def tenant(request: Request, slug: Annotated[str, Path()]) -> TenantConfig:
    try:
        return request.app.state.tenants.get(slug)
    except TenantNotFound:
        raise HTTPException(404, "unknown tenant") from None


Tenant = Annotated[TenantConfig, Depends(tenant)]


def tenant_admin(
    request: Request,
    t: Tenant,
    x_admin_token: Annotated[str, Header()] = "",
) -> TenantConfig:
    """This tenant's admin token unlocks approvals, tickets, the knowledge base and
    analytics. Another tenant's token does not."""
    if not request.app.state.tenants.check_admin_token(t.slug, x_admin_token):
        raise HTTPException(403, "admin token required for this tenant")
    return t


TenantAdmin = Annotated[TenantConfig, Depends(tenant_admin)]


def platform_admin(x_admin_token: Annotated[str, Header()] = "") -> None:
    token = get_settings().admin_token
    if not token or not hmac.compare_digest(x_admin_token, token):
        raise HTTPException(403, "forbidden")


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")
