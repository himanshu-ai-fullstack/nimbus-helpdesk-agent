import Link from "next/link";
import { Suspense } from "react";
import { API_URL } from "@/lib/api";
import type { Tenant } from "@/lib/types";

export default function Home() {
  return (
    <main className="mx-auto w-full max-w-5xl flex-1 overflow-y-auto px-4 py-12">
      <h1 className="text-2xl font-semibold">HelpDesk Agent Platform</h1>
      <p className="mt-2 max-w-2xl text-zinc-500">
        One AI support agent, many companies. Each company has its own knowledge base, connected records, approval
        policies, ticket queue and analytics, isolated in the database. Pick one to talk to its agent.
      </p>
      <Suspense fallback={<p className="mt-8 text-sm text-zinc-500">Loading companies…</p>}>
        <TenantList />
      </Suspense>
    </main>
  );
}

async function TenantList() {
  let tenants: Tenant[] = [];
  try {
    const res = await fetch(`${API_URL}/api/tenants`, { cache: "no-store" });
    tenants = await res.json();
  } catch {
    return <p className="mt-8 text-sm text-red-600">Couldn&apos;t reach the API at {API_URL}.</p>;
  }
  return (
    <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {tenants.map((t) => (
        <Link
          key={t.slug}
          href={`/t/${t.slug}`}
          className="group flex flex-col rounded-2xl border border-zinc-200 bg-white p-5 transition hover:shadow-md dark:border-zinc-800 dark:bg-zinc-900"
        >
          <div className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl text-lg font-semibold text-white" style={{ background: t.brand_color }}>
              {t.name[0]}
            </span>
            <div>
              <div className="font-semibold">{t.name}</div>
              <div className="text-xs text-zinc-500">{t.industry}</div>
            </div>
          </div>
          <p className="mt-3 text-sm text-zinc-600 dark:text-zinc-400">{t.tagline}</p>
          <div className="mt-4 flex flex-wrap gap-1.5 text-xs">
            <span className="rounded-full bg-zinc-100 px-2 py-0.5 dark:bg-zinc-800">Agent: {t.persona}</span>
            <span className="rounded-full bg-zinc-100 px-2 py-0.5 dark:bg-zinc-800">For {t.audience}</span>
            {Object.values(t.actions).map((label) => (
              <span key={label} className="rounded-full bg-zinc-100 px-2 py-0.5 dark:bg-zinc-800">{label}</span>
            ))}
          </div>
          <span className="mt-4 text-sm font-medium group-hover:underline" style={{ color: t.brand_color }}>
            Chat with {t.persona} →
          </span>
        </Link>
      ))}
    </div>
  );
}
