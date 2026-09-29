# MVP QA checklist (M34)

M34 is done when every box is ticked **and** the owner signs off (section E) ([PROJECT.md](PROJECT.md) M34, v1.31).
Each ticked box names its evidence.

## A. Automated checks (Claude runs these)

- [x] Full backend suite green: 541 tests, including the safety suite S1–S12 (M31). CI run 36473609784 on `c9bdbae`, all 5 jobs green.
- [x] Browser E2E green: 9 flows, in the same CI run (job `e2e`).
- [x] Security checklist 13/13 (M30). CI jobs `security` and `backend`, plus `pip-audit` and `npm audit`.
- [x] Restore drill on the **live** database passed: `crm-20260928-195831.dump`, 5/5 checks, 1.2 s (2026-09-29).
- [x] Clean-clone drill passed: fresh GitHub clone set up from the docs alone (M33, 2026-09-29).
- [ ] Final CI run green on the release commit, i.e. the commit that ticks M34.

## B. Open items from earlier milestones

- [ ] **M12 real test send:** one email to the owner's **own second address**. The owner approves it and switches sending on and off; see "How to do the test send" below. Closes M12's gate waiver.
- [ ] **M16 AI eval ≥ 90%** on the 40 synthetic replies, split over two days (free tier):
  - [ ] Part 1: items 1–20. The first attempt (2026-09-29 00:57 UTC+5) hit the free tier's daily quota after item 1 and was stopped; nothing was saved. Run after the quota resets at 12:00 UTC+5 (07:00 UTC). The second attempt (2026-09-29 ~14:45 UTC) met Gemini overload (HTTP 503) and its retries used up the day's quota; it was stopped and nothing was saved. The eval now stops at once on "rate limited" and retries "busy" only twice (after 30 s and 90 s).
  - [ ] Part 2: items 21–40, on the following day after 12:00 UTC+5, then the combined score.
  - Command, run from the repo root (keeps the results between days):
    `docker compose run --rm -v "${PWD}/backend/ai_eval/results:/app/ai_eval/results" api python -m scripts.run_ai_eval --part 1` (then `--part 2`)

## C. Walkthrough on real data (owner drives, Claude checks)

- [ ] Import the real Berlin CSV: the preview matches expectations and the import summary is plausible.
- [ ] Leads: filters work on real data; the **Duplicates** suggestions make sense (merge or dismiss as needed).
- [ ] Profile & CV complete; the CV PDF is uploaded and set as default.
- [ ] Template → drafts: the previews read correctly for 3 real companies (no raw `{{…}}`, sensible contact picked).
- [ ] The test email (B) arrives in the second inbox with the right subject, text, sender name and CV attachment.
- [ ] A reply to it from the second inbox is detected as **reply**: notification shown, lead set to *replied*, any pending email to that company cancelled, and AI analysis present if enabled.
- [ ] After the test, sending is back **OFF** and nothing else was sent (Outbox → Sent has exactly 1 email).

## D. One week of real use at 5 emails/day (deferred by the owner, 2026-09-29)

Not started. It needs the owner's explicit go-ahead. When it starts:
- [ ] Daily cap set to 5 in Settings.
- [ ] 7 days of use. The owner approves every email; Claude checks the logs daily on request:
  - ≤ 5 sent per day and the 90 s gap respected
  - every sent email was approved by the owner (audit log)
  - nothing was sent to blocked or replied companies
  - inbox sync healthy, a daily backup made, no errors
- [ ] Daily notes:

| Day | Date | Sent | Replies | Bounces | Issues |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |
| 4 | | | | | |
| 5 | | | | | |
| 6 | | | | | |
| 7 | | | | | |

## E. Owner sign-off

- [ ] All boxes above are ticked.
- [ ] Signed off by the owner: ______________________ Date: __________

---

## How to do the test send (B, owner only)

Before you start:
- Make sure nothing else is queued: **Outbox → Queued** must be empty. Switching sending on sends everything that is queued.
- You need a second email address of your own (not the Gmail connected to the app).

1. **Leads → Add company manually**: name `QA test (own address)`, no domain.
2. On that company, add a contact with **your second address**.
3. **Leads**: select only that company, then **Add to compose list**.
4. **Compose list**: choose a template, tick "attach CV" if you want to check the attachment, then **Create 1 draft(s)**. If it says the company was skipped for unresolved variables, fill those fields in **Profile & CV** (or use `{{name | fallback}}` in the template) and try again.
5. **Outbox → Drafts**: open it, check the preview, then **Approve & queue this email**.
6. **Outbox**: **Enable sending**. Within about 30 s the email is sent.
7. **Stop sending** straight away.
8. Check the second inbox. Then reply to the email from there (this covers checklist C's reply check); the app picks the reply up within about 2 minutes.
9. Tell Claude "check the test send", and I'll verify everything in B and C from the logs and database.
