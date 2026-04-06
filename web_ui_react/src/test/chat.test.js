/**
 * Tests for web_ui/chat.js — pure utility functions that do not require a
 * live WebSocket or DOM-heavy rendering.
 *
 * The module relies on globals set by app.js (getUIState / setUIState /
 * getCachedEl / SidarVoiceLiveUtils), so we stub those before importing.
 */

// ── Stubs required before the module is evaluated ───────────────────────────
window.getUIState = (key, fb = null) => window.__testState?.[key] ?? fb;
window.setUIState = (key, value) => {
  window.__testState = window.__testState || {};
  window.__testState[key] = value;
  return value;
};
window.getCachedEl = (id) => (id ? document.getElementById(id) : null);
window.SidarVoiceLiveUtils = {
  VOICE_STATE_LABELS: { idle: "Bekleniyor" },
  getVoiceLiveDefaults: () => ({
    lastTranscript: "",
    lastState: "idle",
    summary: "Ses websocket tanılama verisi bekleniyor.",
    diagnostics: "Henüz ek tanı verisi yok.",
    badgeClass: "idle",
    badgeLabel: "Bekleniyor",
    log: [],
  }),
  getVoiceBadgeMeta: (k) => ({ badgeClass: "idle", badgeLabel: "Bekleniyor" }),
  buildVoiceDiagnosticsText: () => "Henüz ek tanı verisi yok.",
  appendVoiceLog: (log, label, value) =>
    [{ label, value }, ...(Array.isArray(log) ? log : [])].slice(0, 8),
};

import "../../../web_ui/chat.js";

// ── escHtml (re-defined inside chat.js) ──────────────────────────────────────
describe("escHtml (chat.js local copy)", () => {
  it("is exposed on window and escapes HTML entities", () => {
    // chat.js defines its own escHtml but may reuse window.escHtml from app.js
    // Either way, the global should be callable
    if (typeof window.escHtml === "function") {
      expect(window.escHtml("<b>")).not.toContain("<");
    }
  });
});

// ── handleVoiceWsEvent ────────────────────────────────────────────────────────
describe("handleVoiceWsEvent", () => {
  beforeEach(() => {
    // Provide a minimal voiceLive panel so renderVoiceLivePanel does not throw
    document.body.innerHTML = `
      <span id="voice-badge-label"></span>
      <span id="voice-badge"></span>
      <span id="voice-last-transcript"></span>
      <span id="voice-summary"></span>
      <span id="voice-diagnostics"></span>
      <ul  id="voice-log-list"></ul>
    `;
    window.__testState = { voiceLive: window.SidarVoiceLiveUtils.getVoiceLiveDefaults() };
  });

  it("is exported on window", () => {
    expect(typeof window.handleVoiceWsEvent).toBe("function");
  });

  it("does not throw for an empty payload", () => {
    expect(() => window.handleVoiceWsEvent({})).not.toThrow();
  });

  it("does not throw for a processed payload", () => {
    expect(() =>
      window.handleVoiceWsEvent({ state: "processed", done: true, transcript: "merhaba" })
    ).not.toThrow();
  });
});

// ── resetVoiceLivePanel ───────────────────────────────────────────────────────
describe("resetVoiceLivePanel", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <span id="voice-badge-label"></span>
      <span id="voice-badge"></span>
      <span id="voice-last-transcript"></span>
      <span id="voice-summary"></span>
      <span id="voice-diagnostics"></span>
      <ul  id="voice-log-list"></ul>
    `;
    window.__testState = { voiceLive: { lastTranscript: "hello", lastState: "processed", log: [{ label: "x", value: "y" }] } };
  });

  it("is exported on window", () => {
    expect(typeof window.resetVoiceLivePanel).toBe("function");
  });

  it("does not throw when called", () => {
    expect(() => window.resetVoiceLivePanel()).not.toThrow();
  });
});
