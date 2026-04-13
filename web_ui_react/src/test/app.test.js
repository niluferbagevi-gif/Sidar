/**
 * Tests for web_ui/app.js — UIStore, helper functions, and utility exports
 */
import "../../../web_ui/app.js";

describe("UIStore — seed defaults", () => {
  it("initialises window.UIStore with all required default keys", () => {
    const s = window.UIStore.state;
    expect(s).toHaveProperty("isCurrentUserAdmin", false);
    expect(s).toHaveProperty("isStreaming", false);
    expect(s).toHaveProperty("msgCounter", 0);
    expect(s).toHaveProperty("currentRepo", "niluferbagevi-gif/Sidar");
    expect(s).toHaveProperty("currentBranch", "main");
    expect(s).toHaveProperty("defaultBranch", "main");
    expect(s).toHaveProperty("currentSessionId", null);
    expect(s).toHaveProperty("attachedFileContent", null);
    expect(s).toHaveProperty("attachedFileName", null);
    expect(s).toHaveProperty("allSessions");
    expect(Array.isArray(s.allSessions)).toBe(true);
    expect(s).toHaveProperty("cachedRepos", null);
    expect(s).toHaveProperty("cachedBranches", null);
  });

  it("includes a voiceLive sub-object with the expected shape", () => {
    const vl = window.UIStore.state.voiceLive;
    expect(vl).toMatchObject({
      lastTranscript: "",
      lastState: "idle",
      badgeClass: "idle",
      badgeLabel: "Bekleniyor",
    });
    expect(Array.isArray(vl.log)).toBe(true);
  });
});

describe("getUIState / setUIState", () => {
  it("reads an existing key from the store", () => {
    expect(window.getUIState("isStreaming")).toBe(false);
  });

  it("returns the fallback for an unknown key", () => {
    expect(window.getUIState("__nonexistent__", "fallback")).toBe("fallback");
  });

  it("writes and reads back a value", () => {
    window.setUIState("msgCounter", 42);
    expect(window.getUIState("msgCounter")).toBe(42);
    // restore
    window.setUIState("msgCounter", 0);
  });
});

describe("getCachedEl", () => {
  it("returns null for null or undefined id", () => {
    expect(window.getCachedEl(null)).toBeNull();
    expect(window.getCachedEl(undefined)).toBeNull();
    expect(window.getCachedEl("")).toBeNull();
  });

  it("caches DOM lookups on repeated calls", () => {
    const div = document.createElement("div");
    div.id = "test-cached-el";
    document.body.appendChild(div);

    const first = window.getCachedEl("test-cached-el");
    const second = window.getCachedEl("test-cached-el");
    expect(first).toBe(div);
    expect(first).toBe(second);

    document.body.removeChild(div);
  });
});

describe("escHtml", () => {
  it("escapes the five HTML special characters", () => {
    const raw = `<script>alert("xss") & 'test'</script>`;
    const escaped = window.escHtml(raw);
    expect(escaped).not.toContain("<");
    expect(escaped).not.toContain(">");
    expect(escaped).not.toContain('"');
    expect(escaped).not.toContain("'");
    expect(escaped).not.toContain("&");
  });

  it("returns empty string for null/undefined", () => {
    expect(window.escHtml(null)).toBe("");
    expect(window.escHtml(undefined)).toBe("");
  });

  it("leaves plain text untouched", () => {
    expect(window.escHtml("hello world")).toBe("hello world");
  });
});
