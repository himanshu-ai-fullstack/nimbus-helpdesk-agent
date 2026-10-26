import Link from "next/link";

export default function NotFound() {
  return (
    <main className="mx-auto max-w-xl flex-1 px-4 py-16 text-center">
      <h1 className="text-xl font-semibold">There&apos;s nothing at this address</h1>
      <Link href="/" className="mt-4 inline-block text-sm underline">Choose a company</Link>
    </main>
  );
}
