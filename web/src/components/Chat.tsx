"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { API_URL } from "@/lib/api";
import type { HelpdeskMessage } from "@/lib/types";
import { ToolPart } from "./ToolPart";

const SUGGESTIONS = [
  "What's the difference between Pro and Business?",
  "I'm priya@lumen.example. We added 3 seats by mistake this week, can I get that refunded?",
  "arjun@tinyfox.example here. I want a full refund of my annual plan.",
  "Our SSO test fails with 'audience mismatch'. How do I fix it?",
  "I lost my 2FA phone and I'm the workspace owner. Please help.",
];

export function Chat() {
  const [input, setInput] = useState("");
  const { messages, sendMessage, status, stop, error } = useChat<HelpdeskMessage>({
    transport: new DefaultChatTransport({ api: `${API_URL}/api/chat` }),
  });
  const bottom = useRef<HTMLDivElement>(null);
  const busy = status === "submitted" || status === "streaming";

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  function send(text: string) {
    if (!text.trim() || busy) return;
    sendMessage({ text });
    setInput("");
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl px-4 py-6">
          {messages.length === 0 && (
            <div className="py-10">
              <h1 className="text-2xl font-semibold">Hi, I&apos;m Nim 👋</h1>
              <p className="mt-2 text-zinc-500">
                The AI support agent for Nimbus, a fictional project management app. I can answer
                product questions from the help center, look up demo accounts and invoices, propose
                refunds for a human to approve, and escalate with a triaged ticket.
              </p>
              <div className="mt-6 grid gap-2 sm:grid-cols-2">
                {SUGGESTIONS.map((s) => (
                  <button key={s} onClick={() => send(s)}
                    className="rounded-xl border border-zinc-200 dark:border-zinc-800 p-3 text-left text-sm hover:border-indigo-400 hover:bg-indigo-50/50 dark:hover:bg-indigo-950/30">
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m) => (
            <div key={m.id} className={`mb-6 flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              {m.role === "user" ? (
                <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-indigo-600 px-4 py-2 text-white">
                  {m.parts.map((p, i) => (p.type === "text" ? <span key={i}>{p.text}</span> : null))}
                </div>
              ) : (
                <div className="w-full">
                  {m.parts.map((p, i) => {
                    if (p.type === "text") {
                      return (
                        <div key={i} className="prose-chat">
                          <ReactMarkdown>{p.text}</ReactMarkdown>
                        </div>
                      );
                    }
                    if (p.type === "reasoning") {
                      if (!p.text) return null;
                      return (
                        <details key={i} className="my-1 text-xs text-zinc-500">
                          <summary className="cursor-pointer select-none">Thinking</summary>
                          <p className="mt-1 whitespace-pre-wrap border-l-2 border-zinc-200 dark:border-zinc-700 pl-3">{p.text}</p>
                        </details>
                      );
                    }
                    return <ToolPart key={i} part={p} />;
                  })}
                </div>
              )}
            </div>
          ))}

          {status === "submitted" && <div className="text-sm text-zinc-500 animate-pulse">Nim is thinking…</div>}
          {error && (
            <div className="rounded-lg bg-red-50 dark:bg-red-950/40 p-3 text-sm text-red-700 dark:text-red-300">
              {error.message.includes("429") ? "You're sending messages quickly. Try again in a few minutes." : "Something went wrong. Please try again."}
            </div>
          )}
          <div ref={bottom} />
        </div>
      </div>

      <form onSubmit={(e) => { e.preventDefault(); send(input); }}
        className="border-t border-zinc-200 dark:border-zinc-800 bg-white/80 dark:bg-zinc-950/80 backdrop-blur">
        <div className="mx-auto flex max-w-3xl gap-2 px-4 py-3">
          <input value={input} onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about billing, plans, SSO, refunds…"
            className="flex-1 rounded-xl border border-zinc-300 dark:border-zinc-700 bg-transparent px-4 py-2.5 outline-none focus:border-indigo-500" />
          {busy ? (
            <button type="button" onClick={stop} className="rounded-xl border border-zinc-300 dark:border-zinc-700 px-4 text-sm">Stop</button>
          ) : (
            <button type="submit" disabled={!input.trim()} className="rounded-xl bg-indigo-600 px-4 text-sm font-medium text-white disabled:opacity-40">Send</button>
          )}
        </div>
      </form>
    </div>
  );
}
