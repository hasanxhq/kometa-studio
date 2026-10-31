import { describe, expect, it } from "vitest";

import { pageTitle } from "./nav";

describe("The header's title", () => {
  it("names nested pages for what they show, in Plex's words", () => {
    expect(pageTitle("/libraries")).toBe("Libraries");
    expect(pageTitle("/libraries/TV%20Shows")).toBe("Library");
    expect(pageTitle("/libraries/TV%20Shows/collections/8752")).toBe("Collection");
    expect(pageTitle("/activity/queue/12")).toBe("Run");
    expect(pageTitle("/activity/queue")).toBe("Queue");
    expect(pageTitle("/items")).toBe("Edit");
    expect(pageTitle("/")).toBe("Overview");
    expect(pageTitle("/nowhere")).toBe("Kometa Studio");
  });
});
