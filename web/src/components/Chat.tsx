"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { API_URL, api, storage } from "@/lib/api";
import type { AgentMessage, Citation } from "@/lib/types";
import { Citations } from "./cards/Sources";
import { useTenant } from "./tenant";
import { ToolPart } from "./ToolPart";

const conversationKey = (slug: string) => `conversation:${slug}`;

/** Restores this browser's conversation with the tenant (history lives on the
 * server), then hands it to the chat. */
export function Chat() {
  const { tenant } = useTenant();
  const [session, setSession] = useState<{ id: string; messages: AgentMessage[] } | null>(null);

  useEffect(() => {
    let live = true;
    const saved = storage.get(conversationKey(tenant.slug));
    const restore = saved
      ? api<{ messages: AgentMessage[] }>(`/api/t/${tenant.slug}/conversations/${saved}`).then((c) => ({
          id: saved,
          messages: c.messages,
        }))
      : Promise.reject(new Error("no saved conversation"));
    restore
      .catch(() => ({ id: crypto.randomUUID(), messages: [] as AgentMessage[] }))
      .then((s) => live && setSession(s));
    return () => {
      live = false;
    };
  }, [tenant.slug]);

  function newChat() {
    storage.set(conversationKey(tenant.slug), null);
    setSession({ id: crypto.randomUUID(), messages: [] });
  }

  if (!session) return <div className="flex-1" />;
  return <ChatSession key={session.id} id={session.id} initialMessages={session.messages} onNewChat={newChat} />;
}

function ChatSession({ id, initialMessages, onNewChat }: { id: string; initialMessages: AgentMessage[]; onNewChat: () => void }) {
  const { tenant } = useTenant();
  const [input, setInput] = useState("");
  const transport = useMemo(
    () =>
      new DefaultChatTransport<AgentMessage>({
        api: `${API_URL}/api/t/${tenant.slug}/chat`,
        // The server keeps the history; send only the new message.
        prepareSendMessagesRequest: ({ id, messages }) => ({ body: { id, message: messages[messages.length - 1] } }),
      }),
    [tenant.slug],
  );
  const { messages, sendMessage, status, stop, error } = useChat<AgentMessage>({ id, messages: initialMessages, transport });
  const bottom = useRef<HTMLDivElement>(null);
  const busy = status === "submitted" || status === "streaming";

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  function send(text: string) {
    if (!text.trim() || busy) return;
    storage.set(conversationKey(tenant.slug), id);
    sendMessage({ text });
    setInput("");
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl px-4 py-6">
          {messages.length === 0 && (
            <div className="py-10">
              <h1 className="text-2xl font-semibold">Hi, I&apos;m {tenant.persona} 👋</h1>
              <p className="mt-2 text-zinc-500">{tenant.greeting}</p>
              <div className="mt-6 grid gap-2 sm:grid-cols-2">
                {tenant.suggestions.map((s) => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    className="rounded-xl border border-zinc-200 p-3 text-left text-sm hover:border-[var(--brand)] dark:border-zinc-800"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, idx) => (
            <div key={m.id} className={`mb-6 flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              {m.role === "user" ? (
                <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-[var(--brand)] px-4 py-2 text-white">
                  {m.parts.map((p, i) => (p.type === "text" ? <span key={i}>{p.text}</span> : null))}
                </div>
              ) : (
                <AssistantMessage message={m} done={!(busy && idx === messages.length - 1)} />
              )}
            </div>
          ))}

          {status === "submitted" && <div className="animate-pulse text-sm text-zinc-500">{tenant.persona} is thinking…</div>}
          {error && (
            <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">
              {error.message.includes("budget")
                ? "This demo has used its model budget for today. Try again tomorrow."
                : error.message.includes("429") || error.message.includes("Too many")
                  ? "You're sending messages quickly. Try again in a few minutes."
                  : "Something went wrong. Please try again."}
            </div>
          )}
          <div ref={bottom} />
        </div>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="border-t border-zinc-200 bg-white/80 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/80"
      >
        <div className="mx-auto flex max-w-3xl gap-2 px-4 py-3">
          {messages.length > 0 && !busy && (
            <button type="button" onClick={onNewChat} title="Start a new conversation"
              className="rounded-xl border border-zinc-300 px-3 text-sm text-zinc-600 dark:border-zinc-700 dark:text-zinc-300">
              New
            </button>
          )}
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            maxLength={4000}
            placeholder={`Message ${tenant.persona}…`}
            className="min-w-0 flex-1 rounded-xl border border-zinc-300 bg-transparent px-4 py-2.5 outline-none focus:border-[var(--brand)] dark:border-zinc-700"
          />
          {busy ? (
            <button type="button" onClick={stop} className="rounded-xl border border-zinc-300 px-4 text-sm dark:border-zinc-700">
              Stop
            </button>
          ) : (
            <button type="submit" disabled={!input.trim()} className="rounded-xl bg-[var(--brand)] px-4 text-sm font-medium text-white disabled:opacity-40">
              Send
            </button>
          )}
        </div>
      </form>
    </div>
  );
}

type Part = AgentMessage["parts"][number];
type Segment = { kind: "text"; text: string; key: number } | { kind: "part"; part: Part; key: number };

/** Claude splits cited answers into several text blocks at citation boundaries.
 * Join consecutive text so markdown (lists, sentences) renders as one piece. */
function segments(parts: Part[]): Segment[] {
  const out: Segment[] = [];
  parts.forEach((part, i) => {
    if (part.type.startsWith("data-")) return;
    const last = out[out.length - 1];
    if (part.type === "text") {
      if (last?.kind === "text") last.text += part.text;
      else out.push({ kind: "text", text: part.text, key: i });
    } else {
      out.push({ kind: "part", part, key: i });
    }
  });
  return out;
}

function AssistantMessage({ message, done }: { message: AgentMessage; done: boolean }) {
  const citations: Citation[] = message.parts.flatMap((p) => (p.type === "data-citation" ? [p.data] : []));
  const hasText = message.parts.some((p) => p.type === "text" && p.text.trim());
  return (
    <div className="w-full">
      {segments(message.parts).map((s) => {
        if (s.kind === "text") {
          return (
            <div key={s.key} className="prose-chat">
              <ReactMarkdown>{s.text}</ReactMarkdown>
            </div>
          );
        }
        const p = s.part;
        const i = s.key;
        if (p.type === "reasoning") {
          if (!p.text) return null;
          return (
            <details key={i} className="my-1 text-xs text-zinc-500">
              <summary className="cursor-pointer select-none">Thinking</summary>
              <p className="mt-1 whitespace-pre-wrap border-l-2 border-zinc-200 pl-3 dark:border-zinc-700">{p.text}</p>
            </details>
          );
        }
        if (p.type.startsWith("tool-")) return <ToolPart key={i} part={p} />;
        return null;
      })}
      {done && <Citations citations={citations} />}
      {done && hasText && <Feedback messageId={message.id} />}
    </div>
  );
}

function Feedback({ messageId }: { messageId: string }) {
  const { tenant } = useTenant();
  const [rating, setRating] = useState<1 | -1 | null>(null);

  async function rate(value: 1 | -1) {
    setRating(value);
    try {
      await api(`/api/t/${tenant.slug}/feedback`, { method: "POST", body: JSON.stringify({ message_id: messageId, rating: value }) });
    } catch {
      setRating(null);
    }
  }

  return (
    <div className="mt-1 flex items-center gap-1 text-xs text-zinc-400">
      {rating ? (
        <span>Thanks for the feedback.</span>
      ) : (
        <>
          <span className="mr-1">Helpful?</span>
          <button onClick={() => rate(1)} aria-label="Helpful" className="rounded px-1 hover:bg-zinc-100 dark:hover:bg-zinc-800">👍</button>
          <button onClick={() => rate(-1)} aria-label="Not helpful" className="rounded px-1 hover:bg-zinc-100 dark:hover:bg-zinc-800">👎</button>
        </>
      )}
    </div>
  );
}
