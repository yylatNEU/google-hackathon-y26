import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

test.use({ viewport: { width: 1280, height: 900 } });

const API_URL = process.env.PARKPULSE_TEST_API_URL ?? "http://127.0.0.1:8000";
const APP_URL = process.env.PARKPULSE_TEST_APP_URL ?? "http://127.0.0.1:3000";

function attachRuntimeGuards(page: Page) {
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
      runtimeErrors.push(text);
    }
  });
  return { runtimeErrors, failedResponses };
}

test("command center exposes live-feed and review-label reliability controls", async ({ page, request }) => {
  test.setTimeout(120000);
  const guards = attachRuntimeGuards(page);

  const gcpStatus = await request.get(`${API_URL}/api/gcp/trace-eval-status`, { timeout: 5000 });
  expect(gcpStatus.ok()).toBeTruthy();

  await page.goto(`${APP_URL}?api=${encodeURIComponent(API_URL)}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Park operating loop" })).toBeVisible({ timeout: 20000 });
  await expect(page.getByText("Operational data contract")).toBeVisible({ timeout: 20000 });
  await expect(page.getByText("Ops review label queue")).toBeVisible({ timeout: 20000 });
  await expect(page.getByRole("button", { name: "Run operating loop" })).toBeEnabled({ timeout: 15000 });
  await expect(page.getByRole("button", { name: "Refresh feeds" })).toBeEnabled({ timeout: 15000 });
  await expect(page.getByRole("button", { name: "Refresh labels" })).toBeEnabled({ timeout: 15000 });
  await expect(page.getByRole("button", { name: "Auto-label high confidence" })).toBeEnabled({ timeout: 15000 });
  await expect(page.getByText(/Backend unavailable/)).toHaveCount(0);

  expect(guards.runtimeErrors).toEqual([]);
  expect(guards.failedResponses).toEqual([]);
});

test("low-confidence live-feed event enters ops review label queue", async ({ page, request }) => {
  test.setTimeout(120000);
  const guards = attachRuntimeGuards(page);

  const eventId = `pw-review-${Date.now()}`;
  const feedResponse = await request.post(`${API_URL}/api/park/live-feed-events`, {
    data: {
      id: eventId,
      source: "operator_signal",
      signal_type: "guest_care",
      entity_id: "first_aid",
      confidence: 0.42,
      value: "Medical support requested near first aid; needs corroboration.",
    },
    timeout: 10000,
  });
  expect(feedResponse.ok()).toBeTruthy();

  await page.goto(`${APP_URL}?api=${encodeURIComponent(API_URL)}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Ops review label queue")).toBeVisible({ timeout: 20000 });
  await page.getByRole("button", { name: "Refresh labels" }).click();
  await expect(page.locator("body")).toContainText(/scan agent|operator signal|guest care/i, { timeout: 20000 });
  await expect(page.getByRole("button", { name: "Need evidence" }).first()).toBeVisible({ timeout: 20000 });

  await page.getByRole("button", { name: "Need evidence" }).first().click();
  await expect(page.locator("body")).toContainText(/Review label needs more evidence|needs more evidence/i, { timeout: 20000 });
  await expect(page.getByText(/Backend unavailable/)).toHaveCount(0);

  expect(guards.runtimeErrors).toEqual([]);
  expect(guards.failedResponses).toEqual([]);
});
