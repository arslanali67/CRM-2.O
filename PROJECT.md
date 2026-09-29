# Job Outreach CRM: Project Specification

> **This file is the single source of truth for what gets built.**
> Nothing is implemented unless it is described here. See [CLAUDE.md](CLAUDE.md) for the change process.

- **Source:** CRM_MILESTONES.pdf (v1.0 draft, Sept 25, 2026)
- **Spec version:** 1.40
- **Last updated:** 2026-09-28

---

## 1. Purpose

A private, single-user CRM that turns the scraper's company CSVs into human-controlled job outreach:

1. Import company leads from CSV.
2. Compose emails and approve each one individually.
3. Send approved emails safely (exactly once, rate-limited).
4. Detect replies in the inbox.
5. Analyse replies with AI.
6. Track opportunities and interviews.

## 2. Non-negotiable safety rule

The system may **prepare, personalize and, only after explicit per-email approval, send**.

It must **never**:
- automatically reply to anyone
- automatically send follow-ups
- negotiate
- apply to jobs
- message anyone on LinkedIn

If a company replies, the system **only notifies and analyses**. Follow-ups are tasks for the owner, never emails.

Suppression and safety checks are built **before** any sending code exists.

## 3. Tech stack

| Layer | Choice |
|---|---|
| Orchestration | Docker Compose |
| Frontend | Next.js |
| Backend API | FastAPI (Python) |
| Database | PostgreSQL |
| Queue / cache | Redis |
| Background jobs | Celery |
| Email | Personal Gmail over SMTP+IMAP with an app password (see §8 Q1) |
| AI | Gemini API free tier, for testing; provider stays switchable in Settings (see §8 Q2) |
| Hosting | Owner's laptop only, localhost (see §8 Q3) |

Users: exactly one (the owner). Owner login only.

---

## 4. Milestones

Tags: **[SAFETY]** outbound-risk control · **[AI]** LLM involved · **[CORE]** critical path

### Phase 0: Discovery (Done)

- **M0 Project discovery.** Scraper analysis (`ai_companies.py`, 91-row Berlin CSV), architecture, database, API, AI and email design, blueprint.
  - Done when: the blueprint is approved and the open questions (§8) are answered.

### Phase 1A: Foundation & Data (Weeks 1–6)

Goal: clean companies in, nothing sent out yet.

- **M1 Project foundation [CORE].** Docker Compose (Next.js, FastAPI, Postgres, Redis, Celery), owner login, logging, CI.
  - Depends on: M0. Done when: `make up` works, login works, CI is green.
- **M2 Database foundation [SAFETY].** Migrations, partial unique indexes, a database constraint enforcing "no send without approval", append-only audit log.
  - **Migrations:** plain `.sql` files in `backend/migrations/`, applied in order by a small psycopg runner, tracked in `schema_migrations`. Run automatically on API start. No ORM/Alembic.
  - **`outbound_emails`:** recipient, subject, body, status (`draft` / `approved` / `queued` / `sending` / `sent` / `failed` / `cancelled`), DB-generated `content_hash` (SHA-256 of recipient+subject+body), `approved_at`, `approved_content_hash`, `sent_at`, `provider_message_id`, `idempotency_key`, timestamps.
    - CHECK: status `approved`/`queued`/`sending`/`sent` requires `approved_at` set and `approved_content_hash = content_hash` (editing content after approval is rejected unless reset to draft).
    - CHECK: status `sent` requires `sent_at`.
    - Partial unique index: at most one in-flight (`approved`/`queued`/`sending`) email per recipient (case-insensitive).
    - Unique: `idempotency_key`; `provider_message_id` where not null.
  - **`audit_log`:** timestamp, actor, action, entity type/id, JSON data. Append-only: triggers reject UPDATE, DELETE and TRUNCATE.
  - **Tests:** every constraint tested against a real Postgres test database, locally and in CI.
  - Company/contact tables and the duplicate-domain index are M5; automatic activity logging is M24.
  - Depends on: M1. Done when: constraint tests pass on real Postgres.
- **M3 Personal profile & CV.** Skills, experience, links, preferences; CV versions; `{{my_*}}` template variables.
  - **Profile (single record):** full name, email, phone, location, headline, summary; skills (list); experience entries (title, company, start, end — empty end = current job — description); links (LinkedIn, GitHub, portfolio); preferences (target roles, target locations, work mode: remote / hybrid / onsite / any, availability).
  - **CV versions:** PDF only (magic-byte check), max 5 MB, stored in Postgres so backups include them. Each version has a label; versions are immutable (re-upload = new version). Exactly one default, enforced by the database. Download any version.
  - **Variables (16):** `my_full_name`, `my_first_name`, `my_email`, `my_phone`, `my_location`, `my_headline`, `my_summary`, `my_skills`, `my_top_skills` (first 3 skills), `my_current_title`, `my_current_company` (from the experience entry with no end date), `my_linkedin`, `my_github`, `my_portfolio`, `my_target_role` (first target role), `my_availability`. Empty variables are reported as unresolved, never rendered blank.
  - **UI:** Profile page with the form, CV version list (upload, set default, download) and a live preview of every variable, with unresolved ones flagged.
  - Profile saves, CV uploads and default changes are written to `audit_log`.
  - Depends on: M2. Done when: all `my_*` variables resolve and a default CV is set.
- **M5 Companies & contacts [CORE].** CRUD, provenance (where each record came from), email classes: careers / personal / generic / unsuitable.
  - **Companies:** name (required), domain (normalized: lowercase, no scheme/`www.`/path), website, industry, city, country, description, LinkedIn URL. DB-enforced: no two active companies share a domain.
  - **Contacts:** company (required), name, email, role, phone, LinkedIn URL; at least a name or an email. DB-enforced: no two active contacts share an email (case-insensitive).
  - **Delete = archive** (`archived_at`), with restore. Nothing is hard-deleted.
  - **Provenance:** `source` (`manual` / `csv_import`) plus source detail (file name, row number; filled by M4), created/updated timestamps.
  - **Email classes (rules on the local part):** `careers` (jobs, careers, karriere, bewerbung, hr, recruiting, talent, personal, …), `generic` (info, contact, kontakt, hello, office, team, mail, support, sales, …), `unsuitable` (noreply, datenschutz, privacy, abuse, postmaster, billing, rechnung, presse, legal, newsletter, …, and malformed addresses), otherwise `personal`. Manual override per contact; a manual class is never overwritten by the rules.
  - **UI:** Companies list (active, optionally archived) with add form; company page to edit it and add/edit/archive its contacts with class override.
  - Create, update, archive and restore are written to `audit_log`.
  - Depends on: M2. Done when: CRUD and email classification are tested.
- **M25 Do-not-contact list [SAFETY].** Block by email, domain or company, with an audited override.
  - **Block types:** email (exact address); domain (the domain and all its subdomains); company (the company's domain and subdomains, plus every contact stored under that company). Each block needs a reason. At most one active block per email / domain / company.
  - **Audited override = lift:** lifting a block requires a written reason. Blocks are never deleted or edited (DB-enforced); a lifted block stays listed with when and why. Adding and lifting are written to `audit_log`.
  - **DB enforcement:** a trigger refuses any `outbound_emails` insert/update into `approved` / `queued` / `sending` whose recipient is actively blocked. Adding a block automatically cancels matching `approved` / `queued` emails, each cancellation written to `audit_log`. An email already `sending` cannot be recalled; M12's pre-send check covers it.
  - **UI:** Do-not-contact page (add block, list active and lifted blocks, lift with reason). Company page: "Block company" button and a "blocked" badge on suppressed contacts.
  - Blocked rows during CSV import are handled in M4.
  - Depends on: M5. Done when: no code path can send to a suppressed recipient.
- **M4 CSV import [CORE].** Upload, `ai_companies` preset, batch city/country, validation, preview, error CSV download, dedupe on import.
  - **Flow:** upload CSV (max 5 MB, 5,000 rows; UTF-8, fallback Windows-1252) with batch city/country → preview (per row: new / duplicate / blocked / error, plus contacts to add and skipped emails) → Import commits the same file. Nothing is written on preview.
  - **`ai_companies` preset:** `company` → name; `website` → website + domain; `field` → industry; `linkedin` → company LinkedIn; `all_emails` → one contact per usable email (auto-classified); `contact_name` → one name-only contact per person (comma-separated); `twitter`, `github`, `facebook`, `instagram`, `remote_jobs`, `is_ai`, `mentions_city`, `source` → kept in the company's `source_detail` with file name and row number.
  - **Email cleaning:** strip scraping artifacts (leading `u003e`/`u003c`/`%20`); drop placeholders (`muster.de`, `firma.de`, `company.com`, `example.com`, …) and addresses with a top-level domain over 10 letters; off-domain addresses kept only if same brand (company domain label contained in the email's domain label or vice versa). Every skipped email is reported with its reason.
  - **Dedupe:** row whose domain matches an active company → skipped; email already on an active contact → skipped; repeated email within the file → imported once.
  - **Blocked (M25):** row whose domain or company is blocked → skipped; blocked email → skipped.
  - **Error CSV:** rejected rows with a reason column, downloadable.
  - **Provenance & audit:** companies/contacts get `source = csv_import` with file and row; each import writes one `import.completed` audit entry with counts.
  - The real scraped CSV is never committed (public repo); tests use a synthetic sample; the 91/0 criterion is verified locally on the test database.
  - Depends on: M5, M25. Done when: the Berlin CSV imports as 91 companies and re-import creates 0 duplicates.
- **M6 Lead management.** Stages NEW → … → CLOSED, filters, bulk select to hand off to the composer.
  - **A lead is a company.** Stages: `new` → `qualified` → `contacted` → `replied` → `closed`, plus `on_hold` (reachable from any stage). Closing requires a reason. Manual changes now; M12 will set `contacted` and M15 `replied`.
  - **Stage changes are DB-logged** (trigger → `audit_log` `company.stage_changed` with from/to and close reason).
  - **Leads page** (replaces the Companies list): filters for stage, country, city, industry (contains), source, has usable email, has careers email, show blocked (hidden by default); up to 500 rows; row checkboxes and select-all-shown.
  - **Bulk actions:** set stage; add to compose list.
  - **Compose list (hand-off to M10):** saved list of companies with a best recipient each: active, unblocked contact; careers > personal > generic; never unsuitable. Blocked companies and companies without an eligible recipient are refused with a reason. Removable. Compose page shows the list until M10 adds writing and approval.
  - Depends on: M4, M5. Done when: leads can be filtered, selected and handed to the composer.
- **M24 Activity timeline.** Every state change logged. Built here, extended by each later milestone.
  - **Email events, DB-enforced:** triggers on `outbound_emails` write an `audit_log` row on creation (`outbound_email.created`) and on every status change (`outbound_email.<new status>`), with from/to status and recipient. No code path can change an email's status unlogged.
  - **Actor:** `owner` for requests made through the app (set per DB connection), `system` otherwise (e.g. M25 auto-cancel, which now logs through the same trigger with the suppression that caused it: one row per cancellation).
  - Other entities keep their app-level audit entries (M3, M5, M25); later milestones add theirs.
  - **UI:** Activity page (global feed, newest first, load more) and a Timeline section on each company page (company, its contacts, its blocks, and emails to its contacts or domain), shown in plain language.
  - Index on `audit_log (entity_type, entity_id, id)`.
  - Depends on: M2. Done when: approved / queued / sent events are logged per email.

**Phase exit:** the real Berlin CSV imports to 91 companies, re-import creates zero duplicates, and leads are filterable.

### Phase 1B: Outreach (Weeks 7–12)

Goal: approve every email, send exactly once.

- **M8 Email templates.** Variables, strict rendering (an unresolved variable is an error, never blank), immutable versions.
  - **Templates:** name + versions; each version has a plain-text subject and body. Saving an edit creates a new version; versions are immutable and never deleted (DB-enforced). The latest version is current. Archive/restore. All changes audited.
  - **Variables (26):** the 16 `my_*` (M3); `company_name`, `company_domain`, `company_website`, `company_city`, `company_country`, `company_industry`; `contact_name`, `contact_first_name`, `contact_role`, `contact_email`.
  - **Save-time checks:** unknown variable names and malformed braces are rejected with the exact problem.
  - **Render-time checks:** any variable without a value fails rendering and lists every unresolved variable; never rendered blank. Optional fallback syntax `{{var | fallback}}` renders the fallback when the value is empty.
  - **UI:** Templates page (list, create, edit → new version, version history, archive), variable reference with click-to-insert, preview against a chosen lead using its best recipient (M6).
  - Depends on: M3, M6. Done when: templates are versioned and unresolved variables are always caught.
- **M21 Notes & tasks.** Notes on every entity; follow-ups are tasks for the owner, never emails.
  - **Notes** on companies, contacts and templates (M19/M20 add opportunities and interviews): plain text, created/edited times, edit, soft delete (hidden but kept). All changes audited.
  - **Tasks** for the owner: title, optional date-only due date, optional details, optionally linked to a company / contact / template; done/reopen, edit, soft delete. Tasks have no link to sending and can never trigger an email.
  - **"Today"** is the owner's browser date (sent with the request), so due status follows the laptop's timezone.
  - **UI:** Tasks page grouped Overdue / Today / Upcoming / No date / Done; Home shows overdue and due-today counts. Company page: company notes and tasks plus per-contact notes. Template page: notes and tasks. Quick follow-up buttons (+3 days, +1 week).
  - Depends on: M5. Done when: notes/tasks appear on every entity page and the due list is correct.
- **M26 Email safety controls [SAFETY].** 12 checks, run at approval **and** again at send (suppression, duplicates, unresolved variables, limits, …).
  - **The 12 checks:**
    1. Do-not-contact: recipient address/domain/company not blocked.
    2. Valid address: well-formed, not a placeholder, sane top-level domain.
    3. Known, suitable contact: recipient is an active stored contact whose class is not `unsuitable`.
    4. Active lead: company not archived; stage not `closed` or `on_hold`.
    5. No duplicate in flight: no other approved/queued/sending email to the same address.
    6. Recipient cooldown: no email sent to this address in the last 30 days.
    7. Company cooldown: no email sent to anyone at this company in the last 14 days.
    8. Variables resolved: no `{{…}}` or stray braces left in subject or body.
    9. Content complete: subject 1–200 characters, body 1–20,000 characters.
    10. Approval valid (send only): approval present, content unchanged since approval, approval at most 7 days old.
    11. Rate limits: at send, fewer than 20 sent in the last 24 hours and at least 90 s since the last send; at approval, fewer than 20 already approved/queued/sending.
    12. Kill switch (send only): sending is enabled.
  - **Approval** runs all approval-stage checks; any failure refuses approval and names every failed check.
  - **Send** re-runs all 12 under a row lock. Failures of 11–12 are temporary (the email waits in the queue); any other failure cancels the email with the reasons.
  - Failed check runs are written to `audit_log`.
  - **Schema:** `outbound_emails` gains `contact_id`, `company_id`, `template_version_id`; a single-row `app_settings` holds `sending_enabled` (default **off**), daily cap 20, gap 90 s, cooldowns 30 / 14 days, approval max age 7 days. UI for settings is M29; kill-switch toggle is M12.
  - Depends on: M25, M8. Done when: all 12 gates are tested and re-checked at send time.
- **M10 Email composer [SAFETY].** Exact preview, per-email approval bound to a content hash (editing after approval voids approval), no "approve all".
  - **Create drafts** from the compose list with a chosen template: each company gets a draft rendered strictly for its best recipient, linked to company, contact and template version; companies with unresolved variables or no eligible recipient are skipped with reasons; drafted companies leave the compose list.
  - **CV attachment (owner's choice in the UI):** "Attach CV" option when creating drafts (CV picker, default CV preselected, unticked by default) and per draft (change or remove). The attached CV version is part of the content hash, so changing it after approval requires re-approval.
  - **Outbox:** Drafts / Queued / Sent / Cancelled (with reasons). **Draft page:** exact preview (From, To, Subject, Body, attachment), edit subject/body/attachment, discard, M26 check results.
  - **Approval:** per email only, one click "Approve & queue": the UI sends the content hash it displayed; a mismatch is refused; then M26 `approve()` runs all checks; on success the email is queued. No bulk-approve endpoint or button exists (tested). Queued emails can be pulled back to draft (clears the approval).
  - Depends on: M8, M26. Done when: nothing is queued without per-email approval.
- **M11 Email provider integration [CORE].** SMTP+IMAP adapter for personal Gmail using an app password (no OAuth), credentials encrypted at rest. Other providers are Phase 3.
  - **Encryption (pulled forward from M30):** app password encrypted with Fernet (`cryptography` dependency); key only in `.env` as `CREDENTIALS_KEY`, never in the DB. Lost key = re-enter the app password.
  - **Account record (single):** Gmail address, display name, fixed Gmail servers (smtp.gmail.com:465 SSL, imap.gmail.com:993 SSL), encrypted password, connected / last-tested times and result.
  - **Secrecy:** the password is never returned by the API (only whether one is stored), never logged or audited, never pre-filled; spaces are stripped.
  - **Test connection:** SMTP login without sending and IMAP login with read-only inbox select; per-protocol result; 15 s timeouts.
  - **UI:** Email account page (connect, test, disconnect = wipe password). Composer "From" shows the connected address.
  - Sending is M12; inbox reading is M14. Tests use a fake mail server.
  - The owner enters the real app password themselves (Claude never handles it).
  - Depends on: M1, M30. Done when: the Gmail account is connected and credentials are encrypted.
- **M12 Email sending [SAFETY].** Single-lane queue, daily cap and minimum gap, idempotency, Message-ID recovery, kill switch.
  - **Queue:** a Celery `beat` service ticks every 30 s; the worker takes a Postgres advisory lock (only one sender ever runs) and sends at most one email per tick, the oldest queued. M26 `claim_for_send()` re-checks all 12 gates (11–12 → wait; others → cancel).
  - **Exactly once:** a unique Message-ID is stored before the SMTP attempt. An email left in `sending` (crash / dropped connection) is recovered next tick by searching the Gmail Sent folder (IMAP, read-only) for that Message-ID: found → `sent`; not found after 10 minutes → `failed` ("needs review"). Never resent automatically. Definite SMTP rejections → `failed` with the reason.
  - **Kill switch:** Enable / Stop sending on the Outbox page; enabling requires a connected, tested account and confirmation; audited both ways; off by default.
  - **Message:** exactly the approved content, plain text, from the connected Gmail with display name, CV PDF attached if chosen.
  - **After send:** `sent_at` and Message-ID recorded; lead stage `new`/`qualified` → `contacted`.
  - Tests use fake SMTP/IMAP; a guard fails any attempt to reach real Gmail from tests. No real email is sent while building M12; the Phase 1B real test send waits for the owner's explicit go-ahead.
  - Depends on: M10, M11, M26. Done when: sending is exactly-once and the safety tests are green.
- **M13 Email history.** Statuses, timestamps, provider IDs, threads.
  - **Provider IDs:** besides the Message-ID, the worker looks each sent email up in Gmail Sent (IMAP, read-only) and stores Gmail's message ID and thread ID. Best-effort: retried on later ticks for up to 24 h; never blocks sending.
  - **History page:** every email past draft (queued / sending / sent / failed / cancelled); filters by status, company, date range; search by recipient or subject; key timestamps and reasons per row.
  - **Email detail:** status timeline from `audit_log` (every change with time, actor, reason), provider IDs, thread.
  - **Threads:** emails grouped by Gmail thread ID (an email without one yet is its own thread); thread view lists the conversation in order. Replies join threads in M14/M15.
  - **Company page:** Emails section grouped by thread.
  - Depends on: M12. Done when: every sent email is in history with its thread.

**Phase exit:** a real test email reaches the owner's second inbox, and duplicate, do-not-contact and kill-switch tests all block sends.

### Phase 1C: Replies (Weeks 13–16)

Goal: never miss a reply, never answer automatically.

- **M14 Inbox synchronization [CORE].** Incremental cursor-based polling, idempotent storage, resync handling.
  - **Read-only:** mailboxes opened read-only, bodies fetched with `BODY.PEEK` (nothing marked read); nothing moved, deleted or sent.
  - **Mailboxes:** Gmail All Mail and Spam (found by special-use flags); messages from the owner's own address are skipped.
  - **Cursor:** per mailbox UIDVALIDITY + last UID; incremental fetch in batches; first sync looks back 14 days. UIDVALIDITY change → rescan by date. Daily safety re-scan of the last 2 days. Errors recorded, retried next run.
  - **Idempotent:** keyed by Gmail message ID (X-GM-MSGID), so re-fetching never duplicates.
  - **Only relevant messages stored** (owner's choice): headers are checked first; a message is stored in full only if it is in a Gmail thread the owner started, references one of the owner's Message-IDs (In-Reply-To / References), comes from a known contact or company domain, or is a bounce (Mailer-Daemon / postmaster) arriving within 3 days after a CRM send (personal bounces are not stored). Others are only counted.
  - **Stored per message:** Gmail message/thread IDs, headers (From, To, Subject, Date, Message-ID, In-Reply-To, References), plain-text body up to 100 KB, attachment names only (never contents).
  - **Schedule:** every 2 minutes via beat, own lock, independent of the sending kill switch.
  - **UI:** Inbox page (stored messages, sync status, Sync now); inbound messages appear in thread views and company Emails. Classification is M15.
  - **Soak:** simulated 24 h in tests, plus a real read-only 24 h run with a stored-vs-Gmail reconciliation.
  - Depends on: M11, M13. Done when: a 24 h soak test shows no missed and no duplicate messages.
- **M15 Reply detection.** Rule-based, no AI, in this order: bounce → auto-reply/OOO → thread match → sender match → unrelated.
  - **Rules (first match wins):** (1) **bounce**: `multipart/report` delivery-status or Mailer-Daemon/postmaster sender; DSN parsed for failed recipient, status (5.x.x hard, 4.x.x soft/delayed) and original Message-ID (links the bounced CRM email). (2) **auto_reply**: `Auto-Submitted: auto-replied/auto-generated`, `X-Autoreply`, `X-Autorespond`, `Precedence: auto_reply/bulk`, or OOO subjects (Out of Office, Automatic reply, Abwesenheitsnotiz, Automatische Antwort, …). (3) **reply** by thread: references one of our Message-IDs or is in one of our Gmail threads. (4) **reply** by sender: known contact or company domain that was emailed in the last 60 days, and not mailing-list mail (`List-Id` / `List-Unsubscribe`) nor machine mail (`Auto-Submitted`, or an unsuitable sender such as noreply@). (5) **unrelated**: everything else.
  - Runs on ingestion and can be re-run over all stored messages. M14 additionally stores Auto-Submitted, Precedence, X-Autoreply, X-Autorespond, List-Id, List-Unsubscribe, Content-Type and the parsed DSN fields.
  - **Effects (never sends anything):** reply → lead stage `replied`; auto-reply → recorded only; bounce → CRM email marked bounced (hard/soft). Owner-approved protective actions: **hard bounce → do-not-contact** for that address (reason with status code; liftable); **reply → cancel pending** approved/queued emails to that company (reason "company replied; review first").
  - **UI:** label badge and filter in Inbox; labels in threads and on company pages. Notifications are M17.
  - Tests: realistic `.eml` fixture corpus (hard/soft bounces incl. Exchange NDR, Outlook and German OOO, header-only auto-reply, in-thread reply, colleague reply, company newsletter, personal mail).
  - Depends on: M14. Done when: 100% correct on bounce/OOO/reply fixtures.
- **M16 AI reply analysis [AI].** 12 classification labels; extraction of dates, links and documents, each field with a verbatim evidence quote.
  - **Labels (12):** `interview_request`, `interested`, `needs_info`, `scheduling`, `application_redirect`, `referral`, `keep_on_file`, `not_hiring`, `rejection`, `offer`, `unsubscribe_request` (suggestion only; the AI never blocks), `other`.
  - **Extraction:** dates (interview slots, deadlines, start dates, availability), links (portal, booking, assessment, video call), requested documents, contact people (referrals), plus a label evidence quote.
  - **Evidence enforced in code:** every quote must appear verbatim (whitespace-normalised) in the analysed text; links must appear literally; anything unverified is dropped and logged. No action is ever triggered by AI output.
  - **Scope & privacy:** only M15 `reply` messages are analysed; quoted history (e.g. `>` lines, "On … wrote:") is stripped before sending; email text is treated as untrusted data. Gemini free tier (Google may use free-tier inputs).
  - **Runs:** background task every 2 minutes, up to 5 new replies per run, throttled; manual re-run. Results on Inbox and thread pages.
  - **Config:** `GEMINI_API_KEY` in `.env` (added by the owner), model name configurable.
  - **Evaluation:** ~40 synthetic reply emails (English/German, all labels); automated tests use a fake Gemini; the ≥90% check is one real run through the owner's key (approved).
  - **Sample eval (owner decision 2026-09-29):** the real run uses a sample of 12 items, one per label (`run_ai_eval --sample`), which fits one day's free-tier quota; pass = at least 11/12 correct and 0 stored fields without evidence. The full 40-item run stays available.
  - Depends on: M15. Done when: ≥90% label accuracy (sample: ≥11/12) and 0 extracted fields without evidence.
- **M17 Notifications.** Bell icon, priority by classification, deep link to the reply.
  - **Events (owner-approved):** inbound message labelled reply / auto_reply / bounce (never unrelated); email ending `failed`, or `cancelled` by send-time safety checks or because the company replied; inbox sync failing 3 runs in a row; AI analysis failing after all retries.
  - **Exactly once, DB-enforced:** notifications are created by database triggers with a unique key per (event kind, source); a later AI analysis updates the same notification's priority/summary instead of adding one.
  - **Priority:** high = AI offer / interview_request / scheduling / needs_info; normal = AI interested / referral / application_redirect / unsubscribe_request, unanalysed reply, hard bounce, sending and system problems; low = AI keep_on_file / not_hiring / rejection / other, auto-reply, soft bounce.
  - **Deep link:** to the thread, scrolled to and highlighting the message (or to the email / Inbox for non-message events).
  - **UI:** top bar with bell and unread count on every page (refresh every 30 s), dropdown of latest, Notifications page, mark read / mark all read. In-app only; nothing is emailed.
  - Depends on: M16 (works with M15 labels; AI priority applies once analyses exist). Done when: exactly one notification per event, deep-linked.
- **M18 Dashboard.** KPIs: leads, sent, replies, reply rate, interested, opportunities, interviews, offers; activity feeds.
  - **Period:** 7 / 30 / 90 days or all time.
  - **KPIs:** leads = active companies (+ by stage); sent = emails sent in period (+ daily series); replies = inbound labelled `reply` in period (+ distinct companies); reply rate = companies that replied ÷ companies emailed in period; interested = replies with AI label interested / interview_request / scheduling / needs_info / offer; offers = AI label offer; bounces and auto-replies as health signals.
  - **Opportunities and interviews:** placeholder tiles until M19 / M20 wire in real counts (owner's choice; no proxies).
  - **Feeds:** latest replies (with labels), upcoming and overdue tasks, recent activity.
  - **Performance:** one API call, indexed queries; measured < 500 ms with 10k companies and thousands of emails. Tests recompute every KPI with independent SQL.
  - Depends on: M17. Done when: KPIs match SQL checks and the page loads in <500 ms.

**Phase exit:** a reply appears within one sync interval, correctly labelled, and the provider records **zero** automatic sends.

### Phase 1D: Workspace & Hardening (Weeks 17–22)

Goal: ready for daily use.

- **M23 Company / contact detail.** 360° page: contacts, emails, replies, opportunity, notes, tasks, timeline.
  - **Company page:** summary header (stage, domain, blocked, last emailed, last reply + AI label, counts of contacts / emails / replies / open tasks) and tabs: Overview (editable details, stage, block, latest reply + AI summary), Contacts (each links to its page), Emails & replies (by thread), Notes, Tasks, Timeline, Opportunity (placeholder until M19).
  - **Contact page** `/contacts/{id}`: details, email class, blocked status, emails sent to them, their replies, their notes, tasks and timeline (own events plus emails to/from their address).
  - **API:** `GET /companies/{id}/overview`, `GET /contacts/{id}`, contact timeline.
  - Test: a company with every kind of related record; each must appear on the company or contact page with a working link.
  - Depends on: M13, M15, M21. Done when: every related record is reachable from the page.
- **M22 Search & filtering.** Global search plus filters by country, industry, stage, reply, template, date.
  - **Global search** in the top bar (≥ 2 characters): companies (name, domain), contacts (name, email), sent emails (subject, recipient), replies (subject, sender), templates (name), notes (text); top 5 per kind, grouped, each linked.
  - **New Leads filters:** name/domain contains; reply (replied / not replied / reply with a given AI label); emailed with template X; last emailed between, last reply between, added between. Combine with the existing M6 filters.
  - **Speed:** Postgres `pg_trgm` trigram indexes (built into Postgres, no new package). Global search and filtered Leads each < 300 ms at 10k companies, 20k contacts, 10k emails, 5k replies.
  - Depends on: M5, M13. Done when: <300 ms at 10k companies.
- **M19 Job opportunity pipeline.** Stages NEW → … → OFFER → HIRED; only factual events change a stage automatically.
  - **Stages (owner's choice, closes §7 gap):** `new` → `applied` → `screening` → `interviewing` → `offer` → `hired`, plus `rejected` and `withdrawn`.
  - **Opportunity:** role title, company, contact, source reply (inbound message), stage; stage history logged by a DB trigger (from, to, when, actor, reason).
  - **Creation:** one click "Create opportunity" on a reply (Inbox, thread, company page), prefilled from the reply and its AI label; never automatic.
  - **Only facts move stages automatically:** creation from a reply (`new`); recording an interview in M20 (→ `interviewing`). AI labels never move a stage; they only show a one-click suggestion. Manual stage changes are always allowed, with an optional note.
  - **UI:** Opportunities page grouped by stage (Kanban is Phase 3); opportunity page (stage, history, linked reply/thread, contact, AI suggestion, notes, tasks); the company Opportunity tab and dashboard Opportunities KPI become real. Notes and tasks accept `opportunity`.
  - Depends on: M16. Done when: reply → opportunity → all stages, with history.
- **M29 Settings.** Email account, AI provider, limits, notifications, cooldowns.
  - **Settings page `/settings`:** sending limits (daily cap 1–100, gap 30–3600 s, approval validity 1–30 days); cooldowns (recipient / company 0–365 days); AI (on/off, model name validated against Google's model list, key presence only); notification kinds (reply, auto-reply, bounce, sending problems, system problems; all on by default); email account summary linking to its page.
  - **Rules:** the kill switch stays on the Outbox (settings cannot enable sending); the AI key stays in `.env`; every change audited with before/after; all values read fresh from the DB on use (no restart).
  - Depends on: M11, M16. Done when: settings are validated, audited and applied without restart.
- **M7 Duplicate management.** Match by domain / email / LinkedIn / name; merge with snapshot and undo.
  - **Suggestions only:** a Duplicates page lists pairs of active companies that probably match, with the reason: same main domain in another form (e.g. `acme.de` / `jobs.acme.de`, or `acme.de` / `acme.com` with the same name); a contact's email domain equals the other company's domain; same company LinkedIn URL; very similar names (pg_trgm). Nothing merges automatically; a pair can be dismissed as "not a duplicate".
  - **Merge (owner picks the survivor):** all records of the other company move to the survivor (contacts, sent/received emails, opportunities, notes, tasks, notifications, compose list); the other company is archived; blank survivor fields are filled from it.
  - **Snapshot & undo:** the merge stores exactly which rows moved and the survivor's previous fields. Undo moves those rows back and un-archives the other company; records created after the merge stay. Merge and undo are audited.
  - **Safety:** a do-not-contact block on either company carries over to the survivor; merge is refused while either company has an email approved, queued or sending; undo is refused with the reason if it would break a rule (e.g. the domain is now taken by another active company).
  - Depends on: M4, M5. Done when: merge + undo work and no duplicate active domains exist.
- **M32 Backup & recovery [SAFETY].** Nightly `pg_dump`, restore with sending disabled, CSV and full export.
  - Depends on: M1, M2. Done when: the restore drill passes and sending is off after restore.
  - **Daily catch-up backup:** whenever the app runs and the last good backup is older than 24 h, `pg_dump` (custom format, includes CVs) writes to the git-ignored `backups/` folder with a manifest of row counts; the last 14 are kept. PostgreSQL 18 client tools (from postgresql.org) are added to the backend image.
  - **Backup page `/backup`:** last backup time/size, list of backups, "Back up now"; a dashboard warning when the last backup is older than 48 h.
  - **Restore (CLI only, never in the web UI):** `make restore FILE=…` stops worker and beat, restores, then before anything runs: sending forced OFF; approved/queued emails go back to draft (fresh approval needed); an email caught mid-send is marked failed ("check Gmail Sent before resending"); the restore is audited.
  - **Restore drill:** `make restore-drill` restores the newest backup into a throwaway database and checks row counts against the manifest, safety triggers present, sending off, CVs readable; then drops it. An automated test does the same on test data.
  - **Exports** (on `/backup`): CSV of companies, contacts, sent emails and replies; full export ZIP of every table as JSON plus CV PDFs, excluding the encrypted app password.
  - `.env` is not in backups; the owner keeps a copy (without it, reconnect Gmail after a restore).
- **M30 Security [SAFETY].** Encryption, CSRF protection, redacted logs, localhost binding, prompt-injection hardening.
  - Continuous. Done when: the security checklist is fully green.
  - **Security checklist** (each item has an automated check):
    1. Gmail app password encrypted (Fernet), never returned by the API, never exported.
    2. Localhost binding: only web is published, on 127.0.0.1; Postgres, Redis and API have no published ports (test on the compose file).
    3. Validation errors never echo rejected input.
    4. Prompt injection: email is untrusted data, fixed output schema, every claim must quote the email, links http(s) and present in the email; AI output can never send, approve or change a stage (tested with a hostile email and a compliant fake model).
    5. Upload limits (CV PDF 5 MB with magic bytes, CSV 5 MB / 5000 rows); no raw-HTML rendering in the frontend.
    6. CSRF: SameSite=Strict session cookie plus rejection (403) of cross-site state-changing requests (`Origin` / `Sec-Fetch-Site`).
    7. Login brute force: 5 failures within 15 min lock logins for 15 min.
    8. Redacted logs: email addresses and `.env` secret values are masked in API and worker logs.
    9. Security headers on every page: frame blocking, content-security policy, nosniff, no-referrer.
    10. Header injection: the database rejects line breaks in email subjects and recipients.
    11. Weak secrets: the app refuses to start with a `SESSION_SECRET` shorter than 32 characters.
    12. CI secret scan (small script, no new tool): tracked files must not contain API keys, Fernet keys or `.env` files.
    13. CI dependency audit: `pip-audit` (CI-only tool) and `npm audit` fail on known high-severity vulnerabilities.
  - **Owner to-dos (listed, not gating):** rotate the Gemini key that was pasted into chat; enable disk encryption (BitLocker); keep a private copy of `.env`.
- **M31 Testing [SAFETY].** Unit, integration, API, E2E, plus safety suite S1–S12 (e.g. reply → no send, no reply → no follow-up).
  - Continuous. Done when: safety suite S1–S12 and CI are green.
  - **Safety suite S1–S12** (`tests/test_safety_suite.py`, one named test per case, end to end through API, database, sender and inbox sync with the fake Gmail):
    - S1 Reply → no send: a company reply cancels its pending emails; nothing more is sent to it automatically.
    - S2 No reply → no follow-up: time passes without a reply; no email is created or sent; follow-ups exist only as owner tasks.
    - S3 No approval → no send: drafts never send; the database refuses queued/sent without a matching approval.
    - S4 Edit voids approval: any change to recipient, subject, body or CV after approval blocks sending until re-approved.
    - S5 Exactly once: one approval sends one email; no bulk approve; a crash mid-send never sends twice.
    - S6 Do-not-contact: blocked email/domain/company never receives mail; blocking cancels pending emails; a hard bounce blocks the address.
    - S7 Kill switch: sending OFF sends nothing; switching off applies before the next email; Settings cannot enable it; a restore forces it off.
    - S8 Limits: daily cap, minimum gap and recipient/company cooldowns enforced at send time.
    - S9 Inbound never triggers outbound: replies, auto-replies, bounces, unrelated mail and spam never create or send an email.
    - S10 AI cannot act: AI output (even from a hostile email) never sends, approves, changes a stage or creates an opportunity.
    - S11 No other channels: the code only contacts Gmail SMTP/IMAP and Gemini (network calls scanned against an allowlist); no LinkedIn or job sites.
    - S12 No negotiation or applying: emails are only created from the owner's template by the owner's action; no endpoint or background task creates emails by itself.
  - **E2E:** Playwright (`@playwright/test`, dev-only) against the real Docker stack with sending OFF and no Gmail account: login, lockout, CSV import, leads, compose → approve (stays queued, never sent), settings, backup page, security headers. Runs in CI.
- **M33 Documentation.** README, setup, email integration, AI, troubleshooting, user guide.
  - Done when: a clean machine can be set up from the docs alone.
  - **Docs:** `README.md` (what it is, safety rule, quick start) and `docs/`: `setup.md` (Windows: Docker Desktop, Git, optional make; plain `docker compose` equivalents), `email.md` (Gmail 2-step verification, app password, connect, sending switch), `ai.md` (Gemini key, free-tier limits and privacy, Settings), `troubleshooting.md`, `user-guide.md` (daily workflow), `backup.md` (backups, restore, drill, exports).
  - **Setup helper:** `make setup` (or one `docker run` command) asks for the login email and password, generates every secret, writes `.env`; never prints secrets, refuses to overwrite an existing `.env`. Needs only Docker.
  - **Verification:** clean-clone drill: fresh clone from GitHub into an empty folder, docs followed word for word as a separate stack on its own port; passes when login, the dashboard and the restore drill work. Every gap found is fixed in the docs.
- **M34 Final QA.** Full checklist plus one week of real use at 5 emails/day.
  - Done when: checklist 100% and owner sign-off.
  - **QA checklist** (`QA-CHECKLIST.md`, each item ticked with evidence): A automated (full suite, S1–S12, E2E, CI on the release commit; security 13/13; live restore drill; clean-clone drill); B open items (M12 real test send to the owner's own second address; M16 eval on the 12-item sample, ≥11/12); C walkthrough on real data (real CSV import, leads/duplicates, profile/CV, template → preview, the test email checked in the second inbox, a reply from it detected, pending cancelled, notified, analysed); D one week of real use at 5/day, owner approves every email, daily log check; E owner sign-off.
  - **Owner decisions (2026-09-29):** the "send no email" instruction is lifted **only for one test email to the owner's own second address**, approved and sent by the owner (sending switched on and off by the owner; Claude never approves or enables sending). A second test email to `awejutt@gmail.com` (confirmed by the owner as theirs or consenting) is also allowed (2026-09-29), prepared by Claude and approved by the owner. The week of real use (D) is deferred; the owner decides later, so M34 stays open until then. The M16 eval runs as a 12-item sample, one per label, in a single day (replaces the earlier two-day split, owner decision 2026-09-29).

**Phase exit:** the QA checklist is 100% complete and signed off, and the restore drill passes.

### Phase 2: Assist (Months 6–7)

Goal: AI that helps without inventing.

- **M9 AI personalization [AI].** Company-specific drafts where every claim cites an allowed fact; human review is mandatory.
  - **Slot only:** the AI writes 1–2 sentences into a `{{personal_line}}` variable the owner places in a template; the owner's own wording stays unchanged. Input: only the company's verified facts from `personalization_facts()` (M27), never scraped data or AI claims.
  - **Citations and grounding (enforced in code):** each sentence lists the fact ids it relies on; a sentence is dropped if it cites nothing, cites a fact that is not one of that company's verified facts, or contains specifics (numbers, names, products, places) absent from its cited facts (and from the company name). If nothing survives or there are no verified facts, the template's fallback `{{personal_line | …}}` is used or the company is skipped as unresolved.
  - **Human review:** personalized drafts are ordinary drafts: the same 12 checks and one-by-one approval; the preview highlights the AI sentence with each cited fact and its source; approval binds the exact final text. Citations are stored with the email.
  - **Use:** a "Personalize from verified facts" checkbox on the Compose page; one Gemini request per draft; at most 10 personalized per run (free tier), the rest fall back.
  - **Evaluation (Phase 2 exit):** a set of ~10 synthetic companies with facts, run through the grounding check with a hostile fake model trying to invent claims (automated) and optionally the real model; pass = 0 ungrounded sentences reach a draft.
  - **Dependency exception (owner decision, 2026-09-30):** built while M16's sample eval is still pending; AI steps are tested with fake models.
  - Depends on: M10, M16. Done when: every company claim has a source.
- **M27 Company research [AI].** Verified facts, scraped data and AI analysis kept strictly separate.
  - **Three strictly separate kinds of information**, each in its own table and its own labelled section of a new **Research** tab on the company page: (1) **scraped data** from the CSV import ("scraped, unverified"); (2) **AI claims** extracted by Gemini from the company's own web pages, each with a verbatim quote from the page and the page URL, claims whose quote is not on the page dropped ("AI, unverified"); (3) **verified facts**: only facts the owner confirmed (Verify on an AI claim, optionally reworded, or added manually with a source), with source and verification date. Verify / reject / add / remove are audited.
  - **Only verified facts reach personalization:** M9 reads company facts only through one database function that returns verified facts and nothing else; tests prove scraped data and AI claims can never come out of it.
  - **Manual research:** the owner clicks Research on a company: one Gemini request per run; nothing is emailed or changed automatically; AI can never create or change a verified fact.
  - **Website fetching (owner decision, 2026-09-30; S11 extended to allow exactly this):** on the owner's click, read-only GET of up to 3 pages (home, /about, /careers) of the company's own domain only; http(s); 10 s timeout; 1 MB per page; no JavaScript; text extracted from HTML. **SSRF guard:** the resolved IP of every request and every redirect must be public (private, loopback, link-local, reserved and Docker-internal addresses refused); at most 3 redirects, each staying on the company's domain. Fetched text is stored as a dated snapshot so every claim's evidence stays checkable.
  - **Dependency exception (owner decision, 2026-09-30):** built while M16's sample eval is still pending; the AI step is tested with a fake model, real runs need Gemini quota.
  - Depends on: M23, M16. Done when: only verified facts reach personalization.
- **M20 Interview management.** Timezone-safe records, in-app reminders, `.ics` export.
  - **Interview:** belongs to an opportunity; title, start (local date/time + the IANA time zone it was agreed in), duration, kind (video/phone/onsite), meeting link (http/https only) or address, interviewers, notes, status scheduled/done/cancelled, outcome note. Recording one moves the opportunity to `interviewing` via M19's fact path (never backwards). Notes and tasks accept `interview`. Never sends email. All changes audited.
  - **Time zones:** stored as a UTC instant plus the zone; shown in the interview's zone and the owner's; local times that do not exist or are ambiguous (DST changes) are rejected with a clear message.
  - **Reminders (in-app):** notifications 24 h and 1 h before, exactly once each, deep-linked; missed ones fire on the next start if the interview is still ahead; none for cancelled/past interviews. New notification kind `interview` (on by default) added to the M29 Settings kinds.
  - **`.ics` export:** per interview, UTC times, stable UID and SEQUENCE so re-imports update the event.
  - **UI:** Interviews section on the opportunity page; `/interviews` page (upcoming / past); dashboard Interviews tile becomes real; company page lists its interviews; one-click prefill from an AI-found interview date (prefill only, owner confirms).
  - Depends on: M19. Done when: timezones are correct and reminders fire.
- **M28 Analytics.** Reply rate by template version, country, industry, source; bounce rate.
  - **Page `/analytics`** with the dashboard's period filter (7 / 30 / 90 days / all time).
  - **Metrics per group:** sent (emails sent in the period); **reply rate** = sent emails with a real reply ÷ sent, where a reply is credited to the latest email sent to that company before it arrived (auto-replies and bounces never count); **bounce rate** = bounced ÷ sent, hard and soft shown separately; **opportunities** created from those replies (M19).
  - **Breakdowns:** template version; country; industry (multi-value industries split, a company counts in each); source (manual / CSV import and which file).
  - **Honesty:** every rate shows its counts; groups with fewer than 10 sent are marked "few data"; overall numbers match the dashboard's definitions.
  - **Verification:** seeded dataset with hand-calculated expected values for every metric and breakdown (replies to older emails, colleague replies, bounces, multi-industry, auto-replies, emails outside the period); < 500 ms at 10k emails.
  - Depends on: M18, M19. Done when: all metrics are correct on seeded data.

**Phase exit:** no ungrounded AI claim ever reaches a draft, measured on the evaluation set.

### Phase 2b: Frontend (owner-approved 2026-09-30)

Goal: a complete, consistent frontend on top of the finished backend. **No behaviour or safety rule changes**: same API, same one-by-one approval, every existing test (including S1–S12 and the E2E suite) keeps passing. Each F-milestone gets detailed specs here and the owner's approval before it is built. Done before M34's final QA, so the owner signs off the finished UI.

**Decisions (owner, 2026-09-30):** own design system in plain CSS (CSS variables + CSS modules built into Next.js; **no new dependencies**); hand-made SVG charts (no chart library); the Kanban board stays in Phase 3.

- **F1 Design system & app shell.** Tokens (colour, type, spacing) with light and dark mode; reusable components (buttons, inputs, selects, tables, tabs, cards, badges, in-app confirm dialogs replacing browser pop-ups, toasts, empty/loading/error states); sidebar navigation grouped Work / Insights / Setup; top bar with search, bell and account menu; mobile drawer.
  - **Tokens** (`app/globals.css`): colours (background, surfaces, borders, text, one accent blue, success/warning/danger), spacing, radius, type scale with the system font stack (no web fonts); light and dark mode following the system, with a remembered manual toggle.
  - **Components** (`app/ui/`): Button, Field (label/hint/error), Input, Select, Textarea, Checkbox, Card, Badge, Table, Tabs, PageHeader, Stat, EmptyState, Spinner, ErrorState, Toast, Confirm/Prompt dialog.
  - **App shell** on every signed-in page: sidebar grouped Work (Dashboard, Leads, Compose, Outbox, Inbox, Opportunities, Interviews, Tasks) / Insights (Analytics, History, Activity) / Setup (Templates, Import, Duplicates, Do-not-contact, Profile & CV, Email account, Settings, Backup & export) with live count badges (queued emails, unread replies, tasks due) and the current page highlighted; top bar with search, an always-visible Sending ON/OFF pill (red when on), bell, theme toggle, account menu with sign-out; mobile drawer; login keeps its own centred layout.
  - **No browser pop-ups:** every `window.confirm`/`prompt`/`alert` becomes an in-app dialog (the sending switch's confirmation keeps its queue/cap/gap text and explicit click).
  - Base styles make existing pages consistent now; the dashboard's link row is removed (navigation lives in the sidebar). Page redesigns follow in F2–F8.
  - Done when: every page renders in the shell and every sidebar link works; a test proves no browser confirm/prompt/alert remains; light and dark are readable; the mobile drawer works; E2E extended (sidebar links, in-app dialogs, theme persistence); all existing tests, S1–S12 and E2E pass.
- **F2 Dashboard.** KPI cards, sent-per-day SVG chart, latest replies, tasks due, next interview, backup warning, system status.
- **F3 Leads & companies.** Leads table with filter panel, sorting, paging and bulk-action bar; company page header + tabs; contact page; Import as a 3-step wizard; Duplicates.
- **F4 Outreach.** Template editor with live preview against a real lead; Compose as a stepper; Outbox list and detail (preview, safety-check panel, Approve); prominent sending switch; History.
- **F5 Inbox & threads.** Two-pane inbox (list + reading pane) with labels and AI analysis panel; conversation view; notifications page.
- **F6 Pipeline.** Opportunities grouped by stage (lists), opportunity page, Interviews page (upcoming/past timeline).
- **F7 Research & personalization.** Research tab (facts / claims / scraped) and AI-sentence review in the Outbox, polished.
- **F8 Setup area.** Settings, Email account, Profile & CV, Do-not-contact, Backup & export, Activity in one layout; first-run checklist (connect Gmail, profile, CV, template, import).
- **F9 Quality pass.** Mobile layout and accessibility (keyboard, labels, contrast) on every page; consistent states; E2E extended to every page.

### Phase 3: Extend (Later)

Same safety rules apply.

- Kanban board and saved filters for the pipeline and lead lists.
- Second email provider and read-only calendar access (free slots).
- "Run scraper" button (subprocess), plus import presets for the HVAC / Meta Ads CSVs.
- **[SAFETY]** Reply-draft suggestion, off by default: drafts only, the same per-email approval is required.

---

## 5. Build order

Sequential, single developer. Rows marked **GATE** must pass before the next row starts.

| When | Work | Milestones |
|---|---|---|
| Done | Discovery | M0 |
| Wk 1–2 | Foundation & database | M1, M2 |
| Wk 3–4 | Profile, companies, suppression, activity log | M3, M5, M25, M24 |
| Wk 5–6 | CSV import & leads | M4, M6 |
| Wk 7–8 | **GATE:** Templates & safety gates (before any sending code) | M8, M21, M26 |
| Wk 9–10 | Composer & mailbox | M10, M11 |
| Wk 11–12 | **GATE:** Sending & history (first real test send to own address) | M12, M13 |
| Wk 13–14 | Inbox sync & reply detection | M14, M15 |
| Wk 15–16 | AI analysis & dashboard | M16, M17, M18 |
| Wk 17–18 | Workspace | M23, M22, M19, M29 |
| Wk 19–20 | Data safety | M7, M32, M30 |
| Wk 21–22 | **GATE:** MVP release | M31, M33, M34 |
| Mo 6–7 | Assist | M9, M27, M20, M28 |
| Next | Frontend (before M34 sign-off) | F1–F9 |
| Later | Extend | Phase 3 |

MVP effort estimate: 95–135 developer-days.

**Gate waiver (2026-09-27, Owner):** the Wk 11–12 gate's real test send to the owner's second inbox is waived until the owner chooses to do it (the owner instructed that no email be sent). All automated gate checks pass. M13, M14 and M15 were/are built under this waiver. The test send stays pending in MILESTONES.md.

**Gate waiver (2026-09-30, Owner):** Phase 2 (Assist) may start before the Wk 21–22 MVP gate passes. M34 stays open: the sample AI eval, profile/CV, the real-use-week decision and the owner's sign-off remain on `QA-CHECKLIST.md` and must still be completed before the MVP counts as released. Phase 2 starts with M20.

## 6. Out of scope

Anything not listed in this file, including:
- Multiple users, teams or roles.
- Automatic replies, follow-ups, negotiation or job applications.
- Any LinkedIn messaging or automation.

## 7. Known gaps

The PDF refers to a companion `PERSONAL_AI_JOB_OUTREACH_CRM_PROJECT_BLUEPRINT.pdf` for full per-milestone detail. That blueprint is **not** in this folder. Items it defines are not in scope here until they are added to this file:
- ~~Safety test cases S1–S12 (M31).~~ Closed 2026-09-28: defined by the owner in M31 (v1.29).

## 8. Open questions (all answered 2026-09-27)

| # | Question | Blocks | Answer |
|---|---|---|---|
| Q1 | Which mailbox sends outreach: Gmail/Workspace (Gmail API), Outlook/M365 (Graph), or other (SMTP+IMAP)? | M11 | **Personal Gmail over SMTP+IMAP with an app password** (requires 2-step verification). Avoids the 7-day OAuth token expiry. |
| Q2 | AI provider for reply classification: hosted model or local Ollama? | M16 | **Gemini API free tier, for testing only.** Owner decides the final provider later. Free-tier inputs may be used by Google to improve its products. Provider must stay switchable via Settings (M29). |
| Q3 | Run on this laptop only (localhost), or on a private VPS? | M1, M30 | **Laptop only, localhost.** Inbox sync runs only while the app is running; missed replies are fetched on next start. |
| Q4 | Daily send cap and custom domain? | M12 | **20 emails/day with a 90 s minimum gap. No custom domain;** send from personal Gmail. |

---

## 9. Change log

| Date | Version | Change | Approved by |
|---|---|---|---|
| 2026-09-27 | 1.0 | Initial spec from CRM_MILESTONES.pdf v1.0 | Owner |
| 2026-09-27 | 1.1 | Answered Q1–Q4: Gmail SMTP+IMAP, Gemini free tier (testing), laptop only, 20/day with 90 s gap. M11 narrowed to SMTP+IMAP (no OAuth). | Owner |
| 2026-09-27 | 1.2 | M2 detailed: plain SQL migrations, `outbound_emails` with DB-enforced approval-hash constraint and partial unique indexes, append-only `audit_log`. M1: API has no published port (only reachable via web). | Owner |
| 2026-09-27 | 1.3 | M3 detailed: profile fields, PDF CV versions in Postgres with one enforced default, 16 `my_*` variables, Profile page. | Owner |
| 2026-09-27 | 1.4 | M5 detailed: company/contact fields, archive instead of delete, provenance, unique active domain/email, email-class rules with manual override, list + company pages. | Owner |
| 2026-09-27 | 1.5 | M25 detailed: email/domain/company blocks with reason, lift-with-reason as the audited override, DB trigger refusing approve/queue/send to blocked recipients, auto-cancel of pending emails on new block. | Owner |
| 2026-09-27 | 1.6 | M24 detailed: DB triggers log every email status change with actor; M25 auto-cancel routed through them; Activity page and company timeline. | Owner |
| 2026-09-27 | 1.7 | M4 detailed: preview-then-import flow, `ai_companies` column mapping, email cleaning with same-brand rule, dedupe, blocked rows skipped, error CSV; real CSV kept out of the public repo. | Owner |
| 2026-09-27 | 1.8 | M6 detailed: lead stages new / qualified / contacted / replied / closed + on_hold (closes §7 lead-stage gap), DB-logged stage changes, Leads page with filters and bulk actions, compose list with best-recipient pick. | Owner |
| 2026-09-27 | 1.9 | M8 detailed: immutable template versions, 26 variables, save-time and render-time strict checks, `{{var \| fallback}}` syntax, preview against a real lead. | Owner |
| 2026-09-27 | 1.10 | M21 detailed: notes on companies/contacts/templates, owner tasks with date-only due dates judged by the browser's date, Tasks page and per-page panels. | Owner |
| 2026-09-27 | 1.11 | M26 detailed: the 12 safety checks (closes §7 gap), approval/send semantics, `outbound_emails` links, `app_settings` with sending off by default. | Owner |
| 2026-09-27 | 1.12 | M10 detailed: drafts from compose list + template, optional CV attachment chosen in the UI and bound into the content hash, outbox and draft page, one-click per-email "Approve & queue" bound to the displayed hash, no bulk approve. | Owner |
| 2026-09-27 | 1.13 | M11 detailed: Fernet credential encryption pulled forward from M30 (new dependency `cryptography`, key in `.env`), single Gmail account with connect / test (no send) / disconnect, password never exposed. | Owner |
| 2026-09-27 | 1.14 | M12 detailed: beat + single-lane worker with advisory lock, Message-ID stored before send and recovered from Gmail Sent (no auto-resend), kill switch on Outbox, stage → contacted; no real sends during build. | Owner |
| 2026-09-27 | 1.15 | M13 detailed: Gmail message/thread IDs fetched read-only after sending, History page with filters, per-email status timeline, thread view, company Emails section. | Owner |
| 2026-09-27 | 1.16 | M14 detailed: read-only IMAP sync of All Mail + Spam with UID cursors, 14-day first look-back, resync + daily re-scan, only outreach-relevant messages stored, Inbox page, simulated and real 24 h soak. Refined during build: bounces count only within 3 days after a CRM send (privacy; narrows the approved rule). | Owner |
| 2026-09-27 | 1.17 | Gate waiver recorded: Wk 11–12 real test send deferred by the owner; M13–M15 built under the waiver. | Owner |
| 2026-09-27 | 1.18 | M15 detailed: five ordered rules with DSN parsing and auto-reply headers; effects: replied stage, bounced marking, hard bounce → do-not-contact, reply → cancel pending emails to that company. | Owner |
| 2026-09-27 | 1.19 | M16 detailed: the 12 AI labels (closes §7 gap), code-enforced verbatim evidence, replies only with quoted history stripped, background analysis, synthetic evaluation set with one approved real run. | Owner |
| 2026-09-28 | 1.20 | M17 detailed: notification events (replies/auto-replies/bounces, sending problems, system problems), DB-trigger exactly-once with AI priority updates, deep links to the message, bell on every page. Also: default Gemini model gemini-3.8-flash (2.5 closed to new users); M16 eval deferred by owner (free tier 20 requests/day/model). | Owner |
| 2026-09-28 | 1.21 | M18 detailed: KPI definitions with period filter, placeholder tiles for opportunities/interviews until M19/M20, feeds, <500 ms at 10k companies. Process: full test suite now runs every 2–3 milestones (owner's request); milestones stay unticked until that batch run. | Owner |
| 2026-09-28 | 1.22 | M23 detailed: tabbed company page with summary header, new contact page, opportunity placeholder until M19, reachability test. | Owner |
| 2026-09-28 | 1.23 | M22 detailed: global search over 6 record types, reply/template/date/text Leads filters, pg_trgm indexes, <300 ms at 10k companies. | Owner |
| 2026-09-28 | 1.24 | M19 detailed: 8 opportunity stages (closes the last §7 stage gap), one-click creation from a reply, DB-logged stage history, AI suggestions only, Opportunities pages, real dashboard/company opportunity data. | Owner |
| 2026-09-28 | 1.25 | M29 detailed: Settings page for limits, cooldowns, AI on/off + validated model, notification kinds; kill switch stays on Outbox; key stays in .env; audited; live without restart. | Owner |
| 2026-09-28 | 1.26 | M7 detailed: duplicate suggestions (domain / email / LinkedIn / name), manual merge with survivor choice, snapshot + undo, do-not-contact carry-over, no merge with pending emails. | Owner |
| 2026-09-28 | 1.27 | M32 detailed: daily catch-up pg_dump (14 kept, manifest), /backup page, CLI-only restore that forces sending off and returns approved/queued emails to draft, restore drill, CSV + full JSON/CV export; PostgreSQL 18 client tools in the backend image. | Owner |
| 2026-09-28 | 1.28 | M30 detailed: 13-item security checklist as the definition of done (CSRF origin check, login lockout, log redaction, security headers, header-injection guard, secret-strength check, CI secret scan, CI dependency audit with new CI-only tool pip-audit, plus checks for existing protections); owner to-dos listed. | Owner |
| 2026-09-28 | 1.29 | M31 detailed: safety suite S1–S12 defined (closes the last §7 gap); Playwright browser E2E (new dev-only dependency @playwright/test) against the Docker stack in CI. | Owner |
| 2026-09-29 | 1.30 | M33 detailed: README + six guides in docs/, `make setup` helper that writes .env with generated secrets (Docker only), clean-clone drill as the done-check. | Owner |
| 2026-09-29 | 1.31 | M34 detailed: QA checklist A–E; owner allows one test email to their own second address (owner approves and switches sending); week of real use deferred; M16 eval split over two days (eval script gets --part 1/2 with a combined score). | Owner |
| 2026-09-29 | 1.32 | M16 eval by sample (owner's request): 12 items, one per label, pass ≥11/12 and 0 unproven fields; fits one day's free quota; replaces the two-day split. | Owner |
| 2026-09-29 | 1.33 | M34: second test email allowed to awejutt@gmail.com (owner confirmed own/consenting address); owner approves it. | Owner |
| 2026-09-30 | 1.34 | MVP gate waiver: Phase 2 may start while M34 stays open (its checklist items remain required for the MVP release); M20 first. | Owner |
| 2026-09-30 | 1.35 | M20 detailed: interviews on opportunities, zone-safe times (DST gaps/overlaps rejected), 24 h + 1 h in-app reminders exactly once (new notify kind `interview`), .ics export with stable UID, /interviews page, dashboard tile, AI-date prefill. | Owner |
| 2026-09-30 | 1.36 | M28 detailed: /analytics with reply rate (credited to the latest prior email to the company), bounce rate hard/soft and opportunities, by template version, country, split industry and source; few-data marking; hand-checked seeded tests; < 500 ms at 10k emails. | Owner |
| 2026-09-30 | 1.37 | M27 detailed: scraped data / AI claims (verbatim evidence + URL) / owner-verified facts kept separate; only verified facts via one DB function for M9; manual Research fetches up to 3 pages of the company's own site with an SSRF guard (S11 extended to allow exactly this); built before M16's eval passes (owner's exception). | Owner |
| 2026-09-30 | 1.38 | M9 detailed: AI fills only {{personal_line}} from verified facts with per-sentence citations; strict grounding check drops unproven sentences; highlighted with sources in the preview; one-by-one approval unchanged; max 10 per run; eval set with 0 ungrounded claims; built before M16's eval (owner's exception). | Owner |
| 2026-09-30 | 1.39 | Phase 2b Frontend added: F1–F9 (design system & shell, dashboard, leads, outreach, inbox, pipeline, research, setup, quality), plain CSS and hand-made SVG charts with no new dependencies, Kanban stays in Phase 3, done before M34 sign-off; each F-milestone detailed and approved before building. | Owner |
| 2026-09-30 | 1.40 | F1 detailed: tokens with light/dark, component set, grouped sidebar with live badges, always-visible sending pill, mobile drawer, in-app dialogs replace browser pop-ups; done-when with no-pop-up test and extended E2E. | Owner |
