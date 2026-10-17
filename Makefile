# Firstlight: everyday commands. Settings come from .env, and from .env.local when it exists.
ENV_FILES = $(foreach f,.env .env.local,$(if $(wildcard $(f)),--env-file $(f)))
COMPOSE   = docker compose $(ENV_FILES)

.PHONY: up down ps logs config mongosh pull test lint fmt deploy

.env:
	cp .env.example .env
	sed -i.bak -e "s/^MONGO_ROOT_PASSWORD=$$/MONGO_ROOT_PASSWORD=$$(openssl rand -hex 24)/" -e "s/^GATEWAY_TOKEN=$$/GATEWAY_TOKEN=$$(openssl rand -hex 24)/" -e "s/^DEMO_CODE=$$/DEMO_CODE=$$(openssl rand -hex 5)/" .env && rm -f .env.bak
	@echo "Created .env from .env.example with a random MongoDB password, gateway token and demo code. Fill in the keys you have."

up: .env            ## start the profiles listed in COMPOSE_PROFILES
	$(COMPOSE) up -d --build --wait

down:               ## stop everything (data volumes are kept)
	$(COMPOSE) down

ps:
	$(COMPOSE) ps

logs:               ## follow logs, e.g. make logs s=api
	$(COMPOSE) logs -f --tail=100 $(s)

config:             ## validate compose.yaml with the current settings
	$(COMPOSE) config --quiet && echo "compose.yaml is valid"

pull:
	$(COMPOSE) pull --ignore-buildable

mongosh:            ## open a shell on the local MongoDB
	$(COMPOSE) exec mongo mongosh "mongodb://localhost:27017/?directConnection=true"

test:               ## unit tests; set MONGODB_URI to include the MongoDB integration tests
	uv run pytest -q

lint:               ## ruff, formatting check, mypy, web typecheck
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src
	cd web && npm run typecheck

fmt:
	uv run ruff check --fix .
	uv run ruff format .

deploy:             ## sync to the VPS and restart (add ARGS=--build to build there)
	scripts/deploy.sh $(ARGS)
