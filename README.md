# Firstlight

**Every pond makes it to morning.**

Oxygen in a shrimp pond bottoms out just before dawn. Firstlight runs the night shift: it forecasts how many minutes each pond has before it runs short of oxygen, tells a pond in trouble from a fouled sensor or a dropped gateway, acts within seconds, and proves the pond recovered. Built on MongoDB and Datadog.

Built for [MUGVN Hackathon 2026: Real-time Operations](https://mini-hackathon-sep-2026.mugvn.com/).
The build window runs from 17 to 31 October 2026; the application code lands in this repository during that window.

![One incident, end to end](docs/images/incident-timeline.png)

![How Firstlight works](docs/images/architecture-overview.png)

## Documentation

- [Architecture](docs/ARCHITECTURE.md): components, flows, failure modes, deployment
- [MongoDB data model](docs/MONGODB-DATA-MODEL.md): collections, lifecycle, aggregation pipelines
- [Datadog observability](docs/DATADOG-OBSERVABILITY.md): tags, monitors, SLOs, dashboards, webhook
- [Incident scenarios](docs/INCIDENT-SCENARIOS.md): the five incidents the demo triggers
- [Declaration](docs/DECLARATION.md): reused components, data and AI tools

## Run it

Requirements: Docker with Compose v2, [uv](https://docs.astral.sh/uv/), Node 22 or newer.

```bash
make up          # first run creates .env from .env.example; COMPOSE_PROFILES picks what starts
make test        # unit tests (set MONGODB_URI to also run the MongoDB integration tests)
make lint        # ruff, mypy and the web typecheck
```

| Profile | Starts |
|---|---|
| `localdb` | MongoDB 8.0 (`mongodb/mongodb-atlas-local`), with Atlas Search and Vector Search |
| `datadog` | Datadog Agent (needs `DD_API_KEY` and `DD_SITE`) |
| `app` | `api`, `brain`, `edge`, `web` |
| `proxy` | Caddy with automatic HTTPS for `PUBLIC_HOST` |

The demo host runs `localdb,datadog,app,proxy` and is deployed with `scripts/deploy.sh`.

## Repository conventions

- `docs/` holds the public technical documentation.
- Commits follow [Conventional Commits](https://www.conventionalcommits.org/). Enable the hooks once per clone:

  ```bash
  git config core.hooksPath scripts/hooks
  ```

  `pre-commit` refuses credentials and anything under `private/`; `commit-msg` checks the subject line.
