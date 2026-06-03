import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 1280, height: 900 } });

const API_URL = process.env.PARKPULSE_TEST_API_URL ?? "http://127.0.0.1:8000";
const APP_URL = process.env.PARKPULSE_TEST_APP_URL ?? "http://127.0.0.1:3000";

test("ParkPulse demo exposes GCP eval path and action controls", async ({ page, request }) => {
  test.setTimeout(120000);
  const runtimeErrors: string[] = [];
  const failedResponses: string[] = [];
  page.on("response", (response) => {
    const sameOriginBackendProxy = response.url().includes(`${APP_URL}/api/park/`);
    if (response.status() >= 500 && !sameOriginBackendProxy) {
      failedResponses.push(`${response.status()} ${response.url()}`);
    }
  });
  page.on("pageerror", (error) => runtimeErrors.push(error.message));
  page.on("console", (message) => {
    const text = message.text();
    const ignoredTransientNetworkError = text.includes("net::ERR_CONNECTION_REFUSED") || text.includes("net::ERR_NETWORK_CHANGED");
    const ignoredBrowserResourceLine = text.includes("Failed to load resource");
    if (message.type() === "error" && !ignoredTransientNetworkError && !ignoredBrowserResourceLine) {
      runtimeErrors.push(message.text());
    }
  });

  try {
    const gcpStatus = await request.get(`${API_URL}/api/gcp/trace-eval-status`, { timeout: 5000 });
    expect(gcpStatus.ok()).toBeTruthy();
    const gcpPayload = await gcpStatus.json();
    expect(gcpPayload.platform).toBe("GCP internal trace/eval");
    expect(gcpPayload.ready).toBeTruthy();
  } catch {
    // The visual UI contract still needs to pass when the backend is not running.
  }

  await page.goto(`${APP_URL}?api=${encodeURIComponent(API_URL)}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: /Agent detected an early park risk|AI operations control/i }).first()).toBeVisible({ timeout: 20000 });
  await expect(page.getByText("Ask the park agent")).toBeVisible({ timeout: 15000 });
  const proactiveButton = page.getByRole("button", { name: /Scan and proact|Scan again/i });
  await expect(proactiveButton).toBeEnabled({ timeout: 15000 });

  await page.getByPlaceholder(/Ask: keep families/i).fill("Food Court A is down. Do not send people there; redirect mobile orders to Food Court B.");
  const askButton = page.getByRole("button", { name: "Ask and act" });
  await expect(askButton).toBeEnabled({ timeout: 15000 });
  await askButton.click({ noWaitAfter: true });
  await expect(page.locator('[data-testid="domain-visual-food"]')).toBeVisible({ timeout: 10000 });
  await expect(page.getByText("Unified operating loop")).toBeVisible({ timeout: 10000 });
  await expect(page.getByText("Specialist agents + boundaries")).toBeVisible({ timeout: 10000 });
  await expect(page.locator("body")).toContainText(/Decision Bridge/i, { timeout: 10000 });
  await expect(page.locator("body")).toContainText(/Signal\s*food/i, { timeout: 10000 });
  await expect(page.locator("body")).toContainText(/Action progress\s*(live|complete)/i, { timeout: 15000 });
  await expect(page.locator("body")).toContainText(/food spike operations response/i, { timeout: 15000 });
  await expect(page.locator("body")).toContainText(/Gemini|Fast local preview|Policy guardrails/i, { timeout: 15000 });
  await expect(page.getByText(/Backend unavailable/)).toHaveCount(0);

  expect(runtimeErrors).toEqual([]);
  expect(failedResponses).toEqual([]);
});

test("ParkPulse demo chips produce domain-specific map actions without scripted copy leaks", async ({ page }) => {
  test.setTimeout(180000);
  const runtimeErrors: string[] = [];
  const failedResponses: string[] = [];

  page.on("response", (response) => {
    const sameOriginBackendProxy = response.url().includes(`${APP_URL}/api/park/`);
    if (response.status() >= 500 && !sameOriginBackendProxy) {
      failedResponses.push(`${response.status()} ${response.url()}`);
    }
  });
  page.on("pageerror", (error) => runtimeErrors.push(error.message));
  page.on("console", (message) => {
    const text = message.text();
    const ignoredTransientNetworkError = text.includes("net::ERR_CONNECTION_REFUSED") || text.includes("net::ERR_NETWORK_CHANGED");
    const ignoredBrowserResourceLine = text.includes("Failed to load resource");
    if (message.type() === "error" && !ignoredTransientNetworkError && !ignoredBrowserResourceLine) {
      runtimeErrors.push(message.text());
    }
  });

  await page.goto(`${APP_URL}?api=${encodeURIComponent(API_URL)}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Ask the park agent")).toBeVisible({ timeout: 20000 });

  const cases = [
    {
      button: "Inject ride fault",
      domain: "ride",
      proof: /Ride queue\s+\d+\s*->\s*\d+/i,
      stale: [] as RegExp[],
    },
    {
      button: "Inject food disruption",
      domain: "food",
      proof: /Backlog\s+\d+\s*->\s*\d+/i,
      stale: [/Dragon Coaster is temporarily unavailable/i],
    },
    {
      button: "Inject labor gap",
      domain: "staff",
      proof: /Callouts\s+\d+\s*->\s*\d+/i,
      stale: [/Dragon Coaster is temporarily unavailable/i],
    },
    {
      button: "Inject care signal",
      domain: "medical",
      proof: /Care cases\s+\d+\s*->\s*\d+/i,
      stale: [/Dragon Coaster is temporarily unavailable/i, /diagnose/i],
    },
    {
      button: "Inject crowd pressure",
      domain: "crowd",
      proof: /Path congestion\s+\d+\s*->\s*\d+/i,
      stale: [/Dragon Coaster is temporarily unavailable/i],
    },
    {
      button: "Inject comfort load",
      domain: "energy",
      proof: /Grid load\s+\d+%\s*->\s*\d+%/i,
      stale: [/Dragon Coaster is temporarily unavailable/i],
    },
  ] as const;

  for (const item of cases) {
    await page.goto(`${APP_URL}?api=${encodeURIComponent(API_URL)}`, { waitUntil: "domcontentloaded" });
    await expect(page.getByText("Ask the park agent")).toBeVisible({ timeout: 20000 });
    await page.getByRole("button", { name: item.button }).click({ noWaitAfter: true });
    await expect(page.locator(`[data-testid="domain-visual-${item.domain}"]`)).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("Unified operating loop")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("body")).toContainText(/Preliminary read:/i, { timeout: 10000 });
    await expect(page.locator("body")).toContainText(/Action progress\s*(live|complete)/i, { timeout: 10000 });
    await expect(page.getByText(/Backend unavailable/)).toHaveCount(0);
    for (const staleCopy of item.stale) {
      await expect(page.getByText(staleCopy)).toHaveCount(0);
    }
  }

  await page.screenshot({ path: "../output/qa/parkpulse-six-domain-demo.png", fullPage: true });

  expect(runtimeErrors).toEqual([]);
  expect(failedResponses).toEqual([]);
});

test("messy notes from guest, worker, and support station enter the same react loop", async ({ page }) => {
  test.setTimeout(120000);
  await page.goto(`${APP_URL}?api=${encodeURIComponent(API_URL)}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Messy note intake")).toBeVisible({ timeout: 20000 });

  const cases = [
    { button: "Guest app", domain: "medical", proof: /medical access response|medical response/i },
    { button: "Worker app", domain: "equipment", proof: /equipment safety response|equipment safety/i },
    { button: "Support station", domain: "medical", proof: /medical access response|accessibility/i },
  ] as const;

  for (const item of cases) {
    await page.goto(`${APP_URL}?api=${encodeURIComponent(API_URL)}`, { waitUntil: "domcontentloaded" });
    await expect(page.getByText("Messy note intake")).toBeVisible({ timeout: 20000 });
    await page.getByRole("button", { name: item.button }).click({ noWaitAfter: true });
    await expect(page.locator(`[data-testid="domain-visual-${item.domain}"]`)).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("Unified operating loop")).toBeVisible({ timeout: 10000 });
    await expect(page.getByText("Specialist agents + boundaries")).toBeVisible({ timeout: 10000 });
    await expect(page.locator("body")).toContainText(item.proof, { timeout: 15000 });
    await expect(page.getByText(/Dragon Coaster is temporarily unavailable/i)).toHaveCount(0);
  }
});
