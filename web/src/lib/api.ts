export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export function usd(n: number) {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}
