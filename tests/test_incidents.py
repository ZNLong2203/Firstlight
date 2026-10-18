"""Whole incidents on a simulated clock: physics, gateway, ingest API, brain, command bus, physics again."""

import random
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from tests.conftest import DEMO_CODE

from firstlight.brain.evidence import Evidence, diagnose, recent_release
from firstlight.brain.incidents import Policy, find_problems, incident_cycle, recovered
from firstlight.brain.main import forecast_once
from firstlight.brain.playbooks import ensure_playbooks
from firstlight.core.config import get_settings
from firstlight.core.metrics import Metrics
from firstlight.core.models import FaultRequest
from firstlight.edge.farms import build_farms
from firstlight.edge.gateway import Gateway
from firstlight.edge.world import World

STEP = timedelta(seconds=10)
DEMO = {"X-Demo-Code": DEMO_CODE}


class Harness:
    """Two farms on a fast clock. Stands in for the gateways' command channels by running pending
    commands after every tick and acknowledging them through the real API."""

    def __init__(self, client: httpx.AsyncClient, db: Any, farms: int = 2) -> None:
        self.client, self.db = client, db
        self.farms = build_farms(farms, 4)
        self.gateways = [Gateway(farm) for farm in self.farms]
        self.world = World(self.farms, self.gateways)
        self.rng = random.Random(11)
        self.now = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)
        self.policy = Policy(recovery_min=2, escalate_after_min=10, farm_offset_hours=0)
        self.metrics = Metrics(get_settings())

    async def start(self, minutes: int = 3) -> None:
        for _ in range(300):  # settle the night in memory first
            for farm in self.farms:
                farm.step(2.0, 60, self.rng)
        await ensure_playbooks(self.db)
        for farm in self.farms:
            manifest = farm.manifest().model_dump(mode="json")
            assert (
                await self.client.put(f"/v1/gateways/{farm.gateway}/manifest", json=manifest)
            ).status_code == 200
        await self.tick(minutes * 6)

    async def tick(self, n: int = 1) -> None:
        for _ in range(n):
            self.now += STEP
            for farm in self.farms:
                farm.step(2.0, STEP.total_seconds(), self.rng)
            for gateway in self.gateways:
                gateway.collect(self.now, self.rng)
                await gateway.flush(self.client)
            await forecast_once(self.db, self.metrics, self.now)
            await incident_cycle(self.db, self.metrics, self.policy, self.now)
            await self.run_commands()

    async def run_commands(self) -> None:
        async for command in self.db.commands.find({"status": {"$in": ["pending", "sent"]}}):
            gateway = self.world.gateways[command["gateway"]]
            if not gateway.online:
                continue
            wire = {"id": str(command["_id"]), **{k: command.get(k) for k in ("action", "pond", "device")}}
            result = {**gateway.execute(wire), "executed_at": self.now.isoformat()}
            response = await self.client.post(
                f"/v1/commands/{command['_id']}/ack", json={"gateway": gateway.id, **result}
            )
            assert response.status_code == 200

    async def until(self, pond_or_key: str, status: str, limit: int = 60) -> dict[str, Any]:
        for _ in range(limit):
            incident = await self.db.incidents.find_one(
                {"$or": [{"key": pond_or_key}, {"ponds": pond_or_key}]}, sort=[("opened_at", -1)]
            )
            if incident and incident["status"] == status:
                return incident  # type: ignore[no-any-return]
            await self.tick()
        raise AssertionError(f"{pond_or_key} never reached {status}: {incident and incident['status']}")


async def test_aerator_failure_is_fixed_by_the_standby_and_proven(api: tuple[httpx.AsyncClient, Any]) -> None:
    harness = Harness(*api)
    await harness.start()
    assert await harness.db.incidents.count_documents({}) == 0, "a quiet night opens nothing"

    pond = harness.world.ponds["BL-01-A3"]
    fault = harness.world.apply(FaultRequest(id="CH-T1", kind="aerator_trip", pond=pond.id), harness.now)
    mitigating = await harness.until(pond.id, "verifying", limit=6)
    assert mitigating["diagnosis"]["cause"] == "aerator_failure"
    assert mitigating["at_risk"]["value_vnd"] > 0 and mitigating["at_risk"]["ponds"] == 1
    assert mitigating["diagnosis"]["device"] == fault.device and mitigating["diagnosis"]["confidence"] >= 0.5
    assert pond.aerators[-1].on, "the standby aerator was started through the command bus"
    kinds = [entry["kind"] for entry in mitigating["timeline"]]
    assert (
        kinds[:5] == ["detected", "diagnosed", "action_sent", "notify", "ticket"] and "action_done" in kinds
    )
    notify = next(e for e in mitigating["timeline"] if e["kind"] == "notify")
    assert fault.device in notify["text"] and pond.aerators[-1].id in notify["text"]

    resolved = await harness.until(pond.id, "resolved", limit=30)
    metrics = resolved["metrics"]
    assert metrics["mttd_s"] <= 20 and metrics["time_to_action_s"] <= 20
    assert metrics["mttr_min"] >= 2, "recovery is only counted after the standby started"
    assert metrics["min_do"] >= 4.0 and metrics["oxygen_debt"] == 0
    state = await harness.db.pond_state.find_one({"_id": pond.id})
    assert "open_incident" not in state and [t["device"] for t in state["repair_tickets"]] == [fault.device]

    await harness.tick(6)
    assert await harness.db.incidents.count_documents({}) == 1, (
        "a broken aerator with a ticket is not a new alarm"
    )
    harness.world.clear("CH-T1")  # the technician repairs it
    await harness.tick(2)
    state = await harness.db.pond_state.find_one({"_id": pond.id})
    closed = await harness.db.incidents.find_one({"_id": resolved["_id"]})
    assert state["repair_tickets"] == [] and closed["actions"][-1]["status"] == "done"


async def test_fouled_probe_is_a_ticket_not_a_wake_up_call(api: tuple[httpx.AsyncClient, Any]) -> None:
    harness = Harness(*api)
    await harness.start()
    pond = harness.world.ponds["ST-01-A2"]
    harness.world.apply(FaultRequest(id="CH-T2", kind="probe_fouling", pond=pond.id), harness.now)
    dismissed = await harness.until(pond.id, "dismissed", limit=30)
    assert dismissed["diagnosis"]["cause"] == "sensor_fault" and dismissed["false_alarm_prevented"]
    assert not any(e["kind"] == "notify" for e in dismissed["timeline"]), "nobody is woken up"
    assert [a["kind"] for a in dismissed["actions"]] == ["ticket"]
    assert pond.do > 4.0, "the water was fine all along"

    await harness.tick(3)
    state = await harness.db.pond_state.find_one({"_id": pond.id})
    assert state["status"] == "sensor" and state["sensor_ticket"]["incident"] == dismissed["_id"]
    assert await harness.db.incidents.count_documents({"ponds": pond.id}) == 1, (
        "no second alarm while it stays dirty"
    )

    harness.world.clear("CH-T2")  # someone cleaned the probe
    await harness.tick(2)
    state = await harness.db.pond_state.find_one({"_id": pond.id})
    closed = await harness.db.incidents.find_one({"_id": dismissed["_id"]})
    assert "sensor_ticket" not in state and closed["actions"][0]["status"] == "done"


async def test_blind_gateway_is_watched_and_the_gap_checked_when_it_returns(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    harness = Harness(*api)
    await harness.start()
    gateway = harness.world.gateways["GW-BL01-1"]
    harness.world.apply(FaultRequest(id="CH-T3", kind="gateway_offline", gateway=gateway.id), harness.now)
    harness.world.ponds["BL-01-A1"].probe.stuck_at = 3.2  # low oxygen while nobody can see it
    monitoring = await harness.until(gateway.id, "monitoring", limit=12)
    assert monitoring["scope"] == "gateway" and monitoring["diagnosis"]["cause"] == "gateway_offline"
    assert len(monitoring["ponds"]) == 4
    assert harness.world.ponds["BL-01-A1"].aerators[-1].on, "the gateway's failsafe acted on its own"

    harness.world.ponds["BL-01-A1"].probe.stuck_at = None
    harness.world.clear("CH-T3")
    resolved = await harness.until(gateway.id, "resolved", limit=6)
    gap = resolved["timeline"][-1]["gap"]
    assert gap["coverage"] >= 0.95, "store-and-forward delivered the readings from the blind spell"
    assert [e["pond"] for e in gap["failsafe"]] == ["BL-01-A1"]


async def test_power_cut_waits_for_approval_then_runs_the_generator(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    harness = Harness(*api)
    await harness.start()
    harness.world.apply(FaultRequest(id="CH-T4", kind="power_outage", farm="ST-01"), harness.now)
    waiting = await harness.until("ST-01", "awaiting_approval", limit=6)
    assert waiting["scope"] == "farm" and waiting["diagnosis"]["cause"] == "power_outage"
    assert not harness.world.farms["ST-01"].generator_running, "a costly step waits for a person"

    approve = {"action": "generator.start"}
    path = f"/v1/incidents/{waiting['_id']}/approve"
    assert (await harness.client.post(path, json=approve)).status_code == 403, "approving needs the demo code"
    assert (await harness.client.post(path, json=approve, headers=DEMO)).status_code == 200
    assert (await harness.client.post(path, json=approve, headers=DEMO)).status_code == 409, "only once"
    await harness.until("ST-01", "verifying", limit=4)
    assert harness.world.farms["ST-01"].generator_running
    resolved = await harness.until("ST-01", "resolved", limit=30)
    listed = (await harness.client.get("/v1/incidents")).json()
    assert resolved["_id"] in [i["_id"] for i in listed]
    detail = (await harness.client.get(f"/v1/incidents/{resolved['_id']}")).json()
    assert [c["action"] for c in detail["commands"]] == ["generator.start"]
    assert [e["kind"] for e in detail["timeline"]].count("approved") == 1


async def test_recovery_allows_an_afternoon_decline_but_not_a_relapse(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    """In the afternoon oxygen eases down from 7 mg/L as the algae slow: that pond has recovered. A pond
    falling just as fast from 4.3 mg/L has not."""
    _, db = api
    now = datetime.now(UTC).replace(microsecond=0)
    for pond, start in (("afternoon", 7.5), ("relapse", 4.3)):
        await db.readings.insert_many(
            [
                {
                    "ts": now - timedelta(seconds=10 * i),
                    "meta": {"farm": "F", "pond": pond, "gateway": "g"},
                    "do": start - 0.004 * (24 - i),
                }
                for i in range(24)
            ]
        )
    after = now - timedelta(minutes=3)
    assert await recovered(db, ["afternoon"], now, 2, after)
    assert not await recovered(db, ["relapse"], now, 2, after)


def test_problems_are_grouped_by_their_likely_cause() -> None:
    now = datetime.now(UTC)
    fresh = now - timedelta(seconds=5)
    stale = now - timedelta(minutes=5)

    def state(
        pond: str, farm: str, gateway: str, ts: datetime, on: int = 3, running: int = 3
    ) -> dict[str, Any]:
        last = {"ts": ts, "do": 5.0, "aerators_on": on, "aerators_running": running, "probe_q": 1.0}
        return {"_id": pond, "farm": farm, "gateway": gateway, "last": last}

    states = [state(f"A-0{i}", "A", "GW-A", stale) for i in range(4)]  # a silent gateway
    states += [state(f"B-0{i}", "B", "GW-B", fresh, running=0) for i in range(4)]  # a dark farm
    states += [state("C-01", "C", "GW-C", fresh, running=2), state("C-02", "C", "GW-C", fresh)]
    states.append({**state("C-03", "C", "GW-C", fresh), "forecast": {"rate_3m": -0.5}})  # falls too fast
    problems = {p.key: p for p in find_problems(states, set(), now)}
    assert set(problems) == {"GW-A", "B", "C-01", "C-03"}
    assert problems["C-03"].signals == ["fast_drop"]
    assert (problems["GW-A"].scope, problems["B"].scope, problems["C-01"].signals) == (
        "gateway",
        "farm",
        ["aerator_down"],
    )


def test_diagnosis_weighs_evidence_for_and_against() -> None:
    evidence = [
        Evidence("aerator_current_drop", "aerator_failure", "support", 0.6, "AE-1 drew 6.1 A, then 0 A"),
        Evidence("farm_power", "power_outage", "support", 0.8, "every aerator on the farm stopped"),
        Evidence("farm_power", "aerator_failure", "against", 0.4, "one aerator would not stop the farm"),
    ]
    diagnosis = diagnose(evidence)
    assert diagnosis.cause == "power_outage" and diagnosis.confidence == 0.64
    assert diagnose([]).cause == "unknown"


async def test_backend_regression_is_traced_to_the_release_that_caused_it(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    client, db = api
    harness = Harness(client, db, farms=5)
    await harness.start()
    # What release 1.4 does to ingest, seen from outside: most gateways stop getting their batches in,
    # not all in the same second.
    gateways = list(harness.world.gateways.values())[:4]
    for batch in (gateways[:2], gateways[2:3]):
        for gateway in batch:
            gateway.online = False
        await harness.tick()
    # 1.4 records its start once it is up: after the last batch, which the old version took.
    releases = [("1.3", harness.now - timedelta(hours=2)), ("1.4", harness.now - timedelta(seconds=5))]
    await db.deployments.insert_many(
        [{"service": "firstlight-api", "version": v, "started_at": t, "config": {}} for v, t in releases]
    )
    monitoring = await harness.until("estate", "monitoring", limit=10)
    diagnosis = monitoring["diagnosis"]
    assert monitoring["scope"] == "estate" and diagnosis["cause"] == "ingest_regression"
    assert diagnosis["release"]["version"] == "1.4" and diagnosis["release"]["previous"] == "1.3"
    message = next(e["text"] for e in monitoring["timeline"] if e["kind"] == "notify")
    assert "1.4" in message and "rollback về 1.3" in message

    gateways[3].online = False  # one more gateway's batches stop getting in while the incident is open
    await harness.tick(8)
    late = {p.id for p in gateways[3].farm.ponds}
    grown = await db.incidents.find_one({"_id": monitoring["_id"]})
    assert late <= set(grown["ponds"]), "the estate incident takes in a gateway that goes quiet later"

    for batch in (gateways[:3], gateways[3:]):  # rolled back: the batches get in again, that one last
        for gateway in batch:
            gateway.online = True
        await harness.tick()
    resolved = await harness.until("estate", "resolved", limit=6)
    assert resolved["metrics"]["coverage"] >= 0.95
    assert await db.incidents.count_documents({"scope": "gateway"}) == 0, (
        "going quiet and coming back gateway by gateway is still one incident"
    )


def test_a_fleet_going_quiet_waits_to_be_one_problem() -> None:
    now = datetime.now(UTC)

    def gateway(farm: str, silent_s: float) -> list[dict[str, Any]]:
        ts = now - timedelta(seconds=silent_s)
        last = {"ts": ts, "do": 5.0, "aerators_on": 3, "aerators_running": 3, "probe_q": 1.0}
        pond = {"farm": farm, "gateway": f"GW-{farm}", "last": last}
        return [{"_id": f"{farm}-0{i}", **pond} for i in range(3)]

    def problems(*silences: float) -> list[tuple[str, int]]:
        states = [s for farm, silent in zip("ABCDE", silences, strict=True) for s in gateway(farm, silent)]
        return [(p.key, len(p.ponds)) for p in find_problems(states, set(), now)]

    assert problems(65, 62, 55, 50, 45) == [], "two crossed the line first; the rest of the fleet follows"
    assert problems(65, 65, 65, 45, 5) == [("estate", 12)], "with the one about to cross, not the last one"
    assert problems(65, 5, 5, 5, 5) == [("GW-A", 3)], "quiet while the others report: that gateway's problem"
    assert problems(85, 50, 45, 40, 35) == [("GW-A", 3)], "the fleet slowed but never stopped: no waiting"


def test_a_release_that_stopped_ingest_starts_just_after_the_last_reading() -> None:
    now = datetime.now(UTC)
    releases = [  # newest first
        {"version": "1.4", "started_at": now},
        {"version": "1.3", "started_at": now - timedelta(minutes=2)},
    ]
    assert recent_release(releases, now - timedelta(seconds=8)) == {
        "version": "1.4",
        "previous": "1.3",
        "started_at": now,
    }, "the old version took the last batch; 1.4 took nothing"
    earlier = recent_release(releases, now - timedelta(seconds=90))
    assert earlier and earlier["version"] == "1.3", "data that stopped well before 1.4 is not 1.4's doing"
