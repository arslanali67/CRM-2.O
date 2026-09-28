.PHONY: up down logs test password backup restore restore-drill e2e

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

E2E = docker compose -p crm-e2e --env-file frontend/e2e/.env.e2e

e2e:       ## Browser E2E on an isolated stack (port 3100, test-only owner, sending OFF, no Gmail); your data is untouched
	node frontend/e2e/setup-env.mjs
	$(E2E) up -d --build --wait
	for i in $$(seq 90); do curl -sf http://127.0.0.1:3100/api/health >/dev/null && break; sleep 2; done
	cd frontend && npx playwright test; status=$$?; cd .. && $(E2E) down -v; exit $$status
