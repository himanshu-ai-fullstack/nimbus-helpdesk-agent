"use client";

import { useState } from "react";

type Article = { id: number; title: string; excerpt: string; score: number };

export function Sources({ query, articles }: { query: string; articles: Article[] }) {
  const [open, setOpen] = useState(false);
  const titles = [...new Set(articles.map((a) => a.title))];
  return (
    <div className="my-2 text-xs text-zinc-500">
      <button onClick={() => setOpen(!open)} className="inline-flex items-center gap-1.5 hover:text-zinc-800 dark:hover:text-zinc-200">
        <span>📚 Searched help center for “{query}”</span>
        <span>· {titles.length} article{titles.length === 1 ? "" : "s"}</span>
        <span>{open ? "▾" : "▸"}</span>
      </button>
      {!open && (
        <div className="mt-1 flex flex-wrap gap-1.5">
          {titles.map((t) => (
            <span key={t} className="rounded-md bg-zinc-100 dark:bg-zinc-800 px-2 py-0.5">{t}</span>
          ))}
        </div>
      )}
      {open && (
        <div className="mt-2 space-y-2">
          {articles.map((a) => (
            <div key={a.id} className="rounded-lg border border-zinc-200 dark:border-zinc-800 p-2">
              <div className="flex justify-between font-medium text-zinc-700 dark:text-zinc-300">
                <span>{a.title}</span>
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
