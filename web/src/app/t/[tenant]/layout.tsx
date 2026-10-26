import { Suspense, type ReactNode } from "react";
import { TenantShell } from "@/components/tenant";

export default function TenantLayout({ children, params }: { children: ReactNode; params: Promise<{ tenant: string }> }) {
  return (
    <Suspense fallback={<div className="flex-1" />}>
      <TenantShell params={params}>{children}</TenantShell>
    </Suspense>
  );
}
