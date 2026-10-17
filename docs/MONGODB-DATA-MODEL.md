# MongoDB data model

> **Status:** the collections and pipelines below match the running code. They are written for MongoDB 8.0 and run on `mongodb-atlas-local:8.0.34` on the demo host, which includes Atlas Search and Vector Search; the same code runs on Atlas. Toto forecasts and incident search are marked as planned. Measured figures (ingest rate, compression, `explain()` output) are added in the last section.

![Data in MongoDB](images/mongodb-data-model.png)

## Why this shape

| Need | Where it lives | Reason |
|---|---|---|
| Every reading, compressed, queried by pond and time | `readings`, a **time series** collection | Bucketed and column-compressed storage; 8.0 block processing speeds up the window functions that run every 10 s. |
| Something the console and gateways can subscribe to | `pond_state`, `commands`, `incidents` (regular collections) | Time series collections do not support change streams. |
| Exactly-once handling of retries | `ingest_batches`, `alerts` with unique indexes | Time series collections cannot carry a unique index. |
| Validation of device documents | `devices` with `$jsonSchema` | Time series collections do not support schema validation. |
| Searching past incidents by meaning | `incidents` with Atlas Vector Search and Atlas Search | Search indexes cannot be built on time series collections. |
| Cheap long-term history | `readings_1m`, a time series collection the brain inserts into; `readings_1h`, a regular collection built with `$merge` | `$merge` cannot write into a time series collection, so the brain writes the minute rollups itself. |

The pond id (`BL-01-A3`) is the join key everywhere. It appears in `readings.meta.pond`, `pond_state._id`, `devices.pond`, `commands.pond` and `incidents.pond`, and as the `pond` tag on every Datadog metric, span and log.

## Collections

### `readings`: time series

```js
db.createCollection("readings", {
  timeseries: { timeField: "ts", metaField: "meta", granularity: "seconds" },
  expireAfterSeconds: 14 * 24 * 3600
})
db.readings.createIndex({ "meta.pond": 1, ts: -1 })
```

One document per pond per tick carries every measurement for that tick. This produces fewer buckets and better compression than one document per sensor. The `meta` fields are stable identifiers only.

```js
{
  ts: ISODate("2026-10-20T19:11:00Z"),
  meta: { farm: "BL-01", pond: "BL-01-A3", gateway: "GW-BL01-1" },
  do: 4.21, temp: 29.4, ph: 7.62,
  aer: [ { id: "AE-1", on: true, amp: 6.1 }, { id: "AE-2", on: true, amp: 0.0 } ],
  probe: { id: "DO-A3", q: 0.98 },
  batch: "GW-BL01-1:000912"
}
```

### `pond_state`: computed pattern, change stream to the console

```js
{
  _id: "BL-01-A3", farm: "BL-01", gateway: "GW-BL01-1", area_m2: 3900,
  aerators: ["AE-BL-01-A3-1", "AE-BL-01-A3-2"], standby: ["AE-BL-01-A3-S"], probe: "DO-BL-01-A3",
  status: "watch",                       // ok | watch | alert | sensor | blind
  last: { ts: ISODate("…"), do: 4.21, temp: 29.4, ph: 7.62, aerators_on: 3, aerators_running: 2,
          aer: [ { id: "AE-BL-01-A3-1", on: true, amp: 0.0 }, … ], probe_q: 0.98 },
  forecast: { at: ISODate("…"), minutes_to_hypoxia: 24, slope_per_min: -0.05, points: 12 },
  freshness_s: 12, open_incident: "INC-0042",
  repair_tickets: [ { device: "AE-BL-01-A3-1", incident: "INC-0042" } ],  // known, handled faults
  sensor_ticket: { incident: "INC-0043", probe: "DO-BL-01-A3" }            // probe known to be wrong
}
```

Ingest updates `last` with a pipeline update that only replaces it when the reading is newer, so a gateway's late backlog never rewinds the pond. The brain writes `status` and `forecast` every 10 s. A repair ticket keeps a broken aerator's 0 A from raising a new alarm until it draws current again; Toto's `p10` and `p90` join `forecast` when that work lands.

### `commands`: the command bus

```js
{
  _id: ObjectId("…"), gateway: "GW-BL01-1", pond: "BL-01-A3", device: "AE-BL-01-A3-S",
  action: "aerator.on", incident: "INC-0042", risk: "auto",
  status: "done",                        // pending → sent → done | failed | expired
  attempts: 0, created_at: ISODate("…"), deliver_by: ISODate("…"),   // two minutes to get through
  executed_at: ISODate("…"),             // by the gateway's clock, when the device acted
  acked_at: ISODate("…"), result: { device: "AE-BL-01-A3-S", on: true, turning: true },
  expires_at: ISODate("…")               // kept seven days
}
db.commands.createIndex({ gateway: 1, status: 1 })
db.commands.createIndex({ status: 1, created_at: 1 })
db.commands.createIndex({ expires_at: 1 }, { expireAfterSeconds: 0 })
```

A command not acknowledged within 15 s is set back to `pending`, which the change stream delivers again; after three retries or two minutes it expires and the incident escalates. Gateways run each command id once and acknowledge repeats with the first result, so delivery is at least once and execution exactly once.

### `incidents`: what happened, what we did, what to do next time

```js
{
  _id: "INC-0042", key: "BL-01-A3", open: true,          // `open` is removed when it closes
  scope: "pond",                                         // pond | gateway | farm | estate
  pond: "BL-01-A3", ponds: ["BL-01-A3"], farm: "BL-01", gateway: "GW-BL01-1",
  status: "verifying",  // investigating → mitigating → verifying → resolved; also monitoring,
                        // awaiting_approval, escalated, dismissed (a stopped false alarm)
  opened_at: ISODate("…"), signals: ["aerator_down"],
  at_detection: { do: 4.62, minutes_to_hypoxia: null, last_seen: ISODate("…") },
  diagnosis: { cause: "aerator_failure", confidence: 0.85, onset: ISODate("…"), device: "AE-BL-01-A3-1",
               scores: { aerator_failure: 0.85, sensor_fault: -0.2, gateway_offline: -0.2, … } },
  evidence: [ { check: "aerator_current_drop", cause: "aerator_failure", verdict: "support", weight: 0.85,
                detail: "AE-BL-01-A3-1 drew 8.9 A, then 0 A", at: ISODate("…") },
              { check: "probe_quality", cause: "sensor_fault", verdict: "against", weight: 0.2, … },
              { check: "freshness", cause: "gateway_offline", verdict: "against", weight: 0.2, … } ],
  timeline: [ { t: ISODate("…"), kind: "detected", source: "brain", signals: ["aerator_down"] },
              { t: ISODate("…"), kind: "diagnosed", cause: "aerator_failure", confidence: 0.85 },
              { t: ISODate("…"), kind: "action_sent", action: "aerator.on", device: "AE-BL-01-A3-S", command: ObjectId("…") },
              { t: ISODate("…"), kind: "notify", to: "owner", text: "Ao BL-01-A3: quạt … ngừng quay lúc 00:55 …" },
              { t: ISODate("…"), kind: "action_done", … }, { t: ISODate("…"), kind: "verifying", … }, … ],
  actions: [ { kind: "command", action: "aerator.on", device: "AE-BL-01-A3-S", command: ObjectId("…") },
             { kind: "ticket", target: "repair_aerator", device: "AE-BL-01-A3-1", status: "open", text: "…" } ],
  approvals: [],                                         // costly steps waiting for a person
  metrics: { mttd_s: 10, time_to_action_s: 1, mttr_min: 2.8, min_do: 4.45, below_safe_min: 0,
             oxygen_debt: 0.0, lead_time_min: null }
}
db.incidents.createIndex({ pond: 1, status: 1 })
db.incidents.createIndex({ opened_at: -1 })
// one open incident per pond, gateway, farm or estate: a second detector finds the first instead
db.incidents.createIndex({ key: 1 }, { unique: true, partialFilterExpression: { open: true } })
```

The ground truth of a demo fault is not stored on the incident: it lives in `chaos`, which the brain never reads while it investigates. Embedding, summaries and postmortems are planned with the AI investigator.

When an incident resolves, the brain embeds its summary with Gemini (`gemini-embedding-2`, 768 dimensions, returned already normalised) and stores it in `embedding`. The model ignores the `taskType` parameter, so the task goes into the text: documents are embedded as `title: none | text: …` and queries as `task: search result | query: …`. On our own test set of 22 incidents and 18 English and Vietnamese queries, this kept top-1 accuracy at 100% and raised cross-language recall@3 from 0.06 to 0.62. Two search indexes cover the collection:

```json
// incident_vectors (vectorSearch)
{ "fields": [
    { "type": "vector", "path": "embedding", "numDimensions": 768, "similarity": "cosine" },
    { "type": "filter", "path": "status" },
    { "type": "filter", "path": "diagnosis.cause" } ] }

// incident_text (search)
{ "mappings": { "dynamic": false, "fields": {
    "summary": { "type": "string" }, "postmortem_md": { "type": "string" } } } }
```

On Atlas, automated embedding with Voyage AI can replace the Gemini step; the queries stay the same.

### Other collections

| Collection | Shape | Indexes and features |
|---|---|---|
| `devices` | `type` (`do_probe`, `aerator`, `feeder`, `generator`, `gateway`), `pond`, `farm`, and type-specific fields such as `aerator.kw` or `probe.cleaned_at` | `$jsonSchema` with `oneOf` per type; `2dsphere` on farm location |
| `alerts` | raw Datadog webhook: `alert_id`, `transition`, `monitor`, `pond`, `payload`, `received_at` | unique `{ alert_id: 1, transition: 1 }` |
| `ingest_batches` | `_id` = batch id, `received_at` | TTL 1 day on `received_at` |
| `readings_1m` | time series: `minute`, `meta { pond, farm, gateway }`, `do_avg`, `do_min`, `do_max`, `temp`, `ph`, `n` | kept 180 days (`expireAfterSeconds`); `{ meta.pond, minute }` |
| `readings_1h` | `_id { pond, hour }`, `farm`, `do_avg`, `do_min`, `do_max`, `safe_minutes`, `minutes` | kept indefinitely |
| `playbooks` | `_id` = cause, `steps [ { action, target, risk } ]`, `then` (`verify`, `dismiss`, `monitor`, `escalate`) | unique on `cause`; defaults written once, edits kept |
| `chaos` | the demo's ground truth: `kind`, `pond`, `gateway`, `farm`, `device`, `started_at`, `cleared_at` | `{ status: 1, started_at: -1 }` |
| `events` | what a gateway did on its own (the failsafe), reported with its next batch | `_id` = batch id + index, so a retry adds nothing; TTL 30 days |
| `counters` | `_id: "incident"`, `seq` | `$inc` gives the next `INC-0001` id |
| `reports` | `{ farm, date }`, incidents, minimum DO per pond, SLO (planned) | unique `{ farm: 1, date: 1 }` |

## Aggregation pipelines

Each pipeline answers one operational question.

### How many minutes until this pond runs out of oxygen?

Least-squares slope of DO over the last 12 minutes, for every pond in one aggregation every 10 s. The fit only uses readings since the pond's setup last changed. That means a change in the number of turning aerators, or a jump of 0.2 or more in the probe's signal quality: when an aerator stops, the standby starts or a fouled probe is cleaned, the old trend no longer describes the pond. The pipeline works like this:

1. `$shift` compares each reading with the one before.
2. A running `$sum` numbers the regimes.
3. A `$group` keeps the running sums of the regression for each pond and regime.

```js
const all = { documents: ["unbounded", "current"] }, whole = { documents: ["unbounded", "unbounded"] }
const byPond = { partitionBy: "$meta.pond", sortBy: { ts: 1 } }
db.readings.aggregate([
  { $match: { ts: { $gte: since } } },
  { $set: { turning: { $size: { $filter: { input: "$aer", cond: { $gte: ["$$this.amp", 0.5] } } } },
            q: { $ifNull: ["$probe.q", 1] } } },
  { $setWindowFields: { ...byPond, output: {
      prev_turning: { $shift: { output: "$turning", by: -1 } },
      prev_q:       { $shift: { output: "$q", by: -1 } } } } },
  { $setWindowFields: { ...byPond, output: {
      regime: { $sum: { $cond: [ { $and: [ { $ne: ["$prev_turning", null] }, { $or: [
                  { $ne: ["$prev_turning", "$turning"] },
                  { $gte: [ { $abs: { $subtract: ["$q", "$prev_q"] } }, 0.2 ] } ] } ] }, 1, 0 ] },
                window: all },
      newest_ts: { $max: "$ts", window: whole } } } },
  { $set: { t: { $divide: [ { $subtract: ["$ts", since] }, 60000 ] } } },   // minutes: small numbers
  { $group: { _id: { pond: "$meta.pond", regime: "$regime" },
      n: { $sum: 1 }, st: { $sum: "$t" }, sy: { $sum: "$do" },
      stt: { $sum: { $multiply: ["$t", "$t"] } }, sty: { $sum: { $multiply: ["$t", "$do"] } },
      do_1m: { $avg: { $cond: [ { $lte: [ { $subtract: ["$newest_ts", "$ts"] }, 60000 ] }, "$do", null ] } } } },
  { $group: { _id: "$_id.pond", fit: { $top: { sortBy: { "_id.regime": -1 }, output: "$$ROOT" } } } },
  // slope = (sty/n - st/n * sy/n) / (stt/n - (st/n)^2), in mg/L per minute, once n >= 9
  // minutes_to_hypoxia = (do_1m - 3) / -slope while the slope is below -0.005
])
```

The same `$group` also keeps the first and newest reading of the last three minutes. Their difference is `rate_3m`, the value `$derivative` would give, and it is published once the window holds 12 readings.

The first version fitted the line with a third `$setWindowFields` stage, using `$covariancePop` and `$stdDevPop` over the regime partition. It was timed stage by stage on the demo's 200 ponds (14,400 readings in the window). That stage and the `$top` after it cost 384 of the 684 ms, because each window stage sorts and passes every reading again. Running sums in a `$group` give the same result for all 200 live ponds, and the median time drops from 671 ms to 345 ms.

### Pond, sensor or data path?

The evidence engine reads a pond's last 15 minutes with the rate of change of DO and pH:

```js
{ $setWindowFields: { sortBy: { ts: 1 },
    output: { do_rate: { $derivative: { input: "$do", unit: "minute" }, window: { range: [-180, 0], unit: "second" } },
              ph_rate: { $derivative: { input: "$ph", unit: "minute" }, window: { range: [-180, 0], unit: "second" } } } } }
```

From these it weighs each plane: an aerator switched on but drawing 0 A (pond), DO falling faster than water can lose oxygen while every aerator turns, or DO falling a lot while pH holds (sensor), and how fresh the readings are or how many gateways went quiet (data path).

### Is the probe stuck?

```js
{ $setWindowFields: { partitionBy: "$meta.pond", sortBy: { ts: 1 },
    output: { sd_5m: { $stdDevPop: "$do", window: { range: [-300, 0], unit: "second" } } } } },
{ $match: { sd_5m: { $lt: 0.005 } } }
```

### How much stress did the shrimp take? (oxygen debt)

```js
db.readings.aggregate([
  { $match: { "meta.pond": "BL-01-A3", ts: { $gte: start, $lte: end } } },
  { $set: { deficit: { $max: [0, { $subtract: [4, "$do"] }] } } },
  { $setWindowFields: { sortBy: { ts: 1 },
      output: { debt: { $integral: { input: "$deficit", unit: "minute" },
                        window: { documents: ["unbounded", "current"] } } } } },
  { $group: { _id: null, oxygen_debt: { $max: "$debt" }, min_do: { $min: "$do" } } }
])
```

### What happened while a gateway was offline?

When the ponds report again, the backlog the gateway stored is checked slot by slot. Readings are grouped into 20-second slots, `$densify` adds every slot that got none, and the count of empty slots gives the coverage of the blind spell:

```js
db.readings.aggregate([
  { $match: { "meta.pond": { $in: ponds }, ts: { $gte: from, $lt: to } } },
  { $group: { _id: { pond: "$meta.pond", slot: { $dateTrunc: { date: "$ts", unit: "second", binSize: 20 } } },
              min_do: { $min: "$do" } } },
  { $project: { _id: 0, pond: "$_id.pond", slot: "$_id.slot", min_do: 1 } },
  { $densify: { field: "slot", partitionByFields: ["pond"],
                range: { step: 20, unit: "second", bounds: [from, to] } } },
  { $group: { _id: null, slots: { $sum: 1 }, min_do: { $min: "$min_do" },
              missing: { $sum: { $cond: [ { $eq: [ { $type: "$min_do" }, "missing" ] }, 1, 0 ] } } } }
])
```

`$fill` with `method: "linear"` draws the chart across a gap that stayed empty.

### Rollups for the data lifecycle

The minute rollups go into `readings_1m`, a time series collection like the readings themselves. `$merge` cannot write into one, so the brain runs the aggregation and inserts the rows:

```js
const rows = db.readings.aggregate([
  { $match: { ts: { $gte: start, $lt: end } } },
  { $group: {
      _id: { pond: "$meta.pond", minute: { $dateTrunc: { date: "$ts", unit: "minute" } } },
      farm: { $first: "$meta.farm" }, gateway: { $first: "$meta.gateway" },
      do_avg: { $avg: "$do" }, do_min: { $min: "$do" }, do_max: { $max: "$do" },
      temp: { $avg: "$temp" }, ph: { $avg: "$ph" }, n: { $sum: 1 } } },
  { $project: { _id: 0, minute: "$_id.minute",
      meta: { pond: "$_id.pond", farm: "$farm", gateway: "$gateway" },
      do_avg: 1, do_min: 1, do_max: 1, temp: 1, ph: 1, n: 1 } }
]).toArray()
db.readings_1m.insertMany(rows, { ordered: false })
```

`start` is the minute after the newest row already stored, or the first reading after it, so a stretch without data is skipped. `end` is the last complete minute, at most an hour later. A brain that was down therefore catches up an hour per cycle instead of leaving a hole, and nothing is rolled up twice. The hourly rollups are small enough for a regular collection, so they use `$merge` from `readings_1m` into `readings_1h`.

### How is the night going across the estate?

The console's night curve: every ten minutes since dusk, the lowest reading of any pond, and the 10th percentile and median of the ponds' minute averages. It runs over the minute rollups with `$percentile` and `$median`, and takes about 120 ms for a night of 200 ponds. The API computes it at most once a minute, however many consoles ask.

```js
db.readings_1m.aggregate([
  { $match: { minute: { $gte: dusk, $lt: dawn } } },
  { $group: { _id: { $dateTrunc: { date: "$minute", unit: "minute", binSize: 10 } },
      min:    { $min: "$do_min" },
      p10:    { $percentile: { input: "$do_avg", p: [0.1], method: "approximate" } },
      median: { $median: { input: "$do_avg", method: "approximate" } } } },
  { $sort: { _id: 1 } }
])
```

### Have we seen this before?

Hybrid search: vector similarity and keyword relevance, merged with Reciprocal Rank Fusion. `$rankFusion` is not enabled on 8.0, so the fusion is written with `$unionWith`, which runs on any 8.0 deployment:

```js
const k = 60                      // RRF constant
const closed = ["resolved", "dismissed"]
const rank = [                    // turn a ranked list into 1 / (k + rank)
  { $group: { _id: null, ids: { $push: "$_id" } } },
  { $unwind: { path: "$ids", includeArrayIndex: "r" } },
  { $project: { _id: "$ids", score: { $divide: [1, { $add: ["$r", k + 1] }] } } }
]
db.incidents.aggregate([
  { $vectorSearch: { index: "incident_vectors", path: "embedding", queryVector: qv,
                     numCandidates: 100, limit: 10, filter: { status: { $in: closed } } } },
  { $match: { _id: { $ne: openId } } },
  ...rank,
  { $unionWith: { coll: "incidents", pipeline: [
      { $search: { index: "incident_text", text: { query: q, path: "memory_text" } } },
      { $match: { status: { $in: closed }, _id: { $ne: openId } } },
      { $limit: 10 }, ...rank ] } },
  { $group: { _id: "$_id", score: { $sum: "$score" } } },
  { $sort: { score: -1 } }, { $limit: 3 },
  { $lookup: { from: "incidents", localField: "_id", foreignField: "_id", as: "incident" } },
  { $unwind: "$incident" }
])
```

Every incident gets a `memory_text` once it closes: a few plain sentences on its scope, signals, cause, evidence, actions and outcome, plus the investigator's summary. That text is embedded with `gemini-embedding-2` at 768 dimensions and stored next to it. When a new incident opens, `q` is its own text and `qv` that text's embedding. `incident_vectors` (vector index, cosine, filters on `status` and `diagnosis.cause`) and `incident_text` (Atlas Search on `memory_text`) are created by the brain at start. The three incidents found go to the investigator and to the console's incident drawer.

## Change streams

| Stream | Filter | Consumer |
|---|---|---|
| `pond_state` | `insert`, `update`, `replace` | API → console (SSE), coalesced to one message per second |
| `incidents` | `insert`, `update`, `replace` | API → console (SSE) |
| `commands` | `insert`, or `update` that sets `status: "pending"` (a retry) | API → the gateway's command channel (SSE) |

The API opens one stream per collection and fans out in memory, so the number of streams does not grow with the number of consoles or gateways. After an error each stream resumes from its last token. Nothing is lost across an API restart either: a console starts from a fresh snapshot, and a gateway that connects receives every command it has not acknowledged.

## Measurements

Measured on the demo host on 17/10/2026 with `scripts/measure.py`, which only reads. The host has 2 vCPU and 8 GB and runs MongoDB 8.0.34 (atlas-local) next to the app.

| What | Result |
|---|---|
| Forecast for 200 ponds, 14,400 readings in the window | median 345 ms; 671 ms with the third window stage |
| The forecast's plan | `CLUSTERED_IXSCAN` over the buckets: 200 buckets read for 200 ponds, because each pond's last 12 minutes sit in its current one-hour bucket |
| Evidence window, one pond, 15 minutes | median 4 ms |
| Storage of raw readings | 1.45 million readings in 4,200 buckets, about 346 per bucket. Each reading is 403 bytes as a document and 6.8 bytes on disk: 9.4 MB of data and 3.1 MB of indexes. Kept 14 days, that is 1.1 MB per pond. |
| Storage of one-minute rollups | 127,000 rows in a regular collection: 149 bytes each on disk, of which the indexes are more than half (`_id`, `pond_minute` and the TTL index). Kept 180 days, that is 36.8 MB per pond. Per minute of a pond's history, a rollup row takes 3.5 times the space of the six readings it summarises. |

Kept like that, the rollups were the part that did not scale: at 2,000 ponds they would have needed about 74 GB, more than the demo host's 35 GB disk. Now they are a time series collection too, written by the brain as described above. The space they take now will be measured once a few days of rows exist.

Still to measure:
- sustained ingest at ten times the demo's farms (`scripts/loadtest.sh`);
- the space the same readings take in a regular collection (`scripts/measure.py --compare`).
