.PHONY: up down logs test password backup restore restore-drill

up:        ## Build and start everything (http://localhost:3000)
	docker compose up -d --build

down:      ## Stop everything (data is kept)
	docker compose down

logs:      ## Follow logs of all services
	docker compose logs -f

test:      ## Run backend tests inside the api image (uses a throwaway crm_test database)
	docker compose run --rm api python -m pytest -q

password:  ## Generate OWNER_PASSWORD_HASH for .env
	docker compose run --rm --no-deps api python -m app.auth

backup:    ## Make a backup now (into ./backups)
	docker compose run --rm api python -m app.backup create

restore:   ## Replace ALL data with a backup: make restore FILE=crm-YYYYMMDD-HHMMSS.dump (sending ends up OFF)
	@test -n "$(FILE)" || (echo "usage: make restore FILE=crm-....dump (see ./backups)"; exit 1)
	docker compose stop web api worker beat
	docker compose run --rm api python -m app.backup restore $(FILE)
	docker compose up -d

restore-drill:  ## Restore the newest backup (or FILE=...) into a throwaway database and verify it
	docker compose run --rm api python -m app.backup drill $(FILE)
