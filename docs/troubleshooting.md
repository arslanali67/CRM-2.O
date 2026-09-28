# Troubleshooting

First steps for almost anything:
```powershell
docker compose ps              # which services are running?
docker compose logs --tail 100 api worker
```
Logs never contain your secrets. Email addresses are shown shortened, e.g. `j***@acme.de`.

## Starting

**`error during connect` / `open //./pipe/docker_engine` / `Cannot connect to the Docker daemon`**
Docker Desktop is not running. Start it, wait for *Engine running*, then run the command again.

**`required variable POSTGRES_PASSWORD is missing a value: set POSTGRES_PASSWORD in .env`**
`.env` is missing or incomplete. Run the setup step ([setup.md](setup.md#3-create-your-settings-file-env)), from the project folder.

**`SESSION_SECRET must be at least 32 characters`** (api keeps restarting)
The session secret in `.env` is too short. Generate a new one:
```powershell
docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_urlsafe(32))"
```
Put it in `.env` as `SESSION_SECRET=…`, then run `docker compose up -d`. Everyone is signed out.

**`Bind for 127.0.0.1:3000 failed: port is already allocated`**
Something else uses port 3000. Stop it, or add `WEB_PORT=3001` to `.env`, run `docker compose up -d`, and open http://localhost:3001.

**The build fails with a timeout while downloading packages**
It's a network hiccup. Run `docker compose up -d --build` again; downloads are cached.

**The API logs show `password authentication failed for user "crm"`**
`POSTGRES_PASSWORD` in `.env` was changed after the first start. The database keeps the password it was created with. Put the old value back.

If the old value is lost and you have a backup, a fresh start (this deletes the current database) is:
1. `docker compose down -v`
2. `docker compose up -d`
3. Restore the backup ([backup.md](backup.md#restore-replaces-all-data)).

## Signing in

**"Invalid email or password"**
- Use the email and password from the setup step. The email is not case-sensitive.
- Forgot the password? Set a new one ([setup.md](setup.md#changing-your-login-password)).

**"Too many failed logins; try again in N min"**
After 5 wrong passwords within 15 minutes, logins are locked for 15 minutes, even with the right password. Wait, or restart the API to clear the lock:
```powershell
docker compose restart api
```

**"Cross-site request refused" (403)**
Open the app as exactly **http://localhost:3000** or **http://127.0.0.1:3000**. Other addresses, or pages from other sites, are refused on purpose.

## Gmail

**Test says "authentication failed: check the address and the app password"**
- Use an **app password**, not your normal Google password ([email.md](email.md#2-create-an-app-password)).
- 2-Step Verification must be on.
- Copy the 16 letters exactly. Spaces don't matter.
- If you recently changed your Google password, all app passwords were revoked. Create a new one.

**"… and that IMAP is enabled in Gmail settings"**
In Gmail: **Settings → See all settings → Forwarding and POP/IMAP → Enable IMAP**, then save and test again.

**"could not connect (…)"**
The internet connection is down, or a firewall or VPN blocks ports 465 (SMTP) and 993 (IMAP).

**"stored credentials cannot be decrypted with this CREDENTIALS_KEY"**
`CREDENTIALS_KEY` in `.env` changed, for example on a new machine or after restoring on another laptop. Enter the app password again on the Email account page.

**"Enable sending" is greyed out**
Connect and successfully **test** an email account first.

**An email stays "queued"**
Check, in order:
1. Is sending ON (top of the Outbox)?
2. Has the daily cap been reached (the Outbox shows `sent in the last 24 h`)?
3. The minimum gap is 90 s by default.

Queued emails are re-checked before sending. If a check fails, the email is cancelled and the reason is shown on it.

**Notification "Inbox sync is failing"**
The inbox could not be read 3 times in a row: no internet, a revoked app password, or Gmail being down. Test the account on the Email account page. The sync catches up by itself once it works again.

## AI analysis

**"rate limited by Gemini (free tier); will retry"**
The free tier allows about 20 requests per day per model. Analyses retry automatically, up to 3 attempts 10 minutes apart. Use another model in Settings or a paid key if this happens often.

**"Gemini is busy (HTTP 503); will retry"**
Temporary. Retries are automatic.

**"Gemini returned HTTP 404 … not found"**
The model was retired or is not available for your key. Choose one from **Settings → Show available models**.

**"could not reach Gemini (ConnectError)"**
No internet, or DNS failed. Retries are automatic.

## Backups

**The dashboard says the last backup is old**
The app was probably not running for a while. Open **Backup & export → Back up now**. If that fails, the message says why, e.g. the disk is full.

**`pg_dump failed: … server version mismatch`**
The images are out of date. Run `docker compose up -d --build`.

## Still stuck

- `docker compose logs api worker` shows the real error.
- The **Activity** page shows what happened and when.
- The dashboard's **System status** shows whether the database, Redis and the worker are reachable.
