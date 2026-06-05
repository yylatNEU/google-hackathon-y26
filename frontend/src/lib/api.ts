const localApiUrls = ["http://127.0.0.1:8010", "http://127.0.0.1:8000", "http://127.0.0.1:8017"];
const defaultRequestTimeoutMs = 12000;
const transientTransportAttempts = 2;
const roleSessionTokenStorageKey = "parkpulse.roleSessionToken";
export const longRunningRequestTimeoutMs = 30000;

type ParkPulseRequestInit = RequestInit & {
  timeoutMs?: number;
};

const roleTokenCache = new Map<string, { token: string; expiresAt: number }>();
const roleTokenInflight = new Map<string, Promise<string>>();

function browserSessionStorage() {
  try {
    return typeof globalThis.sessionStorage !== "undefined" ? globalThis.sessionStorage : null;
  } catch {
    return null;
  }
}

function browserLocalStorage() {
  try {
    return typeof globalThis.localStorage !== "undefined" ? globalThis.localStorage : null;
  } catch {
    return null;
  }
}

function stripRoleTokenFromUrl() {
  if (typeof globalThis.location === "undefined" || typeof globalThis.history === "undefined") return;
  const url = new URL(globalThis.location.href);
  if (!url.searchParams.has("roleToken")) return;
  url.searchParams.delete("roleToken");
  globalThis.history.replaceState(globalThis.history.state, "", `${url.pathname}${url.search}${url.hash}`);
}

export function getParkPulseRoleSessionToken() {
  if (typeof globalThis.location !== "undefined") {
    const token = new URLSearchParams(globalThis.location.search).get("roleToken");
    if (token) {
      browserSessionStorage()?.setItem(roleSessionTokenStorageKey, token);
      browserLocalStorage()?.removeItem(roleSessionTokenStorageKey);
      stripRoleTokenFromUrl();
      return token;
    }
  }
  const sessionToken = browserSessionStorage()?.getItem(roleSessionTokenStorageKey);
  if (sessionToken) return sessionToken;
  const legacyToken = browserLocalStorage()?.getItem(roleSessionTokenStorageKey);
  if (legacyToken) {
    browserSessionStorage()?.setItem(roleSessionTokenStorageKey, legacyToken);
    browserLocalStorage()?.removeItem(roleSessionTokenStorageKey);
    return legacyToken;
  }
  return "";
}

export function setParkPulseRoleSessionToken(token: string) {
  const storage = browserSessionStorage();
  if (!storage) return;
  const normalized = token.trim();
  if (normalized) {
    storage.setItem(roleSessionTokenStorageKey, normalized);
  } else {
    storage.removeItem(roleSessionTokenStorageKey);
  }
  browserLocalStorage()?.removeItem(roleSessionTokenStorageKey);
}

export function getApiUrls(): string[] {
  const urlOverride =
    typeof globalThis.location !== "undefined"
      ? new URLSearchParams(globalThis.location.search).get("api") || undefined
      : undefined;
  if (urlOverride) return Array.from(new Set([urlOverride, ...localApiUrls]));
  const viteEnv = import.meta.env as Record<string, string | undefined> | undefined;
  const configured = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env?.NEXT_PUBLIC_API_URL;
  const sameOrigin = typeof globalThis.location !== "undefined" ? globalThis.location.origin : undefined;
  const configuredUrls = [viteEnv?.VITE_API_URL, configured].filter(Boolean) as string[];
  const localDevSameOrigin = (() => {
    if (!sameOrigin) return false;
    try {
      const url = new URL(sameOrigin);
      if (!["127.0.0.1", "localhost", "::1"].includes(url.hostname)) return false;
      return !["8010", "8000", "8017"].includes(url.port);
    } catch {
      return false;
    }
  })();
  if (localDevSameOrigin && sameOrigin) return Array.from(new Set([...localApiUrls, sameOrigin]));
  const fallbacks = [...localApiUrls, sameOrigin];
  return Array.from(new Set([...configuredUrls, ...fallbacks].filter(Boolean) as string[]));
}

function headersToEntries(headers?: HeadersInit): Array<[string, string]> {
  if (!headers) return [];
  if (typeof Headers !== "undefined" && headers instanceof Headers) return Array.from(headers.entries());
  if (Array.isArray(headers)) return headers.map(([key, value]) => [key, value]);
  return Object.entries(headers).map(([key, value]) => [key, String(value)]);
}

function headerValue(entries: Array<[string, string]>, name: string) {
  const lowered = name.toLowerCase();
  return entries.find(([key]) => key.toLowerCase() === lowered)?.[1];
}

async function getSignedRoleToken(apiUrl: string, role: string, timeoutMs: number) {
  const cacheKey = `${apiUrl}:${role}`;
  const cached = roleTokenCache.get(cacheKey);
  const nowSeconds = Math.floor(Date.now() / 1000);
  if (cached && cached.expiresAt - 30 > nowSeconds) return cached.token;

  roleTokenInflight.delete(cacheKey);

  const tokenPromise = (async () => {
    const response = await request(
      `${apiUrl}/api/park/auth/dev-session`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ role, subject: "parkpulse-browser-command-center" }),
      },
      Math.min(timeoutMs, 5000),
    );
    if (!response.ok) throw new Error(`${apiUrl}/api/park/auth/dev-session returned ${response.status}`);
    const payload = (await response.json()) as { token?: string; expires_at?: number };
    if (!payload.token) throw new Error("ParkPulse role session issuer did not return a token.");
    roleTokenCache.set(cacheKey, {
      token: payload.token,
      expiresAt: Number(payload.expires_at ?? Math.floor(Date.now() / 1000) + 300),
    });
    return payload.token;
  })();
  roleTokenInflight.set(cacheKey, tokenPromise);
  try {
    return await tokenPromise;
  } finally {
    roleTokenInflight.delete(cacheKey);
  }
}

async function getOptionalSignedRoleToken(apiUrl: string, role: string, timeoutMs: number) {
  try {
    return await getSignedRoleToken(apiUrl, role, timeoutMs);
  } catch {
    return undefined;
  }
}

function requestWithXhr(url: string, init?: RequestInit, timeoutMs = defaultRequestTimeoutMs): Promise<Response> {
  if (typeof XMLHttpRequest === "undefined") {
    return Promise.reject(new Error("No browser request transport is available."));
  }

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(init?.method ?? "GET", url, true);
    xhr.timeout = timeoutMs;

    for (const [key, value] of headersToEntries(init?.headers)) {
      xhr.setRequestHeader(key, value);
    }

    xhr.onload = () => {
      const contentType = xhr.getResponseHeader("content-type");
      const response = {
        ok: xhr.status >= 200 && xhr.status < 300,
        status: xhr.status,
        headers: { get: (name: string) => name.toLowerCase() === "content-type" ? contentType : null },
        json: async () => JSON.parse(xhr.responseText || "null"),
        text: async () => xhr.responseText,
      } as Response;
      resolve(response);
    };
    xhr.onerror = () => reject(new Error(`XHR failed for ${url}`));
    xhr.ontimeout = () => reject(new Error(`XHR timed out for ${url}`));
    xhr.send((init?.body as XMLHttpRequestBodyInit | null | undefined) ?? null);
  });
}

function request(url: string, init?: RequestInit, timeoutMs = defaultRequestTimeoutMs) {
  if (url.includes("/api/park/staff-training") || url.includes("/api/park/auth/dev-session")) {
    return requestWithXhr(url, init, timeoutMs);
  }
  if (typeof globalThis.fetch === "function" && typeof globalThis.AbortController === "function") {
    const controller = new AbortController();
    const timeout = globalThis.setTimeout(() => {
      controller.abort(new Error(`ParkPulse API request timed out after ${Math.round(timeoutMs / 1000)}s.`));
    }, timeoutMs);
    const inputSignal = init?.signal;
    const abortFromInput = () => controller.abort(inputSignal?.reason);
    inputSignal?.addEventListener("abort", abortFromInput, { once: true });

    return globalThis.fetch(url, { ...init, signal: controller.signal }).finally(() => {
      globalThis.clearTimeout(timeout);
      inputSignal?.removeEventListener("abort", abortFromInput);
    });
  }
  return requestWithXhr(url, init, timeoutMs);
}

function isTransportError(error: Error) {
  return (
    error.name === "AbortError" ||
    error.message.includes("Failed to fetch") ||
    error.message.includes("Load failed") ||
    error.message.includes("NetworkError") ||
    error.message.includes("XHR failed") ||
    error.message.includes("timed out")
  );
}

function responseContentType(response: Response) {
  try {
    return response.headers?.get("content-type") ?? "";
  } catch {
    return "";
  }
}

function normalizeParkPulseApiError(error: unknown, path: string) {
  if (error instanceof Error) {
    if (isTransportError(error)) {
      const urls = getApiUrls().join(", ") || "the configured API URL";
      return new Error(`ParkPulse API did not respond for ${path} within the request budget. Checked ${urls}.`);
    }
    return error;
  }
  return new Error(`Unable to reach ParkPulse API at ${path}`);
}

export async function fetchParkPulseApi(path: string, init?: ParkPulseRequestInit) {
  let lastError: unknown;
  const { timeoutMs = defaultRequestTimeoutMs, ...requestInit } = init ?? {};
  const method = String(requestInit.method ?? "GET").toUpperCase();
  const maxAttempts = method === "GET" || method === "HEAD" ? transientTransportAttempts : 1;

  for (const apiUrl of getApiUrls()) {
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      try {
        const headerEntries = headersToEntries(requestInit.headers);
        const requestedRole = headerValue(headerEntries, "x-parkpulse-role");
        const hasAuthorization = Boolean(headerValue(headerEntries, "authorization"));
        const hasRoleToken = Boolean(headerValue(headerEntries, "x-parkpulse-role-token"));
        const storedRoleToken = !hasAuthorization && !hasRoleToken && path !== "/api/park/auth/dev-session" ? getParkPulseRoleSessionToken() : "";
        const token =
          requestedRole && !hasAuthorization && !hasRoleToken && !storedRoleToken && path !== "/api/park/auth/dev-session"
            ? await getOptionalSignedRoleToken(apiUrl, requestedRole, timeoutMs)
            : undefined;
        const roleToken = storedRoleToken || token || "";
        const signedHeaders = roleToken ? { ...Object.fromEntries(headerEntries), "x-parkpulse-role-token": roleToken } : requestInit.headers;
        const response = await request(`${apiUrl}${path}`, { ...requestInit, headers: signedHeaders }, timeoutMs);
        if (response.ok) {
          const contentType = responseContentType(response).toLowerCase();
          if (path.startsWith("/api/") && contentType.includes("text/html")) {
            lastError = new Error(`${apiUrl}${path} returned HTML instead of API JSON`);
            break;
          }
          return response;
        }
        lastError = new Error(`${apiUrl}${path} returned ${response.status}`);
        break;
      } catch (error) {
        lastError = error;
        if (!(error instanceof Error) || !isTransportError(error) || attempt >= maxAttempts) {
          break;
        }
      }
    }
  }

  throw normalizeParkPulseApiError(lastError, path);
}
