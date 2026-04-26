import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  TOKEN_KEY,
  getStoredToken,
  setStoredToken,
  buildAuthHeaders,
  fetchJson,
} from "./api.js";

const mockFetch = (response) => {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
};

// localStorage stub — her testten önce temizlenir
beforeEach(() => {
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
    localStorage.setItem(TOKEN_KEY, "test-bearer-token");
    expect(getStoredToken()).toBe("test-bearer-token");
  });

  it("trims whitespace from stored token", () => {
    localStorage.setItem(TOKEN_KEY, "  trimmed-token  ");
    expect(getStoredToken()).toBe("trimmed-token");
  });

  it("returns empty string for whitespace-only value", () => {
    localStorage.setItem(TOKEN_KEY, "   ");
    expect(getStoredToken()).toBe("");
  });
});

describe("setStoredToken", () => {
  it("stores a valid token in localStorage", () => {
    setStoredToken("yeni-token");
    expect(localStorage.getItem(TOKEN_KEY)).toBe("yeni-token");
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
    expect(localStorage.getItem(TOKEN_KEY)).toBe("trimmed");
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
});

describe("buildAuthHeaders", () => {
  it("returns Authorization header when token exists", () => {
    localStorage.setItem(TOKEN_KEY, "my-token");
    const headers = buildAuthHeaders();
    expect(headers).toEqual({ Authorization: "Bearer my-token" });
  });

  it("returns empty object when no token", () => {
    const headers = buildAuthHeaders();
    expect(headers).toEqual({});
  });

  it("merges extra headers when token exists", () => {
    localStorage.setItem(TOKEN_KEY, "tok");
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
    localStorage.setItem(TOKEN_KEY, "tok");
    const extra = { "X-Foo": "bar" };
    buildAuthHeaders(extra);
    expect(extra).toEqual({ "X-Foo": "bar" });
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
    localStorage.setItem(TOKEN_KEY, "test-tok");
    const fetchMock = mockFetch({
      ok: true,
      headers: { get: () => "application/json" },
      json: async () => ({}),
    });

    await fetchJson("/api/secure");
    const [, options] = fetchMock.mock.calls[0];
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
});
