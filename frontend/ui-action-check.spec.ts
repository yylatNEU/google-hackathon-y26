import { expect, test, type Page } from "@playwright/test";

test.use({ viewport: { width: 1280, height: 900 } });

const API_URL = process.env.PARKPULSE_TEST_API_URL ?? "http://127.0.0.1:8000";
const APP_URL = process.env.PARKPULSE_TEST_APP_URL ?? "http://127.0.0.1:3000";

function watchRuntime(page: Page) {
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

async function openCommandCenter(page: Page) {
  await page.goto(`${APP_URL}?api=${encodeURIComponent(API_URL)}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Park operating loop" })).toBeVisible({ timeout: 20000 });
  await expect(page.getByRole("heading", { name: "Operational data contract" })).toBeVisible({ timeout: 20000 });
}

async function expectNoAuthOrTransportRegression(page: Page) {
  const body = page.locator("body");
  await expect(body).not.toContainText(/auth\/dev-session returned 403|Missing signed role session token/i);
  await expect(body).not.toContainText(/ParkPulse API did not respond/i);
  await expect(body).not.toContainText(/Backend unavailable/i);
}

test("command center exposes the current production operating-loop contract", async ({ page, request }) => {
  test.setTimeout(120000);
  const { runtimeErrors, failedResponses } = watchRuntime(page);

  const gcpStatus = await request.get(`${API_URL}/api/gcp/trace-eval-status`, { timeout: 15000 });
  expect(gcpStatus.ok()).toBeTruthy();
  const gcpPayload = await gcpStatus.json();
  expect(gcpPayload.platform).toBe("GCP internal trace/eval");
  expect(gcpPayload.ready).toBeTruthy();

  await openCommandCenter(page);
  await expect(page.getByRole("link", { name: "Venue Profile" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Experience Studio" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Staff trainer" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Run operating loop" })).toBeEnabled({ timeout: 20000 });
  await expect(page.getByRole("heading", { name: "Signals, features, predictors, optimizer, gate, execute or review, learn" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Observed outcome reward model" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Bounded dispatch ready|Human approval required/i })).toBeVisible();
  await expectNoAuthOrTransportRegression(page);

  expect(runtimeErrors).toEqual([]);
  expect(failedResponses).toEqual([]);
});

test("live-feed review and training panels use signed local role sessions", async ({ page }) => {
  test.setTimeout(120000);
  const { runtimeErrors, failedResponses } = watchRuntime(page);

  await openCommandCenter(page);
  await expect(page.getByText("Live feeds and review")).toBeVisible();
  await expect(page.getByText("Training readiness and weak spots")).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh feeds" })).toBeEnabled({ timeout: 20000 });
  await expect(page.getByRole("button", { name: "Refresh training" })).toBeEnabled({ timeout: 20000 });

  await page.getByRole("button", { name: "Refresh feeds" }).click({ noWaitAfter: true });
  await expect(page.getByText("Ready feeds")).toBeVisible({ timeout: 20000 });
  await expect(page.getByText("Open reviews")).toBeVisible({ timeout: 20000 });
  await expect(page.getByText("Training candidates")).toBeVisible({ timeout: 20000 });
  await page.getByRole("button", { name: "Refresh training" }).click({ noWaitAfter: true });
  await expect(page.getByRole("heading", { name: "Observed outcome reward model" })).toBeVisible({ timeout: 20000 });
  await expect(page.getByText("GCP ML path")).toBeVisible({ timeout: 20000 });
  await expectNoAuthOrTransportRegression(page);

  expect(runtimeErrors).toEqual([]);
  expect(failedResponses).toEqual([]);
});

test("expanded product entry points stay visible without drifting back to the retired six-domain demo", async ({ page }) => {
  test.setTimeout(120000);
  const { runtimeErrors, failedResponses } = watchRuntime(page);

  await openCommandCenter(page);
  await expect(page.getByRole("link", { name: "Staff trainer" })).toHaveAttribute("href", "/staff-training");
  await expect(page.getByRole("link", { name: "Venue Profile" })).toHaveAttribute("href", "/venue-profile");
  await expect(page.getByRole("link", { name: "Experience Studio" })).toHaveAttribute("href", "/experience-studio");
  await expect(page.getByRole("link", { name: "Labs" })).toHaveAttribute("href", "/labs");
  await expect(page.getByText("Staff roleplay trainer")).toBeVisible({ timeout: 20000 });
  await expect(page.locator("body")).not.toContainText(/Ask the park agent|Inject ride fault|Messy note intake/i);

  await page.screenshot({ path: "../output/qa/parkpulse-expanded-platform-entry-points.png", fullPage: true });

  expect(runtimeErrors).toEqual([]);
  expect(failedResponses).toEqual([]);
});
