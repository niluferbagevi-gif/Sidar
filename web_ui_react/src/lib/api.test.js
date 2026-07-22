import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  TOKEN_KEY,
  TOKEN_CHANGE_EVENT,
  TOKEN_STORAGE_MODE_KEY,
  getStoredToken,
  setStoredToken,
  clearStoredToken,
  getTokenPrincipal,
  getCurrentUser,
  buildAuthHeaders,
  fetchJson,
  DEFAULT_FETCH_TIMEOUT_MS,
  runPoyrazOperation,
  generateLandingPage,
  generateCampaignCopy,
  planServiceOperations,
  listCoverageTasks,
  analyzeCoverage,
  generateCoverageCandidate,
  runCoverageBatch,
  listHitlPending,
  respondHitl,
} from "./api.js";

const mockFetch = (response) => {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
};

// localStorage stub — her testten önce temizlenir
beforeEach(() => {
  setStoredToken("");
  localStorage.clear();
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("TOKEN_KEY sabiti", () => {
  it("is sidar_access_token", () => {
    expect(TOKEN_KEY).toBe("sidar_access_token");
  });

});

describe("getStoredToken", () => {
  it("returns empty string when no token stored", () => {
    expect(getStoredToken()).toBe("");
  });

  it("returns stored token", () => {
    localStorage.setItem(TOKEN_STORAGE_MODE_KEY, "local");
    localStorage.setItem(TOKEN_KEY, "test-bearer-token");
    expect(getStoredToken()).toBe("test-bearer-token");
  });

  it("trims whitespace from stored token", () => {
    localStorage.setItem(TOKEN_STORAGE_MODE_KEY, "local");
    localStorage.setItem(TOKEN_KEY, "  trimmed-token  ");
    expect(getStoredToken()).toBe("trimmed-token");
  });

  it("returns empty string for whitespace-only value", () => {
    localStorage.setItem(TOKEN_STORAGE_MODE_KEY, "local");
    localStorage.setItem(TOKEN_KEY, "   ");
    expect(getStoredToken()).toBe("");
  });
});

describe("setStoredToken", () => {
  it("stores a valid token in memory by default", () => {
    setStoredToken("yeni-token");
    expect(getStoredToken()).toBe("yeni-token");
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it("removes the key when empty string provided", () => {
    localStorage.setItem(TOKEN_KEY, "önceki");
    setStoredToken("");
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it("removes the key when null provided", () => {
    localStorage.setItem(TOKEN_KEY, "önceki");
    setStoredToken(null);
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it("removes the key when whitespace-only provided", () => {
    localStorage.setItem(TOKEN_KEY, "önceki");
    setStoredToken("   ");
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it("trims token before storing", () => {
    setStoredToken("  trimmed  ");
    expect(getStoredToken()).toBe("trimmed");
  });

  it("persists to localStorage only when explicitly requested", () => {
    setStoredToken("  persisted  ", { persist: true });
    expect(localStorage.getItem(TOKEN_KEY)).toBe("persisted");
    expect(localStorage.getItem(TOKEN_STORAGE_MODE_KEY)).toBe("local");
  });

  it("notifies listeners when the normalized token changes", () => {
    const listener = vi.fn();
    window.addEventListener(TOKEN_CHANGE_EVENT, listener);
    try {
      setStoredToken("yeni-token");
      expect(listener).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener(TOKEN_CHANGE_EVENT, listener);
    }
  });

  it("does not notify listeners when the normalized token stays the same", () => {
    setStoredToken("aynı-token");
    const listener = vi.fn();
    window.addEventListener(TOKEN_CHANGE_EVENT, listener);
    try {
      setStoredToken("  aynı-token  ");
      expect(listener).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener(TOKEN_CHANGE_EVENT, listener);
    }
  });

  it("clearStoredToken removes the active token", () => {
    setStoredToken("active-token");

    clearStoredToken();

    expect(getStoredToken()).toBe("");
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });

});

describe("api.js localStorage checks", () => {
  it("handles missing localStorage gracefully", () => {
    const originalDescriptor = Object.getOwnPropertyDescriptor(globalThis, "localStorage");

    Object.defineProperty(globalThis, "localStorage", {
      value: undefined,
      configurable: true,
      writable: true,
    });

    try {
      expect(getStoredToken()).toBe("");
      expect(() => setStoredToken("test-token")).not.toThrow();
    } finally {
      if (originalDescriptor) {
        Object.defineProperty(globalThis, "localStorage", originalDescriptor);
      } else {
        delete globalThis.localStorage;
      }
    }
  });

  it("tolerates localStorage access errors", () => {
    const originalDescriptor = Object.getOwnPropertyDescriptor(globalThis, "localStorage");

    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      get() {
        throw new Error("storage denied");
      },
    });

    try {
      expect(getStoredToken()).toBe("");
      expect(() => setStoredToken("fallback-token")).not.toThrow();
      expect(getStoredToken()).toBe("fallback-token");
    } finally {
      if (originalDescriptor) {
        Object.defineProperty(globalThis, "localStorage", originalDescriptor);
      } else {
        delete globalThis.localStorage;
      }
    }
  });

});

describe("buildAuthHeaders", () => {
  it("returns Authorization header when token exists", () => {
    setStoredToken("my-token");
    const headers = buildAuthHeaders();
    expect(headers).toEqual({ Authorization: "Bearer my-token" });
  });

  it("returns empty object when no token", () => {
    const headers = buildAuthHeaders();
    expect(headers).toEqual({});
  });

  it("merges extra headers when token exists", () => {
    setStoredToken("tok");
    const headers = buildAuthHeaders({ "Content-Type": "application/json" });
    expect(headers["Authorization"]).toBe("Bearer tok");
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("returns only extra headers when no token", () => {
    const headers = buildAuthHeaders({ "X-Custom": "değer" });
    expect(headers).toEqual({ "X-Custom": "değer" });
    expect(headers["Authorization"]).toBeUndefined();
  });

  it("does not mutate extraHeaders argument", () => {
    setStoredToken("tok");
    const extra = { "X-Foo": "bar" };
    buildAuthHeaders(extra);
    expect(extra).toEqual({ "X-Foo": "bar" });
  });
});

describe("getTokenPrincipal", () => {
  const makeJwt = (payload) => {
    const encodedPayload = btoa(JSON.stringify(payload))
      .replace(/=/g, "")
      .replace(/\+/g, "-")
      .replace(/\//g, "_");
    return `e30.${encodedPayload}.sig`;
  };

  it("returns null on invalid JWT payloads", () => {
    expect(getTokenPrincipal("header.not-json.signature")).toBeNull();
  });

  it("parses sub, username, role, tenant_id and exp from a valid JWT payload", () => {
    const payload = { sub: "42", username: "demo", role: "Admin", tenant_id: "t1", exp: 999 };

    expect(getTokenPrincipal(makeJwt(payload))).toEqual({
      id: "42",
      username: "demo",
      role: "admin",
      tenant_id: "t1",
      exp: 999,
    });
  });

  it("falls back to payload id and default user metadata when optional claims are missing", () => {
    expect(getTokenPrincipal(makeJwt({ id: "99" }))).toMatchObject({
      id: "99",
      username: "",
      role: "user",
      tenant_id: "default",
      exp: 0,
    });
    expect(getTokenPrincipal(makeJwt({}))).toMatchObject({ id: "", role: "user" });
  });
});


describe("fetchJson — başarılı JSON yanıtı", () => {
  it("returns parsed JSON for 200 response", async () => {
    mockFetch({
      ok: true,
      headers: { get: () => "application/json" },
      json: async () => ({ result: "tamam" }),
    });

    const data = await fetchJson("/api/test");
    expect(data).toEqual({ result: "tamam" });
  });

  it("includes Authorization header in request", async () => {
    setStoredToken("test-tok");
    const fetchMock = mockFetch({
      ok: true,
      headers: { get: () => "application/json" },
      json: async () => ({}),
    });

    await fetchJson("/api/secure");
    const [, options] = fetchMock.mock.calls[0];
    // Bearer token is the only auth model — no cookie-based credentials
    // should ever be requested alongside it (see fetchJson's comment).
    expect(options.credentials).toBeUndefined();
    expect(options.headers["Authorization"]).toBe("Bearer test-tok");
  });

  it("returns text for non-JSON content-type", async () => {
    mockFetch({
      ok: true,
      headers: { get: () => "text/plain" },
      text: async () => "düz metin yanıt",
    });

    const data = await fetchJson("/api/text");
    expect(data).toBe("düz metin yanıt");
  });
});

describe("fetchJson — hata yanıtları", () => {
  it("throws error with detail message for 400+ responses with JSON", async () => {
    mockFetch({
      ok: false,
      status: 400,
      headers: { get: () => "application/json" },
      json: async () => ({ detail: "Geçersiz istek" }),
    });

    await expect(fetchJson("/api/fail")).rejects.toThrow("Geçersiz istek");
  });

  it("throws error with error field from JSON payload", async () => {
    mockFetch({
      ok: false,
      status: 401,
      headers: { get: () => "application/json" },
      json: async () => ({ error: "Yetkisiz erişim" }),
    });

    await expect(fetchJson("/api/auth")).rejects.toThrow("Yetkisiz erişim");
  });

  it("throws error with text body when response is not JSON", async () => {
    mockFetch({
      ok: false,
      status: 500,
      headers: { get: () => "text/html" },
      text: async () => "Sunucu hatası",
    });

    await expect(fetchJson("/api/server-error")).rejects.toThrow("Sunucu hatası");
  });

  it("throws default message when no detail or error field", async () => {
    mockFetch({
      ok: false,
      status: 422,
      headers: { get: () => "application/json" },
      json: async () => ({}),
    });

    await expect(fetchJson("/api/unprocessable")).rejects.toThrow("İstek başarısız oldu");
  });

  it("passes custom options to fetch", async () => {
    const fetchMock = mockFetch({
      ok: true,
      headers: { get: () => "application/json" },
      json: async () => ({}),
    });

    await fetchJson("/api/post", { method: "POST", body: JSON.stringify({ key: "val" }) });
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/post");
    expect(options.method).toBe("POST");
    expect(options.body).toBe(JSON.stringify({ key: "val" }));
  });

  it("propagates errors thrown while reading response.ok", async () => {
    const response = {
      headers: { get: () => "application/json" },
      json: async () => ({ detail: "ignored" }),
    };

    Object.defineProperty(response, "ok", {
      get() {
        throw new Error("ok değeri okunamadı");
      },
    });

    mockFetch(response);
    await expect(fetchJson("/api/broken-response")).rejects.toThrow("ok değeri okunamadı");
  });

  it("passes an AbortSignal to fetch so requests can be cancelled", async () => {
    const fetchMock = mockFetch({
      ok: true,
      headers: { get: () => "application/json" },
      json: async () => ({}),
    });

    await fetchJson("/api/test");
    const [, options] = fetchMock.mock.calls[0];
    expect(options.signal).toBeInstanceOf(AbortSignal);
  });
});

describe("fetchJson — timeout & cancellation", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // Gerçek fetch, signal abort edildiğinde AbortError ile reddeder; testte
  // backend'in hiç yanıt vermediği (isteğin sonsuza kadar askıda kaldığı)
  // durumu simüle etmek için bu davranışı taklit ediyoruz.
  function abortError() {
    const err = new Error("The operation was aborted.");
    err.name = "AbortError";
    return err;
  }

  function mockAbortAwareFetch() {
    const fetchMock = vi.fn((_url, opts) => {
      // Real fetch rejects synchronously (checking signal.aborted) when given
      // an already-aborted signal, instead of waiting for a future event.
      if (opts?.signal?.aborted) {
        return Promise.reject(abortError());
      }
      return new Promise((_resolve, reject) => {
        opts?.signal?.addEventListener("abort", () => reject(abortError()));
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("rejects with a clear timeout error instead of hanging forever", async () => {
    mockAbortAwareFetch();

    const pending = fetchJson("/api/hangs-forever");
    const assertion = expect(pending).rejects.toThrow(/zaman aşımına uğradı/);
    await vi.advanceTimersByTimeAsync(DEFAULT_FETCH_TIMEOUT_MS);
    await assertion;
  });

  it("honors a custom timeoutMs option", async () => {
    mockAbortAwareFetch();

    const pending = fetchJson("/api/slow", { timeoutMs: 5000 });
    const assertion = expect(pending).rejects.toThrow(/zaman aşımına uğradı \(5000ms\)/);
    await vi.advanceTimersByTimeAsync(5000);
    await assertion;
  });

  it("does not time out when timeoutMs is disabled", async () => {
    mockFetch({
      ok: true,
      headers: { get: () => "application/json" },
      json: async () => ({ ok: true }),
    });

    const data = await fetchJson("/api/no-timeout", { timeoutMs: 0 });
    expect(data).toEqual({ ok: true });
  });

  it("propagates an externally supplied AbortSignal's cancellation (e.g. component unmount)", async () => {
    mockAbortAwareFetch();
    const externalController = new AbortController();

    const pending = fetchJson("/api/cancel-me", { signal: externalController.signal });
    const assertion = expect(pending).rejects.toMatchObject({ name: "AbortError" });
    externalController.abort();
    await assertion;
    // External cancellation must not be reworded as a timeout error.
    await expect(pending).rejects.not.toThrow(/zaman aşımına uğradı/);
  });

  it("aborts immediately when an already-aborted signal is passed in", async () => {
    mockAbortAwareFetch();
    const externalController = new AbortController();
    externalController.abort();

    await expect(
      fetchJson("/api/already-cancelled", { signal: externalController.signal }),
    ).rejects.toMatchObject({ name: "AbortError" });
  });
});


describe("agent API bridge helpers", () => {
  function mockJsonFetch() {
    return mockFetch({
      ok: true,
      headers: { get: () => "application/json" },
      json: async () => ({ success: true }),
    });
  }



  it("gets the current authenticated user", async () => {
    const fetchMock = mockJsonFetch();

    await getCurrentUser();

    expect(fetchMock).toHaveBeenCalledWith("/auth/me", expect.objectContaining({ headers: {} }));
  });

  it("posts Poyraz operation payloads to operation endpoints", async () => {
    const fetchMock = mockJsonFetch();

    await runPoyrazOperation("create_operation_checklist", { title: "Todo" });
    await generateLandingPage({ brand_name: "Sidar" });
    await generateCampaignCopy({ campaign_name: "Launch" });
    await planServiceOperations({ campaign_name: "Launch" });

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/operations/poyraz/run",
      "/api/operations/landing-page",
      "/api/operations/campaign-copy",
      "/api/operations/service-plan",
    ]);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      tool_name: "create_operation_checklist",
      payload: { title: "Todo" },
      room_id: "ops:control",
    });
    for (const [, options] of fetchMock.mock.calls) {
      expect(options.method).toBe("POST");
      expect(options.headers["Content-Type"]).toBe("application/json");
    }
  });

  it("uses QA coverage REST endpoints", async () => {
    const fetchMock = mockJsonFetch();

    await listCoverageTasks({ status: "tests_written", limit: 5 });
    await analyzeCoverage({ limit: 3 });
    await generateCoverageCandidate({ coverage_finding: { target_path: "src/a.py" } });
    await runCoverageBatch({ limit: 2 });

    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/qa/coverage/tasks?status=tests_written&limit=5",
    );
    expect(fetchMock.mock.calls.slice(1).map(([url]) => url)).toEqual([
      "/api/qa/coverage/analyze",
      "/api/qa/coverage/generate",
      "/api/qa/coverage/batch",
    ]);
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ limit: 3 });
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({
      coverage_finding: { target_path: "src/a.py" },
    });
    expect(JSON.parse(fetchMock.mock.calls[3][1].body)).toEqual({ limit: 2 });
  });

  it("uses HITL REST endpoints", async () => {
    const fetchMock = mockJsonFetch();

    await listHitlPending();
    await respondHitl("req/1", { approved: true, decided_by: "tester" });

    expect(fetchMock.mock.calls[0][0]).toBe("/api/hitl/pending");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/hitl/respond/req%2F1");
    expect(fetchMock.mock.calls[1][1].method).toBe("POST");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      approved: true,
      decided_by: "tester",
    });
  });

  it("serializes default empty operation payloads", async () => {
    const fetchMock = mockJsonFetch();

    await generateLandingPage();
    await generateCampaignCopy();
    await planServiceOperations();

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/operations/landing-page",
      "/api/operations/campaign-copy",
      "/api/operations/service-plan",
    ]);
    for (const [, options] of fetchMock.mock.calls) {
      expect(options.method).toBe("POST");
      expect(JSON.parse(options.body)).toEqual({});
    }
  });

  it("omits QA coverage query string when filters are absent", async () => {
    const fetchMock = mockJsonFetch();

    await listCoverageTasks();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/qa/coverage/tasks",
      expect.objectContaining({ headers: {} }),
    );
  });

  it("serializes default empty HITL response payload", async () => {
    const fetchMock = mockJsonFetch();

    await respondHitl("req-empty");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/hitl/respond/req-empty");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({});
  });

  it("serializes null HITL response payload as an empty object", async () => {
    const fetchMock = mockJsonFetch();

    await respondHitl("req-null", null);

    expect(fetchMock.mock.calls[0][0]).toBe("/api/hitl/respond/req-null");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({});
  });
});
