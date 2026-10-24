import Link from "next/link";

export function Header() {
  return (
    <header className="border-b border-zinc-200 dark:border-zinc-800">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-indigo-600 text-white text-sm">N</span>
          Nimbus Support
        </Link>
        <nav className="flex gap-4 text-sm text-zinc-500">
          <Link href="/" className="hover:text-zinc-900 dark:hover:text-zinc-100">Chat</Link>
          <Link href="/tickets" className="hover:text-zinc-900 dark:hover:text-zinc-100">Ticket queue</Link>
        </nav>
      </div>
    </header>
  );
}
