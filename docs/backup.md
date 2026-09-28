# Backup, restore and export

## Automatic backups

- While the app runs, it makes a full backup whenever the last one is **older than 24 hours**. It catches up after the laptop was asleep or off.
- Backups go to the **`backups`** folder of the project (e.g. `backups\crm-20260928-180154.dump` plus a small `.json` manifest with row counts). The **last 14** are kept.
- They include all data, CVs too. They do **not** include `.env`.
- **Backup & export** (dashboard link) shows the backups and has **Back up now**.
- The dashboard warns when the last backup is **older than 48 hours**, or when there is none yet.

From a terminal: `docker compose run --rm api python -m app.backup create`. With make: `make backup`.

**Copy the `backups` folder and your `.env` somewhere else from time to time** (USB stick, cloud drive). A backup on the same disk does not survive a dead disk. Turning on BitLocker is recommended, because backups are not encrypted.

## Check that a backup really restores (restore drill)

```powershell
docker compose run --rm api python -m app.backup drill
```
With make: `make restore-drill`.

The drill:
1. Restores the newest backup (or `FILE=…` with make) into a **throwaway** database.
2. Checks that every table's row count matches the manifest, the safety triggers are present, sending is off, no email is left approved or queued, and every CV is readable.
3. Deletes the throwaway database.

It prints `"passed": true` when all checks pass. Your live data is not touched.

## Restore (replaces ALL data)

Only possible from a terminal, on purpose:

```powershell
docker compose stop web api worker beat
docker compose run --rm api python -m app.backup restore crm-20260928-180154.dump
docker compose up -d
```
With make: `make restore FILE=crm-20260928-180154.dump`.

After a restore, before anything runs:
- **Sending is switched OFF.**
- Emails that were approved or queued in the backup go **back to draft** and need a fresh approval, because they may have been sent after the backup was taken.
- An email that was being sent at backup time is marked **failed**, with a note to check Gmail's Sent folder before resending.
- The restore is recorded in Activity.

If you restore on a new machine with a different `.env`, reconnect Gmail (Email account page), since the stored app password can only be decrypted with the old `CREDENTIALS_KEY`.

## Export

On **Backup & export**:
- **CSV:** companies, contacts, sent emails, replies. The files open in Excel, and cells that could run as formulas are neutralised.
- **Full export (ZIP):** every table as JSON, plus your CV PDFs. The stored Gmail app password is never exported.
