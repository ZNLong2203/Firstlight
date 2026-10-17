# Architecture

> **Status:** design baseline. Figures marked *target* are design targets; they are replaced by measurements from the running system as the build lands.

Firstlight runs the night shift for shrimp ponds. It forecasts how many minutes each pond has before it runs short of oxygen. It works out whether an alarm comes from the pond, the probe or the data path, acts within seconds, and proves the pond recovered.

![One incident, end to end](images/incident-timeline.png)

---

## 1. System at a glance

![How Firstlight works](images/architecture-overview.png)

| Component | Role | Runs as |
|---|---|---|
| **firstlight-edge** | Simulated farms: 200 ponds with a physics model of dissolved oxygen (DO), 50 4G gateways, aerators that obey commands, and a chaos API that injects real faults. | Python process |
| **firstlight-api** | Ingests gateway batches, streams live state to the console and commands to gateways over SSE, and receives Datadog webhooks. | FastAPI |
| **firstlight-brain** | Forecasts every pond every 30 s, gathers evidence, picks a playbook, sends commands, verifies recovery and writes the postmortem. It also runs a local failsafe. | Python worker |
| **firstlight-web** | The operator console: the night board, incidents and the chaos panel. | React (Vite), Datadog RUM |
| **MongoDB 8.0** | Operational database: time series readings, live state, the command bus, incidents and incident memory. Atlas Search and Vector Search included. | `mongodb/mongodb-atlas-local:8.0.34` on the same host; the code runs unchanged on Atlas by changing `MONGODB_URI` |
| **Datadog** | Dashboards, monitors and SLOs, APM, logs, RUM, LLM Observability, notebooks. | Managed (SaaS) |
| **Gemini** | Writes the investigation summary, the farmer's message and the postmortem draft. It never decides an action. | Gemini API (`gemini-3.8-flash`, falling back to `gemini-3.5-flash`) |

## 2. Design principles

1. **Right data, right place.** MongoDB keeps every reading at full resolution, plus every command and every incident. Datadog receives low-cardinality signals: one series per pond or gateway, about 1,000 contexts, plus the software's own traces, logs and metrics. Datadog cost does not grow with the number of sensors.
2. **Treat each pond as a service.** The SLI is `minutes_to_hypoxia`. The SLO is "oxygen safety" per pond, with an error budget and burn-rate alerts. Each incident gets an MTTD, an MTTR and a postmortem: SRE practice applied to a living system.
3. **AI stays off the critical path.** Detection and safe actions are deterministic and take seconds, and there is a local failsafe. Gemini explains and drafts; every call is traced and scored in Datadog LLM Observability.

## 3. Main flows

### A. Telemetry (every 10 s)

1. A gateway batches 10 s of readings for its ponds and posts them to `POST /v1/ingest` with a `batch_id`. The trace starts here: the gateway is instrumented with ddtrace, so the trace context travels in the HTTP headers.
2. The API validates the batch and records `batch_id` in `ingest_batches`, which has a unique index and a 1-day TTL. A retried batch is acknowledged and dropped. Time series collections cannot carry a unique index, so deduplication happens here.
3. `readings.insert_many(ordered=False)` writes one document per pond per tick. A `bulk_write` updates `pond_state` with the latest values and freshness.
4. DogStatsD emits `firstlight.pond.*` and `firstlight.gateway.*` metrics tagged `farm`, `pond` and `gateway`.
5. A change stream on `pond_state` pushes the update to the console over SSE. *Target:* under 1 s from batch to screen.

### B. Detection (every 30 s)

1. One aggregation computes a least-squares DO trend for all 200 ponds over the last 30 minutes, using `$setWindowFields` with `$covariancePop` and `$stdDevPop`. The result is `linear_min`, the minutes until DO crosses 3 mg/L.
2. [Toto](https://huggingface.co/Datadog), Datadog's open-weights time series model, forecasts all ponds in one CPU batch from `readings_1m` and gives `toto_p10_min`. A spike on synthetic nights measured about 10 ms per pond and 0.24 s for 200 ponds. Its p10 quantile caught an aerator failure that the median missed.
3. `minutes_to_hypoxia = min(linear_min, toto_p10_min)` is written to `pond_state.forecast` and sent to Datadog.
4. Datadog monitor **M1** (`minutes_to_hypoxia < 30`, multi-alert by pond) fires and calls `@webhook-firstlight`.
5. **Local failsafe:** if DO drops below 3 mg/L, or the forecast below 10 minutes, and no incident is open, the brain opens one and acts without waiting for Datadog.

### C. Investigation: pond, sensor or data path?

![Pond, sensor or data path?](images/three-planes.png)

The API answers the webhook immediately; Datadog times out at 15 s and retries on 5xx. It deduplicates on `alert_id + transition` and queues an incident job. The brain then runs nine checks in parallel. Each returns a hypothesis, a verdict, a weight and a link to the MongoDB document or the Datadog trace or log behind it.

| Plane | Check | Source |
|---|---|---|
| Pond | an aerator's current drops to 0 A within ±2 min of the DO slope change | MongoDB `readings` |
| Pond | every aerator on the farm goes off together (power cut) | MongoDB |
| Pond | the DO day–night swing collapses and pH shifts (algae crash) | MongoDB |
| Sensor | DO falls faster than physics allows with the aerators that are running | MongoDB + model |
| Sensor | rolling variance collapses to about 0 (stuck value) or drifts slowly (fouling) | MongoDB |
| Sensor | pH, temperature and neighbouring ponds disagree with the DO reading | MongoDB |
| Data path | freshness by gateway; gaps found with `$densify` | MongoDB |
| Data path | reconnect errors from the gateway | Datadog Logs API |
| Data path | ingest p95 by `version`, next to deploy markers | Datadog Metrics and Events API |

The weighted sum gives a cause and a confidence, for example `aerator_failure 0.93`. In parallel and off the critical path, Gemini receives the evidence and the three most similar past incidents, found with `$vectorSearch` over `incidents`. It writes the summary, a plain-Vietnamese message for the farmer and a postmortem draft.

### D. Response: a closed loop through MongoDB

1. The brain looks up the diagnosis in `playbooks`. Each step carries a risk level:
   - `auto`: backup aerator on, pause the feeder, message the farmer, open a repair ticket.
   - `approve`: start the generator, emergency water exchange. An operator approves these in the console.
2. The brain inserts the step into `commands` with `status: pending` and a TTL on `expires_at`.
3. The API holds **one** change stream on `commands` and forwards each command to the gateway's open SSE channel. A single stream, rather than one per gateway, keeps the connection pool small.
4. The gateway applies the command to its device and calls `POST /v1/commands/{id}/ack`. The incident timeline updates and `firstlight.command.ack_latency_ms` is recorded.
5. A command without an ack after 15 s is retried, then escalated.

### E. Proof of recovery

1. The verifier marks the pond recovered when DO is ≥ 4 mg/L and its slope is ≥ 0 for N consecutive minutes (2 in demo mode). If the pond is not improving after X minutes, the next playbook step runs or a person is paged.
2. A recovery record is computed with aggregations:
   - lead time: predicted breach time minus detection time;
   - MTTD and MTTR;
   - minimum DO;
   - oxygen debt: `$integral` of (4 − DO)⁺ over time.
3. Monitor M1 returns to OK, and the "Recovered" webhook closes the incident.
4. The brain creates a Datadog notebook through the API, with before-and-after graphs, the timeline and trace links. It stores the postmortem in `incidents`, where it is embedded automatically and becomes memory for the next incident.
5. In demo mode the chaos registry knows the injected fault. The diagnosis is scored against it and submitted to LLM Observability as an evaluation, so RCA accuracy is a number on a dashboard.

### F. Data lifecycle and the night report

- Every minute, `$merge` rolls `readings` up into `readings_1m`; every hour into `readings_1h`. `$merge` cannot target a time series collection, so the rollups are regular collections.
- Retention:

  | Collection | Kept for |
  |---|---|
  | raw `readings` | 14 days |
  | `readings_1m` | 180 days |
  | `readings_1h` | indefinitely |
  | `commands` | 7 days |
  | `ingest_batches` | 1 day |

- At 06:00 farm time the brain writes a **night report** per farm: incidents, actions, minimum DO per pond and the oxygen-safety SLO. The farmer sleeps through the night and reads it in the morning.

## 4. Incident lifecycle

![Incident lifecycle](images/incident-lifecycle.png)

A pond has at most one open incident; later alerts for the same pond attach to it. Each transition appends to `incidents.timeline` and appears in Datadog as a span or an event.

## 5. Reliability and failure modes

| What fails | What Firstlight does |
|---|---|
| Datadog unreachable, or a webhook lost | The local failsafe opens the incident and runs `auto` steps. Datadog catches up when it returns. |
| Gemini unavailable | Detection, diagnosis, actions and proof still run. Only the written summary is missing; a template message goes to the farmer. |
| Duplicate webhook or retried batch | Unique indexes on `alerts {alert_id, transition}` and `ingest_batches._id` make both idempotent. |
| API or brain restarts | Change streams resume from the token saved in `stream_state`. Incident jobs are documents, not memory. |
| Gateway offline | Ponds are marked **blind** with the last safe estimate. Gateways store and forward, and the gap is filled with `$densify` and `$fill` once data returns. |
| Command not acknowledged | Retried after 15 s, then escalated to a person. |
| Bad deploy | Deployment Tracking places the regression next to its `version`. Rollback is a single compose command. |
| Host disk or data loss | A nightly `mongodump` archive is kept on the host for three days; pond data is synthetic and can be regenerated by the simulator. |

## 6. Security and data

- Secrets (`DD_API_KEY`, `DD_APP_KEY`, `MONGODB_URI`, `GEMINI_API_KEY`, `WEBHOOK_SECRET`, `DEMO_CODE`) live only in `.env` on the host. The repository ships `.env.example` with empty values, and a pre-commit hook blocks keys and connection strings.
- The Datadog webhook carries a shared-secret header, which the API checks before doing anything.
- The console is read-only by default; the chaos panel and approvals require a demo code.
- All pond data is synthetic, produced by the simulator and shaped after public aquaculture datasets. No personal, production or regulated data is used.
- MongoDB is never reachable from the internet: its port binds to 127.0.0.1, it requires a password generated on the host, and its container is capped at 3 GB of memory.

## 7. Deployment

![Deployment](images/deployment.png)

| Environment | Composition | Purpose |
|---|---|---|
| Local | `make up` starts the profiles in `COMPOSE_PROFILES`: `localdb` (`mongodb/mongodb-atlas-local:8.0.34`), `datadog` (Agent), `app` (api, brain, edge, web) | Development and integration tests |
| Demo | One VM in Singapore (2 vCPU, 8 GB) runs the same compose file with `COMPOSE_PROFILES=localdb,datadog,app,proxy`: Caddy serves HTTPS and MongoDB runs next to the app. | The public demo and the webhook endpoint. The simulator runs 24/7 so that anomaly monitors learn a real history. |
| CI | GitHub Actions: ruff, mypy, eslint; pytest against an `atlas-local` service container; image build; `DD_VERSION` set to the git sha | Quality gate and Deployment Tracking |

## 8. Technology choices

| Choice | Why |
|---|---|
| Python 3.12, FastAPI, PyMongo `AsyncMongoClient` | Toto, ddtrace and LLM Observability are strongest in Python; Motor is deprecated in favour of PyMongo's async API. PyMongo is pinned below 4.18 until ddtrace supports it. |
| MongoDB time series + regular collections | Time series for compressed, bucketed readings. Regular collections where change streams, Search, unique indexes or `$jsonSchema` are needed, because time series supports none of them. |
| Change streams for the console and the command bus | The database is the single source of truth for state and for control, with resume tokens for restarts. |
| Datadog Toto + aggregation trend | An explainable baseline from the database, plus a foundation model that reacts sooner to sudden changes; the more cautious of the two wins. |
| One Python image, three processes | Simple to build and maintain, while Datadog still sees separate `edge`, `api` and `brain` services. |
| Docker Compose on one VM | One command to run anywhere. Long-lived change streams and SSE need a process that stays up. |
| MongoDB on the same host | No network hop on the hot path, no shared-tier limits on operations, storage or transfer, and Datadog Database Monitoring works (on Atlas it needs M10 or larger). Pinned to 8.0, the long-term-support release. |
| Pinned image versions | `mongodb-atlas-local:8.0.34`, `datadog/agent:7.84.3`, `caddy:2.11.7`, `python:3.12.15-slim`, `nginx:1.30.6-alpine`: every deploy runs exactly what was tested. |

## 9. Repository layout

```
src/firstlight/
  api/        FastAPI: ingest, SSE, Datadog webhook, incidents, chaos proxy
  brain/      forecast, evidence, playbooks, verifier, investigator, reports
  edge/       pond physics, gateways, chaos API
  core/       models, Mongo collections, validators, indexes, telemetry
  ai/         Gemini client, prompts, LLM Observability, evaluations
web/          React console
infra/
  caddy/      Caddyfile for the demo host
  datadog/    dashboards, monitors and SLOs as JSON, plus apply script
  mongo/      collections, $jsonSchema, indexes, search indexes, playbooks
docs/         this documentation
tests/        unit and integration tests (atlas-local)
compose.yaml  one file for laptop and VM; COMPOSE_PROFILES picks localdb, datadog, app, proxy
Makefile      make up, down, logs, config, mongosh
scripts/      vps-bootstrap.sh (Docker, swap, ufw, fail2ban) and deploy.sh (sync and restart on the VPS)
```

## Further reading

- [MongoDB data model](MONGODB-DATA-MODEL.md)
- [Datadog observability](DATADOG-OBSERVABILITY.md)
- [Incident scenarios](INCIDENT-SCENARIOS.md)
