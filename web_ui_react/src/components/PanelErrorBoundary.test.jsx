import React from "react";
import { render, screen } from "@testing-library/react";
import { PanelErrorBoundary } from "./PanelErrorBoundary.jsx";

function BrokenPanel() {
  throw new Error("boom");
}

describe("PanelErrorBoundary", () => {
  it("renders fallback when child panel throws", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <PanelErrorBoundary>
        <BrokenPanel />
      </PanelErrorBoundary>
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Panel yüklenemedi");
    spy.mockRestore();
  });
});
