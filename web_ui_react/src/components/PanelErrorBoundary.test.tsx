import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PanelErrorBoundary } from "./PanelErrorBoundary.jsx";

function BrokenPanel(): never {
  throw new Error("boom");
}

describe("PanelErrorBoundary", () => {
  const suppressExpectedRuntimeError = (event: ErrorEvent) => {
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
