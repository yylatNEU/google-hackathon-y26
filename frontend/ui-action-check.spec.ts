import { expect, test, type Page } from "@playwright/test";

test.use({ viewport: { width: 1280, height: 900 } });

const API_URL = process.env.PARKPULSE_TEST_API_URL ?? "http://127.0.0.1:8010";
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
  await page.goto(`${APP_URL}/ops?api=${encodeURIComponent(API_URL)}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Park operating loop" })).toBeVisible({ timeout: 20000 });
  await expect(page.getByRole("heading", { name: "Operational data contract" })).toBeVisible({ timeout: 20000 });
}

async function openStaffTraining(page: Page) {
  await page.goto(`${APP_URL}/staff-training?api=${encodeURIComponent(API_URL)}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Roleplay Trainer" })).toBeVisible({ timeout: 20000 });
  await page.getByRole("button", { name: /Lost Child Report/ }).click();
  await expect(page.getByRole("heading", { name: "Lost Child Report" }).first()).toBeVisible({ timeout: 20000 });
}

async function expectNoAuthOrTransportRegression(page: Page) {
  const body = page.locator("body");
  await expect(body).not.toContainText(/auth\/dev-session returned 403|Missing signed role session token/i);
  await expect(body).not.toContainText(/ParkPulse API did not respond/i, { timeout: 30000 });
  await expect(body).not.toContainText(/Backend unavailable/i, { timeout: 30000 });
}

async function refreshFeedsUntilReviewed(page: Page) {
  const refresh = page.getByRole("button", { name: "Refresh feeds" });
  const refreshStale = page.getByRole("button", { name: "Refresh stale" });
  await refreshStale.click({ noWaitAfter: true });
  await refresh.click({ noWaitAfter: true });
  await expect
    .poll(
      async () => {
        const bodyText = await page.locator("body").innerText();
        const match = bodyText.match(/Ready feeds\s+([0-6])\/6/i);
        const readyCount = match ? Number(match[1]) : 0;
        const statusReady = /Status\s+ready/i.test(bodyText);
        const statusReviewed = /Status\s+review/i.test(bodyText);
        const noOpenReviews = /Open reviews\s+0/i.test(bodyText);
        const weakFeedEvidence = /Weak feeds\s+[1-6]/i.test(bodyText) || /stale|review_blocked/i.test(bodyText);
        return statusReady ? readyCount === 6 : readyCount >= 5 && statusReviewed && noOpenReviews && weakFeedEvidence;
      },
      { timeout: 120000, message: "live feed health should reach ready or signed review mode with weak-feed evidence" },
    )
    .toBeTruthy();
}

test("command center exposes the current production operating-loop contract", async ({ page, request }) => {
  test.setTimeout(120000);
  const { runtimeErrors, failedResponses } = watchRuntime(page);

  const gcpStatus = await request.get(`${API_URL}/api/gcp/trace-eval-status`, { timeout: 60000 });
  expect(gcpStatus.ok()).toBeTruthy();
  const gcpPayload = await gcpStatus.json();
  expect(gcpPayload.platform).toBe("GCP internal trace/eval");
  expect(gcpPayload.ready).toBeTruthy();

  await openCommandCenter(page);
  await expect(page.getByRole("link", { name: "Ops Agent" })).toHaveAttribute("href", "/ops-agent");
  await expect(page.getByRole("link", { name: "Monitor" })).toHaveAttribute("href", "/monitor");
  await expect(page.getByRole("link", { name: "Runtime proof" })).toHaveAttribute("href", "/operation-proof");
  await expect(page.getByRole("link", { name: "Executive" })).toHaveAttribute("href", "/executive");
  await expect(page.getByRole("button", { name: "Run incident review" })).toBeEnabled({ timeout: 20000 });
  await expect(page.getByRole("button", { name: "Live-feed case" })).toBeEnabled({ timeout: 20000 });
  await expect(page.getByText("Operating decision", { exact: true })).toBeVisible();
  await expect(page.getByText("Decision audit receipt")).toBeVisible();
  await expect(page.getByRole("heading", { name: /Bounded dispatch ready|Human approval required/i })).toBeVisible();
  await expect(page.getByTestId("api-targets")).toHaveAttribute("data-api-targets", API_URL);
  const apiTargets = await page.getByTestId("api-targets").getAttribute("data-api-targets");
  expect(apiTargets?.split(",").map((item) => item.trim()).filter(Boolean)).toEqual([API_URL]);
  await expectNoAuthOrTransportRegression(page);

  expect(runtimeErrors).toEqual([]);
  expect(failedResponses).toEqual([]);
});

test("live-feed review panel uses signed local role sessions", async ({ page }) => {
  test.setTimeout(180000);
  const { runtimeErrors, failedResponses } = watchRuntime(page);

  await openCommandCenter(page);
  await expect(page.getByText("Live feeds and review")).toBeVisible();
  await expect(page.getByText("Operational data contract")).toBeVisible();
  await expect(page.getByText("Systematic growth loop")).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh feeds" })).toBeEnabled({ timeout: 20000 });

  await refreshFeedsUntilReviewed(page);
  await expect(page.getByText("Ready feeds")).toBeVisible({ timeout: 20000 });
  await expect(page.getByText("Open reviews")).toBeVisible({ timeout: 20000 });
  await expect(page.getByText("Training candidates")).toBeVisible({ timeout: 20000 });
  await expectNoAuthOrTransportRegression(page);

  expect(runtimeErrors).toEqual([]);
  expect(failedResponses).toEqual([]);
});

test("staff training roleplay keeps the employee turn and returns coaching", async ({ page }) => {
  test.setTimeout(90000);
  const { runtimeErrors, failedResponses } = watchRuntime(page);

  await openStaffTraining(page);
  await expectNoAuthOrTransportRegression(page);
  const vertexGuest = page.getByLabel("Vertex AI guest");
  if (await vertexGuest.isChecked()) {
    await vertexGuest.uncheck();
  }

  await page.getByRole("button", { name: "Start roleplay" }).click();
  await expect(page.getByText("Session active. Read the guest message below, then reply as the employee.")).toBeVisible({ timeout: 20000 });

  const employeeReply =
    "I am sorry, I will help right now. Please stay here while I call security. What is she wearing, and where did you last see her near the carousel?";
  await page.getByLabel("Employee response").fill(employeeReply);
  const sendReply = page.getByRole("button", { name: "Send reply" });
  await expect(sendReply).toBeEnabled();
  await sendReply.click();

  await expect(page.getByText(employeeReply)).toBeVisible({ timeout: 30000 });
  await expect(page.getByText(/Strong response|Continue the conversation|Say next/).first()).toBeVisible({ timeout: 30000 });
  await expect(page.getByText(/strong|passing/).first()).toBeVisible({ timeout: 30000 });
  await expect(page.getByText("Scores: deterministic")).toBeVisible({ timeout: 30000 });
  await expect(page.locator("body")).not.toContainText(/Training session was not found|has expired/i);
  await expectNoAuthOrTransportRegression(page);

  expect(runtimeErrors).toEqual([]);
  expect(failedResponses).toEqual([]);
});

test("agent role run API preserves role boundaries and strict eval traces", async ({ request }) => {
  test.setTimeout(360000);
  const cases = [
    { mode: "scan", message: "scan the park for weak signals" },
    { mode: "react", message: "food court is overloaded and mobile orders are backing up" },
    { mode: "proact", message: "watch for a weak bottleneck before it becomes an incident" },
    { mode: "customer", message: "where should my family go next" },
    { mode: "qa", message: "pre-deploy reliability QA" },
  ];

  for (const roleCase of cases) {
    const response = await request.post(`${API_URL}/api/park/agent-role-run`, {
      data: { message: roleCase.message, mode: roleCase.mode, execute: true },
      timeout: 90000,
    });
    expect(response.ok()).toBeTruthy();
    const payload = await response.json();
    expect(payload.selected_role).toBe(roleCase.mode);
    expect(payload.digital_twin_tools?.deliberate_eval?.status).toBe("passed");
    expect(payload.digital_twin_tools?.deliberate_eval?.required_without_output).toEqual([]);
    expect(payload.digital_twin_tools?.deliberate_eval?.critical_failures).toEqual([]);
    if (roleCase.mode === "scan" || roleCase.mode === "customer" || roleCase.mode === "qa") {
      expect(payload.role_run?.dispatch_count).toBe(0);
    }
    expect(payload.role_trace_sample?.status).toBe("recorded");
  }

  const evalResponse = await request.get(`${API_URL}/api/park/agent-role-eval?real=1`, { timeout: 90000 });
  expect(evalResponse.ok()).toBeTruthy();
  const evalPayload = await evalResponse.json();
  expect(evalPayload.status).toBe("passed");
  expect(evalPayload.passed_role_count).toBe(5);
  expect(evalPayload.failed_role_count).toBe(0);
  for (const role of evalPayload.roles ?? []) {
    expect(role.trace?.deliberate_eval?.status).toBe("passed");
  }
});

test("expanded product entry points stay visible without drifting back to the retired six-domain demo", async ({ page }) => {
  test.setTimeout(120000);
  const { runtimeErrors, failedResponses } = watchRuntime(page);

  await page.goto(`${APP_URL}?api=${encodeURIComponent(API_URL)}`, { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Start with the park, not the prompt." })).toBeVisible({ timeout: 20000 });
  await expect(page.locator('a[href="/venue-profile"]').first()).toBeVisible();
  await expect(page.locator('a[href="/experience-studio"]').first()).toBeVisible();
  await expect(page.locator('a[href="/guest-triage"]').first()).toBeVisible();
  await expect(page.locator('a[href="/ops"]').first()).toBeVisible();
  await expect(page.locator('a[href="/staff-training"]').first()).toBeVisible();
  await expect(page.locator('a[href="/agent-handshake"]').first()).toBeVisible();
  await expect(page.getByText("Employee Training").first()).toBeVisible({ timeout: 20000 });
  await expect(page.locator("body")).not.toContainText(/Ask the park agent|Inject ride fault|Messy note intake/i);

  await page.screenshot({ path: "../output/qa/parkpulse-expanded-platform-entry-points.png", fullPage: true });

  expect(runtimeErrors).toEqual([]);
  expect(failedResponses).toEqual([]);
});
