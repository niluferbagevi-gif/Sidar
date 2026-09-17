import { vi, describe, it, expect, beforeEach } from "vitest";

const renderMock = vi.fn();
const createRootMock = vi.fn(() => ({ render: renderMock }));

vi.mock("react-dom/client", () => ({
  default: { createRoot: createRootMock },
  createRoot: createRootMock,
}));

vi.mock("./App.js", () => ({
  default: () => null,
}));

describe("main entrypoint", () => {
  beforeEach(() => {
    vi.resetModules();
    renderMock.mockClear();
    createRootMock.mockClear();
    document.body.innerHTML = '<div id="root"></div>';
  });

  it("creates a root and renders the app tree", async () => {
    await import("./main.tsx");

    expect(createRootMock).toHaveBeenCalledTimes(1);
    expect(createRootMock).toHaveBeenCalledWith(document.getElementById("root"));
    expect(renderMock).toHaveBeenCalledTimes(1);
  });

  it("fails clearly when the root element is missing", async () => {
    document.body.innerHTML = "";

    await expect(import("./main.tsx")).rejects.toThrow("Sidar frontend root elementi bulunamadı.");
    expect(createRootMock).not.toHaveBeenCalled();
  });
});
