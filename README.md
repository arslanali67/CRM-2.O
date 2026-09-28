# Job Outreach CRM

A personal CRM for a job search by email, run on your own laptop. You can:
- import companies from a CSV
- write templated emails and approve each one yourself before it is sent from your Gmail
- track replies, with optional AI help to read them
- manage the opportunities that come out of those replies

## The safety rule

The system may **prepare, personalize and, only after your explicit approval of each email, send**.
It **never** replies to anyone automatically, never sends follow-ups, never negotiates, never applies to jobs and never messages anyone on LinkedIn. When a company replies, the app only notifies you and analyses the reply; any follow-up is a task for you, never an email.

This is enforced in the database and covered by the safety test suite S1–S12 ([PROJECT.md](PROJECT.md) §2, M31).
Sending is **OFF** until you switch it on in the Outbox.

## Quick start (Windows, about 10 minutes)

You need **Docker Desktop** and **Git**. [docs/setup.md](docs/setup.md) walks through installing them.

```powershell
git clone https://github.com/arslanali67/CRM-2.O.git
cd CRM-2.O
docker run --rm -it -v "${PWD}:/work" -w /work python:3.12-slim python backend/scripts/setup_env.py
docker compose up -d --build
```

The third line asks for the email and password you want to log in with, then writes `.env` with every secret generated. If you have `make` installed, `make setup` does the same.

Open **http://localhost:3000** and sign in. The first build takes a few minutes.

## Documentation

| Guide | What it covers |
|---|---|
| [Setup](docs/setup.md) | Installing, first start, updating, stopping, changing your password |
| [Email (Gmail)](docs/email.md) | 2-step verification, app password, connecting, the sending switch |
| [AI analysis](docs/ai.md) | Gemini key, free-tier limits and privacy, choosing the model |
| [User guide](docs/user-guide.md) | The daily workflow: import → compose → approve → replies → opportunities |
| [Backup & restore](docs/backup.md) | Automatic backups, restore, restore drill, exports |
| [Troubleshooting](docs/troubleshooting.md) | Real errors and how to fix them |

## Project files

- [PROJECT.md](PROJECT.md): the specification. It is the single source of truth for what gets built.
- [MILESTONES.md](MILESTONES.md): progress.
- [CLAUDE.md](CLAUDE.md): the change process.

## Running the tests

```powershell
docker compose run --rm api python -m pytest -q      # backend + safety suite (uses a throwaway crm_test database)
make e2e                                             # browser tests on an isolated copy (port 3100)
```

Tests never contact Gmail or Gemini.
