from typing import Any

import httpx
from tests.conftest import WEBHOOK_SECRET
from tests.test_incidents import Harness

from firstlight.core.models import FaultRequest

SIGNED = {"X-Firstlight-Signature": WEBHOOK_SECRET}


def alert(transition: str, pond: str, cycle: str = "cycle-1") -> dict[str, str]:
    return {
        "alert_id": cycle,
        "transition": transition,
        "monitor_id": "12345",
        "title": "[Triggered] Hypoxia forecast under 30 min",
        "scope": f"farm:{pond[:5].lower()},pond:{pond.lower()}",
        "tags": "env:demo,service:firstlight-brain",
        "link": "https://app.datadoghq.com/monitors/12345",
        "date": "1792219200000",
    }


async def test_webhook_needs_the_secret_and_ignores_retries(api: tuple[httpx.AsyncClient, Any]) -> None:
    client, db = api
    body = alert("Triggered", "BL-01-A3")
    assert (await client.post("/v1/hooks/datadog", json=body)).status_code == 401
    assert (
        await client.post("/v1/hooks/datadog", json=body, headers={"X-Firstlight-Signature": "x"})
    ).status_code == 401
    first = await client.post("/v1/hooks/datadog", json=body, headers=SIGNED)
    again = await client.post("/v1/hooks/datadog", json=body, headers=SIGNED)
    assert first.json() == {"accepted": True, "duplicate": False} and again.json()["duplicate"] is True
    stored = await db.alerts.find_one({"alert_id": "cycle-1"})
    assert stored["targets"] == {"farm": "BL-01", "pond": "BL-01-A3"} and stored["transition"] == "triggered"


async def test_datadog_confirms_what_the_brain_already_handles(api: tuple[httpx.AsyncClient, Any]) -> None:
    harness = Harness(*api)
    await harness.start()
    pond = harness.world.ponds["BL-01-A3"]
    harness.world.apply(FaultRequest(id="CH-H1", kind="aerator_trip", pond=pond.id), harness.now)
    incident = await harness.until(pond.id, "verifying", limit=6)
    await harness.client.post("/v1/hooks/datadog", json=alert("Triggered", pond.id), headers=SIGNED)
    await harness.tick()
    linked = await harness.db.incidents.find_one({"_id": incident["_id"]})
    confirmation = next(e for e in linked["timeline"] if e["kind"] == "datadog")
    assert confirmation["transition"] == "triggered" and confirmation["after_brain_s"] is not None
    assert await harness.db.incidents.count_documents({}) == 1, (
        "the alert joins the incident, it does not open one"
    )


async def test_a_monitor_alerting_on_every_pond_is_one_line(api: tuple[httpx.AsyncClient, Any]) -> None:
    harness = Harness(*api)
    await harness.start()
    harness.world.apply(FaultRequest(id="CH-T5", kind="power_outage", farm="ST-01"), harness.now)
    incident = await harness.until("ST-01", "awaiting_approval", limit=6)
    ponds = sorted(incident["ponds"])
    alerts = [alert("Triggered", pond, f"cycle-{i}") for i, pond in enumerate(ponds)]
    for body in [*alerts, alert("Recovered", ponds[0], "cycle-0")]:
        await harness.client.post("/v1/hooks/datadog", json=body, headers=SIGNED)
    await harness.tick()
    linked = await harness.db.incidents.find_one({"_id": incident["_id"]})
    datadog = [e for e in linked["timeline"] if e["kind"] == "datadog"]
    lines = [(e["transition"], e["count"], e["per"], e["monitor"]) for e in datadog]
    assert lines == [
        ("triggered", len(ponds), "pond", "Hypoxia forecast under 30 min"),
        ("recovered", 1, "pond", "Hypoxia forecast under 30 min"),
    ], "one line per run of the same transition, not one per pond"


async def test_an_alert_that_arrives_after_the_close_joins_the_closed_incident(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    harness = Harness(*api)
    await harness.start()
    pond = harness.world.ponds["BL-01-A3"]
    harness.world.apply(FaultRequest(id="CH-H2", kind="aerator_trip", pond=pond.id), harness.now)
    resolved = await harness.until(pond.id, "resolved", limit=40)
    await harness.client.post("/v1/hooks/datadog", json=alert("Triggered", pond.id, "late-1"), headers=SIGNED)
    await harness.tick()
    assert await harness.db.incidents.count_documents({}) == 1, (
        "Datadog saw it late; it is not a new incident"
    )
    closed = await harness.db.incidents.find_one({"_id": resolved["_id"]})
    assert closed["timeline"][-1]["kind"] == "datadog" and closed["status"] == "resolved"


async def test_an_alert_the_rules_cannot_explain_waits_for_a_person(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    harness = Harness(*api)
    await harness.start()
    await harness.client.post(
        "/v1/hooks/datadog", json=alert("Triggered", "ST-01-A4", "cycle-9"), headers=SIGNED
    )
    await harness.tick()
    opened = await harness.db.incidents.find_one({"key": "ST-01-A4"})
    assert opened["detected_by"] == "datadog" and opened["signals"][0].startswith("datadog:")
    escalated = await harness.until("ST-01-A4", "escalated", limit=12)
    assert escalated["diagnosis"]["cause"] == "unknown", (
        "the pond looks fine to the rules, so a person decides"
    )
