/**
 * Tests for web_ui/sidebar.js — pure / synchronous helpers.
 *
 * Async helpers that call fetchAPI are smoke-tested only (no-throw contract).
 */

// ── Stubs ────────────────────────────────────────────────────────────────────
const _state = {};
window.getUIState = (key, fb = null) => (key in _state ? _state[key] : fb);
window.setUIState = (key, value) => { _state[key] = value; return value; };
window.getCachedEl = (id) => (id ? document.getElementById(id) : null);
window.escHtml = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
window.fetchAPI = vi.fn().mockResolvedValue({
  json: async () => ({ success: true, sessions: [], active_session: null }),
});
// Functions expected to exist in a full page context — minimal stubs
window.showChatPanel = vi.fn();
window.showTaskPanel = vi.fn();
window.loadSessionHistory = vi.fn().mockResolvedValue(undefined);
window.startTask = vi.fn();
window.quickTask = vi.fn();

import "../../../web_ui/sidebar.js";

// ── formatRelTime ────────────────────────────────────────────────────────────
describe("formatRelTime", () => {
  it("returns 'az önce' for timestamps less than 60 seconds ago", () => {
    const nowSec = Math.floor(Date.now() / 1000);
    expect(formatRelTime(nowSec - 10)).toBe("az önce");
  });

  it("returns minutes for timestamps between 1–59 minutes ago", () => {
    const nowSec = Math.floor(Date.now() / 1000);
    expect(formatRelTime(nowSec - 120)).toMatch(/dk önce/);
  });

  it("returns hours for timestamps between 1–23 hours ago", () => {
    const nowSec = Math.floor(Date.now() / 1000);
    expect(formatRelTime(nowSec - 7200)).toMatch(/sa önce/);
  });

  it("returns days for timestamps 1–6 days ago", () => {
    const nowSec = Math.floor(Date.now() / 1000);
    expect(formatRelTime(nowSec - 86400 * 2)).toMatch(/gün önce/);
  });

  it("returns weeks for timestamps >= 7 days ago", () => {
    const nowSec = Math.floor(Date.now() / 1000);
    expect(formatRelTime(nowSec - 86400 * 10)).toMatch(/hf önce/);
  });

  it("returns empty string for falsy input", () => {
    expect(formatRelTime(null)).toBe("");
    expect(formatRelTime(0)).toBe("");
    expect(formatRelTime(undefined)).toBe("");
  });
});

// ── renderSessionList ────────────────────────────────────────────────────────
describe("renderSessionList", () => {
  function setupDom() {
    document.body.innerHTML = `<div id="session-list"></div>`;
    _state.currentSessionId = null;
    _state.allSessions = [];
  }

  it("clears the list when given an empty array", () => {
    setupDom();
    renderSessionList([]);
    expect(document.getElementById("session-list").innerHTML).toBe("");
  });

  it("renders one item per session", () => {
    setupDom();
    const sessions = [
      { id: "s1", title: "Oturum 1", updated_at: Math.floor(Date.now() / 1000) - 30 },
      { id: "s2", title: "Oturum 2", updated_at: Math.floor(Date.now() / 1000) - 130 },
    ];
    renderSessionList(sessions);
    expect(document.querySelectorAll(".session-item")).toHaveLength(2);
  });

  it("marks the active session with the 'active' class", () => {
    setupDom();
    _state.currentSessionId = "s1";
    const sessions = [
      { id: "s1", title: "Aktif", updated_at: Math.floor(Date.now() / 1000) - 5 },
      { id: "s2", title: "Pasif", updated_at: Math.floor(Date.now() / 1000) - 5 },
    ];
    renderSessionList(sessions);
    const items = document.querySelectorAll(".session-item");
    const activeItem = [...items].find((el) => el.classList.contains("active"));
    expect(activeItem).toBeTruthy();
  });

  it("escapes HTML in session titles", () => {
    setupDom();
    renderSessionList([{ id: "x", title: "<script>bad</script>", updated_at: 0 }]);
    expect(document.getElementById("session-list").innerHTML).not.toContain("<script>");
  });
});

// ── filterSessions ────────────────────────────────────────────────────────────
describe("filterSessions", () => {
  beforeEach(() => {
    document.body.innerHTML = `<div id="session-list"></div>`;
    _state.allSessions = [
      { id: "1", title: "Python dersi", updated_at: 0 },
      { id: "2", title: "React bileşeni", updated_at: 0 },
    ];
    _state.currentSessionId = null;
  });

  it("shows all sessions for an empty query", () => {
    filterSessions("");
    expect(document.querySelectorAll(".session-item")).toHaveLength(2);
  });

  it("filters sessions by title substring (case-insensitive)", () => {
    filterSessions("python");
    expect(document.querySelectorAll(".session-item")).toHaveLength(1);
  });
});

// ── showTaskPanel / showChatPanel ────────────────────────────────────────────
describe("panel toggle helpers", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="task-panel" style="display:none"></div>
      <div id="chat-panel" style="display:flex"></div>
      <div id="input-area" tabindex="0"></div>
      <nav>
        <button id="tasks-nav-tab" class="nav-tab"></button>
        <button id="chat-nav-tab" class="nav-tab"></button>
      </nav>
    `;
  });

  it("showTaskPanel shows task-panel and hides chat-panel", () => {
    showTaskPanel();
    expect(document.getElementById("task-panel").style.display).toBe("flex");
    expect(document.getElementById("chat-panel").style.display).toBe("none");
  });

  it("showChatPanel shows chat-panel and hides task-panel", () => {
    showChatPanel();
    expect(document.getElementById("chat-panel").style.display).toBe("flex");
    expect(document.getElementById("task-panel").style.display).toBe("none");
  });
});

// ── toggleSidebar ─────────────────────────────────────────────────────────────
describe("toggleSidebar", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div class="sidebar"></div>
      <div id="sidebar-overlay"></div>
    `;
  });

  it("opens the sidebar on first call", () => {
    toggleSidebar();
    expect(document.querySelector(".sidebar").classList.contains("open")).toBe(true);
    expect(document.getElementById("sidebar-overlay").classList.contains("active")).toBe(true);
  });

  it("closes the sidebar on second call", () => {
    toggleSidebar();
    toggleSidebar();
    expect(document.querySelector(".sidebar").classList.contains("open")).toBe(false);
    expect(document.getElementById("sidebar-overlay").classList.contains("active")).toBe(false);
  });
});
