import { notFound } from "next/navigation";
import { Suspense, type ReactNode } from "react";
import { TenantShell } from "@/components/tenant";
import { getTenant } from "@/lib/tenants";

type Props = { children: ReactNode; params: Promise<{ tenant: string }> };

export default function TenantLayout({ children, params }: Props) {
  return (
    <Suspense fallback={<div className="flex-1" />}>
      <TenantLoader params={params}>{children}</TenantLoader>
    </Suspense>
  );
}

async function TenantLoader({ children, params }: Props) {
  const { tenant: slug } = await params;
  const tenant = await getTenant(slug);
  if (!tenant) notFound();
  return <TenantShell tenant={tenant}>{children}</TenantShell>;
}
