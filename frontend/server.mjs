import { Buffer } from "node:buffer";
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));
const distDir = resolve(__dirname, "dist");
const port = Number(process.env.PORT || 3000);
const apiBaseUrl = (process.env.PARKPULSE_API_URL || "").replace(/\/$/, "");
const apiIdentityAudience = (process.env.PARKPULSE_API_IDENTITY_AUDIENCE || apiBaseUrl).replace(/\/$/, "");
const roleSessionIssuerKey = (process.env.PARKPULSE_ROLE_SESSION_ISSUER_KEY || "").trim();
const roleProxyAllowedRoles = new Set(
  (process.env.PARKPULSE_FRONTEND_ROLE_PROXY_ALLOWED_ROLES || "customer,onsite_worker,ops_team")
    .split(",")
    .map((role) => role.trim().toLowerCase())
    .filter(Boolean),
);
const identityTokenRefreshSkewMs = 60_000;
let cachedIdentityToken = null;
let cachedIdentityTokenAudience = "";
let cachedIdentityTokenExpiresAt = 0;
let identityTokenInflight = null;
const cachedRoleSessions = new Map();
const roleSessionRefreshSkewSeconds = 60;

const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".txt": "text/plain; charset=utf-8",
  ".webp": "image/webp",
};

function sendJson(response, status, payload) {
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
  });
  response.end(JSON.stringify(payload));
}

async function identityToken(audience) {
  if (!audience) return null;
  const now = Date.now();
  if (cachedIdentityToken && cachedIdentityTokenAudience === audience && cachedIdentityTokenExpiresAt - identityTokenRefreshSkewMs > now) {
    return cachedIdentityToken;
  }
  if (identityTokenInflight) {
    return identityTokenInflight;
  }
  identityTokenInflight = (async () => {
    const metadataUrl =
      "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity" +
      `?audience=${encodeURIComponent(audience)}&format=full`;
    const response = await fetch(metadataUrl, { headers: { "Metadata-Flavor": "Google" } });
    if (!response.ok) {
      throw new Error(`metadata identity token failed: ${response.status}`);
    }
    cachedIdentityToken = await response.text();
    cachedIdentityTokenAudience = audience;
    cachedIdentityTokenExpiresAt = decodeJwtExpiryMs(cachedIdentityToken) || now + 45 * 60_000;
    return cachedIdentityToken;
  })();
  try {
    return await identityTokenInflight;
  } finally {
    identityTokenInflight = null;
  }
}

function shouldSendIdentityToken(apiUrl) {
  if (process.env.PARKPULSE_API_IDENTITY_AUDIENCE) return true;
  try {
    const url = new URL(apiUrl);
    return url.hostname.endsWith(".run.app") || url.hostname.includes("googleapis.com");
  } catch {
    return false;
  }
}

function decodeJwtExpiryMs(token) {
  try {
    const [, payload] = token.split(".");
    if (!payload) return 0;
    const decoded = JSON.parse(Buffer.from(payload.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("utf8"));
    return Number(decoded.exp || 0) * 1000;
  } catch {
    return 0;
  }
}

function decodeJwtExpirySeconds(token) {
  return Math.floor(decodeJwtExpiryMs(token) / 1000);
}

function normalizeRole(role) {
  return String(role || "ops_team").trim().toLowerCase().replace(/-/g, "_");
}

function headerValue(headers, name) {
  return headers.get(name) || headers.get(name.toLowerCase()) || "";
}

async function readRequestJson(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  if (!chunks.length) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
  } catch {
    return {};
  }
}

async function trustedRoleSession(role, subject = "parkpulse-frontend-proxy") {
  const normalizedRole = normalizeRole(role);
  if (!roleSessionIssuerKey || !roleProxyAllowedRoles.has(normalizedRole)) return null;

  const cacheKey = `${normalizedRole}:${subject}`;
  const nowSeconds = Math.floor(Date.now() / 1000);
  const cached = cachedRoleSessions.get(cacheKey);
  if (cached && cached.expiresAt - roleSessionRefreshSkewSeconds > nowSeconds) return cached;

  const token = shouldSendIdentityToken(apiBaseUrl) ? await identityToken(apiIdentityAudience) : null;
  const headers = {
    accept: "application/json",
    "content-type": "application/json",
    "x-parkpulse-role-issuer-key": roleSessionIssuerKey,
  };
  if (token) {
    headers.authorization = `Bearer ${token}`;
    headers["x-serverless-authorization"] = `Bearer ${token}`;
  }

  const upstream = await fetch(`${apiBaseUrl}/api/park/auth/operator-session`, {
    method: "POST",
    headers,
    body: JSON.stringify({ role: normalizedRole, subject }),
  });
  const payload = await upstream.json().catch(() => ({}));
  if (!upstream.ok || payload.status !== "issued" || !payload.token) {
    throw new Error(`trusted role session failed: ${upstream.status}`);
  }
  const session = {
    token: payload.token,
    role: normalizedRole,
    subject,
    expiresAt: Number(payload.expires_at || decodeJwtExpirySeconds(payload.token) || nowSeconds + 300),
    payload,
  };
  cachedRoleSessions.set(cacheKey, session);
  return session;
}

async function maybeHandleRoleSessionRequest(request, response, targetUrl) {
  if (targetUrl.pathname !== "/api/park/auth/dev-session" || !["GET", "POST"].includes(request.method || "GET")) {
    return false;
  }
  const queryRole = targetUrl.searchParams.get("role");
  const querySubject = targetUrl.searchParams.get("subject");
  const body = request.method === "POST" ? await readRequestJson(request) : {};
  const role = normalizeRole(body.role || queryRole || "ops_team");
  const subject = String(body.subject || querySubject || "parkpulse-browser-command-center");
  const session = await trustedRoleSession(role, subject);
  if (!session) {
    sendJson(response, 403, {
      status: "blocked",
      mode: "frontend_trusted_role_session_issuer",
      role,
      readiness_issues: ["Frontend trusted role session issuer is not configured for this role."],
    });
    return true;
  }
  sendJson(response, 200, {
    ...session.payload,
    mode: "frontend_trusted_role_session_issuer",
    frontend_proxy_issuer: true,
  });
  return true;
}

async function proxyApi(request, response) {
  if (!apiBaseUrl) {
    sendJson(response, 503, { status: "api_proxy_unconfigured", message: "PARKPULSE_API_URL is not set." });
    return;
  }

  try {
    const targetUrl = new URL(request.url || "/", apiBaseUrl);
    if (await maybeHandleRoleSessionRequest(request, response, targetUrl)) return;

    const headers = new Headers();
    for (const [key, value] of Object.entries(request.headers)) {
      if (!value || ["host", "connection", "content-length", "authorization", "x-serverless-authorization", "x-parkpulse-role-issuer-key"].includes(key.toLowerCase())) continue;
      headers.set(key, Array.isArray(value) ? value.join(",") : value);
    }
    const token = shouldSendIdentityToken(apiBaseUrl) ? await identityToken(apiIdentityAudience) : null;
    if (token) {
      headers.set("authorization", `Bearer ${token}`);
      headers.set("x-serverless-authorization", `Bearer ${token}`);
    }
    if (!headerValue(headers, "x-parkpulse-role-token")) {
      const requestedRole = headerValue(headers, "x-parkpulse-role");
      const session = requestedRole ? await trustedRoleSession(requestedRole) : null;
      if (session?.token) headers.set("x-parkpulse-role-token", session.token);
    }

    const upstream = await fetch(targetUrl, {
      method: request.method,
      headers,
      body: ["GET", "HEAD"].includes(request.method || "GET") ? undefined : request,
      duplex: "half",
    });

    response.writeHead(upstream.status, Object.fromEntries(upstream.headers.entries()));
    if (upstream.body) {
      for await (const chunk of upstream.body) response.write(chunk);
    }
    response.end();
  } catch (error) {
    sendJson(response, 502, {
      status: "api_proxy_failed",
      message: error instanceof Error ? error.message : String(error),
    });
  }
}

async function serveStatic(request, response) {
  const requestUrl = new URL(request.url || "/", "http://localhost");
  const pathname = decodeURIComponent(requestUrl.pathname);
  const normalized = normalize(pathname).replace(/^(\.\.[/\\])+/, "");
  const candidate = join(distDir, normalized);
  let filePath = candidate.endsWith("/") ? join(distDir, "index.html") : candidate;

  if (!filePath.startsWith(distDir)) {
    response.writeHead(403);
    response.end("Forbidden");
    return;
  }

  try {
    const fileStat = await stat(filePath);
    if (!fileStat.isFile()) {
      filePath = join(distDir, "index.html");
      await stat(filePath);
    }
    response.writeHead(200, {
      "content-type": contentTypes[extname(filePath)] || "application/octet-stream",
      "cache-control": filePath.endsWith("index.html") ? "no-store" : "public, max-age=31536000, immutable",
    });
    if (request.method === "HEAD") {
      response.end();
      return;
    }
    createReadStream(filePath).pipe(response);
  } catch {
    const fallbackPath = join(distDir, "index.html");
    try {
      await stat(fallbackPath);
      response.writeHead(200, {
        "content-type": contentTypes[extname(fallbackPath)] || "application/octet-stream",
        "cache-control": "no-store",
      });
      if (request.method === "HEAD") {
        response.end();
        return;
      }
      createReadStream(fallbackPath).pipe(response);
    } catch {
      response.writeHead(404);
      response.end("Not found");
    }
  }
}

createServer((request, response) => {
  if ((request.url || "").startsWith("/api/") || request.url === "/readyz" || request.url === "/health" || request.url === "/healthz") {
    void proxyApi(request, response);
    return;
  }
  void serveStatic(request, response);
}).listen(port, "0.0.0.0", () => {
  console.log(`ParkPulse frontend listening on ${port}`);
});
