# Job Outreach CRM: Project Specification

> **This file is the single source of truth for what gets built.**
> Nothing is implemented unless it is described here. See [CLAUDE.md](CLAUDE.md) for the change process.

- **Source:** CRM_MILESTONES.pdf (v1.0 draft, Sept 25, 2026)
- **Spec version:** 1.7
- **Last updated:** 2026-09-27

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
  - Depends on: M3, M6. Done when: templates are versioned and unresolved variables are always caught.
- **M21 Notes & tasks.** Notes on every entity; follow-ups are tasks for the owner, never emails.
  - Depends on: M5. Done when: notes/tasks appear on every entity page and the due list is correct.
- **M26 Email safety controls [SAFETY].** 12 checks, run at approval **and** again at send (suppression, duplicates, unresolved variables, limits, …).
  - Depends on: M25, M8. Done when: all 12 gates are tested and re-checked at send time.
- **M10 Email composer [SAFETY].** Exact preview, per-email approval bound to a content hash (editing after approval voids approval), no "approve all".
  - Depends on: M8, M26. Done when: nothing is queued without per-email approval.
- **M11 Email provider integration [CORE].** SMTP+IMAP adapter for personal Gmail using an app password (no OAuth), credentials encrypted at rest. Other providers are Phase 3.
  - Depends on: M1, M30. Done when: the Gmail account is connected and credentials are encrypted.
- **M12 Email sending [SAFETY].** Single-lane queue, daily cap and minimum gap, idempotency, Message-ID recovery, kill switch.
  - Depends on: M10, M11, M26. Done when: sending is exactly-once and the safety tests are green.
- **M13 Email history.** Statuses, timestamps, provider IDs, threads.
  - Depends on: M12. Done when: every sent email is in history with its thread.

**Phase exit:** a real test email reaches the owner's second inbox, and duplicate, do-not-contact and kill-switch tests all block sends.

### Phase 1C: Replies (Weeks 13–16)

Goal: never miss a reply, never answer automatically.

- **M14 Inbox synchronization [CORE].** Incremental cursor-based polling, idempotent storage, resync handling.
  - Depends on: M11, M13. Done when: a 24 h soak test shows no missed and no duplicate messages.
- **M15 Reply detection.** Rule-based, no AI, in this order: bounce → auto-reply/OOO → thread match → sender match → unrelated.
  - Depends on: M14. Done when: 100% correct on bounce/OOO/reply fixtures.
- **M16 AI reply analysis [AI].** 12 classification labels; extraction of dates, links and documents, each field with a verbatim evidence quote.
  - Depends on: M15. Done when: ≥90% label accuracy and 0 extracted fields without evidence.
- **M17 Notifications.** Bell icon, priority by classification, deep link to the reply.
  - Depends on: M16. Done when: exactly one notification per event, deep-linked.
- **M18 Dashboard.** KPIs: leads, sent, replies, reply rate, interested, opportunities, interviews, offers; activity feeds.
  - Depends on: M17. Done when: KPIs match SQL checks and the page loads in <500 ms.

**Phase exit:** a reply appears within one sync interval, correctly labelled, and the provider records **zero** automatic sends.

### Phase 1D: Workspace & Hardening (Weeks 17–22)

Goal: ready for daily use.

- **M23 Company / contact detail.** 360° page: contacts, emails, replies, opportunity, notes, tasks, timeline.
  - Depends on: M13, M15, M21. Done when: every related record is reachable from the page.
- **M22 Search & filtering.** Global search plus filters by country, industry, stage, reply, template, date.
  - Depends on: M5, M13. Done when: <300 ms at 10k companies.
- **M19 Job opportunity pipeline.** Stages NEW → … → OFFER → HIRED; only factual events change a stage automatically.
  - Depends on: M16. Done when: reply → opportunity → all stages, with history.
- **M29 Settings.** Email account, AI provider, limits, notifications, cooldowns.
  - Depends on: M11, M16. Done when: settings are validated, audited and applied without restart.
- **M7 Duplicate management.** Match by domain / email / LinkedIn / name; merge with snapshot and undo.
  - Depends on: M4, M5. Done when: merge + undo work and no duplicate active domains exist.
- **M32 Backup & recovery [SAFETY].** Nightly `pg_dump`, restore with sending disabled, CSV and full export.
  - Depends on: M1, M2. Done when: the restore drill passes and sending is off after restore.
- **M30 Security [SAFETY].** Encryption, CSRF protection, redacted logs, localhost binding, prompt-injection hardening.
  - Continuous. Done when: the security checklist is fully green.
- **M31 Testing [SAFETY].** Unit, integration, API, E2E, plus safety suite S1–S12 (e.g. reply → no send, no reply → no follow-up).
  - Continuous. Done when: safety suite S1–S12 and CI are green.
- **M33 Documentation.** README, setup, email integration, AI, troubleshooting, user guide.
  - Done when: a clean machine can be set up from the docs alone.
- **M34 Final QA.** Full checklist plus one week of real use at 5 emails/day.
  - Done when: checklist 100% and owner sign-off.

**Phase exit:** the QA checklist is 100% complete and signed off, and the restore drill passes.

### Phase 2: Assist (Months 6–7)

Goal: AI that helps without inventing.

- **M9 AI personalization [AI].** Company-specific drafts where every claim cites an allowed fact; human review is mandatory.
  - Depends on: M10, M16. Done when: every company claim has a source.
- **M27 Company research [AI].** Verified facts, scraped data and AI analysis kept strictly separate.
  - Depends on: M23, M16. Done when: only verified facts reach personalization.
- **M20 Interview management.** Timezone-safe records, in-app reminders, `.ics` export.
  - Depends on: M19. Done when: timezones are correct and reminders fire.
- **M28 Analytics.** Reply rate by template version, country, industry, source; bounce rate.
  - Depends on: M18, M19. Done when: all metrics are correct on seeded data.

**Phase exit:** no ungrounded AI claim ever reaches a draft, measured on the evaluation set.

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
| Later | Extend | Phase 3 |

MVP effort estimate: 95–135 developer-days.

## 6. Out of scope

Anything not listed in this file, including:
- Multiple users, teams or roles.
- Automatic replies, follow-ups, negotiation or job applications.
- Any LinkedIn messaging or automation.

## 7. Known gaps

The PDF refers to a companion `PERSONAL_AI_JOB_OUTREACH_CRM_PROJECT_BLUEPRINT.pdf` for full per-milestone detail. That blueprint is **not** in this folder. Items it defines are not in scope here until they are added to this file:
- The exact list of the 12 email safety checks (M26).
- The 12 AI reply labels (M16).
- Safety test cases S1–S12 (M31).
- Intermediate lead and opportunity stages (M6, M19).

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
