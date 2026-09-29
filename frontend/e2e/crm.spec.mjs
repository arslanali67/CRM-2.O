// M31 browser E2E against the isolated stack (`make e2e`): sending OFF, no Gmail account, test-only owner.
// Runs in order; each step builds on the previous one (import -> compose -> approve).
import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const env = Object.fromEntries(readFileSync(join(here, ".env.e2e"), "utf8").trim().split("\n").map((l) => {
  const i = l.indexOf("=");
  return [l.slice(0, i), l.slice(i + 1)];
}));
const OWNER = { email: env.OWNER_EMAIL, password: env.E2E_PASSWORD };

test.describe.configure({ mode: "serial" });
let page;

async function login(p, password = OWNER.password) {
  await p.goto("/login");
  await p.getByLabel("Email").fill(OWNER.email);
  await p.getByLabel("Password").fill(password);
  await p.getByRole("button", { name: "Sign in" }).click();
}

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage();
});
test.afterAll(async () => page.close());

test("security headers on pages and API; cross-site changes refused", async ({ request }) => {
  const r = await request.get("/login");
  const h = r.headers();
  expect(h["content-security-policy"]).toContain("frame-ancestors 'none'");
  expect(h["x-frame-options"]).toBe("DENY");
  expect(h["x-content-type-options"]).toBe("nosniff");
  expect(h["referrer-policy"]).toBe("no-referrer");
  expect(h["x-powered-by"]).toBeUndefined();
  const api = await request.get("/api/health");
  expect(api.headers()["x-frame-options"]).toBe("DENY");
  const evil = await request.post("/api/auth/login", {
    data: { email: OWNER.email, password: OWNER.password }, headers: { Origin: "https://evil.example" },
  });
  expect(evil.status()).toBe(403);
});

test("login: wrong password refused, right one opens the dashboard", async () => {
  await login(page, "not-the-password");
  await expect(page.locator('p[role="alert"]')).toHaveText("Invalid email or password");
  await login(page);
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByText("No backup yet.")).toBeVisible(); // M32 warning on a fresh install
});

test("CSV import: preview first, then import", async () => {
  await page.goto("/import");
  await page.locator('input[type="file"]').setInputFiles(join(here, "fixtures", "companies.csv"));
  await page.getByLabel("City").fill("Berlin");
  await page.getByLabel("Country").fill("Germany");
  await page.getByRole("button", { name: "Preview (nothing is saved)" }).click();
  await page.getByRole("button", { name: "Import 2 new companies" }).click();
  await expect(page.getByText("Imported 2 companies")).toBeVisible();
});

test("leads: both companies listed and handed to the compose list", async () => {
  await page.goto("/companies");
  await expect(page.getByRole("link", { name: "E2E Alpha Robotics" })).toBeVisible();
  await expect(page.getByRole("link", { name: "E2E Beta Vision" })).toBeVisible();
  await page.getByLabel("Select all shown").check();
  await page.getByRole("button", { name: "Add to compose list" }).click();
  await page.goto("/compose");
  await expect(page.getByText("E2E Alpha Robotics")).toBeVisible();
});

test("template and drafts: nothing is approved by creating drafts", async () => {
  await page.goto("/templates");
  await page.getByLabel("Name").fill("E2E intro");
  await page.getByLabel("Subject").fill("Hello {{company_name}}");
  await page.getByLabel("Body (plain text)").fill("Hi there,\nI'd like to join {{company_name}}.\nBest regards");
  await page.getByRole("button", { name: "Create template" }).click();
  await page.goto("/compose");
  await page.getByLabel("Template").selectOption({ label: "E2E intro (v1)" });
  await page.getByRole("button", { name: "Create 2 draft(s)" }).click();
  await expect(page.getByText("2 draft(s) created.")).toBeVisible();
  const queued = await (await page.request.get("/api/outbox?status=queued")).json();
  expect(queued.emails).toHaveLength(0);
});

test("approve one email: it is queued, and with sending OFF it is never sent", async () => {
  test.setTimeout(120_000);
  await page.goto("/outbox");
  await expect(page.getByText("Sending is OFF")).toBeVisible();
  await page.getByRole("link", { name: "jobs@e2e-alpha-robotics.de" }).click();
  await page.getByRole("button", { name: "Approve & queue this email" }).click();
  await expect(page.getByText("Approved and queued.")).toBeVisible();
  await page.waitForTimeout(40_000); // longer than one sender tick (30 s)
  const sent = await (await page.request.get("/api/outbox?status=sent")).json();
  const queued = await (await page.request.get("/api/outbox?status=queued")).json();
  const drafts = await (await page.request.get("/api/outbox?status=draft")).json();
  expect(sent.emails).toHaveLength(0);
  expect(queued.emails.map((e) => e.to_email)).toEqual(["jobs@e2e-alpha-robotics.de"]);
  expect(drafts.emails.map((e) => e.to_email)).toEqual(["careers@e2e-beta-vision.de"]); // approving one never approves another
});

test("settings: a change is saved and shows in the activity log", async () => {
  await page.goto("/settings");
  await page.getByLabel("Daily sending cap (emails/day):").fill("5");
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByText(/Saved: daily cap/)).toBeVisible();
  await page.goto("/activity");
  await expect(page.getByText(/Settings changed: daily cap 20 → 5/)).toBeVisible();
});

test("backup: back up now, then the dashboard warning is gone", async () => {
  test.setTimeout(90_000);
  await page.goto("/backup");
  await page.getByRole("button", { name: "Back up now" }).click();
  await expect(page.getByText(/Backup written: crm-/)).toBeVisible({ timeout: 60_000 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByText("No backup yet.")).toHaveCount(0);
});

test("interviews: record one with its time zone, see it on the dashboard, export .ics", async () => {
  const companies = await (await page.request.get("/api/leads")).json();
  const acme = companies.leads.find((l) => l.name === "E2E Alpha Robotics");
  const opp = await (await page.request.post("/api/opportunities", {
    data: { company_id: acme.id, title: "Robotics Engineer" }, headers: { Origin: new URL(page.url()).origin },
  })).json();
  await page.goto(`/opportunities/${opp.id}`);
  await page.getByRole("button", { name: "Record an interview" }).click();
  await page.getByLabel("Title").fill("First call");
  await page.getByLabel("Date and time").fill("2030-10-07T15:00");
  await page.getByLabel("Time zone it was agreed in").selectOption("America/New_York");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Interview recorded.")).toBeVisible();
  await expect(page.getByText("Mon 07 Oct 2030, 15:00 (America/New_York)")).toBeVisible();
  await expect(page.getByText("interviewing").first()).toBeVisible(); // the fact moved the stage
  const list = await (await page.request.get(`/api/opportunities/${opp.id}/interviews`)).json();
  expect(list[0].starts_at).toContain("2030-10-07T19:00:00"); // 15:00 EDT = 19:00 UTC
  const ics = await (await page.request.get(`/api/interviews/${list[0].id}/calendar.ics`)).text();
  expect(ics).toContain("DTSTART:20301007T190000Z");
  await page.goto("/");
  await expect(page.getByText(/next: E2E Alpha Robotics/)).toBeVisible();
  await page.goto("/interviews");
  await expect(page.getByRole("link", { name: "First call" })).toBeVisible();
  await page.goto("/activity");
  await expect(page.getByText(/Interview recorded: First call/)).toBeVisible();
});

test("analytics: the page loads with its breakdowns", async () => {
  await page.goto("/analytics");
  await expect(page.getByRole("heading", { name: "Analytics" })).toBeVisible();
  for (const t of ["By template version", "By country", "By industry", "By source"]) {
    await expect(page.getByRole("heading", { name: t })).toBeVisible();
  }
  await page.getByRole("button", { name: "All time" }).click();
  await expect(page.getByText(/0 sent/)).toBeVisible(); // sending stays OFF in E2E
});

test("lockout: five wrong passwords lock logins, even the right one", async ({ browser }) => {
  const p = await browser.newPage();
  for (let i = 0; i < 5; i++) {
    await login(p, `wrong-${i}`);
    await expect(p.locator('p[role="alert"]')).toHaveText("Invalid email or password");
  }
  await login(p);
  await expect(p.locator('p[role="alert"]')).toContainText("Too many failed logins");
  await p.close();
});
