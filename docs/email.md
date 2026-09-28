# Email (Gmail)

The app sends from and reads replies in your **personal Gmail** over SMTP and IMAP, using an **app password**.

- The inbox is only ever opened **read-only**: it never marks mail as read, moves it or deletes it.
- The app password is encrypted (Fernet, with `CREDENTIALS_KEY` from `.env`) before it is stored, and it is never shown again.

## 1. Turn on 2-Step Verification

App passwords only exist when 2-Step Verification is on.

1. Go to https://myaccount.google.com/security.
2. Under "How you sign in to Google", open **2-Step Verification** and turn it on.

## 2. Create an app password

1. Go to https://myaccount.google.com/apppasswords. If the page doesn't appear, 2-Step Verification is not on yet.
2. App name: `Job Outreach CRM`, then click **Create**.
3. Google shows a 16-letter password (e.g. `abcd efgh ijkl mnop`). Copy it. It is shown only once.

You can revoke it at any time on the same page. The app then stops sending and syncing until you enter a new one.

## 3. Connect it in the app

1. Open **Email account** (link on the dashboard), or go to http://localhost:3000/email-account.
2. Enter:
   - your Gmail address
   - optionally a display name (shown as the sender, e.g. `Arslan Ali`)
   - the app password
3. Click **Save & test connection**. The test only logs in to SMTP and IMAP; **nothing is sent**.
4. The status should read **connected**. If it says *test failed*, see [troubleshooting](troubleshooting.md#gmail).

**Disconnect** deletes the stored app password.

## 4. Sending is off until you switch it on

Nothing leaves your mailbox until **both** of these are true:
1. You approved that exact email (Outbox → email → **Approve & queue this email**). Approval is per email; there is no bulk approve.
2. The **sending switch** at the top of the **Outbox** is ON. Switching it on asks for confirmation and needs a connected, tested account.

**While sending is on:**
- The worker sends one queued email at a time.
- It keeps within the daily cap (default 20 per 24 h) and the minimum gap (default 90 s). Both are adjustable in **Settings**.
- It re-runs all 12 safety checks just before each send, including do-not-contact, cooldowns, "the company already replied" and "the content is still exactly what you approved".
- An email that fails a check is not sent. Rate limits and the kill switch make it wait; other failures cancel it.

**Stop sending** in the Outbox takes effect before the next email. Settings can never switch sending on; only the Outbox can.

## What gets read from your inbox

- Every 2 minutes, while the app runs, it reads new messages in **All Mail** and **Spam**, read-only.
- It only **stores** messages related to your outreach:
  - replies to your emails
  - messages in the same Gmail threads
  - bounces
  - mail from your contacts or their company domains

  Everything else is skipped.
- On first connection it looks back 14 days.

Stored messages are labelled **reply**, **auto-reply**, **bounce** or **unrelated**:
- **reply:** cancels any pending emails to that company and moves the lead to *replied*.
- **auto-reply:** changes nothing.
- **hard bounce:** puts the address on the do-not-contact list.

None of these ever sends anything.
