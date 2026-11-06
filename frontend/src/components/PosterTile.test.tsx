import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { PickTick, PosterTile, StatusBadge, type StatusBadgeState } from "./PosterTile";

function renderBadge(state: StatusBadgeState) {
  return render(<StatusBadge state={state} />);
}

describe("StatusBadge", () => {
  it("in_plex with count shows ok dot and the count; title In Plex · N titles", () => {
    renderBadge({ kind: "in_plex", count: 31 });
    expect(screen.getByTitle("In Plex · 31 titles")).toHaveTextContent("31");
  });

  it("in_plex without count shows In Plex", () => {
    renderBadge({ kind: "in_plex" });
    expect(screen.getByTitle("In Plex")).toHaveTextContent("In Plex");
  });

  it("in_plex with titles coming shows info dot and count · coming; title lists both", () => {
    renderBadge({ kind: "in_plex", count: 31, coming: 3 });
    expect(screen.getByTitle("In Plex · 31 titles · 3 coming")).toHaveTextContent("31 · 3 coming");
  });

  it("queued shows Queued", () => {
    renderBadge({ kind: "queued" });
    expect(screen.getByTitle("Queued")).toHaveTextContent("Queued");
  });

  it("building shows Building", () => {
    renderBadge({ kind: "building" });
    expect(screen.getByTitle("Building")).toHaveTextContent("Building");
  });

  it("removing shows Removing", () => {
    renderBadge({ kind: "removing" });
    expect(screen.getByTitle("Removing")).toHaveTextContent("Removing");
  });

  it("missing shows dashed outline and Not built", () => {
    const { container } = renderBadge({ kind: "missing" });
    expect(screen.getByTitle("Not built")).toHaveTextContent("Not built");
    expect(container.querySelector(".border-dashed")).toBeTruthy();
  });

  it("failed shows Failed", () => {
    renderBadge({ kind: "failed" });
    expect(screen.getByTitle("Failed")).toHaveTextContent("Failed");
  });

  it("will_remove shows Will be removed", () => {
    renderBadge({ kind: "will_remove" });
    expect(screen.getByTitle("Will be removed")).toHaveTextContent("Will be removed");
  });

  it("changed shows Changed", () => {
    renderBadge({ kind: "changed" });
    expect(screen.getByTitle("Changed")).toHaveTextContent("Changed");
  });
});

describe("PosterTile", () => {
  it("to renders a link to the given path", () => {
    render(
      <MemoryRouter>
        <PosterTile title="Test" to="/collections/1" art={<div>art</div>}>
          <span>Caption</span>
        </PosterTile>
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Test" })).toHaveAttribute("href", "/collections/1");
  });

  it("onOpen renders a dialog button", () => {
    const onOpen = vi.fn();
    render(
      <PosterTile title="Tile" onOpen={onOpen} art={<div>art</div>}>
        <span>Caption</span>
      </PosterTile>,
    );
    const btn = screen.getByRole("button", { name: "Tile" });
    expect(btn).toHaveAttribute("aria-haspopup", "dialog");
    fireEvent.click(btn);
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("pick shows pressed/unpressed tick and does not trigger open when toggling", () => {
    const onOpen = vi.fn();
    const onToggle = vi.fn();
    render(
      <PosterTile title="Pick me" onOpen={onOpen} art={<div>art</div>} pick={{ selected: false, onToggle }}>
        <span>Caption</span>
      </PosterTile>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Pick Pick me" }));
    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(onOpen).not.toHaveBeenCalled();
  });
});

describe("PickTick", () => {
  it("mirrors aria-pressed from selected", () => {
    const { rerender } = render(<PickTick title="X" selected={false} onToggle={() => {}} />);
    expect(screen.getByRole("button", { name: "Pick X" })).toHaveAttribute("aria-pressed", "false");
    rerender(<PickTick title="X" selected onToggle={() => {}} />);
    expect(screen.getByRole("button", { name: "Pick X" })).toHaveAttribute("aria-pressed", "true");
  });
});
