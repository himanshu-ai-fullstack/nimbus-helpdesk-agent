import hashlib
import hmac
from pathlib import Path

import yaml
from psycopg_pool import AsyncConnectionPool

from .models import TenantConfig

TENANTS_DIR = Path(__file__).resolve().parents[2] / "tenants"


class TenantNotFound(KeyError):
    pass


def load_tenant(folder: Path) -> TenantConfig:
    raw = (folder / "tenant.yaml").read_bytes()
    data = yaml.safe_load(raw) or {}
    if data.get("slug", folder.name) != folder.name:
        raise ValueError(f"{folder}: slug {data.get('slug')!r} must match the folder name")
    data.setdefault("slug", folder.name)
    data["version"] = hashlib.sha256(raw).hexdigest()[:12]
    return TenantConfig.model_validate(data)


def load_tenants(root: Path = TENANTS_DIR) -> dict[str, TenantConfig]:
    tenants = {}
    for folder in sorted(p for p in root.iterdir() if (p / "tenant.yaml").exists()):
        t = load_tenant(folder)
        tenants[t.slug] = t
    if not tenants:
        raise RuntimeError(f"no tenants found in {root}")
    return tenants


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class TenantRegistry:
    """Tenant configs plus their admin-token hashes, held in memory for the life of
    the process; the `tenants` table mirrors them for foreign keys and analytics."""

    def __init__(self, tenants: dict[str, TenantConfig], root: Path = TENANTS_DIR):
        self._tenants = tenants
        self.root = root
        self._token_hashes: dict[str, str] = {}

    def get(self, slug: str) -> TenantConfig:
        try:
            return self._tenants[slug]
        except KeyError:
            raise TenantNotFound(slug) from None

    def all(self) -> list[TenantConfig]:
        return list(self._tenants.values())

    def folder(self, slug: str) -> Path:
        return self.root / self.get(slug).slug

    def check_admin_token(self, slug: str, token: str) -> bool:
        expected = self._token_hashes.get(slug)
        if not expected or not token:
            return False
        return hmac.compare_digest(expected, hash_token(token))

    async def sync(self, pool: AsyncConnectionPool, admin_tokens: dict[str, str]) -> None:
        """Upsert tenant rows and admin-token hashes. Tokens come from the
        environment, so only their hashes ever reach the database."""
        self._token_hashes = {s: hash_token(t) for s, t in admin_tokens.items() if t}
        async with pool.connection() as conn:
            for t in self._tenants.values():
                await conn.execute(
                    "INSERT INTO tenants (id, name, config_version, admin_token_hash) "
                    "VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET "
                    "name = excluded.name, config_version = excluded.config_version, "
                    "admin_token_hash = excluded.admin_token_hash, updated_at = now()",
                    (t.slug, t.name, t.version, self._token_hashes.get(t.slug)),
                )
