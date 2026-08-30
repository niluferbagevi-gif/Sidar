import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Tests for launcher_gui/script.js — selectOption state machine and
 * animation shim fallback (no GSAP dependency).
 *
 * The module calls `eel.start_sidar(...)` on launch; we stub `window.eel`
 * so that launchSidar() can be exercised without the Python runtime.
 */

type EelStartSidarResponse = { status: string; message: string };
type EelStartSidar = (
  mode: string | null,
  provider: string | null,
  level: string | null,
  logLevel: string,
) => () => Promise<EelStartSidarResponse>;

declare global {
  interface Window {
    eel: { start_sidar: EelStartSidar };
    selectOption?: (category: string, value: string) => void;
  }
  // launcher_gui/script.js is a classic (non-module) script, side-effect
  // imported below; it attaches these via `window.foo = foo` /
  // `Object.assign(globalThis, ...)`, which this jsdom test environment
  // resolves as real globals at runtime -- but tsconfig's `include` only
  // covers `src/`, so tsc has no declaration file for that script. These
  // ambient declarations are the typed equivalent of eslint's `globals`
  // override kept for this same file (see eslint.config.js).
  function launchSidar(): Promise<void>;
  function animateStepTransition(outgoingId: string, incomingId: string): void;
}

const startSidarMock = vi.fn<EelStartSidar>(() => () =>
  Promise.resolve({ status: "success", message: "OK" }),
);

// ── Stubs required before the module loads ───────────────────────────────────
window.eel = { start_sidar: startSidarMock };

// Minimal DOM expected by the script
document.body.innerHTML = `
  <div id="step-1" style="display:block"></div>
  <div id="step-2" style="display:none"></div>
  <div id="step-3" style="display:none"></div>
  <div id="step-loading" style="display:none"></div>
  <div id="status-text"></div>
  <div class="pulsate"></div>
`;

import "../../../launcher_gui/script.js";

// ── selectOption ──────────────────────────────────────────────────────────────
describe("selectOption — state machine", () => {
  beforeEach(() => {
    // Reset the module-level currentStep via a fresh DOM and re-export trick.
    // Because the module is already evaluated we just reset the relevant DOM.
    document.body.innerHTML = `
      <div id="step-1" style="display:block"></div>
      <div id="step-2" style="display:none"></div>
      <div id="step-3" style="display:none"></div>
      <div id="step-loading" style="display:none"></div>
      <div id="status-text"></div>
      <div class="pulsate"></div>
    `;
  });

  it("exposes selectOption globally", () => {
    // `typeof x` always returns a string, so `typeof x ?? y` never falls
    // through to `y` — the previous `?? typeof selectOption` fallback was
    // dead code (caught by eslint's no-constant-binary-expression).
    expect(typeof window.selectOption).toBe("function");
  });
});

// ── launchSidar ───────────────────────────────────────────────────────────────
describe("launchSidar — eel bridge", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="step-loading" style="display:block"></div>
      <div id="status-text"></div>
      <div class="pulsate"></div>
    `;
    startSidarMock.mockClear();
  });

  it("calls eel.start_sidar on launch", async () => {
    await launchSidar();
    expect(startSidarMock).toHaveBeenCalledTimes(1);
  });

  it("shows a success message when eel returns status=success", async () => {
    startSidarMock.mockImplementation(() => () =>
      Promise.resolve({ status: "success", message: "Çalıştı" }),
    );
    await launchSidar();
    const statusText = document.getElementById("status-text") as HTMLElement;
    expect(statusText.style.color).toBe("rgb(16, 185, 129)"); // #10b981
  });

  it("shows an error message when eel returns status=error", async () => {
    startSidarMock.mockImplementation(() => () =>
      Promise.resolve({ status: "error", message: "Port meşgul" }),
    );
    await launchSidar();
    const statusText = document.getElementById("status-text") as HTMLElement;
    expect(statusText.textContent).toContain("Port meşgul");
    expect(statusText.style.color).toBe("rgb(239, 68, 68)"); // #ef4444
  });

  it("shows a connection error when eel throws", async () => {
    startSidarMock.mockImplementation(() => () =>
      Promise.reject(new Error("bağlantı kesildi")),
    );
    await launchSidar();
    const statusText = document.getElementById("status-text") as HTMLElement;
    expect(statusText.textContent).toContain("Bağlantı hatası");
  });
});

// ── Animation shim (no GSAP) ─────────────────────────────────────────────────
describe("animation shim", () => {
  it("does not throw when animating a non-existent selector", () => {
    // The shim inside the module guards with querySelector null-check
    expect(() => animateStepTransition("#step-99", "#step-loading")).not.toThrow();
  });
});
