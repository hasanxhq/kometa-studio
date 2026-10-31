// Helpers for page tests: a fake API behind fetch, a fake EventSource, and rendering the app at a path.

import { QueryClient } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router";
import { vi } from "vitest";

import { App } from "./App";

type Handler = (body: unknown) => unknown;

export const signedIn = { allowed: true, reason: null, message: null, configured: true, signed_in: true, local: true };

// Routes "METHOD /path" to a handler; records each call's body. Sign-in is set up and this browser is in, unless a test says otherwise.
export function mockApi(routes: Record<string, Handler>) {
  routes = { "GET /auth": () => signedIn, ...routes };
  const calls: { route: string; body: unknown }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const route = `${init?.method ?? "GET"} ${String(input).replace("/api/v1", "")}`;
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ route, body });
    const handler = routes[route];
    if (!handler) return new Response(JSON.stringify({ detail: `no mock for ${route}` }), { status: 404 });
    const result = handler(body);
    if (result instanceof Response) return result;
    return new Response(JSON.stringify(result), { headers: { "Content-Type": "application/json" } });
  });
  return calls;
}

export function renderAt(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter([{ path: "*", element: <App queryClient={queryClient} /> }], { initialEntries: [path] });
  return render(<RouterProvider router={router} />);
}

// jsdom has no EventSource. Tests push server-sent events through `emit`.
export class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onopen: (() => void) | null = null;
  closed = false;
  private listeners = new Map<string, ((event: MessageEvent) => void)[]>();

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  close() {
    this.closed = true;
  }

  open() {
    act(() => this.onopen?.());
  }

  emit(type: string, data: unknown) {
    act(() => {
      for (const listener of this.listeners.get(type) ?? []) listener(new MessageEvent(type, { data: JSON.stringify(data) }));
    });
  }

  static install() {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
  }

  static latest(): FakeEventSource {
    const source = FakeEventSource.instances.at(-1);
    if (!source) throw new Error("no EventSource was opened");
    return source;
  }
}
