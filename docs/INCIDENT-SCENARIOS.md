# Incident scenarios

> **Status:** design baseline. Timings are targets for the demo and are replaced by the values measured in the recorded run.

Firstlight's demo shows operational incidents from the moment they start to the moment they are resolved. Each one is triggered from the chaos panel and has a **real effect on the running system**: an aerator really stops in the simulator, a gateway's network is really cut, a regression is really deployed. The monitors that fire, the traces, the logs and the recovery numbers are therefore the system's own data, not a recording. The pond values themselves are synthetic and come from the simulator's physics model.

![Pond, sensor or data path?](images/three-planes.png)

## Overview

| # | Scenario | Plane | How it is triggered | Correct diagnosis | Response | In the video |
|---|---|---|---|---|---|---|
| 1 | Aerator failure | Pond | aerator `amp` set to 0 in the simulator; oxygen physics follows | `aerator_failure` | backup aerator on (auto) | ✓ |
| 2 | Fouled DO probe | Sensor | probe reading drifts down while the simulated pond stays healthy | `sensor_fault` | no call; maintenance ticket | ✓ |
| 3 | Slow ingest after a deploy | Data path (backend) | deploy `firstlight-api` v1.4, whose ingest query skips an index | `ingest_regression` | roll back to v1.3 | ✓ |
| 4 | Gateway offline | Data path (edge) | the gateway container's network is cut | `gateway_offline` | mark ponds blind; dispatch | live demo |
| 5 | Farm power cut | Pond | every aerator on one farm stops at once | `power_outage` | generator (needs approval) | live demo |

---

## 1. Aerator failure

![One incident, end to end](images/incident-timeline.png)

| Time *(target)* | What happens | Where it shows |
|---|---|---|
| 02:11:00 | Aerator 2 in pond A3 stops. DO starts falling at about 0.05 mg/L per minute. | simulator; `readings.aer[].amp = 0` |
| +10 s | The gateway's batch carries the new readings. | trace `gateway.send → POST /v1/ingest → mongodb.insert` |
| +30 s | The forecast pipeline gives `minutes_to_hypoxia = 24`. | `pond_state.forecast`; Datadog metric |
| +90 s | Monitor M1 fires; the webhook opens INC-0042. | Datadog monitor; `alerts`, `incidents` |
| +92 s | Evidence: AE-2 current fell to 0 A in the same minute DO turned down; pH agrees; gateway and ingest are healthy. Diagnosis `aerator_failure`, 0.93. | `incidents.evidence`; Datadog logs and APM queried |
| +96 s | Command `aerator.on AE-5` is inserted, forwarded by change stream and acked. The farmer gets one message. | `commands`; ack latency metric |
| +3 min | DO climbs. | console; Datadog |
| +5 min | Rising and stable for 2 minutes: resolved. Lead time 24 min, MTTR about 5 min. The pond never left the safe zone. | `incidents.metrics`; notebook; M1 back to OK |

## 2. Fouled DO probe

| What happens | What Firstlight sees | Outcome |
|---|---|---|
| The probe in pond B1 reads lower and lower, down to 0.8 mg/L, while the simulated water is fine. A threshold system would wake the farmer. | DO falls faster than physics allows with four aerators running. pH, temperature and neighbouring ponds disagree. No aerator or power change happened at that minute. | Diagnosis `sensor_fault`. **No call to the farmer.** A ticket asks someone to clean probe DO-B1, and `false_alarm.prevented` goes up by one. |

## 3. Slow ingest after a deploy

| What happens | What Firstlight sees | Outcome |
|---|---|---|
| `firstlight-api` v1.4 is deployed with an ingest query that does not use the `{meta.pond, ts}` index. Ingest p95 climbs, gateways start buffering, and 30 ponds turn **blind**. | Gateway traces show requests arriving but slow, so this is not a 4G problem. Deployment Tracking places the jump exactly at v1.4. The MongoDB span shows a collection scan, and `explain()` confirms it. | Diagnosis `ingest_regression`. Roll back to v1.3; p95 returns to normal. Gateways flush their buffers, `$densify` and `$fill` close the gap, and the check confirms no pond incident was missed while blind. |

This scenario is a software incident in Firstlight itself, so every signal in it comes straight from the running system.

## 4. Gateway offline

| What happens | What Firstlight sees | Outcome |
|---|---|---|
| The network of gateway GW-BL02-1 is cut, and its four ponds stop reporting. | M3 fires on freshness. M5 fires on reconnect errors in the gateway's logs. The API is healthy. | Diagnosis `gateway_offline`. The four ponds are marked **blind** with the last safe estimate ("pond C2: about 40 minutes of margin"). Someone is dispatched. When the link returns, the buffered batches arrive and the gap is checked. |

## 5. Farm power cut

| What happens | What Firstlight sees | Outcome |
|---|---|---|
| Every aerator on farm BL-03 stops at once. | All ponds on the farm get the same slope change at the same minute, and every `amp` reads 0. | Diagnosis `power_outage`. Starting the generator is an `approve` step: the operator approves it in the console, and the generator command goes out through the same command bus. |

---

## Ground truth and evaluation

The chaos registry records every injected fault with its pond, device and start time. When an incident resolves, Firstlight compares its diagnosis with the registry and submits `rca_correct` to Datadog LLM Observability. The demo reports the accuracy across all runs, not a single example.

## Outside demo mode

The same checks run on every real alert. Without a chaos registry there is no automatic score; instead the operator confirms or corrects the diagnosis in the console, and that answer becomes the evaluation.
