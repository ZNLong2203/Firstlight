# Capacity and cost

> **Status:** measured on 17/10/2026 on the demo host, a HostHatch NVMe 8 GB VM in Singapore (2 vCPU, 8 GB, about 9 USD a month). It runs MongoDB 8.0 and the whole application. Prices are list prices, read the same day from the providers' public pages; the sources are at the end.

## What one host carries

`scripts/loadtest.sh` starts a second API, brain and simulator on the demo host, writing to a database of its own. The demo's 200 ponds keep running beside it, so the host carries both. Each simulated gateway sends a batch every 10 seconds for its farm's ponds, four on average. Every minute the script records:
- readings stored per second;
- how old each pond's newest reading is;
- the brain's cycle time;
- CPU and memory per container.

| Load added to the demo | Readings stored | Newest reading, p99 | Brain cycle (target 10 s) | MongoDB | Errors |
|---|---|---|---|---|---|
| 1,000 ponds on 250 gateways (×5) | 83–86 per s | 11 s | 0.8–1.3 s | 72–78% of one core, 2.0 GB | none |
| 2,000 ponds on 500 gateways (×10) | 147–178 per s | 18–23 s | 13–21 s, 30 s at worst | 60–110% of one core, 2.0 GB | none |

- **At five times the demo,** 1,200 ponds on one host, everything holds with room to spare. The brain forecasts, checks and rolls up every pond in about a second.
- **At ten times,** 2,200 ponds, ingest still holds: no errors, and no reading older than 23 s. The brain, however, takes 13–21 s per cycle, so each pond is forecast every 15–20 s instead of every 10. The brain process itself used under 12% of a core; the time goes in MongoDB, which has two cores for the ingest of 2,200 ponds as well.
- **The simulator** of the ×10 run reached 41–45 of the 50 batches a second it should send. It is one Python process computing the physics of 2,000 ponds.

The next steps for more ponds per host:
- write `pond_state` only when a pond's status or forecast changes, not on every cycle;
- split the forecast into parallel aggregations, one per province;
- give MongoDB more cores, or move it to Atlas, which the code runs on unchanged.

## Cost per pond per month

At 1,200 ponds per host, the load measured above with room to spare. List prices in USD, billed annually where both are listed.

| Item | Price | For 1,200 ponds | Per pond |
|---|---|---|---|
| The VM | $9 a month | $9 | $0.008 |
| Datadog Infrastructure Pro, one host | $15 | $15 | $0.013 |
| Datadog APM: three services, one host | $31 | $31 | $0.026 |
| Datadog custom metrics: about 7.5 per pond (see below) | $5 per 100, after 100 included with the host | 8,900 billed: $445 | $0.371 |
| Datadog logs and RUM | $0.10 per GB ingested, $1.70 per million indexed; RUM $0.15 per 1,000 sessions | under $1 | – |
| LLM Observability | free up to 40,000 LLM spans a month; an incident uses about 6 | $0 | $0 |
| Gemini 3.8 Flash on Vertex AI, if every pond has one incident a month | about $0.014 per incident (see below) | $17 | $0.014 |
| Gemini embeddings | $0.20 per million tokens; two short texts per incident | – | – |
| Telegram | free | $0 | $0 |
| **Total** | | **about $517** | **about $0.43** |

The custom metrics per pond are:
- six gauges tagged with the pond: oxygen, temperature, pH, aerators off, minutes to hypoxia and freshness;
- the gateway's ingest-lag distribution, which counts five times, and its readings count, both shared by the farm's ponds, four on average.

The Gemini cost comes from the demo's 9 investigations so far:
- to investigate, 11,500 input tokens and 500 output tokens on average;
- for the postmortem, 1,700 input and 500 output.

At the introductory price, which runs until 31/12/2026, that is $0.75 per million input tokens and $3.75 per million output tokens. Thinking tokens are billed as output too. They are recorded from this deploy on and not yet in the figure, and the price doubles from 2027.

**Datadog custom metrics are 86% of the bill.** Each pond gauge costs about $0.05 a month, while MongoDB keeps every reading of a pond for 14 days in 1.1 MB. Sending only `minutes_to_hypoxia`, `freshness_seconds` and `do` to Datadog would bring a pond to about $0.28 a month, and the rest stays queryable in MongoDB.

## Against what is at stake

A 3,000 m² pond at day 90 holds about 5 tonnes of shrimp. At the farm-gate prices of 16/10/2026 they are worth about 575 million VND ([how that is estimated](ARCHITECTURE.md#g-what-is-at-stake)). Monitoring that pond for a year costs about $5.

## Sources

| What | Where |
|---|---|
| The VM | [hosthatch.com/products](https://hosthatch.com/products): "NVMe 8 GB", from $9.00 a month |
| Datadog | [datadoghq.com/pricing](https://www.datadoghq.com/pricing/) and the [list page](https://www.datadoghq.com/pricing/list/). The $5 per 100 custom metrics is on the list page only; the main page says to contact sales. How metrics are counted: [custom metrics billing](https://docs.datadoghq.com/account_management/billing/custom_metrics/), where a distribution counts five times per tag combination, ten with percentiles. |
| Vertex AI | [Generative AI pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing): Gemini 3.8 Flash at $0.75 / $3.75 per million tokens until 31/12/2026, then $1.50 / $7.50; reasoning is billed as output |
| Load tests | `scripts/loadtest.sh 250 4` and `scripts/loadtest.sh 500 5`, on the demo host |
| Token counts | the demo's investigations, from `GET /v1/incidents` |
