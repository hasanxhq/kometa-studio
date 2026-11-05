import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mockApi, renderAt } from "../test-utils";
import { PosterMark, Wordmark } from "./Logo";

describe("The logo", () => {
  it("takes its colours from the app's tokens, and screen readers skip the mark", () => {
    const { container } = render(<PosterMark size={32} />);
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).toHaveAttribute("width", "32");
    const paths = [...svg.querySelectorAll("path")];
    expect(paths.map((path) => path.getAttribute("class"))).toEqual(["fill-accent", "fill-accent", "fill-accent", "fill-on-accent"]);
    expect(paths.map((path) => path.getAttribute("opacity"))).toEqual(["0.3", "0.55", null, null]);
  });

  it("is read as Starr Studio, with the star drawn, not spelled", () => {
    render(<Wordmark />);
    const name = screen.getByRole("img", { name: "Starr Studio" });
    expect(name).toHaveTextContent("Starr Studio");
    expect(name).not.toHaveTextContent("*");
    expect(name.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("sits in the sidebar as the mark and the name", async () => {
    mockApi({});
    renderAt("/settings/ui");
    const name = await screen.findByRole("img", { name: "Starr Studio" });
    expect(name.parentElement!.querySelectorAll("svg")).toHaveLength(2); // the mark, and the star in the name
  });
});
