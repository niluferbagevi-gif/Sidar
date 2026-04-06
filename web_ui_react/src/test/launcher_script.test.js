/**
 * Tests for launcher_gui/script.js — selectOption state machine and
 * animation shim fallback (no GSAP dependency).
 *
 * The module calls `eel.start_sidar(...)` on launch; we stub `window.eel`
 * so that launchSidar() can be exercised without the Python runtime.
 */

// ── Stubs required before the module loads ───────────────────────────────────
window.eel = {
  start_sidar: vi.fn(() => () =>
    Promise.resolve({ status: "success", message: "OK" })
  ),
};

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
    expect(typeof window.selectOption ?? typeof selectOption).toBe("function");
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
    window.eel.start_sidar.mockClear();
  });

  it("calls eel.start_sidar on launch", async () => {
    await launchSidar();
    expect(window.eel.start_sidar).toHaveBeenCalledTimes(1);
  });

  it("shows a success message when eel returns status=success", async () => {
    window.eel.start_sidar.mockImplementation(() => () =>
      Promise.resolve({ status: "success", message: "Çalıştı" })
    );
    await launchSidar();
    const statusText = document.getElementById("status-text");
    expect(statusText.style.color).toBe("rgb(16, 185, 129)"); // #10b981
  });

  it("shows an error message when eel returns status=error", async () => {
    window.eel.start_sidar.mockImplementation(() => () =>
      Promise.resolve({ status: "error", message: "Port meşgul" })
    );
    await launchSidar();
    const statusText = document.getElementById("status-text");
    expect(statusText.textContent).toContain("Port meşgul");
    expect(statusText.style.color).toBe("rgb(239, 68, 68)"); // #ef4444
  });

  it("shows a connection error when eel throws", async () => {
    window.eel.start_sidar.mockImplementation(() => () =>
      Promise.reject(new Error("bağlantı kesildi"))
    );
    await launchSidar();
    const statusText = document.getElementById("status-text");
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
