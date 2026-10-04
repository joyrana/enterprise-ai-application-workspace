import { vi } from "vitest";

export interface MockRoute {
  method: string;
  path: string | RegExp;
  status?: number;
  body?: unknown;
  headers?: Record<string, string>;
}

export interface RecordedCall {
  method: string;
  url: string;
  headers: Record<string, string>;
  body: unknown;
}

/**
 * Stubs `fetch` at the HTTP boundary. Each route answers once, in order, so a
 * test states exactly which requests it expects. Unexpected requests fail loudly.
 */
export function mockFetch(routes: MockRoute[]): { calls: RecordedCall[] } {
  const pending = [...routes];
  const calls: RecordedCall[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init: RequestInit = {}) => {
      const method = (init.method ?? "GET").toUpperCase();
      const url = String(input);
      calls.push({
        method,
        url,
        headers: { ...(init.headers as Record<string, string>) },
        body: typeof init.body === "string" ? JSON.parse(init.body) : undefined,
      });
      const index = pending.findIndex(
        (r) => r.method === method && (typeof r.path === "string" ? url.split("?")[0] === r.path : r.path.test(url)),
      );
      if (index === -1) throw new Error(`Unexpected request: ${method} ${url}`);
      const [route] = pending.splice(index, 1);
      const status = route?.status ?? 200;
      const isProblem = status >= 400;
      return new Response(route?.body === undefined ? null : JSON.stringify(route.body), {
        status,
        headers: {
          "Content-Type": isProblem ? "application/problem+json" : "application/json",
          ...route?.headers,
        },
      });
    }),
  );
  return { calls };
}

export function problem(status: number, code: string, title: string, extra: Record<string, unknown> = {}) {
  return { type: `urn:workspace:error:${code}`, title, status, request_id: "req-1", ...extra };
}
