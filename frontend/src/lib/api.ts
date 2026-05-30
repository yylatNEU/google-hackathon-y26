const localApiUrls = ["http://127.0.0.1:8000"];
const defaultRequestTimeoutMs = 12000;
export const longRunningRequestTimeoutMs = 30000;

type ParkPulseRequestInit = RequestInit & {
  timeoutMs?: number;
};

export function getApiUrls() {
  const urlOverride =
    typeof globalThis.location !== "undefined"
      ? new URLSearchParams(globalThis.location.search).get("api") || undefined
      : undefined;
  if (urlOverride) return [urlOverride];
  const viteEnv = import.meta.env as Record<string, string | undefined> | undefined;
  const configured = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env?.NEXT_PUBLIC_API_URL;
  const sameOrigin = typeof globalThis.location !== "undefined" ? globalThis.location.origin : undefined;
  const configuredUrls = [viteEnv?.VITE_API_URL, configured].filter(Boolean) as string[];
  if (configuredUrls.length) return Array.from(new Set(configuredUrls));
  return Array.from(new Set([...localApiUrls, sameOrigin].filter(Boolean) as string[]));
}

function headersToEntries(headers?: HeadersInit): Array<[string, string]> {
  if (!headers) return [];
  if (typeof Headers !== "undefined" && headers instanceof Headers) return Array.from(headers.entries());
  if (Array.isArray(headers)) return headers.map(([key, value]) => [key, value]);
  return Object.entries(headers).map(([key, value]) => [key, String(value)]);
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
      const response = {
        ok: xhr.status >= 200 && xhr.status < 300,
        status: xhr.status,
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
  if (typeof globalThis.fetch === "function") {
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

  for (const apiUrl of getApiUrls()) {
    try {
      const response = await request(`${apiUrl}${path}`, requestInit, timeoutMs);
      if (response.ok) {
        return response;
      }
      lastError = new Error(`${apiUrl}${path} returned ${response.status}`);
    } catch (error) {
      lastError = error;
    }
  }

  throw normalizeParkPulseApiError(lastError, path);
}
