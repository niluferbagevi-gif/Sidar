/**
 * Tests for web_ui/rag.js — modal helpers and ragShowResult.
 *
 * The file contains pure DOM-manipulation helpers that are safe to test in
 * jsdom without a real server.  Async functions that call fetchAPI are
 * exercised only at the surface level (no-throw under stub conditions).
 */

// Stub window.fetchAPI so async calls resolve immediately without a network
window.fetchAPI = vi.fn().mockResolvedValue({
  json: async () => ({ success: true, docs: [], message: "ok" }),
});
window.escHtml = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

import "../../../web_ui/rag.js";

function buildRagDom() {
  document.body.innerHTML = `
    <div id="rag-modal"></div>
    <div class="rag-tab" data-tab="belgeler"></div>
    <div class="rag-tab" data-tab="ekle"></div>
    <div class="rag-pane" data-pane="belgeler"></div>
    <div class="rag-pane" data-pane="ekle"></div>
    <div id="rag-doc-list"></div>
    <input id="rag-filter" value="" />
    <input id="rag-file-path" value="" />
    <input id="rag-file-title" value="" />
    <button id="rag-add-file-btn">Ekle</button>
    <input id="rag-url-input" value="" />
    <input id="rag-url-title" value="" />
    <button id="rag-add-url-btn">Ekle</button>
    <input id="rag-search-q" value="" />
    <div id="rag-search-out"></div>
    <div id="rag-add-result" style="display:none"></div>
    <div id="rag-del-result" style="display:none"></div>
  `;
}

describe("openRagModal / closeRagModal", () => {
  beforeEach(buildRagDom);

  it("adds the 'open' class when opening", () => {
    openRagModal();
    expect(document.getElementById("rag-modal").classList.contains("open")).toBe(true);
  });

  it("removes the 'open' class when closing", () => {
    openRagModal();
    closeRagModal();
    expect(document.getElementById("rag-modal").classList.contains("open")).toBe(false);
  });
});

describe("ragTab", () => {
  beforeEach(buildRagDom);

  it("marks the chosen tab active and unmarcks the others", () => {
    ragTab("ekle");
    const tabs = document.querySelectorAll(".rag-tab");
    const activeTab = [...tabs].find((t) => t.classList.contains("active"));
    expect(activeTab?.dataset.tab).toBe("ekle");
  });

  it("marks the matching pane active", () => {
    ragTab("belgeler");
    const panes = document.querySelectorAll(".rag-pane");
    const activePane = [...panes].find((p) => p.classList.contains("active"));
    expect(activePane?.dataset.pane).toBe("belgeler");
  });
});

describe("ragShowResult", () => {
  beforeEach(buildRagDom);

  it("shows a success message with class 'ok'", () => {
    ragShowResult("rag-add-result", true, "Başarılı");
    const el = document.getElementById("rag-add-result");
    expect(el.style.display).toBe("block");
    expect(el.classList.contains("ok")).toBe(true);
    expect(el.textContent).toBe("Başarılı");
  });

  it("shows an error message with class 'err'", () => {
    ragShowResult("rag-add-result", false, "Hata oluştu");
    const el = document.getElementById("rag-add-result");
    expect(el.classList.contains("err")).toBe(true);
    expect(el.textContent).toBe("Hata oluştu");
  });

  it("silently does nothing for a missing element id", () => {
    expect(() => ragShowResult("__does_not_exist__", true, "x")).not.toThrow();
  });
});

describe("ragAddFile — validation", () => {
  beforeEach(buildRagDom);

  it("shows an error when the file path is empty", async () => {
    document.getElementById("rag-file-path").value = "";
    await ragAddFile();
    const el = document.getElementById("rag-add-result");
    expect(el.classList.contains("err")).toBe(true);
  });
});

describe("ragAddUrl — validation", () => {
  beforeEach(buildRagDom);

  it("shows an error when the URL is empty", async () => {
    document.getElementById("rag-url-input").value = "";
    await ragAddUrl();
    const el = document.getElementById("rag-add-result");
    expect(el.classList.contains("err")).toBe(true);
  });
});
