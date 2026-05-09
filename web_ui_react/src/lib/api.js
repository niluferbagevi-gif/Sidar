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

export function runPoyrazOperation(toolName, payload = {}, roomId = "ops:control") {
  return fetchJson("/api/operations/poyraz/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tool_name: toolName, payload, room_id: roomId }),
  });
}

export function generateLandingPage(payload) {
  return fetchJson("/api/operations/landing-page", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
}

export function generateCampaignCopy(payload) {
  return fetchJson("/api/operations/campaign-copy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
}

export function planServiceOperations(payload) {
  return fetchJson("/api/operations/service-plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
}

export function listCoverageTasks(params = {}) {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.limit) query.set("limit", String(params.limit));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return fetchJson(`/api/qa/coverage/tasks${suffix}`);
}

export function analyzeCoverage(payload = {}) {
  return fetchJson("/api/qa/coverage/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function generateCoverageCandidate(payload = {}) {
  return fetchJson("/api/qa/coverage/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function runCoverageBatch(payload = {}) {
  return fetchJson("/api/qa/coverage/batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function listHitlPending() {
  return fetchJson("/api/hitl/pending");
}

export function respondHitl(requestId, payload = {}) {
  return fetchJson(`/api/hitl/respond/${encodeURIComponent(requestId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
}
