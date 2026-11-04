import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { render } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { BuilderFields, BuiltCollection, CollectionInput } from "../builderApi";
import { HeaderTitleProvider } from "../components/HeaderTitle";
import { mockApi } from "../test-utils";
import { CollectionBuilder } from "./CollectionBuilder";
import { Collections } from "./Collections";

const fields: BuilderFields = {
  library: "Movies",
  library_type: "movie",
  fields: [
    {
      key: "genre",
      label: "Genre",
      kind: "tag",
      modifiers: [
        { key: "", label: "is" },
        { key: "not", label: "is not" },
      ],
      group: "Tags",
      listable: true,
    },
    {
      key: "title",
      label: "Title",
      kind: "string",
      modifiers: [{ key: "", label: "is" }],
      group: "Text",
      listable: false,
    },
    {
      key: "year",
      label: "Year",
      kind: "year",
      modifiers: [
        { key: "gte", label: "≥" },
        { key: "lte", label: "≤" },
      ],
      group: "Numbers",
      listable: false,
    },
    {
      key: "unwatched",
      label: "Unwatched",
      kind: "boolean",
      modifiers: [{ key: "", label: "is" }],
      group: "Flags",
      listable: false,
    },
    {
      key: "addedAt",
      label: "Date added",
      kind: "date",
      modifiers: [{ key: "gte", label: "after" }],
      group: "Dates",
      listable: false,
    },
  ],
  sorts: [
    { key: "title.asc", label: "Title A–Z" },
    { key: "year.desc", label: "Year (newest)" },
  ],
};

const sample: BuiltCollection = {
  id: 7,
  library: "Movies",
  title: "Action Picks",
  filters: { match: "all", rules: [{ field: "genre", modifier: "", value: ["Action"] }] },
  sort_by: "title.asc",
  limit: 50,
  visible: { library: true, home: true, shared: false },
  minimum_items: 1,
  summary: "Action films",
  sort_title: "!Action",
  poster: null,
  state: "in_plex",
  plex_items: 12,
  thumb: null,
  last_built_at: null,
  last_error: null,
  run_id: 3,
};

const KOMETA_POSTER = "https://raw.githubusercontent.com/Kometa-Team/Default-Images/master/genre/Action.jpg";

function renderBuilder(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/collections", element: <Collections /> },
      { path: "/collections/new", element: <CollectionBuilder /> },
      { path: "/collections/:id", element: <CollectionBuilder /> },
    ],
    { initialEntries: [path] },
  );
  return { ...render(
    <QueryClientProvider client={queryClient}>
      <HeaderTitleProvider>
        <RouterProvider router={router} />
      </HeaderTitleProvider>
    </QueryClientProvider>,
  ), router };
}

function baseRoutes(extra: Record<string, (body: unknown) => unknown> = {}) {
  return {
    "GET /config": () => ({ path: "/config/config.yml", libraries: [{ name: "Movies", plex_name: "Movies" }], playlist_files: [] }),
    "GET /builder/fields?library=Movies": () => fields,
    "GET /builder/values?library=Movies&field=genre": () => ({
      values: [
        { key: "Action", title: "Action" },
        { key: "Comedy", title: "Comedy" },
        { key: "Drama", title: "Drama" },
      ],
    }),
    "POST /builder/preview": () => ({
      count: 2,
      items: [
        { rating_key: "1", title: "Die Hard", year: 1988, thumb: "/library/metadata/1/thumb" },
        { rating_key: "2", title: "Speed", year: 1994, thumb: null },
      ],
      problems: [],
    }),
    "GET /collections?library=Movies": () => ({ collections: [] }),
    ...extra,
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("CollectionBuilder", () => {
  it("adds, changes and removes rules; value input follows field kind", async () => {
    mockApi(baseRoutes());
    renderBuilder("/collections/new?library=Movies");

    expect(await screen.findByRole("heading", { name: "New collection", level: 2 })).toBeInTheDocument();
    expect(screen.getAllByRole("group", { name: "Filter rule" })).toHaveLength(1);

    // Listable tag values load from /builder/values
    expect(await screen.findByRole("checkbox", { name: "Action" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Action" }));

    // Change field → modifier resets, value clears, input kind changes
    fireEvent.change(screen.getByLabelText("Field"), { target: { value: "year" } });
    expect(screen.getByLabelText("Modifier")).toHaveValue("gte");
    expect(screen.getByLabelText("Value")).toHaveAttribute("type", "number");
    fireEvent.change(screen.getByLabelText("Value"), { target: { value: "2000" } });

    fireEvent.change(screen.getByLabelText("Field"), { target: { value: "unwatched" } });
    expect(screen.getByLabelText("Value").tagName).toBe("SELECT");
    expect(screen.getByLabelText("Value")).toHaveDisplayValue("No");

    fireEvent.change(screen.getByLabelText("Field"), { target: { value: "addedAt" } });
    expect(screen.getByLabelText("Value")).toHaveAttribute("placeholder", expect.stringContaining("2024-01-31"));

    fireEvent.change(screen.getByLabelText("Field"), { target: { value: "title" } });
    expect(screen.getByLabelText("Value")).toHaveAttribute("type", "text");
    fireEvent.change(screen.getByLabelText("Value"), { target: { value: "Speed" } });

    fireEvent.click(screen.getByRole("button", { name: "Add rule" }));
    expect(screen.getAllByRole("group", { name: "Filter rule" })).toHaveLength(2);

    const rows = screen.getAllByRole("group", { name: "Filter rule" });
    fireEvent.click(within(rows[1]).getByRole("button", { name: "Remove rule" }));
    expect(screen.getAllByRole("group", { name: "Filter rule" })).toHaveLength(1);
  });

  it("debounces preview and sends the current filters", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const calls = mockApi(baseRoutes());
    renderBuilder("/collections/new?library=Movies");
    await screen.findByRole("heading", { name: "New collection", level: 2 });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    await waitFor(() => expect(calls.some((c) => c.route === "POST /builder/preview")).toBe(true));
    const first = calls.filter((c) => c.route === "POST /builder/preview");
    expect(first.at(-1)?.body).toEqual({
      library: "Movies",
      filters: { match: "all", rules: [{ field: "genre", modifier: "", value: [] }] },
      sort_by: null,
    });

    fireEvent.change(screen.getByLabelText("Field"), { target: { value: "year" } });
    fireEvent.change(screen.getByLabelText("Value"), { target: { value: "2000" } });
    fireEvent.click(screen.getByLabelText("Match any of these rules"));

    const before = calls.filter((c) => c.route === "POST /builder/preview").length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });
    expect(calls.filter((c) => c.route === "POST /builder/preview")).toHaveLength(before);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    await waitFor(() => expect(calls.filter((c) => c.route === "POST /builder/preview").length).toBeGreaterThan(before));
    expect(calls.filter((c) => c.route === "POST /builder/preview").at(-1)?.body).toEqual({
      library: "Movies",
      filters: { match: "any", rules: [{ field: "year", modifier: "gte", value: 2000 }] },
      sort_by: null,
    });

    expect(await screen.findByText("2 titles")).toBeInTheDocument();
    expect(screen.getByText("Die Hard")).toBeInTheDocument();
  });

  it("shows preview problems instead of the grid", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockApi(
      baseRoutes({
        "POST /builder/preview": () => ({ count: 0, items: [], problems: ["Pick a genre", "Year needs a number"] }),
      }),
    );
    renderBuilder("/collections/new?library=Movies");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(await screen.findByText("Pick a genre")).toBeInTheDocument();
    expect(screen.getByText("Year needs a number")).toBeInTheDocument();
    expect(screen.queryByLabelText("Preview titles")).not.toBeInTheDocument();
  });

  it("Create sends CollectionInput and navigates back", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const calls = mockApi(
      baseRoutes({
        "POST /collections": (body) => ({
          ...(body as CollectionInput),
          id: 9,
          state: "queued",
          plex_items: null,
          thumb: null,
          last_built_at: null,
          last_error: null,
          run_id: 1,
        }),
      }),
    );
    const { router } = renderBuilder("/collections/new?library=Movies");
    await screen.findByRole("heading", { name: "New collection", level: 2 });

    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "My Action" } });
    await screen.findByRole("checkbox", { name: "Action" });
    fireEvent.click(screen.getByRole("checkbox", { name: "Action" }));
    fireEvent.change(screen.getByLabelText("Sort"), { target: { value: "year.desc" } });
    fireEvent.change(screen.getByLabelText("Limit"), { target: { value: "25" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "My home" }));

    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(calls.some((c) => c.route === "POST /collections")).toBe(true));
    const body = calls.find((c) => c.route === "POST /collections")!.body as CollectionInput;
    expect(body).toEqual({
      library: "Movies",
      title: "My Action",
      filters: { match: "all", rules: [{ field: "genre", modifier: "", value: ["Action"] }] },
      sort_by: "year.desc",
      limit: 25,
      visible: { library: true, home: true, shared: false },
      minimum_items: 1,
      summary: null,
      sort_title: null,
      poster: null,
    });
    await waitFor(() => expect(router.state.location.pathname).toBe("/collections"));
    expect(router.state.location.search).toBe("?library=Movies");
  });

  it("shows a 422's problems", async () => {
    mockApi(
      baseRoutes({
        "POST /collections": () =>
          new Response(JSON.stringify({ detail: { message: "Invalid filters", problems: ["Genre is required", "Limit too high"] } }), {
            status: 422,
            headers: { "Content-Type": "application/json" },
          }),
      }),
    );
    renderBuilder("/collections/new?library=Movies");
    fireEvent.change(await screen.findByLabelText("Title"), { target: { value: "Bad" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(await screen.findByText("Genre is required")).toBeInTheDocument();
    expect(screen.getByText("Limit too high")).toBeInTheDocument();
  });

  it("edit loads the collection and sends PUT", async () => {
    const calls = mockApi(
      baseRoutes({
        "GET /collections/7": () => sample,
        "PUT /collections/7": (body) => ({ ...sample, ...(body as CollectionInput) }),
      }),
    );
    const { router } = renderBuilder("/collections/7");
    expect(await screen.findByLabelText("Title")).toHaveValue("Action Picks");
    expect(screen.getByLabelText("Sort")).toHaveValue("title.asc");
    expect(screen.getByRole("checkbox", { name: "My home" })).toBeChecked();
    expect(await screen.findByRole("checkbox", { name: "Action" })).toBeChecked();

    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Action Remix" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(calls.some((c) => c.route === "PUT /collections/7")).toBe(true));
    expect((calls.find((c) => c.route === "PUT /collections/7")!.body as CollectionInput).title).toBe("Action Remix");
    await waitFor(() => expect(router.state.location.pathname).toBe("/collections"));
  });

  it("delete confirms then calls DELETE", async () => {
    const calls = mockApi(
      baseRoutes({
        "GET /collections/7": () => sample,
        "DELETE /collections/7": () => ({ removed: true, reason: null }),
      }),
    );
    const { router } = renderBuilder("/collections/7");
    await screen.findByLabelText("Title");

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(screen.getByText(/Deletes it from Plex too/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete" })); // confirm

    await waitFor(() => expect(calls.some((c) => c.route === "DELETE /collections/7")).toBe(true));
    await waitFor(() => expect(router.state.location.pathname).toBe("/collections"));
  });

  it("prefills from a ready-made template draft", async () => {
    const draft: CollectionInput = {
      library: "Movies",
      title: "Action Movies",
      filters: { match: "all", rules: [{ field: "genre", modifier: "", value: ["Action"] }] },
      sort_by: null,
      limit: null,
      visible: { library: true, home: false, shared: false },
      minimum_items: 1,
      summary: "From ready-made",
      sort_title: null,
      poster: { kind: "url", url: KOMETA_POSTER },
    };
    mockApi(
      baseRoutes({
        "GET /ready-made/libraries/Movies/categories/genre/customise?block=dynamic_collections&key=Action": () => draft,
      }),
    );
    renderBuilder("/collections/new?library=Movies&category=genre&block=dynamic_collections&key=Action");
    expect(await screen.findByLabelText("Title")).toHaveValue("Action Movies");
    expect(screen.getByLabelText("Summary")).toHaveValue("From ready-made");
    expect(await screen.findByRole("checkbox", { name: "Action" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Kometa's artwork" })).toBeChecked();
  });

  it("picks, uploads and previews a poster; Create sends it", async () => {
    const uploaded = { kind: "file" as const, path: "studio/posters/abcd1234abcd1234.png" };
    const calls: { route: string; body: unknown }[] = [];
    const routes: Record<string, (body: unknown) => unknown> = {
      "GET /auth": () => ({ allowed: true, reason: null, message: null, configured: true, signed_in: true, local: true }),
      ...baseRoutes({
        "POST /collections": (body) => ({
          ...(body as CollectionInput),
          id: 11,
          state: "queued",
          plex_items: null,
          thumb: null,
          last_built_at: null,
          last_error: null,
          run_id: 2,
        }),
      }),
      "POST /builder/posters": () => uploaded,
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const route = `${init?.method ?? "GET"} ${String(input).replace("/api/v1", "")}`;
      let body: unknown;
      if (route === "POST /builder/posters") body = init?.body;
      else if (init?.body) body = JSON.parse(String(init.body));
      calls.push({ route, body });
      const handler = routes[route];
      if (!handler) return new Response(JSON.stringify({ detail: `no mock for ${route}` }), { status: 404 });
      const result = handler(body);
      if (result instanceof Response) return result;
      return new Response(JSON.stringify(result), { headers: { "Content-Type": "application/json" } });
    });

    renderBuilder("/collections/new?library=Movies");
    expect(await screen.findByRole("heading", { name: "Poster", level: 3 })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Plex's own" })).toBeChecked();
    expect(screen.queryByRole("radio", { name: "Kometa's artwork" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: "Upload an image" }));
    const file = new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], "poster.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Upload poster"), { target: { files: [file] } });
    await waitFor(() => expect(calls.some((c) => c.route === "POST /builder/posters")).toBe(true));
    expect(screen.getByLabelText("Poster preview").querySelector("img")).toHaveAttribute("src", "/api/v1/builder/posters/abcd1234abcd1234.png");

    fireEvent.click(screen.getByRole("radio", { name: "Image link" }));
    fireEvent.change(screen.getByLabelText("Poster URL"), { target: { value: "https://example.com/p.jpg" } });
    expect(screen.getByLabelText("Poster preview").querySelector("img")).toHaveAttribute("src", "https://example.com/p.jpg");

    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "With Poster" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(calls.some((c) => c.route === "POST /collections")).toBe(true));
    expect((calls.find((c) => c.route === "POST /collections")!.body as CollectionInput).poster).toEqual({
      kind: "url",
      url: "https://example.com/p.jpg",
    });
  });

  it("shows a 422 template message and starts empty", async () => {
    mockApi(
      baseRoutes({
        "GET /ready-made/libraries/Movies/categories/imdb/customise?block=collections&key=top": () =>
          new Response(JSON.stringify({ detail: { message: "IMDb Top 250 can't be expressed as filters" } }), {
            status: 422,
            headers: { "Content-Type": "application/json" },
          }),
      }),
    );
    renderBuilder("/collections/new?library=Movies&category=imdb&block=collections&key=top");
    expect(await screen.findByText("IMDb Top 250 can't be expressed as filters")).toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toHaveValue("");
  });

  it("asks before leaving with unsaved changes", async () => {
    mockApi(baseRoutes());
    renderBuilder("/collections/new?library=Movies");
    fireEvent.change(await screen.findByLabelText("Title"), { target: { value: "Draft" } });
    fireEvent.click(screen.getByRole("link", { name: "Collections" }));
    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByText("You have unsaved changes")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stay here" }));
    expect(screen.getByLabelText("Title")).toHaveValue("Draft");
  });
});
