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

- [x] **M12 real test send:** one email to the owner's **own second address**. The owner approves it and switches sending on and off; see "How to do the test send" below. Closes M12's gate waiver. **Done 2026-09-29:** email #1 to arslanali223321@gmail.com sent 18:22:36 UTC and #2 to awejutt@gmail.com (added by the owner, PROJECT.md v1.33) sent 18:29:06 UTC. Both owner-approved (audit log), both accepted by Gmail with Message-ID and thread recorded.
- [x] **M16 AI eval on a sample** (**Done 2026-10-02:** 12/12 correct, 0 unproven fields, model nvidia/nemotron-3-ultra-550b-a55b:free via OpenRouter; the earlier Gemini attempts were stopped by quota) (owner decision 2026-09-29, PROJECT.md v1.32): 12 synthetic replies, one per label; pass = at least 11/12 correct and 0 stored fields without evidence. Fits one day's free quota.
  - Earlier attempts (2026-09-28 and 2026-09-29) were stopped by quota and Gemini overload; nothing was saved. The eval now stops at once on "rate limited" and retries "busy" only twice.
  - Run after the daily quota resets at 12:00 UTC+5 (07:00 UTC):
    `docker compose run --rm api python -m scripts.run_ai_eval --sample`

## C. Walkthrough on real data (owner drives, Claude checks)

- [ ] Import the real Berlin CSV: the preview matches expectations and the import summary is plausible.
- [ ] Leads: filters work on real data; the **Duplicates** suggestions make sense (merge or dismiss as needed).
- [ ] Profile & CV complete; the CV PDF is uploaded and set as default.
- [ ] Template → drafts: the previews read correctly for 3 real companies (no raw `{{…}}`, sensible contact picked).
- [ ] The test email (B) arrives in the second inbox with the right subject, text, sender name and CV attachment.
- [x] A reply to it from the second inbox is detected as **reply**: notification shown, lead set to *replied*, any pending email to that company cancelled, and AI analysis present if enabled. **Done:** the reply from awejutt@gmail.com ("Yes, I got your email.") was stored 2 s after arrival, labelled reply (reply header → email #2), the lead set to replied and one notification created; nothing was sent in response. AI analysis was pending (Gemini 503/quota); it retries automatically.
- [x] After the test, sending is back **OFF** and nothing else was sent (Outbox → Sent has exactly 1 email). **Done:** sending was switched OFF at 18:30:12 UTC; exactly 2 emails were sent (both allowed test emails), 0 queued.

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
