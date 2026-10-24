import type { ReactNode } from "react";

export function Card({ title, icon, children, tone = "default" }: {
  title: string;
  icon?: ReactNode;
  children: ReactNode;
  tone?: "default" | "warn" | "success";
}) {
  const border =
    tone === "warn" ? "border-amber-300 dark:border-amber-700" :
    tone === "success" ? "border-emerald-300 dark:border-emerald-700" :
    "border-zinc-200 dark:border-zinc-800";
  return (
    <div className={`my-2 rounded-xl border ${border} bg-white dark:bg-zinc-900 shadow-sm overflow-hidden`}>
      <div className="flex items-center gap-2 px-4 py-2 text-xs font-medium uppercase tracking-wide text-zinc-500 border-b border-zinc-100 dark:border-zinc-800">
        {icon}
        {title}
      </div>
      <div className="p-4 text-sm">{children}</div>
    </div>
  );
}

export function Badge({ children, color = "zinc" }: { children: ReactNode; color?: string }) {
  const colors: Record<string, string> = {
    zinc: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
    green: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-300",
    amber: "bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-300",
    red: "bg-red-100 text-red-800 dark:bg-red-900/50 dark:text-red-300",
    indigo: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/50 dark:text-indigo-300",
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${colors[color] ?? colors.zinc}`}>
      {children}
    </span>
  );
}

export function statusColor(status: string) {
  if (["paid", "active", "approved"].includes(status)) return "green";
  if (["pending_approval", "past_due", "medium", "high"].includes(status)) return "amber";
  if (["unpaid", "denied", "urgent", "cancelled"].includes(status)) return "red";
  return "zinc";
}

export function Skeleton({ label }: { label: string }) {
  return (
    <div className="my-2 flex items-center gap-3 rounded-xl border border-dashed border-zinc-300 dark:border-zinc-700 px-4 py-3 text-sm text-zinc-500">
      <span className="h-2 w-2 animate-pulse rounded-full bg-indigo-500" />
      {label}
    </div>
  );
}
