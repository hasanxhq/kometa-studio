import { describe, expect, it } from "vitest";

import { describeFilter, withFilter } from "./FilterChips";

describe("Filters in words", () => {
  it("names Kometa's attributes and modifiers", () => {
    expect(describeFilter("year.gte", 2000)).toBe("Year ≥ 2000");
    expect(describeFilter("audience_rating.lt", 5)).toBe("Audience rating < 5");
    expect(describeFilter("genre", ["Comedy", "Drama"])).toBe("Genre: Comedy, Drama");
    expect(describeFilter("genre.not", "Horror")).toBe("Genre isn't: Horror");
    expect(describeFilter("release.after", "2020-01-01")).toBe("Released after: 2020-01-01");
    expect(describeFilter("tmdb_keyword.regex", "^space")).toBe("Tmdb keyword matches: ^space");
    expect(describeFilter("actor.count_gte", 2)).toBe("Actor count ≥ 2");
    expect(describeFilter("has_dolby_vision", true)).toBe("Has dolby vision");
  });

  it("adds genres to a list that's there, and replaces numbers", () => {
    expect(withFilter({ genre: "Comedy" }, "genre", "Drama, Comedy")).toEqual({ genre: ["Comedy", "Drama"] });
    expect(withFilter({}, "genre.not", "Horror")).toEqual({ "genre.not": "Horror" });
    expect(withFilter({ "year.gte": 1990 }, "year.gte", "2000")).toEqual({ "year.gte": 2000 });
  });
});
