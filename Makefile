.PHONY: up down logs test password

up:        ## Build and start everything (http://localhost:3000)
	docker compose up -d --build

down:      ## Stop everything (data is kept)
	docker compose down

logs:      ## Follow logs of all services
	docker compose logs -f

test:      ## Run backend tests inside the api image
	docker compose run --rm --no-deps api python -m pytest -q

password:  ## Generate OWNER_PASSWORD_HASH for .env
	docker compose run --rm --no-deps api python -m app.auth
