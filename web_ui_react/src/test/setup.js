import { afterEach, beforeEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const originalConsoleError = console.error.bind(console);
const intentionalConsoleErrorPatterns = [
  /not wrapped in act/i,
  /the current testing environment is not configured to support act/i,
];
let consoleErrorSpy;
let unexpectedConsoleErrors = [];

beforeEach(() => {
  unexpectedConsoleErrors = [];
  consoleErrorSpy = vi.spyOn(console, "error").mockImplementation((...args) => {
    const message = args.map((arg) => String(arg)).join(" ");
    if (intentionalConsoleErrorPatterns.some((pattern) => pattern.test(message))) {
      return;
    }
    unexpectedConsoleErrors.push(message);
    originalConsoleError(...args);
  });
});

afterEach(() => {
  cleanup();
  const consoleErrors = [...unexpectedConsoleErrors];
  unexpectedConsoleErrors = [];
  consoleErrorSpy?.mockRestore();
  consoleErrorSpy = undefined;

  if (consoleErrors.length > 0) {
    throw new Error(`Unexpected console.error call(s):\n${consoleErrors.join("\n")}`);
  }
});

if (!window.matchMedia) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

if (!navigator.mediaDevices) {
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: vi.fn().mockResolvedValue("mock_stream"),
    },
  });
}