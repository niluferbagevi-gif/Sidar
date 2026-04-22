export const TOKEN_KEY = "sidar_access_token";

export function getStoredToken() {
  if (typeof localStorage === "undefined") return "";
  return (localStorage.getItem(TOKEN_KEY) || "").trim();
}

export function setStoredToken(token) {
  if (typeof localStorage === "undefined") return;
  const normalized = String(token || "").trim();
  if (normalized) {
    localStorage.setItem(TOKEN_KEY, normalized);
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
}

export function buildAuthHeaders(extraHeaders = {}) {
  const token = getStoredToken();
  return token ? { ...extraHeaders, Authorization: `Bearer ${token}` } : { ...extraHeaders };
}

export async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      ...(options.headers || {}),
      ...buildAuthHeaders(options.headers || {}),
    },
  });

  const isJson = response.headers.get("content-type")?.includes("application/json");
  const payload = isJson ? await response.json() : await response.text();

  const detail = response.ok
    ? null
    : (typeof payload === "string"
      ? payload
      : payload?.detail || payload?.error || "İstek başarısız oldu");
  if (detail !== null) {
    throw new Error(detail);
  }
  return payload;
}
