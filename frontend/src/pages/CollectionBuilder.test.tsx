import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { render } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { BuilderFields, BuiltCollection, CollectionInput, SourceKind } from "../builderApi";
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
  source: { kind: "filters" },
  filters: { match: "all", rules: [{ field: "genre", modifier: "", value: ["Action"] }] },
  sort_by: "title.asc",
  limit: 50,
  visible: { library: true, home: true, shared: false },
  minimum_items: 1,
  summary: "Action films",
  sort_title: "!Action",
  poster: null,
  download_missing: false,
  request_cap: null,
  request_profile: null,
  state: "in_plex",
  plex_items: 12,
  thumb: null,
  last_built_at: null,
  last_error: null,
  run_id: 3,
  requests: { waiting: 0, requested: 0, downloading: 0, imported: 0, failed: 0 },
};

const listSample: BuiltCollection = {
  id: 8,
  library: "Movies",
  title: "Die Hard Collection",
  source: { kind: "list", builder: "tmdb_collection", value: "1570", label: "Die Hard Collection" },
  filters: { match: "all", rules: [] },
  sort_by: "custom",
  limit: null,
  visible: { library: true, home: false, shared: false },
  minimum_items: 1,
  summary: null,
  sort_title: null,
  poster: null,
  download_missing: false,
  request_cap: null,
  request_profile: null,
  state: "in_plex",
  plex_items: 5,
  thumb: null,
  last_built_at: null,
  last_error: null,
  run_id: 4,
  requests: { waiting: 0, requested: 0, downloading: 0, imported: 0, failed: 0 },
};

const sourceKinds: SourceKind[] = [
  {
    builder: "tmdb_collection",
    label: "TMDb collection (franchise)",
    group: "TMDb",
    input: "search",
    placeholder: "Search franchises",
    choices: null,
    previewable: true,
    available: true,
    why: null,
  },
  {
    builder: "tmdb_list",
    label: "TMDb list",
    group: "TMDb",
    input: "link",
    placeholder: "List URL or id",
    choices: null,
    previewable: true,
    available: true,
    why: null,
  },
  {
    builder: "imdb_chart",
    label: "IMDb chart",
    group: "IMDb",
    input: "choice",
    placeholder: null,
    choices: [
      { value: "top", label: "Top 250" },
      { value: "popular", label: "Popular" },
    ],
    previewable: true,
    available: true,
    why: null,
  },
  {
    builder: "tmdb_popular",
    label: "TMDb Popular",
    group: "TMDb",
    input: "count",
    placeholder: null,
    choices: null,
    previewable: true,
    available: true,
    why: null,
  },
  {
    builder: "mdblist_list",
    label: "MDBList list",
    group: "MDBList",
    input: "link",
    placeholder: "List URL",
    choices: null,
    previewable: false,
    available: false,
    why: "Connect MDBList in Settings → Connect first",
  },
];

const KOMETA_POSTER = "https://raw.githubusercontent.com/Kometa-Team/Default-Images/master/genre/Action.jpg";

async function pickOrganise() {
  fireEvent.click(await screen.findByRole("radio", { name: "Organise what I have" }));
}

async function pickList() {
  fireEvent.click(await screen.findByRole("radio", { name: "Get something new" }));
}

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
    "GET /builder/sources?library=Movies": () => ({ sources: sourceKinds }),
    "POST /builder/preview": () => ({
      count: 2,
      items: [
        { rating_key: "1", title: "Die Hard", year: 1988, thumb: "/library/metadata/1/thumb" },
        { rating_key: "2", title: "Speed", year: 1994, thumb: null },
      ],
      problems: [],
    }),
    "POST /builder/sources/preview": () => ({
      previewable: true,
      why: null,
      total: 3,
      in_library: [{ rating_key: "1", title: "Die Hard", year: 1988, thumb: "/library/metadata/1/thumb" }],
      in_library_count: 1,
      missing: [
        { id: "tt0095016", title: "Die Hard 2", year: 1990, poster: "https://image.tmdb.org/t/p/w185/x.jpg" },
        { id: "tt0112864", title: "Die Hard with a Vengeance", year: 1995, poster: null },
      ],
      missing_count: 2,
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
  it("shows the start choice for a new collection", async () => {
    mockApi(baseRoutes());
    renderBuilder("/collections/new?library=Movies");
    expect(await screen.findByRole("heading", { name: "How to start", level: 3 })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Organise what I have" })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: "Get something new" })).not.toBeChecked();
    expect(screen.queryByRole("group", { name: "Filter rule" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sources", level: 3 })).not.toBeInTheDocument();

    await pickOrganise();
    expect(screen.getAllByRole("group", { name: "Filter rule" })).toHaveLength(1);
  });

  it("adds, changes and removes rules; value input follows field kind", async () => {
    mockApi(baseRoutes());
    renderBuilder("/collections/new?library=Movies");
    await pickOrganise();

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
    await pickOrganise();
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
    await pickOrganise();
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
    await pickOrganise();
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
      source: { kind: "filters" },
      sources: [{ kind: "filters" }],
      filters: { match: "all", rules: [{ field: "genre", modifier: "", value: ["Action"] }] },
      sort_by: "year.desc",
      limit: 25,
      visible: { library: true, home: true, shared: false },
      minimum_items: 1,
      summary: null,
      sort_title: null,
      poster: null,
      download_missing: false,
      request_cap: null,
      request_profile: null,
      confirm_requests: false,
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
    await pickOrganise();
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
      source: { kind: "filters" },
      filters: { match: "all", rules: [{ field: "genre", modifier: "", value: ["Action"] }] },
      sort_by: null,
      limit: null,
      visible: { library: true, home: false, shared: false },
      minimum_items: 1,
      summary: "From ready-made",
      sort_title: null,
      poster: { kind: "url", url: KOMETA_POSTER },
      download_missing: false,
      request_cap: null,
      request_profile: null,
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
    await pickOrganise();
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
    await pickOrganise();
    fireEvent.change(await screen.findByLabelText("Title"), { target: { value: "Draft" } });
    fireEvent.click(screen.getByRole("link", { name: "Collections" }));
    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByText("You have unsaved changes")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stay here" }));
    expect(screen.getByLabelText("Title")).toHaveValue("Draft");
  });

  it("pastes a link to set the list source, and shows a 422 under the box", async () => {
    const calls = mockApi(
      baseRoutes({
        "POST /builder/sources/link": (body) => {
          const url = (body as { url: string }).url;
          if (url.includes("bad")) {
            return new Response(JSON.stringify({ detail: "Studio doesn't recognise that link" }), {
              status: 422,
              headers: { "Content-Type": "application/json" },
            });
          }
          return { builder: "tmdb_collection", value: "1570", label: "Die Hard Collection" };
        },
      }),
    );
    renderBuilder("/collections/new?library=Movies");
    await pickList();

    fireEvent.change(await screen.findByLabelText("Paste a link"), { target: { value: "https://www.themoviedb.org/collection/bad" } });
    fireEvent.click(screen.getByRole("button", { name: "Use link" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Studio doesn't recognise that link");

    fireEvent.change(screen.getByLabelText("Paste a link"), { target: { value: "https://www.themoviedb.org/collection/1570" } });
    fireEvent.click(screen.getByRole("button", { name: "Use link" }));
    await waitFor(() => expect(calls.filter((c) => c.route === "POST /builder/sources/link")).toHaveLength(2));
    expect(await screen.findByLabelText("Chosen source")).toHaveTextContent("Die Hard Collection");
    expect(screen.getByLabelText("Title")).toHaveValue("Die Hard Collection");
  });

  it("search pick sets the source and prefills the title", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const calls = mockApi(
      baseRoutes({
        "GET /builder/sources/search?library=Movies&builder=tmdb_collection&q=die": () => ({
          results: [
            { value: "1570", title: "Die Hard Collection", year: 1988, poster: "https://image.tmdb.org/t/p/w185/a.jpg" },
            { value: "99", title: "Other", year: null, poster: null },
          ],
        }),
      }),
    );
    renderBuilder("/collections/new?library=Movies");
    await pickList();

    fireEvent.change(await screen.findByLabelText("Search TMDb collection (franchise)"), { target: { value: "die" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    await waitFor(() => expect(calls.some((c) => c.route.includes("/builder/sources/search"))).toBe(true));
    fireEvent.click(await screen.findByRole("button", { name: /Die Hard Collection/ }));
    expect(screen.getByLabelText("Chosen source")).toHaveTextContent("Die Hard Collection");
    expect(screen.getByLabelText("Title")).toHaveValue("Die Hard Collection");
  });

  it("list preview shows in-library and missing, or why when not previewable", async () => {
    mockApi(
      baseRoutes({
        "POST /builder/sources/link": () => ({ builder: "tmdb_collection", value: "1570", label: "Die Hard Collection" }),
      }),
    );
    renderBuilder("/collections/new?library=Movies");
    await pickList();
    fireEvent.change(await screen.findByLabelText("Paste a link"), { target: { value: "https://www.themoviedb.org/collection/1570" } });
    fireEvent.click(screen.getByRole("button", { name: "Use link" }));

    expect(await screen.findByRole("heading", { name: "In your library (1)", level: 4 })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Missing (2)", level: 4 })).toBeInTheDocument();
    expect(within(screen.getByLabelText("In your library")).getByText("Die Hard")).toBeInTheDocument();
    const missing = screen.getByLabelText("Missing");
    expect(within(missing).getAllByText("Die Hard 2").length).toBeGreaterThan(0);
    expect(within(missing).getAllByText("Die Hard with a Vengeance").length).toBeGreaterThan(0);
  });

  it("list preview shows why when not previewable", async () => {
    mockApi(
      baseRoutes({
        "POST /builder/sources/link": () => ({ builder: "letterboxd_list", value: "crew", label: "Crew" }),
        "POST /builder/sources/preview": () => ({
          previewable: false,
          why: "Studio can show this list once it has been built",
          total: null,
          in_library: [],
          in_library_count: 0,
          missing: [],
          missing_count: 0,
          problems: [],
        }),
      }),
    );
    renderBuilder("/collections/new?library=Movies");
    await pickList();
    fireEvent.change(await screen.findByLabelText("Paste a link"), { target: { value: "https://letterboxd.com/crew" } });
    fireEvent.click(screen.getByRole("button", { name: "Use link" }));
    expect(await screen.findByText("Studio can show this list once it has been built")).toBeInTheDocument();
    expect(screen.queryByLabelText("In your library")).not.toBeInTheDocument();
  });

  it("unavailable source kinds are disabled with their reason", async () => {
    mockApi(baseRoutes());
    renderBuilder("/collections/new?library=Movies");
    await pickList();
    expect(await screen.findByText("Connect MDBList in Settings → Connect first")).toBeInTheDocument();
    expect(screen.getByLabelText("MDBList list")).toBeDisabled();
  });

  it("Create sends a list source payload", async () => {
    const calls = mockApi(
      baseRoutes({
        "POST /builder/sources/link": () => ({ builder: "tmdb_collection", value: "1570", label: "Die Hard Collection" }),
        "POST /collections": (body) => ({
          ...(body as CollectionInput),
          id: 12,
          state: "queued",
          plex_items: null,
          thumb: null,
          last_built_at: null,
          last_error: null,
          run_id: 5,
        }),
      }),
    );
    const { router } = renderBuilder("/collections/new?library=Movies");
    await pickList();
    fireEvent.change(await screen.findByLabelText("Paste a link"), { target: { value: "https://www.themoviedb.org/collection/1570" } });
    fireEvent.click(screen.getByRole("button", { name: "Use link" }));
    await screen.findByLabelText("Chosen source");
    fireEvent.change(screen.getByLabelText("Order"), { target: { value: "release" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(calls.some((c) => c.route === "POST /collections")).toBe(true));
    expect(calls.find((c) => c.route === "POST /collections")!.body).toEqual({
      library: "Movies",
      title: "Die Hard Collection",
      source: { kind: "list", builder: "tmdb_collection", value: "1570", label: "Die Hard Collection" },
      sources: [{ kind: "list", builder: "tmdb_collection", value: "1570", label: "Die Hard Collection" }],
      filters: { match: "all", rules: [] },
      sort_by: "release",
      limit: null,
      visible: { library: true, home: false, shared: false },
      minimum_items: 1,
      summary: null,
      sort_title: null,
      poster: null,
      download_missing: false,
      request_cap: null,
      request_profile: null,
      confirm_requests: false,
    });
    await waitFor(() => expect(router.state.location.pathname).toBe("/collections"));
  });

  it("Download missing is only for list sources, and disabled when requests are off", async () => {
    mockApi(
      baseRoutes({
        "GET /requests/settings": () => ({
          settings: {
            enabled: false,
            via: "auto",
            radarr: { quality_profile: null, root_folder: null, minimum_availability: "released", search: true },
            sonarr: { quality_profile: null, root_folder: null, monitor: "all", search: true, series_type: "standard" },
            daily_cap: null,
            confirm_over: 25,
          },
          seerr: null,
          connected: { radarr: true, sonarr: false, seerr: false },
        }),
        "POST /builder/sources/link": () => ({ builder: "tmdb_collection", value: "1570", label: "Die Hard Collection" }),
      }),
    );
    renderBuilder("/collections/new?library=Movies");
    await pickOrganise();
    expect(screen.queryByRole("heading", { name: "Missing titles" })).not.toBeInTheDocument();
    await pickList();
    fireEvent.change(await screen.findByLabelText("Paste a link"), { target: { value: "https://www.themoviedb.org/collection/1570" } });
    fireEvent.click(screen.getByRole("button", { name: "Use link" }));
    expect(await screen.findByRole("heading", { name: "Missing titles" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Download missing/ })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Why Download missing is off" }));
    expect(screen.getByRole("link", { name: "Settings → Requests" })).toHaveAttribute("href", "/settings/requests");
  });

  it("resends Create with confirm_requests after a 409 needs_confirm", async () => {
    let calls_n = 0;
    const calls = mockApi(
      baseRoutes({
        "GET /requests/settings": () => ({
          settings: {
            enabled: true,
            via: "arr",
            radarr: { quality_profile: null, root_folder: null, minimum_availability: "released", search: true },
            sonarr: { quality_profile: null, root_folder: null, monitor: "all", search: true, series_type: "standard" },
            daily_cap: null,
            confirm_over: 25,
          },
          seerr: null,
          connected: { radarr: true, sonarr: false, seerr: false },
        }),
        "POST /builder/sources/link": () => ({ builder: "tmdb_collection", value: "1570", label: "Die Hard Collection" }),
        "POST /collections": (body) => {
          calls_n += 1;
          const req = body as { confirm_requests?: boolean };
          if (!req.confirm_requests) {
            return new Response(
              JSON.stringify({ detail: { message: "Request 40 titles now?", needs_confirm: true, count: 40 } }),
              { status: 409, headers: { "Content-Type": "application/json" } },
            );
          }
          return {
            ...(body as CollectionInput),
            id: 20,
            state: "queued",
            plex_items: null,
            thumb: null,
            last_built_at: null,
            last_error: null,
            run_id: 9,
            requests: { waiting: 0, requested: 40, downloading: 0, imported: 0, failed: 0 },
          };
        },
      }),
    );
    const { router } = renderBuilder("/collections/new?library=Movies");
    await pickList();
    fireEvent.change(await screen.findByLabelText("Paste a link"), { target: { value: "https://www.themoviedb.org/collection/1570" } });
    fireEvent.click(screen.getByRole("button", { name: "Use link" }));
    await screen.findByLabelText("Chosen source");
    fireEvent.click(screen.getByRole("checkbox", { name: /Download missing/ }));
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent(/Request 40 titles now/);
    fireEvent.click(screen.getByRole("button", { name: "Request 40" }));
    await waitFor(() => expect(calls_n).toBe(2));
    const confirmed = calls.filter((c) => c.route === "POST /collections").at(-1)?.body as { confirm_requests?: boolean; download_missing?: boolean };
    expect(confirmed.confirm_requests).toBe(true);
    expect(confirmed.download_missing).toBe(true);
    await waitFor(() => expect(router.state.location.pathname).toBe("/collections"));
  });

  it("Download missing offers a quality profile, with the default first, and Create sends the choice", async () => {
    const calls = mockApi(
      baseRoutes({
        "GET /requests/settings": () => ({
          settings: {
            enabled: true,
            via: "auto",
            radarr: { quality_profile: "HD-1080p", root_folder: null, minimum_availability: "released", search: true },
            sonarr: { quality_profile: null, root_folder: null, monitor: "all", search: true, series_type: "standard" },
            daily_cap: null,
            confirm_over: 25,
          },
          seerr: null,
          connected: { radarr: true, sonarr: false, seerr: false },
        }),
        "GET /requests/options": () => ({
          radarr: { quality_profiles: ["Any", "HD-1080p", "Ultra-HD"], root_folders: ["/movies"] },
          sonarr: null,
          errors: {},
        }),
        "POST /builder/sources/link": () => ({ builder: "tmdb_collection", value: "1570", label: "Die Hard Collection" }),
        "POST /collections": (body) => ({
          ...(body as CollectionInput),
          id: 21,
          state: "queued",
          plex_items: null,
          thumb: null,
          last_built_at: null,
          last_error: null,
          run_id: 10,
          requests: { waiting: 0, requested: 1, downloading: 0, imported: 0, failed: 0 },
        }),
      }),
    );
    renderBuilder("/collections/new?library=Movies");
    await pickList();
    fireEvent.change(await screen.findByLabelText("Paste a link"), { target: { value: "https://www.themoviedb.org/collection/1570" } });
    fireEvent.click(screen.getByRole("button", { name: "Use link" }));
    await screen.findByLabelText("Chosen source");
    expect(screen.queryByRole("combobox", { name: "Quality profile" })).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: /Download missing/ }));
    const profile = await screen.findByRole("combobox", { name: "Quality profile" });
    expect(within(profile).getAllByRole("option")[0]).toHaveTextContent("Default (HD-1080p)");
    await within(profile).findByRole("option", { name: "Ultra-HD" });
    fireEvent.change(profile, { target: { value: "Ultra-HD" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(calls.some((c) => c.route === "POST /collections")).toBe(true));
    const sent = calls.find((c) => c.route === "POST /collections")?.body as CollectionInput;
    expect(sent.request_profile).toBe("Ultra-HD");
  });

  it("Download missing through Seerr has no quality profile: Seerr picks it", async () => {
    mockApi(
      baseRoutes({
        "GET /requests/settings": () => ({
          settings: {
            enabled: true,
            via: "auto",
            radarr: { quality_profile: "HD-1080p", root_folder: null, minimum_availability: "released", search: true },
            sonarr: { quality_profile: null, root_folder: null, monitor: "all", search: true, series_type: "standard" },
            daily_cap: null,
            confirm_over: 25,
          },
          seerr: { url: "http://seerr:5055", api_key: "…ab12", username: null, has_password: false },
          connected: { radarr: true, sonarr: false, seerr: true },
        }),
        "POST /builder/sources/link": () => ({ builder: "tmdb_collection", value: "1570", label: "Die Hard Collection" }),
      }),
    );
    renderBuilder("/collections/new?library=Movies");
    await pickList();
    fireEvent.change(await screen.findByLabelText("Paste a link"), { target: { value: "https://www.themoviedb.org/collection/1570" } });
    fireEvent.click(screen.getByRole("button", { name: "Use link" }));
    await screen.findByLabelText("Chosen source");
    fireEvent.click(screen.getByRole("checkbox", { name: /Download missing/ }));
    expect(await screen.findByText("Requests go through Seerr, which picks the quality.")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Quality profile" })).toBeNull();
  });

  it("edit opens a list collection in the list view with source and order", async () => {
    mockApi(
      baseRoutes({
        "GET /collections/8": () => ({ ...listSample, sort_by: "alpha" }),
      }),
    );
    renderBuilder("/collections/8");
    expect(await screen.findByRole("radio", { name: "Get something new" })).toBeChecked();
    expect(screen.getByLabelText("Chosen source")).toHaveTextContent("Die Hard Collection");
    expect(screen.getByLabelText("Title")).toHaveValue("Die Hard Collection");
    expect(screen.getByLabelText("Order")).toHaveValue("alpha");
    expect(screen.queryByRole("group", { name: "Filter rule" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Limit")).not.toBeInTheDocument();
  });

  it("adds a second list source and a titles source; Create sends both in sources", async () => {
    const calls = mockApi(
      baseRoutes({
        "POST /builder/sources/link": () => ({ builder: "tmdb_collection", value: "1570", label: "Die Hard Collection" }),
        "POST /collections": (body) => ({
          ...(body as CollectionInput),
          id: 30,
          state: "queued",
          plex_items: null,
          thumb: null,
          last_built_at: null,
          last_error: null,
          run_id: 11,
        }),
      }),
    );
    renderBuilder("/collections/new?library=Movies");
    await pickList();
    fireEvent.change(await screen.findByLabelText("Paste a link"), { target: { value: "https://www.themoviedb.org/collection/1570" } });
    fireEvent.click(screen.getByRole("button", { name: "Use link" }));
    await screen.findByLabelText("Chosen source");

    fireEvent.click(screen.getByRole("button", { name: "Add another source" }));
    fireEvent.click(screen.getByRole("button", { name: "Individual titles" }));
    fireEvent.change(await screen.findByLabelText("Title ids"), {
      target: { value: "550\nhttps://www.themoviedb.org/movie/603" },
    });
    expect(screen.getByText("Read 2 ids.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(calls.some((c) => c.route === "POST /collections")).toBe(true));
    const sent = calls.find((c) => c.route === "POST /collections")!.body as CollectionInput;
    expect(sent.sources).toEqual([
      { kind: "list", builder: "tmdb_collection", value: "1570", label: "Die Hard Collection" },
      { kind: "titles", builder: "tmdb_movie", ids: ["550", "603"], label: "TMDb movie · 2" },
    ]);
    expect(sent.source).toEqual(sent.sources![0]);
  });

  it("removes a source", async () => {
    mockApi(
      baseRoutes({
        "POST /builder/sources/link": () => ({ builder: "tmdb_collection", value: "1570", label: "Die Hard Collection" }),
      }),
    );
    renderBuilder("/collections/new?library=Movies");
    await pickList();
    fireEvent.change(await screen.findByLabelText("Paste a link"), { target: { value: "https://www.themoviedb.org/collection/1570" } });
    fireEvent.click(screen.getByRole("button", { name: "Use link" }));
    await screen.findByLabelText("Chosen source");

    fireEvent.click(screen.getByRole("button", { name: "Add another source" }));
    fireEvent.click(screen.getByRole("button", { name: "Individual titles" }));
    expect(screen.getAllByRole("listitem", { name: /^Source:/ })).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: "Remove source 2" }));
    expect(screen.getAllByRole("listitem", { name: /^Source:/ })).toHaveLength(1);
    expect(screen.getByLabelText("Chosen source")).toHaveTextContent("Die Hard Collection");
  });

  it("editing an old single-source collection still works", async () => {
    mockApi(
      baseRoutes({
        "GET /collections/8": () => ({ ...listSample, sources: undefined }),
      }),
    );
    renderBuilder("/collections/8");
    expect(await screen.findByRole("radio", { name: "Get something new" })).toBeChecked();
    expect(screen.getByLabelText("Chosen source")).toHaveTextContent("Die Hard Collection");
    expect(screen.getByLabelText("Title")).toHaveValue("Die Hard Collection");
  });

  it("a Plex search source uses the rule editor", async () => {
    mockApi(baseRoutes());
    renderBuilder("/collections/new?library=Movies");
    await pickList();
    fireEvent.click(await screen.findByRole("button", { name: "Add another source" }));
    fireEvent.click(screen.getByRole("button", { name: "Plex search" }));
    expect(screen.getByRole("listitem", { name: "Source: Plex search" })).toBeInTheDocument();
    expect(screen.getAllByRole("group", { name: "Filter rule" }).length).toBeGreaterThanOrEqual(1);
    fireEvent.click(screen.getByRole("button", { name: "Remove source 1" }));
    expect(screen.getByRole("listitem", { name: "Source: Plex search" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Filter rule" })).toBeInTheDocument();
  });

  it("keeps null visibility until the checkbox is changed, and Save sends null", async () => {
    const imported: BuiltCollection = {
      ...listSample,
      id: 42,
      visible: { library: null, home: null, shared: null },
    };
    const calls = mockApi(
      baseRoutes({
        "GET /collections/42": () => imported,
        "PUT /collections/42": (body) => ({ ...imported, ...(body as CollectionInput) }),
      }),
    );
    renderBuilder("/collections/42");
    expect(await screen.findAllByText("Plex's setting")).toHaveLength(3);

    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.route === "PUT /collections/42")).toBe(true));
    const sent = calls.find((c) => c.route === "PUT /collections/42")!.body as CollectionInput;
    expect(sent.visible).toEqual({ library: null, home: null, shared: null });
  });

  it("changing a null visibility checkbox sends a boolean and leaves the others null", async () => {
    const imported: BuiltCollection = {
      ...listSample,
      id: 43,
      visible: { library: null, home: null, shared: null },
    };
    const calls = mockApi(
      baseRoutes({
        "GET /collections/43": () => imported,
        "PUT /collections/43": (body) => ({ ...imported, ...(body as CollectionInput) }),
      }),
    );
    renderBuilder("/collections/43");
    await screen.findAllByText("Plex's setting");
    fireEvent.click(screen.getByRole("checkbox", { name: /Library recommended/ }));
    expect(screen.getAllByText("Plex's setting")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.route === "PUT /collections/43")).toBe(true));
    const sent = calls.find((c) => c.route === "PUT /collections/43")!.body as CollectionInput;
    expect(sent.visible).toEqual({ library: true, home: null, shared: null });
  });
});
