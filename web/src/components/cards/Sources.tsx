"use client";

import { useState } from "react";
import type { Article, Citation } from "@/lib/types";

export function Sources({ query, articles }: { query: string; articles: Article[] }) {
  const [open, setOpen] = useState(false);
  const titles = [...new Set(articles.map((a) => a.title))];
  return (
    <div className="my-2 text-xs text-zinc-500">
      <button onClick={() => setOpen(!open)} className="inline-flex items-center gap-1.5 hover:text-zinc-800 dark:hover:text-zinc-200">
        <span>📚 Searched the knowledge base for “{query}”</span>
        <span>· {titles.length} article{titles.length === 1 ? "" : "s"}</span>
        <span>{open ? "▾" : "▸"}</span>
      </button>
      {!open && (
        <div className="mt-1 flex flex-wrap gap-1.5">
          {titles.map((t) => (
            <span key={t} className="rounded-md bg-zinc-100 px-2 py-0.5 dark:bg-zinc-800">{t}</span>
          ))}
        </div>
      )}
      {open && (
        <div className="mt-2 space-y-2">
          {articles.map((a) => (
            <div key={a.id} className="rounded-lg border border-zinc-200 p-2 dark:border-zinc-800">
              <div className="flex justify-between gap-2 font-medium text-zinc-700 dark:text-zinc-300">
                <span>
                  {a.title}
                  {a.page && <span className="font-normal text-zinc-500"> · page {a.page}</span>}
                </span>
                <span className="font-mono text-zinc-400">rrf {a.score.toFixed(3)}</span>
              </div>
              <p className="mt-1 line-clamp-3 whitespace-pre-line">{a.excerpt}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Numbered chips for the passages an answer cited. Same passage, same number. */
export function Citations({ citations }: { citations: Citation[] }) {
  const [openKey, setOpenKey] = useState<string | null>(null);
  const unique = [...new Map(citations.map((c) => [`${c.source}|${c.citedText}`, c])).entries()];
  if (unique.length === 0) return null;
  const open = unique.find(([key]) => key === openKey)?.[1];
  return (
    <div className="mt-1 text-xs">
      <div className="flex flex-wrap items-center gap-1.5 text-zinc-500">
        <span>Sources:</span>
        {unique.map(([key, c], i) => (
          <button
            key={key}
            onClick={() => setOpenKey(openKey === key ? null : key)}
            title={c.title}
            className={`rounded-md border px-1.5 py-0.5 ${
              openKey === key
                ? "border-[var(--brand)] text-zinc-900 dark:text-zinc-100"
                : "border-zinc-200 hover:border-zinc-400 dark:border-zinc-700"
            }`}
          >
            [{i + 1}] {c.title}
          </button>
        ))}
      </div>
      {open && (
        <blockquote className="mt-2 border-l-2 border-[var(--brand)] pl-3 whitespace-pre-line text-zinc-600 dark:text-zinc-400">
          {open.citedText}
        </blockquote>
      )}
    </div>
  );
}
