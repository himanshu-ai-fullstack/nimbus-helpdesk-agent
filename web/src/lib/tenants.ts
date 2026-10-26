import { cacheLife } from "next/cache";
import { API_URL } from "./api";
import type { Tenant } from "./types";

/** A tenant's public config (branding, persona, suggestions). It only changes when
 * the tenant's config file is redeployed, so cache it on the server. */
export async function getTenant(slug: string): Promise<Tenant | null> {
  "use cache";
  cacheLife("minutes");
  const res = await fetch(`${API_URL}/api/t/${encodeURIComponent(slug)}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`The API returned ${res.status} for tenant ${slug}`);
  return res.json();
}
