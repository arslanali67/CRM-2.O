// M31 browser E2E against the isolated stack (`make e2e`): sending OFF, no Gmail account, test-only owner.
// Runs in order; each step builds on the previous one (import -> compose -> approve).
import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { sql } from "./seed.mjs";
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
  await expect(page.locator('.step[aria-current="step"]')).toContainText("Import"); // wizard step 3
  await expect(page.getByRole("link", { name: "View imported leads" })).toBeVisible();
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
  await page.getByRole("button", { name: "New template" }).first().click();
  const dlg = page.getByRole("dialog", { name: "New template" });
  await dlg.getByLabel("Name", { exact: true }).fill("E2E intro");
  await dlg.getByLabel("Subject").fill("Hello {{company_name}}");
  await dlg.getByLabel("Body (plain text)").fill("Hi there,\nI'd like to join {{company_name}}.\nBest regards");
  await expect(dlg.locator("[data-preview-subject]")).toContainText("Hello E2E"); // live preview rendered a real lead
  await dlg.getByRole("button", { name: "Create template" }).click();
  await page.goto("/compose");
  await expect(page.locator('.step[aria-current="step"]')).toContainText("Leads");
  await page.getByRole("button", { name: "Next: template" }).click();
  await page.getByLabel("Template", { exact: true }).selectOption({ label: "E2E intro (v1)" });
  await page.getByRole("button", { name: "Next: review" }).click();
  await expect(page.getByText("Creating drafts sends nothing and approves nothing.")).toBeVisible();
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
  await expect(page.locator("[data-checks]")).toHaveAttribute("data-checks", "12"); // all 12 safety checks listed
  await expect(page.locator("[data-check]")).toHaveCount(12);
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

test("pipeline: stage chips equal the API, closed ones hide, accepting an AI suggestion moves exactly that one", async () => {
  const origin = new URL(page.url()).origin;
  const beta = sql("SELECT id FROM companies WHERE name = 'E2E Beta Vision'");
  const mid = sql(`INSERT INTO inbound_messages (gmail_msgid, mailbox, from_email, from_name, subject, body_text, relevance, label, company_id, received_at)
    VALUES ('e2e-reply-beta', 'all', 'ben@e2e-beta-vision.de', 'Ben Weber', 'Re: Hello Beta', 'We would like an interview.', 'reply_header', 'reply', ${beta}, now())
    RETURNING id`).split("\n")[0];
  sql(`INSERT INTO ai_analyses (inbound_message_id, status, model, prompt_version, label, label_evidence, summary)
    VALUES (${mid}, 'ok', 'fake', 1, 'interview_request', 'We would like an interview.', 'Beta wants an interview.')`);
  const opp = await (await page.request.post("/api/opportunities", { headers: { Origin: origin }, data: { inbound_message_id: Number(mid), title: "Vision Engineer" } })).json();
  const closed = await (await page.request.post("/api/opportunities", { headers: { Origin: origin }, data: { company_id: Number(beta), title: "Closed role" } })).json();
  await page.request.post(`/api/opportunities/${closed.id}/stage`, { headers: { Origin: origin }, data: { stage: "rejected", reason: "position filled" } });
  const other = (await (await page.request.get("/api/opportunities")).json()).opportunities.find((o) => o.title === "Robotics Engineer");

  await page.goto("/opportunities");
  const api = await (await page.request.get("/api/opportunities")).json();
  for (const s of api.stages) {
    await expect(page.locator(`[data-stage-chip="${s}"] [data-count]`)).toHaveText(String(api.counts[s] || 0));
  }
  await expect(page.locator(`[data-opp="${closed.id}"]`)).toHaveCount(0); // closed stages are hidden by default
  await page.getByLabel(/Show closed/).check();
  await expect(page.locator(`[data-opp="${closed.id}"]`)).toBeVisible();
  await page.getByLabel(/Show closed/).uncheck();
  await page.getByRole("tab", { name: "Table" }).click();
  await expect(page.getByRole("row", { name: /Vision Engineer/ })).toContainText("AI: interviewing");
  await page.getByRole("tab", { name: "By stage" }).click();
  const card = page.locator(`[data-opp="${opp.id}"]`);
  await expect(card).toContainText("AI suggests interviewing");
  await card.getByRole("button", { name: "Accept" }).click();
  await expect(page.locator(".toast", { hasText: "Vision Engineer moved to interviewing." })).toBeVisible();
  const after = (await (await page.request.get("/api/opportunities")).json()).opportunities;
  expect(after.find((o) => o.id === opp.id).stage).toBe("interviewing");
  expect(after.find((o) => o.id === other.id).stage).toBe(other.stage); // nothing else moved
  expect(after.find((o) => o.id === closed.id).stage).toBe("rejected");

  await page.goto(`/opportunities/${opp.id}`);
  await expect(page.locator(".stepper-item.current")).toContainText("interviewing");
  await expect(page.locator("[data-history]").first()).toContainText("accepted AI suggestion (interview_request)");
  await page.getByRole("button", { name: "Move to offer" }).click();
  const d = page.getByRole("dialog");
  await d.getByLabel("Reason (optional)").fill("Verbal offer received");
  await d.getByRole("button", { name: "Move to offer" }).click();
  await expect(page.locator(".stepper-item.current")).toContainText("offer");
  await expect(page.locator("[data-history]").first()).toContainText("Verbal offer received");
  await expect(page.locator(".stepper-item.done")).toHaveCount(4); // new, applied, screening, interviewing
});

test("interviews page: upcoming grouped by day with both time zones, past with outcome", async () => {
  const opp = (await (await page.request.get("/api/opportunities")).json()).opportunities.find((o) => o.title === "Robotics Engineer");
  sql(`INSERT INTO interviews (opportunity_id, title, starts_at, time_zone, duration_minutes, kind, location)
       VALUES (${opp.id}, 'Tomorrow chat', now() + interval '1 day', 'America/New_York', 45, 'video', 'https://meet.example/tomorrow')`);
  sql(`INSERT INTO interviews (opportunity_id, title, starts_at, time_zone, status, outcome)
       VALUES (${opp.id}, 'Earlier screen', now() - interval '3 days', 'Europe/Berlin', 'done', 'went well')`);
  await page.goto("/interviews");
  const tomorrow = page.locator('[data-day="Tomorrow"]');
  await expect(tomorrow.locator("[data-interview]")).toHaveCount(1);
  await expect(tomorrow).toContainText("America/New_York");
  await expect(tomorrow.locator("[data-your-time]")).toBeVisible(); // the owner's own time is shown too
  await expect(tomorrow).toContainText("45 min");
  await expect(page.locator('a[href*="meet.example"]')).toHaveCount(0); // meeting links stay plain text
  await expect(page.locator("[data-day]").nth(1)).toContainText("First call"); // the 2030 interview is a later day group
  await page.getByRole("tab", { name: "Past" }).click();
  await expect(page.getByText("Outcome: went well")).toBeVisible();
});

test("dashboard: every KPI equals the API, the chart has one bar per day, panels link out", async () => {
  const pct = (x) => (x === null || x === undefined ? "—" : `${Math.round(x * 1000) / 10}%`);
  for (const [button, period] of [["30 days", "30"], ["All time", "all"]]) {
    await page.goto("/");
    await page.getByRole("button", { name: button, exact: true }).click();
    const api = await (await page.request.get(`/api/dashboard?period=${period}`)).json();
    const k = api.kpis;
    const want = { leads: k.leads.total, sent: k.sent, reply_rate: pct(k.reply_rate), interested: k.interested, offers: k.offers,
                   opportunities: k.opportunities.open, interviews: k.interviews.upcoming, bounces: k.bounces };
    for (const [id, value] of Object.entries(want)) {
      await expect(page.locator(`[data-kpi="${id}"] [data-value]`)).toHaveText(String(value));
    }
    const chart = page.locator("svg[data-bars]");
    if (k.sent > 0) {
      await expect(chart).toHaveAttribute("data-bars", String(api.sent_series.length));
      await expect(chart).toHaveAttribute("data-max", String(Math.max(...api.sent_series.map((x) => x.sent))));
    } else {
      await expect(page.getByText("No emails sent in this period.")).toBeVisible();
    }
  }
  await expect(page.locator('[data-alert="gmail"]')).toBeVisible(); // no Gmail account in the E2E stack
  await expect(page.locator('[data-alert="backup"]')).toHaveCount(0); // a backup was made earlier in this run
  await page.getByRole("link", { name: /^Upcoming interviews/ }).click();
  await expect(page).toHaveURL(/\/interviews$/);
  await page.goto("/");
  await page.locator("section", { hasText: "Recent activity" }).getByRole("link", { name: "View all" }).click();
  await expect(page).toHaveURL(/\/activity$/);
});

test("template page: live preview follows typing and flags an unresolved variable; sending card and history", async () => {
  const list = await (await page.request.get("/api/templates")).json();
  const t = list.find((x) => x.name === "E2E intro");
  await page.goto(`/templates/${t.id}`);
  const subject = page.getByLabel("Subject");
  await subject.fill("Hi {{company_name}} team");
  await expect(page.locator("[data-preview-subject]")).toContainText("team"); // re-rendered while typing
  await subject.fill("Phone: {{my_phone}}"); // not in the E2E profile
  await expect(page.locator("[data-preview-error]")).toContainText("my_phone");
  await subject.fill("Hi {{my_phone | friend}}"); // a fallback resolves it and is announced
  await expect(page.locator("[data-preview-subject]")).toContainText("Hi friend");
  await expect(page.getByText("Fallback text used for: my_phone")).toBeVisible();
  await expect(page.getByText("unsaved changes")).toBeVisible();
  await page.getByRole("button", { name: "Discard changes" }).click();
  await expect(page.getByText("unsaved changes")).toHaveCount(0);
  await page.goto("/outbox");
  const counts = (await (await page.request.get("/api/outbox?status=draft")).json()).counts;
  for (const st of ["draft", "queued", "sent", "failed", "cancelled"]) {
    await expect(page.getByRole("tab", { name: new RegExp(`^${st} \\(${counts[st] || 0}\\)$`) })).toBeVisible();
  }
  await expect(page.getByRole("button", { name: "Enable sending" })).toBeDisabled(); // no Gmail in E2E
  await expect(page.getByText("Connect and test an email account")).toBeVisible();
  await expect(page.getByRole("progressbar", { name: "Daily cap used" })).toBeVisible();
  await page.goto("/history");
  await expect(page.getByRole("heading", { name: "Email history" })).toBeVisible();
  await expect(page.getByRole("tab", { name: /^all \(\d+\)$/ })).toBeVisible();
});

test("inbox: counted label tabs, two panes, selection kept in the URL, links from emails stay plain text", async () => {
  const company = sql("SELECT id FROM companies WHERE name = 'E2E Alpha Robotics'");
  const body = "Hello, we would love to talk. Please book a slot at https://cal.example.com/alpha/intro and send your CV.";
  const mid = sql(`INSERT INTO inbound_messages (gmail_msgid, mailbox, from_email, from_name, subject, body_text, relevance, label, company_id, received_at)
    VALUES ('e2e-reply-1', 'all', 'anna@e2e-alpha-robotics.de', 'Anna Schmidt', 'Re: Hello E2E Alpha', '${body}', 'reply_header', 'reply', ${company}, now())
    RETURNING id`).split("\n")[0];
  sql(`INSERT INTO ai_analyses (inbound_message_id, status, model, prompt_version, label, label_evidence, summary, extracted)
    VALUES (${mid}, 'ok', 'fake', 1, 'interview_request', 'We would love to talk.', 'Alpha invites you to book an intro call.',
    '{"links": [{"url": "https://cal.example.com/alpha/intro", "purpose": "booking", "evidence": "book a slot at https://cal.example.com/alpha/intro"}], "dates": [], "documents": [{"document": "cv", "evidence": "send your CV"}], "contacts": []}')`);
  const list = await (await page.request.get("/api/inbox")).json();
  const replies = list.filter((m) => m.label === "reply").length;
  await page.goto("/inbox");
  await expect(page.getByRole("tab", { name: new RegExp(`^all \\(${list.length}\\)$`) })).toBeVisible();
  await expect(page.getByRole("tab", { name: new RegExp(`^replies \\(${replies}\\)$`) })).toBeVisible();
  await page.getByRole("tab", { name: /^replies/ }).click();
  await expect(page).toHaveURL(/label=reply/);
  await page.getByRole("button", { name: /Anna Schmidt/ }).click();
  await expect(page).toHaveURL(new RegExp(`m=${mid}`));
  const pane = page.getByRole("region", { name: "Message" });
  await expect(pane.getByRole("heading", { name: "Re: Hello E2E Alpha" })).toBeVisible();
  await expect(pane.locator("[data-ai-label]")).toHaveText("interview request");
  await expect(pane.getByText("Alpha invites you to book an intro call.")).toBeVisible();
  // untrusted-link rule: the URL is shown as plain text, never as a link
  await expect(pane.locator("code", { hasText: "https://cal.example.com/alpha/intro" })).toBeVisible();
  await expect(page.locator('a[href*="cal.example.com"]')).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("region", { name: "Message" }).getByRole("heading", { name: "Re: Hello E2E Alpha" })).toBeVisible(); // survived the reload
  await page.getByRole("link", { name: "Open conversation" }).click();
  await expect(page).toHaveURL(new RegExp(`/threads/.*#in-${mid}`));
  await expect(page.locator(`#in-${mid}.target`)).toBeVisible(); // deep link highlights the message
  await expect(page.getByText("The system never replies on its own.")).toBeVisible();
});

test("notifications: grouped by day, mark one read, then all, and the bell follows", async () => {
  const company = sql("SELECT id FROM companies WHERE name = 'E2E Alpha Robotics'");
  sql(`INSERT INTO notifications (kind, source_type, source_id, priority, title, body, link, company_id)
    VALUES ('reply', 'inbound_message', 'e2e-n1', 'normal', 'Reply from Anna E2E', 'Re: Hello', '/inbox', ${company}),
           ('reply', 'inbound_message', 'e2e-n2', 'high', 'Second E2E reply', 'Re: Again', '/inbox', ${company})`);
  await page.goto("/notifications");
  await expect(page.getByRole("heading", { name: "Today" })).toBeVisible();
  const bell = page.getByRole("button", { name: /^Notifications: \d+ unread$/ });
  const before = Number((await bell.getAttribute("aria-label")).match(/\d+/)[0]);
  expect(before).toBeGreaterThanOrEqual(2);
  await page.getByRole("tab", { name: "unread" }).click();
  await page.getByRole("button", { name: /Reply from Anna E2E/ }).click(); // marks it read and opens its link
  await expect(page).toHaveURL(/\/inbox/);
  await page.goto("/notifications");
  await expect(page.getByRole("button", { name: /^Notifications: \d+ unread$/ })).toHaveAttribute("aria-label", `Notifications: ${before - 1} unread`);
  await page.getByRole("button", { name: "Mark all read" }).click();
  await expect(page.getByRole("button", { name: "Notifications: 0 unread" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Mark all read" })).toBeDisabled();
});

test("inbox on a phone: the list first, then the message with a Back button", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 800 }, storageState: await page.context().storageState() });
  const p = await ctx.newPage();
  await p.goto("/inbox");
  await expect(p.getByRole("region", { name: "Message" })).toBeHidden();
  await p.getByRole("button", { name: /Anna Schmidt/ }).first().click();
  await expect(p.getByRole("region", { name: "Message" })).toBeVisible();
  await expect(p.getByRole("region", { name: "Messages" })).toBeHidden();
  await p.getByRole("button", { name: "← Back to list" }).click();
  await expect(p.getByRole("region", { name: "Messages" })).toBeVisible();
  await ctx.close();
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

test("research: three separate sections; a fact added by hand reaches personalization", async () => {
  const leads = await (await page.request.get("/api/leads")).json();
  const beta = leads.leads.find((l) => l.name === "E2E Beta Vision");
  await page.goto(`/companies/${beta.id}`);
  await page.getByRole("tab", { name: "Research" }).click();
  await expect(page.getByRole("heading", { name: /Verified facts/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: /AI claims/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Scraped data/ })).toBeVisible();
  await page.getByLabel("Fact", { exact: true }).fill("Builds computer-vision QA for factories");
  await page.getByLabel("Source", { exact: true }).fill("CEO interview, Tagesspiegel 2026");
  await page.getByRole("button", { name: "Add fact" }).click();
  await expect(page.getByText("Fact added.")).toBeVisible();
  const facts = await (await page.request.get(`/api/companies/${beta.id}/facts`)).json();
  expect(facts.map((f) => f.fact)).toEqual(["Builds computer-vision QA for factories"]);
});

test("personalization: offered on Compose; without AI it says so, and drafts use the fallback", async () => {
  const origin = new URL(page.url()).origin;
  await page.request.post("/api/templates", { headers: { Origin: origin }, data: {
    name: "Personal", subject: "Hello {{company_name}}",
    body: "Hi there,\n{{personal_line | I have followed your work for a while.}}\nBest" } });
  const leads = await (await page.request.get("/api/leads")).json();
  const beta = leads.leads.find((l) => l.name === "E2E Beta Vision");
  await page.request.post("/api/compose-list", { headers: { Origin: origin }, data: { company_ids: [beta.id] } });
  await page.goto("/compose");
  await page.getByRole("button", { name: "Next: template" }).click();
  await page.getByLabel("Template", { exact: true }).selectOption({ label: "Personal (v1)" });
  await page.getByLabel(/Personalize from verified facts/).check();
  await page.getByRole("button", { name: "Next: review" }).click();
  await page.getByRole("button", { name: /Create 1 draft/ }).click();
  await expect(page.locator('p[role="alert"]')).toContainText("AI is off");
  await page.getByRole("button", { name: "Back" }).click();
  await page.getByLabel(/Personalize from verified facts/).uncheck();
  await page.getByRole("button", { name: "Next: review" }).click();
  await page.getByRole("button", { name: /Create 1 draft/ }).click();
  await expect(page.getByText("1 draft(s) created.")).toBeVisible();
  const drafts = await (await page.request.get("/api/outbox?status=draft")).json();
  const mine = drafts.emails.find((e) => e.subject === "Hello E2E Beta Vision");
  const full = await (await page.request.get(`/api/outbound-emails/${mine.id}`)).json();
  expect(full.body).toContain("I have followed your work for a while.");
});

test("leads: filters live in the URL, sorting and paging work, the bulk bar acts on the selection", async () => {
  const origin = new URL(page.url()).origin;
  for (let i = 1; i <= 55; i++) {
    const n = String(i).padStart(2, "0");
    await page.request.post("/api/companies", { headers: { Origin: origin }, data: { name: `Bulk Co ${n}`, domain: `bulk-co-${n}.de`, country: "Austria" } });
  }
  await page.goto("/companies?q=bulk");
  await expect(page.locator(".chip", { hasText: "Name/domain: bulk" })).toBeVisible();
  await expect(page.getByText("1–50 of 55")).toBeVisible();
  await page.getByRole("button", { name: "Next page" }).click();
  await expect(page.getByText("51–55 of 55")).toBeVisible();
  await page.getByRole("button", { name: "Previous page" }).click();
  await page.getByRole("button", { name: /^Name/ }).click(); // sort descending
  await expect(page.locator("tbody tr").first()).toContainText("Bulk Co 55");
  await page.reload();
  await expect(page.locator(".chip", { hasText: "Name/domain: bulk" })).toBeVisible(); // survived the reload
  await expect(page.getByText("1–50 of 55")).toBeVisible();
  await page.getByRole("checkbox", { name: "Select Bulk Co 01" }).check();
  await page.getByRole("checkbox", { name: "Select Bulk Co 02" }).check();
  const bar = page.getByRole("region", { name: "Bulk actions" });
  await expect(bar).toContainText("2 selected");
  await bar.getByLabel("New stage").selectOption("qualified");
  await expect(page.getByText("2 lead(s) moved to qualified.")).toBeVisible();
  const q = await (await page.request.get("/api/leads?q=bulk&stage=qualified")).json();
  expect(q.leads.map((l) => l.name).sort()).toEqual(["Bulk Co 01", "Bulk Co 02"]);
  await page.getByRole("button", { name: "Remove filter Name/domain" }).click();
  await expect(page).toHaveURL(/\/companies$/);
});

test("company page: header, counted tabs, contact dialogs, add to compose list", async () => {
  const leads = await (await page.request.get("/api/leads?q=alpha")).json();
  await page.goto(`/companies/${leads.leads[0].id}`);
  await expect(page.getByRole("heading", { name: "E2E Alpha Robotics" })).toBeVisible();
  await expect(page.getByRole("tab", { name: /^Contacts \(1\)$/ })).toBeVisible();
  await page.getByRole("tab", { name: /^Contacts/ }).click();
  await page.getByRole("button", { name: "Add contact" }).click();
  const d = page.getByRole("dialog", { name: "Add contact" });
  await d.getByLabel("Name").fill("Hanna Recruiter");
  await d.getByLabel("Email", { exact: true }).fill("hanna@e2e-alpha-robotics.de");
  await d.getByRole("button", { name: "Save contact" }).click();
  await expect(page.getByRole("tab", { name: /^Contacts \(2\)$/ })).toBeVisible();
  await expect(page.getByRole("cell", { name: "hanna@e2e-alpha-robotics.de" })).toBeVisible();
  await page.getByRole("row", { name: /Hanna Recruiter/ }).getByRole("button", { name: "Edit" }).click();
  await page.getByRole("dialog").getByLabel("Role").fill("Talent lead");
  await page.getByRole("dialog").getByRole("button", { name: "Save contact" }).click();
  await expect(page.getByRole("cell", { name: "Talent lead" })).toBeVisible();
  await page.getByRole("button", { name: "Add to compose list" }).click();
  await expect(page.locator(".toast", { hasText: "compose list" })).toBeVisible();
});

test("duplicates: pair side by side, merge through the UI, then undo", async () => {
  const origin = new URL(page.url()).origin;
  await page.request.post("/api/companies", { headers: { Origin: origin }, data: { name: "Dupe Labs", domain: "dupe-labs.de" } });
  await page.request.post("/api/companies", { headers: { Origin: origin }, data: { name: "Dupe Labs Careers", domain: "jobs.dupe-labs.de" } });
  await page.goto("/duplicates");
  const pair = page.locator("[data-pair]", { hasText: "Dupe Labs Careers" });
  await expect(pair).toContainText("same domain");
  await pair.getByRole("button", { name: "Keep left" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Merge" }).click();
  await expect(page.getByText(/^Merged/)).toBeVisible();
  const row = page.getByRole("row", { name: /Dupe Labs/ }).first();
  await row.getByRole("button", { name: "Undo" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Undo merge" }).click();
  await expect(page.getByRole("row", { name: /Dupe Labs/ }).first()).toContainText("undone");
});

test("shell: every sidebar link opens its page inside the app shell", async () => {
  await page.goto("/");
  const links = await page.locator("nav.sidebar a.nav-link").evaluateAll((as) => as.map((a) => a.getAttribute("href")));
  expect(links.length).toBe(19);
  for (const href of links) {
    await page.goto(href);
    await expect(page.locator("nav.sidebar a.nav-link[aria-current=page]")).toHaveAttribute("href", href);
    await expect(page.locator(".content h1").first()).toBeVisible();
    await expect(page.getByText("This page couldn’t load")).toHaveCount(0);
  }
  await expect(page.locator(".topbar .pill")).toContainText("Sending off"); // always visible, OFF in E2E
});

test("shell: dark mode is remembered after a reload", async () => {
  await page.goto("/");
  const before = await page.evaluate(() => document.documentElement.dataset.theme || "");
  await page.getByRole("button", { name: /Switch to (dark|light) mode/ }).click();
  const after = await page.evaluate(() => document.documentElement.dataset.theme);
  expect(after).not.toBe(before);
  await page.reload();
  await expect.poll(() => page.evaluate(() => document.documentElement.dataset.theme)).toBe(after);
});

test("shell: in-app dialogs replace browser pop-ups", async () => {
  let browserDialog = false;
  page.on("dialog", (d) => { browserDialog = true; d.dismiss(); });
  await page.request.post("/api/tasks", { headers: { Origin: new URL(page.url()).origin }, data: { title: "E2E dialog task" } });
  await page.goto("/tasks");
  await page.getByRole("button", { name: "Delete task E2E dialog task" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Delete this task?");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByText("E2E dialog task")).toBeVisible();
  await page.getByRole("button", { name: "Delete task E2E dialog task" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await expect(page.getByText("E2E dialog task")).toHaveCount(0);
  expect(browserDialog).toBe(false);
});

test("shell: on a phone the sidebar is a drawer", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 800 }, storageState: await page.context().storageState() });
  const p = await ctx.newPage();
  await p.goto("/");
  await expect(p.locator("nav.sidebar")).not.toBeInViewport();
  await p.getByRole("button", { name: "Open menu" }).click();
  await expect(p.locator("nav.sidebar")).toBeInViewport();
  await p.locator("nav.sidebar").getByRole("link", { name: "Analytics" }).click();
  await expect(p.getByRole("heading", { name: "Analytics" })).toBeVisible();
  await expect(p.locator("nav.sidebar")).not.toBeInViewport();
  await ctx.close();
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
