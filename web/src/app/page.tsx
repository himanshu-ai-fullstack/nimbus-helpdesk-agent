import { Suspense } from "react";
import { Chat } from "@/components/Chat";

export default function Home() {
  // useChat generates message ids at render time, so the chat renders per visit.
  return (
    <Suspense fallback={<div className="flex-1" />}>
      <Chat />
    </Suspense>
  );
}
