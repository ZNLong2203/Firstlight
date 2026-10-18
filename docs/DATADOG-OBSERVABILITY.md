# Datadog observability

> **Status:** live on a Datadog test org (site ap1) since 18/10/2026. The Agent collects APM traces from the three services, DogStatsD metrics, JSON logs carrying trace ids, and the investigator's LLM Observability spans and evaluations. Monitors, SLOs, dashboards and the webhook are code in `infra/datadog/`, applied with `scripts/datadog-apply.sh`; the notebook in *Proof of recovery* is still the design.

![Observability with Datadog](images/datadog-observability.png)

Datadog has two jobs in Firstlight:

- It watches the **software**: traces, logs and metrics from every service.
- It watches the **ponds**: low-cardinality signals derived in MongoDB, one series per pond or gateway.

Its monitors drive the incident workflow through a webhook. Firstlight writes the proof back as a notebook.

## Tags

Every metric, span, log, RUM event and LLM span carries the same tags. This is what makes "click a red pond, open its trace, its logs and its incident" work.

| Kind | Tags |
|---|---|
| Unified service tagging | `env`, `service` (`firstlight-edge`, `-api`, `-brain`, `-web`), `version` (git sha) |
| Business context | `farm`, `pond`, `gateway`, `incident_id` (when one is open) |

Business tags are set on the active span (`span.set_tag`) and bound to the logger, so a log line and its span share them.

## Getting data in

| Signal | How |
|---|---|
| Traces | `ddtrace` auto-instruments FastAPI, PyMongo and httpx. Gateways call the API with httpx, so one trace runs from the gateway, through the API, to MongoDB. The brain's jobs (forecast, evidence, verify) are custom spans. |
| Logs | JSON to stdout with `dd.trace_id` and `dd.span_id` injected. The Agent tails the containers. |
| Metrics | DogStatsD (UDP 8125) for pond and gateway metrics; APM trace metrics come for free. |
| RUM | Browser SDK in the console, with `allowedTracingUrls` so clicks link to backend traces. |
| LLM Observability | `ddtrace.llmobs`: `workflow`, `agent`, `tool`, `retrieval` and `llm` spans around the Gemini investigator, plus evaluations. |
| Deployments | `DD_VERSION` is the git sha, so Deployment Tracking draws a marker on every chart when the version changes. |

## Custom metrics

About 1,200 contexts: 200 ponds × 6 pond gauges, plus counts and distributions without a pond tag. No per-sensor tags.

| Metric | Type | Tags | Sent by |
|---|---|---|---|
| `firstlight.pond.do`, `.temp`, `.ph`, `.aerators_off` | gauge | farm, pond, gateway | api, on every batch |
| `firstlight.pond.minutes_to_hypoxia` | gauge | farm, pond, gateway | brain, every 10 s (600 when no risk is in sight) |
| `firstlight.pond.freshness_seconds` | gauge | farm, pond, gateway | brain |
| `firstlight.ingest.readings`, `.duplicates` | count | gateway | api |
| `firstlight.ingest.lag_seconds` | distribution | gateway | api: how old a batch is when it lands |
| `firstlight.command.ack_latency_ms` | distribution | action, gateway, status | api |
| `firstlight.incident.opened`, `.resolved` | count | cause, scope | brain |
| `firstlight.incident.mttd_s`, `.mttr_min` | distribution | cause, scope | brain |
| `firstlight.false_alarm.prevented` | count | cause | brain |
| `firstlight.brain.cycle_s` | distribution | | brain: a cycle over 10 s also logs a warning |
| `firstlight.ai.investigations` | count | model, status | brain |
| `firstlight.ai.rca` | count | result, truth | brain, in demo mode |
| `firstlight.ai.latency_ms` | distribution | model, status | brain |

To add with the Datadog setup: per-pond minute counts for the SLOs (`firstlight.pond.safe_minutes`, `.fresh_minutes`, `.total_minutes`), and the gateways' buffer depth and send errors.

## Monitors

Defined in `infra/datadog/monitors.json`. Three of them call the webhook. Each of those alerts carries a pond, gateway or farm: the brain links it to the open incident for that target, with how many seconds after Firstlight's own detection it came, or opens one. The other monitors alert only in Datadog. An aerator under repair, for instance, stays "off" for hours and must not open incident after incident.

| Monitor | Query | Webhook |
|---|---|---|
| A pond is heading for hypoxia | `min(last_2m):min:firstlight.pond.minutes_to_hypoxia{env:demo} by {farm,pond,gateway} < 30`, warning under 45 | yes |
| A gateway's ponds have gone quiet | `max(last_2m):max:firstlight.pond.freshness_seconds{env:demo} by {farm,gateway} > 60` | yes |
| Aerator failure putting a pond at risk | composite: the hypoxia forecast and an aerator that is on but not turning | yes |
| An aerator is switched on but not turning | `max(last_1m):max:firstlight.pond.aerators_off{env:demo} by {farm,pond,gateway} > 0` | no |
| Ingest is slow | `percentile(last_5m):p95:trace.fastapi.request{service:firstlight-api,resource_name:post_/v1/ingest} > 0.5` | no |
| The estate's oxygen is unusually low for this time of night | `anomalies(avg:firstlight.pond.do{env:demo}, 'agile', 3, direction='below', seasonality='daily')` | no |
| The brain's cycle runs past 10 s | `max(last_5m):max:firstlight.brain.cycle_s{env:demo} > 10` | no |
| The AI investigator got a cause wrong | `sum(last_1h):sum:firstlight.ai.rca{result:incorrect}.as_count() > 0` | no |

Every monitor sets `require_full_window: false` and `notify_no_data: false`. A new pond is not judged for its first two minutes (`new_group_delay`), and a monitor that calls the webhook renotifies every 10 minutes. The anomaly monitor needs history, and the simulator runs around the clock to give it some.

## SLOs

Defined in `infra/datadog/slos.json` and based on the monitors above, so they need no extra metric.

| SLO | From the monitor | Target | Window |
|---|---|---|---|
| Oxygen safety | A pond is heading for hypoxia | 99.5% | 7 days |
| Every pond seen | A gateway's ponds have gone quiet | 99% | 7 days |
| Ingest under 500 ms | Ingest is slow | 99% | 7 days |

## Dashboards

Defined in `infra/datadog/dashboards/`, each with an `env` template variable.

| Dashboard | Widgets |
|---|---|
| **Night watch** (business) | lowest oxygen and soonest hypoxia now; incidents and false alarms stopped; oxygen across the estate against the 3 and 4 mg/L lines; the ponds closest to 3 mg/L; incidents by cause; time to detect and to recover; the two pond SLOs; the monitors |
| **Data plane** (system) | ingest rate and p95 by `version`; readings stored; how old a batch is when it lands; the stalest gateways; the brain's cycle; command acknowledgement; MongoDB calls by service; warnings and errors |
| **AI investigator** | investigations finished; share right by the injected fault; investigation time; results over time; where the traces and evaluations are in LLM Observability |

## Applying it, and moving to another org

`scripts/datadog-apply.sh` copies `infra/datadog/` to the demo host and runs `apply.py` there, in a throwaway container with the server's `.env`, so no key leaves the server. Everything is matched by name and tagged `firstlight:managed`: running it again updates in place. To move to another org:
1. put the new `DD_API_KEY`, `DD_APP_KEY` and `DD_SITE` in the server's `.env`;
2. run `docker compose up -d`;
3. run `scripts/datadog-apply.sh`.

## The webhook

`@webhook-firstlight` posts to `https://<PUBLIC_HOST>/v1/hooks/datadog` with this payload:

```json
{
  "alert_id": "$ALERT_CYCLE_KEY",
  "transition": "$ALERT_TRANSITION",
  "monitor_id": "$ALERT_ID",
  "title": "$EVENT_TITLE",
  "scope": "$ALERT_SCOPE",
  "tags": "$TAGS",
  "link": "$LINK",
  "date": "$DATE"
}
```

It carries the header `X-Firstlight-Signature`, which holds `WEBHOOK_SECRET`. The API checks the header, reads the pond, gateway or farm from the alert's scope and tags, and inserts the alert into `alerts` (unique on `alert_id + transition`). It returns 200 within milliseconds, so Datadog's 15 s timeout and retries on 5xx never matter: the brain does the work on its next cycle.

## AI and agent observability

The investigator is a small, bounded agent: Gemini (`gemini-3.8-flash`, falling back to `gemini-3.5-flash`) with five read-only tools and at most five rounds. It never executes an action; the deterministic evidence engine and the playbook decide. It runs on Vertex AI, after the rules have diagnosed the incident and off the critical path.

**What is traced, and how.** ddtrace 4.16 ships a Google GenAI integration that records every `generate_content` and `embed_content` call as an LLM Observability `llm` or `embedding` span, with token counts and no extra code. The investigator is an `agent` span and each tool call a `tool` span, so one incident produces one tree, linked to the brain's APM trace:

```
agent      incident_investigator        tags: incident, rules_cause; metadata: model, rounds
├─ llm        gemini-3.8-flash          auto-instrumented: prompt, output, tokens, latency
├─ tool       pond_readings             arguments and result annotated
├─ tool       recent_deployments        (also gateway_status, farm_overview, past_incidents)
└─ llm        gemini-3.8-flash          the last round has no tools and must answer in the JSON schema
workflow   incident_postmortem          once the incident is closed
└─ llm        gemini-3.8-flash
embedding  gemini-embedding-2           the closed incident, stored as memory; and the query for similar ones
```

Before the agent starts, the three most similar closed incidents are found by hybrid search ([data model](MONGODB-DATA-MODEL.md)) and handed to it with the evidence.

**Evaluations.** No second model grades the first: every check is computed from the record. Each result is stored on the incident and submitted with `LLMObs.submit_evaluation` on the agent's span.

| Evaluation | Type | How it is computed | Why it matters |
|---|---|---|---|
| `agrees_with_rules` | categorical | the agent's cause compared with the rules', when the rules found one | a disagreement goes to a person instead of being acted on |
| `explained_unknown` | categorical | the rules found no cause and the agent offers one | an unknown is not scored as a disagreement; a person checks the suggestion |
| `grounded` | score 0–1 | share of the ponds, farms, gateways and devices the agent names that appear in the incident or in what its tools returned | catches invented evidence |
| `farmer_message_ok` | categorical | Vietnamese, at most 320 characters, names the pond or farm, no internal jargon | the message a farmer reads at 2 a.m. stays short and plain |
| `rca_correct` | categorical, demo mode | the agent's cause compared with the fault injected from the chaos panel, or with the release that carried the regression | accuracy against ground truth; the rules are scored the same way, side by side |

On the demo, 9 incidents had been investigated by 17/10/2026:
- the agent and the rules each matched the injected fault 8 times out of 8;
- every answer was grounded;
- all 9 farmer messages passed.

The console's AI panel shows these numbers from `GET /v1/incidents/ai/stats`.

**Dashboard and monitors.** The AI Investigator dashboard shows latency, tokens and cost per investigation, the fallback-model rate and the four evaluations over time. A monitor alerts the operator, never the farmer, when `rca_correct` falls below 0.8 over the last 20 investigations or when the investigator error rate rises.

**Checked on the trial account before relying on them:** managed evaluations, LLM Observability Experiments, and the agent graph views. The design above works without any of them.

## Proof of recovery

When an incident resolves, the brain creates a notebook through `POST /api/v1/notebooks` containing:

- a summary cell with cause, actions, lead time, MTTR and oxygen debt;
- DO and `minutes_to_hypoxia` for the pond from 10 minutes before detection to 10 minutes after recovery;
- the ack latency of the commands sent;
- links to the incident's traces and logs.

The notebook link is stored on the incident.

## Before the trial ends

Datadog data from a trial does not outlive it. The setup lives as code in `infra/datadog/` and can be recreated in another org with one command, and the demo video is recorded while the data is there.
