# Setup

The app runs entirely on your laptop in Docker. It is only reachable from your own machine, at http://localhost:3000. Nothing is installed on Windows except Docker Desktop and Git.

## 1. Install the tools (once)

1. **Docker Desktop**: download from https://www.docker.com/products/docker-desktop/ and install it with the default options (WSL 2 backend). Restart Windows if asked.
   - Start Docker Desktop and wait until it says **Engine running**.
   - Check in PowerShell: `docker version` shows both a Client and a Server section.
2. **Git**: download from https://git-scm.com/download/win and install it with the defaults.
   - Check: `git --version`.
3. **make** is optional. Every `make …` command in these docs also has a plain `docker …` equivalent. If you want it, run `winget install GnuWin32.Make` and add `C:\Program Files (x86)\GnuWin32\bin` to your PATH.

## 2. Get the code

```powershell
cd $HOME\Desktop
git clone https://github.com/arslanali67/CRM-2.O.git
cd CRM-2.O
```

## 3. Create your settings file (`.env`)

```powershell
docker run --rm -it -v "${PWD}:/work" -w /work python:3.12-slim python backend/scripts/setup_env.py
```

With make, the same command is `make setup`.

It asks for:
- **Your login email**: any address you like. It is only used to sign in to this app.
- **A login password**: at least 12 characters, typed twice. It is stored only as a scrypt hash.

It then generates every secret (session key, database password, encryption key for the Gmail app password) and writes `.env`. It never prints a secret, and it refuses to overwrite an existing `.env`.

**Keep a private copy of `.env`** (e.g. on a USB stick or in a password manager). Backups do not include it on purpose. Never commit or share it; the repository is public.

AI analysis stays off until you add a Gemini key ([ai.md](ai.md)).

## 4. Start

```powershell
docker compose up -d --build
```

With make: `make up`.

The first build downloads and builds everything, which takes 3–10 minutes. Then open **http://localhost:3000** and sign in with the email and password from step 3.

Check that everything is running:
```powershell
docker compose ps
```
You should see `postgres`, `redis`, `api`, `worker`, `beat` and `web`, all `Up`. The dashboard's **System status** line should show `database: ok · redis: ok · worker: ok`.

Next, connect Gmail ([email.md](email.md)). Then read the [user guide](user-guide.md).

## Everyday commands

| What | Command | With make |
|---|---|---|
| Start (also after a reboot) | `docker compose up -d` | `make up` |
| Stop (data is kept) | `docker compose down` | `make down` |
| See logs | `docker compose logs -f` | `make logs` |
| Status | `docker compose ps` | |

Docker Desktop must be running. The app keeps running in the background until you stop it or shut down Windows. Inbox sync only works while it runs; replies that arrive while it's stopped are fetched on the next start.

## Updating to a new version

```powershell
git pull
docker compose up -d --build
```

Database changes (migrations) are applied automatically when the API starts. Make a backup first ([backup.md](backup.md)).

## Changing your login password

1. Generate a new hash:
   ```powershell
   docker compose run --rm --no-deps api python -m app.auth
   ```
   With make: `make password`.
2. Put the printed line into `.env` as `OWNER_PASSWORD_HASH=…`.
3. Restart: `docker compose up -d`.

## Where things are

| What | Where |
|---|---|
| Your data (database, including CVs) | Docker volume `<folder>_pgdata`, e.g. `crm-2o_pgdata` (survives `down`, but not `down -v`) |
| Backups | the `backups` folder in the project |
| Settings and secrets | `.env` in the project |

**Never run `docker compose down -v`** unless you really want to delete all data. `-v` removes the database volume.
