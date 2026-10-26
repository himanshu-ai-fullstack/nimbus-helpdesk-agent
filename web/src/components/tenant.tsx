"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  createContext,
  use,
  useCallback,
  useContext,
  useEffect,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type ReactNode,
} from "react";
import { api, ApiError, storage } from "@/lib/api";
import type { Tenant } from "@/lib/types";

type TenantContext = {
  tenant: Tenant;
  token: string | null;
  setToken: (token: string | null) => void;
};

const Ctx = createContext<TenantContext | null>(null);

export function useTenant(): TenantContext {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useTenant must be used inside TenantShell");
  return ctx;
}

const tokenKey = (slug: string) => `admin-token:${slug}`;

// Admin tokens live in localStorage; this store lets components re-render when a
// token changes, here or in another tab.
const tokenListeners = new Set<() => void>();
function subscribeTokens(listener: () => void) {
  tokenListeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    tokenListeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

export function TenantShell({ params, children }: { params: Promise<{ tenant: string }>; children: ReactNode }) {
  const { tenant: slug } = use(params);
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [missing, setMissing] = useState(false);
  const token = useSyncExternalStore(
    subscribeTokens,
    () => storage.get(tokenKey(slug)),
    () => null,
  );

  useEffect(() => {
    let live = true;
    api<Tenant>(`/api/t/${slug}`)
      .then((t) => live && setTenant(t))
      .catch((e) => live && setMissing(e instanceof ApiError && e.status === 404));
    return () => {
      live = false;
    };
  }, [slug]);

  const setToken = useCallback(
    (value: string | null) => {
      storage.set(tokenKey(slug), value);
      tokenListeners.forEach((l) => l());
    },
    [slug],
  );

  if (missing) {
    return (
      <main className="mx-auto max-w-xl flex-1 px-4 py-16 text-center">
        <h1 className="text-xl font-semibold">No company called “{slug}”</h1>
        <Link href="/" className="mt-4 inline-block text-sm underline">Choose a company</Link>
      </main>
    );
  }
  if (!tenant) return <div className="flex-1" />;

  return (
    <Ctx.Provider value={{ tenant, token, setToken }}>
      <div className="flex min-h-0 flex-1 flex-col" style={{ "--brand": tenant.brand_color } as CSSProperties}>
        <TenantHeader />
        {children}
      </div>
    </Ctx.Provider>
  );
}

const NAV = [
  { href: "", label: "Chat", admin: false },
  { href: "/approvals", label: "Approvals", admin: true },
  { href: "/tickets", label: "Tickets", admin: true },
  { href: "/admin/knowledge", label: "Knowledge", admin: true },
  { href: "/admin/analytics", label: "Analytics", admin: true },
];

function TenantHeader() {
  const { tenant, token } = useTenant();
  const pathname = usePathname();
  const base = `/t/${tenant.slug}`;
  return (
    <header className="border-b border-zinc-200 dark:border-zinc-800">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3">
        <div className="flex items-center gap-3">
          <Link href="/" className="text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100" title="All companies">
            ←
          </Link>
          <Link href={base} className="flex items-center gap-2 font-semibold">
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-[var(--brand)] text-sm text-white">
              {tenant.name[0]}
            </span>
            {tenant.name}
            <span className="hidden text-sm font-normal text-zinc-500 sm:inline">{tenant.tagline}</span>
          </Link>
        </div>
        <nav className="-mx-1 flex gap-1 overflow-x-auto text-sm">
          {NAV.map((item) => {
            const href = base + item.href;
            const active = item.href ? pathname.startsWith(href) : pathname === base;
            return (
              <Link
                key={item.label}
                href={href}
                className={`whitespace-nowrap rounded-lg px-2.5 py-1 ${
                  active
                    ? "bg-zinc-100 font-medium text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100"
                    : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
                }`}
              >
                {item.label}
                {item.admin && !token && <span className="ml-1 text-xs opacity-60">🔒</span>}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}

/** Admin pages render their content only once this tenant's admin token works. */
export function AdminGate({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  const { tenant, token, setToken } = useTenant();
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  async function unlock(e: React.FormEvent) {
    e.preventDefault();
    setChecking(true);
    setError(null);
    try {
      await api(`/api/t/${tenant.slug}/actions?status=pending_approval`, { token: draft.trim() });
      setToken(draft.trim());
    } catch (err) {
      setError(err instanceof ApiError && err.status === 403 ? "That token doesn't unlock this company." : "Couldn't reach the API.");
    } finally {
      setChecking(false);
    }
  }

  return (
    <main className="mx-auto w-full max-w-5xl flex-1 overflow-y-auto px-4 py-8">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">{title}</h1>
          <p className="mt-1 max-w-2xl text-sm text-zinc-500">{description}</p>
        </div>
        {token && (
          <button onClick={() => setToken(null)} className="text-xs text-zinc-500 underline hover:text-zinc-900 dark:hover:text-zinc-100">
            Sign out of {tenant.name} admin
          </button>
        )}
      </div>
      {token ? (
        <div className="mt-6">{children}</div>
      ) : (
        <form onSubmit={unlock} className="mt-6 max-w-md rounded-xl border border-zinc-200 p-4 dark:border-zinc-800">
          <label htmlFor="admin-token" className="text-sm font-medium">{tenant.name} admin token</label>
          <p className="mt-1 text-xs text-zinc-500">
            Support staff and admins of {tenant.name} only. Each company has its own token; another company&apos;s
            token won&apos;t work here.
          </p>
          <div className="mt-3 flex gap-2">
            <input
              id="admin-token"
              type="password"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="min-w-0 flex-1 rounded-lg border border-zinc-300 bg-transparent px-3 py-2 text-sm outline-none focus:border-[var(--brand)] dark:border-zinc-700"
            />
            <button disabled={!draft.trim() || checking} className="rounded-lg bg-[var(--brand)] px-3 text-sm font-medium text-white disabled:opacity-40">
              Unlock
            </button>
          </div>
          {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
        </form>
      )}
    </main>
  );
}
