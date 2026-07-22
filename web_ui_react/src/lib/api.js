export const TOKEN_KEY = "sidar_access_token";
export const TOKEN_CHANGE_EVENT = "sidar:token-change";
export const TOKEN_STORAGE_MODE_KEY = "sidar_token_storage_mode";

let inMemoryToken = "";

function getBrowserStorage(kind = "localStorage") {
  /* c8 ignore next -- Defensive SSR guard for runtimes without globalThis. */
  if (typeof globalThis === "undefined") return null;
  try {
    return globalThis[kind] || null;
  } catch {
    return null;
  }
}

function getTokenStorageMode() {
  const storage = getBrowserStorage("localStorage");
  return storage?.getItem(TOKEN_STORAGE_MODE_KEY) === "local" ? "local" : "memory";
}

function notifyTokenChange(previousToken, normalized) {
  if (previousToken !== normalized && typeof window !== "undefined") {
    window.dispatchEvent(new Event(TOKEN_CHANGE_EVENT));
  }
}

function readLegacyLocalToken() {
  const storage = getBrowserStorage("localStorage");
  return (storage?.getItem(TOKEN_KEY) || "").trim();
}

export function getStoredToken() {
  if (inMemoryToken) return inMemoryToken.trim();
  if (getTokenStorageMode() !== "local") return "";
  return readLegacyLocalToken();
}

export function setStoredToken(token, options = {}) {
  const previousToken = getStoredToken();
  const normalized = String(token || "").trim();
  const persist = options.persist === true;
  const localStorageRef = getBrowserStorage("localStorage");

  inMemoryToken = normalized;
  if (localStorageRef) {
    if (persist && normalized) {
      localStorageRef.setItem(TOKEN_KEY, normalized);
      localStorageRef.setItem(TOKEN_STORAGE_MODE_KEY, "local");
    } else {
      localStorageRef.removeItem(TOKEN_KEY);
      localStorageRef.setItem(TOKEN_STORAGE_MODE_KEY, "memory");
    }
  }
  notifyTokenChange(previousToken, normalized);
}

export function clearStoredToken() {
  setStoredToken("");
}

export function getTokenPrincipal(token = getStoredToken()) {
  const parts = String(token || "").split(".");
  if (parts.length < 2) return null;
  try {
    const base64Payload = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const paddedPayload = base64Payload.padEnd(base64Payload.length + ((4 - (base64Payload.length % 4)) % 4), "=");
    const payload = JSON.parse(atob(paddedPayload));
    return {
      id: String(payload.sub || payload.id || ""),
      username: String(payload.username || ""),
      role: String(payload.role || "user").toLowerCase(),
      tenant_id: String(payload.tenant_id || "default"),
      exp: Number(payload.exp || 0),
    };
  } catch {
    return null;
  }
}

export function isAdminPrincipal(principal) {
  const role = String(principal?.role || "").toLowerCase();
  const username = String(principal?.username || "");
  return role === "admin" || username === "default_admin";
}

export function buildAuthHeaders(extraHeaders = {}) {
  const token = getStoredToken();
  return token ? { ...extraHeaders, Authorization: `Bearer ${token}` } : { ...extraHeaders };
}

// Backend yanıt vermezse (ör. asılı bağlantı, kesilen tünel) çağıran hiçbir
// zaman fetchJson'dan geri dönüş almazdı — Promise sonsuza kadar askıda
// kalırdı. Her istek artık varsayılan olarak zaman aşımına uğrar.
export const DEFAULT_FETCH_TIMEOUT_MS = 30000;

export async function fetchJson(url, options = {}) {
  const { signal: externalSignal, timeoutMs = DEFAULT_FETCH_TIMEOUT_MS, ...fetchOptions } = options;

  // Dahili AbortController hem varsayılan zaman aşımını hem de çağıranın
  // kendi signal'ını (ör. component unmount'ta iptal) tek bir kontrolcüde
  // birleştirir; `AbortSignal.any` henüz her hedef tarayıcıda garanti
  // olmadığından elle kompoze ediyoruz.
  const controller = new AbortController();
  let timedOut = false;
  const timeoutId =
    timeoutMs > 0
      ? setTimeout(() => {
          timedOut = true;
          controller.abort();
        }, timeoutMs)
      : null;

  const onExternalAbort = () => controller.abort();
  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort();
    } else {
      externalSignal.addEventListener("abort", onExternalAbort, { once: true });
    }
  }

  try {
    // Bearer token (Authorization header) is the only auth model this backend
    // uses — it never sets or reads cookies (no Set-Cookie anywhere in the
    // API). Requesting `credentials: "include"` anyway would needlessly widen
    // the CSRF surface by asking the browser to also send whatever cookies
    // exist for this origin (including any future/unrelated ones) on every
    // request, mixing two authentication models for no benefit.
    const response = await fetch(url, {
      ...fetchOptions,
      signal: controller.signal,
      headers: {
        ...(fetchOptions.headers || {}),
        ...buildAuthHeaders(fetchOptions.headers || {}),
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
  } catch (err) {
    if (err?.name === "AbortError" && timedOut) {
      throw new Error(`İstek zaman aşımına uğradı (${timeoutMs}ms): ${url}`);
    }
    // AbortError'ın diğer nedeni (çağıranın kendi signal'ı, ör. unmount)
    // olduğu gibi yeniden fırlatılır; çağıran bunu kendi iptal mantığıyla ele alır.
    throw err;
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
    if (externalSignal) externalSignal.removeEventListener("abort", onExternalAbort);
  }
}

export function getCurrentUser() {
  return fetchJson("/auth/me");
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
