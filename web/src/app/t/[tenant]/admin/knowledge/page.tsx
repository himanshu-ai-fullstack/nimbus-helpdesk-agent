"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Badge, statusColor } from "@/components/cards/Card";
import { AdminGate, useTenant } from "@/components/tenant";
import { api } from "@/lib/api";

type Doc = {
  id: number;
  title: string;
  kind: string;
  source: string;
  status: "processing" | "ready" | "failed";
  error: string | null;
  chunks: number;
  created_at: string;
};

const ACCEPT = ".md,.markdown,.txt,.pdf,.html,.htm";

export default function KnowledgePage() {
  const { tenant } = useTenant();
  return (
    <AdminGate
      title="Knowledge base"
      description={`What ${tenant.persona} answers from. Uploads and pages are chunked, embedded and indexed for hybrid search in ${tenant.name}'s own space; other companies never see them. Text from documents is treated as reference material, never as instructions.`}
    >
      <KnowledgeBase />
    </AdminGate>
  );
}

function KnowledgeBase() {
  const { tenant, token } = useTenant();
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [message, setMessage] = useState<{ tone: "error" | "ok"; text: string } | null>(null);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const base = `/api/t/${tenant.slug}/documents`;

  const load = useCallback(() => {
    api<Doc[]>(base, { token })
      .then(setDocs)
      .catch((e) => setMessage({ tone: "error", text: e.message }));
  }, [base, token]);

  useEffect(load, [load]);

  // Poll while anything is still indexing.
  const processing = docs?.some((d) => d.status === "processing") ?? false;
  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(load, 2000);
    return () => clearInterval(timer);
  }, [processing, load]);

  async function run(label: string, task: () => Promise<unknown>) {
    setBusy(true);
    setMessage(null);
    try {
      await task();
      setMessage({ tone: "ok", text: label });
    } catch (e) {
      setMessage({ tone: "error", text: e instanceof Error ? e.message : "Something went wrong" });
    } finally {
      setBusy(false);
      load();
    }
  }

  function upload(files: FileList | File[]) {
    const list = Array.from(files);
    if (list.length === 0) return;
    run(`Added ${list.length} file${list.length === 1 ? "" : "s"}; indexing…`, async () => {
      for (const file of list) {
        const form = new FormData();
        form.append("file", file);
        await api(base, { method: "POST", body: form, token });
      }
    });
  }

  function addUrl(e: React.FormEvent) {
    e.preventDefault();
    run("Fetched the page; indexing…", async () => {
      await api(`${base}/url`, { method: "POST", body: JSON.stringify({ url: url.trim() }), token });
      setUrl("");
    });
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2">
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            upload(e.dataTransfer.files);
          }}
          className={`flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-6 text-center text-sm ${
            dragging ? "border-[var(--brand)] bg-zinc-100 dark:bg-zinc-900" : "border-zinc-300 dark:border-zinc-700"
          }`}
        >
          <p className="font-medium">Drop files here</p>
          <p className="mt-1 text-xs text-zinc-500">PDF, Markdown, text or HTML, up to 5 MB each</p>
          <button
            type="button"
            disabled={busy}
            onClick={() => fileInput.current?.click()}
            className="mt-3 rounded-lg bg-[var(--brand)] px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40"
          >
            Choose files
          </button>
          <input
            ref={fileInput}
            type="file"
            multiple
            accept={ACCEPT}
            className="hidden"
            onChange={(e) => {
              if (e.target.files) upload(e.target.files);
              e.target.value = "";
            }}
          />
        </div>
        <form onSubmit={addUrl} className="flex flex-col justify-center rounded-xl border border-zinc-200 p-6 dark:border-zinc-800">
          <label htmlFor="doc-url" className="text-sm font-medium">Add a public web page</label>
          <p className="mt-1 text-xs text-zinc-500">
            We fetch it once and keep the main content. Internal and private addresses are refused.
          </p>
          <div className="mt-3 flex gap-2">
            <input
              id="doc-url"
              type="url"
              required
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://…"
              className="min-w-0 flex-1 rounded-lg border border-zinc-300 bg-transparent px-3 py-1.5 text-sm outline-none focus:border-[var(--brand)] dark:border-zinc-700"
            />
            <button disabled={busy || !url.trim()} className="rounded-lg bg-[var(--brand)] px-3 text-sm font-medium text-white disabled:opacity-40">
              Add
            </button>
          </div>
        </form>
      </div>

      {message && (
        <p className={`text-sm ${message.tone === "error" ? "text-red-600" : "text-emerald-700 dark:text-emerald-400"}`}>{message.text}</p>
      )}

      {!docs ? (
        <p className="text-sm text-zinc-500">Loading…</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-zinc-200 dark:border-zinc-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-zinc-50 text-xs text-zinc-500 dark:bg-zinc-900">
              <tr>
                <th className="px-4 py-2 font-medium">Document</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 text-right font-medium">Chunks</th>
                <th className="hidden px-4 py-2 font-medium sm:table-cell">Added</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id} className="border-t border-zinc-100 align-top dark:border-zinc-800">
                  <td className="px-4 py-2">
                    <div className="font-medium">{d.title}</div>
                    <div className="max-w-xs truncate text-xs text-zinc-500" title={d.source}>{d.source}</div>
                    {d.error && <div className="mt-1 text-xs text-red-600">{d.error}</div>}
                  </td>
                  <td className="px-4 py-2">
                    <Badge color={statusColor(d.status)}>{d.status}</Badge>
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">{d.chunks}</td>
                  <td className="hidden px-4 py-2 text-xs text-zinc-500 sm:table-cell">{new Date(d.created_at).toLocaleDateString()}</td>
                  <td className="whitespace-nowrap px-4 py-2 text-right text-xs">
                    <button
                      disabled={busy || d.status === "processing"}
                      onClick={() => run(`Re-indexing “${d.title}”…`, () => api(`${base}/${d.id}/reindex`, { method: "POST", token }))}
                      className="text-zinc-500 underline hover:text-zinc-900 disabled:opacity-40 dark:hover:text-zinc-100"
                    >
                      Re-index
                    </button>
                    <button
                      disabled={busy}
                      onClick={() => {
                        if (window.confirm(`Delete “${d.title}”? ${tenant.persona} will stop using it.`)) {
                          run(`Deleted “${d.title}”.`, () => api(`${base}/${d.id}`, { method: "DELETE", token }));
                        }
                      }}
                      className="ml-3 text-red-600 underline disabled:opacity-40"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
              {docs.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-sm text-zinc-500">No documents yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
