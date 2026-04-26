import React from "react";
import { render, screen } from "@testing-library/react";
import { PanelErrorBoundary } from "./PanelErrorBoundary.jsx";

function BrokenPanel() {
  throw new Error("boom");
}

describe("PanelErrorBoundary", () => {
  const suppressExpectedRuntimeError = (event) => {
    if (event?.error?.message === "boom") {
      event.preventDefault();
    }
  };

  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    window.addEventListener("error", suppressExpectedRuntimeError);
  });

  afterEach(() => {
    window.removeEventListener("error", suppressExpectedRuntimeError);
    vi.restoreAllMocks();
  });

  it("renders fallback when child panel throws", () => {
    render(
      <PanelErrorBoundary>
        <BrokenPanel />
      </PanelErrorBoundary>
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Panel yüklenemedi");
  });
});
