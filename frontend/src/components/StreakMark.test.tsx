import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mockApi, renderAt } from "../test-utils";
import { StreakMark } from "./StreakMark";

describe("The logo", () => {
  it("takes its colours from the app's tokens, and screen readers skip it", () => {
    const { container } = render(<StreakMark size={32} />);
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).toHaveAttribute("width", "32");
    expect([...svg.querySelectorAll("path")].map((path) => path.getAttribute("class"))).toEqual(["fill-text", "fill-accent"]);
  });

  it("sits beside the name in the sidebar, keeping the space between the words", async () => {
    mockApi({});
    renderAt("/settings/ui");
    const name = (await screen.findByText("Studio")).parentElement!;
    expect(name).toHaveTextContent("Kometa Studio");
    expect(name.parentElement!.querySelector("svg")).not.toBeNull();
  });
});
