import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ActionBar, Button } from "./ui";

describe("ActionBar", () => {
  it("is a named region with the summary and the actions", () => {
    render(
      <ActionBar label="Ready-made changes" summary="Build 3">
        <Button>Build</Button>
      </ActionBar>,
    );
    const bar = screen.getByRole("region", { name: "Ready-made changes" });
    expect(within(bar).getByText("Build 3")).toBeInTheDocument();
    expect(within(bar).getByRole("button", { name: "Build" })).toBeInTheDocument();
  });

  it("shows a note only when there is one", () => {
    const { rerender } = render(
      <ActionBar label="Changes" summary="Build 1" note={false}>
        <Button>Build</Button>
      </ActionBar>,
    );
    expect(screen.queryByText("Turn on requests first.")).not.toBeInTheDocument();
    rerender(
      <ActionBar label="Changes" summary="Build 1" note="Turn on requests first.">
        <Button>Build</Button>
      </ActionBar>,
    );
    expect(screen.getByText("Turn on requests first.")).toBeInTheDocument();
  });
});
