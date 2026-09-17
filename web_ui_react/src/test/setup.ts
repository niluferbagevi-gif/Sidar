import { afterEach, beforeEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

declare global {
  // React-DOM's test-utils read this flag at runtime; no @types package
  // declares it, so it needs an ambient declaration here.
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const originalConsoleError = console.error.bind(console);
const intentionalConsoleErrorPatterns = [
  /not wrapped in act/i,
  /the current testing environment is not configured to support act/i,
];
let consoleErrorSpy: ReturnType<typeof vi.spyOn> | undefined;
let unexpectedConsoleErrors: string[] = [];

beforeEach(() => {
  unexpectedConsoleErrors = [];
  consoleErrorSpy = vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => {
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
    value: vi.fn().mockImplementation((query: string) => ({
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
  // Minimal stand-in -- jsdom has no layout engine, so a real ResizeObserver
  // would never fire anyway; components under test only need the
  // constructor to exist and not throw.
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

if (!navigator.mediaDevices) {
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: vi.fn().mockResolvedValue("mock_stream"),
    },
  });
}
