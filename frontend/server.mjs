import { createReadStream, existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));
const distDir = resolve(__dirname, "dist");
const port = Number(process.env.PORT || 3000);
const apiBaseUrl = (process.env.PARKPULSE_API_URL || "").replace(/\/$/, "");

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
  const metadataUrl =
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity" +
    `?audience=${encodeURIComponent(audience)}&format=full`;
  const response = await fetch(metadataUrl, { headers: { "Metadata-Flavor": "Google" } });
  if (!response.ok) {
    throw new Error(`metadata identity token failed: ${response.status}`);
  }
  return response.text();
}

async function proxyApi(request, response) {
  if (!apiBaseUrl) {
    sendJson(response, 503, { status: "api_proxy_unconfigured", message: "PARKPULSE_API_URL is not set." });
    return;
  }

  try {
    const targetUrl = new URL(request.url || "/", apiBaseUrl);
    const headers = new Headers();
    for (const [key, value] of Object.entries(request.headers)) {
      if (!value || ["host", "connection", "content-length"].includes(key.toLowerCase())) continue;
      headers.set(key, Array.isArray(value) ? value.join(",") : value);
    }
    const token = await identityToken(apiBaseUrl);
    if (token) headers.set("authorization", `Bearer ${token}`);

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
  const filePath = existsSync(candidate) && !candidate.endsWith("/") ? candidate : join(distDir, "index.html");

  if (!filePath.startsWith(distDir)) {
    response.writeHead(403);
    response.end("Forbidden");
    return;
  }

  try {
    await readFile(filePath);
    response.writeHead(200, {
      "content-type": contentTypes[extname(filePath)] || "application/octet-stream",
      "cache-control": filePath.endsWith("index.html") ? "no-store" : "public, max-age=31536000, immutable",
    });
    createReadStream(filePath).pipe(response);
  } catch {
    response.writeHead(404);
    response.end("Not found");
  }
}

createServer((request, response) => {
  if ((request.url || "").startsWith("/api/") || request.url === "/readyz" || request.url === "/healthz") {
    void proxyApi(request, response);
    return;
  }
  void serveStatic(request, response);
}).listen(port, "0.0.0.0", () => {
  console.log(`ParkPulse frontend listening on ${port}`);
});
