import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from firstlight.brain.notebooks import ATTEMPTS, NotebookWriter, app_host, notebook
from firstlight.core.config import Settings

NOW = datetime(2026, 10, 19, 3, 0, tzinfo=UTC)
SETTINGS = Settings(
    dd_site="ap1.datadoghq.com", dd_api_key="api", dd_app_key="app", dd_env="demo", public_host="demo.example"
)


def aerator_incident(**extra: Any) -> dict[str, Any]:
    opened = NOW - timedelta(minutes=5)
    return {
        "_id": "INC-0001",
        "scope": "pond",
        "pond": "BL-01-A3",
        "farm": "BL-01",
        "gateway": "GW-BL01-1",
        "ponds": ["BL-01-A3"],
        "status": "resolved",
        "detected_by": "brain",
        "opened_at": opened,
        "closed_at": NOW - timedelta(minutes=2),
        "diagnosis": {"cause": "aerator_failure", "confidence": 0.85, "onset": opened - timedelta(seconds=4)},
        "evidence": [
            {
                "check": "aerator_current_drop",
                "cause": "aerator_failure",
                "verdict": "support",
                "weight": 0.85,
                "detail": "AE-BL-01-A3-1 drew 9.0 A, then 0 A",
            },
        ],
        "actions": [{"kind": "command", "action": "aerator.on", "device": "AE-BL-01-A3-S", "command": "c1"}],
        "metrics": {
            "mttd_s": 4,
            "time_to_action_s": 1,
            "mttr_min": 2.2,
            "min_do": 4.55,
            "below_safe_min": 0.0,
            "oxygen_debt": 0.0,
        },
        "investigation": {"cause": "aerator_failure"},
        "postmortem": {
            "status": "done",
            "title": "Aerator failure in BL-01-A3",
            "model": "gemini",
            "postmortem_md": "### Summary\nThe standby took over.",
            "follow_ups": ["Repair AE-1"],
        },
        "timeline": [{"t": opened, "kind": "detected", "signals": ["aerator_down"]}],
        **extra,
    }


def cells(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [c["attributes"]["definition"] for c in body["data"]["attributes"]["cells"]]


def test_a_pond_incident_shows_its_oxygen_and_the_postmortem() -> None:
    command = {"_id": "c1", "created_at": NOW, "acked_at": NOW + timedelta(seconds=1)}
    body = notebook(aerator_incident(), [command], "demo", "ap1.datadoghq.com", "demo.example", 7)
    attributes = body["data"]["attributes"]
    assert attributes["name"] == "Firstlight · INC-0001 · Aerator failure · pond BL-01-A3"
    assert attributes["time"] == {
        "start": "2026-10-19T02:44:56Z",
        "end": "2026-10-19T03:08:00Z",
        "live": False,
    }
    summary, *graphs, postmortem = cells(body)
    assert "| Outcome | resolved 2.2 min after the onset |" in summary["text"]
    assert (
        "confirmed by the gateway in 1 s" in summary["text"]
        and "for aerator failure (+0.85)" in summary["text"]
    )
    assert "https://demo.example/#INC-0001" in summary["text"] and "%40incident%3AINC-0001" in summary["text"]
    queries = [r["q"] for g in graphs for r in g["requests"]]
    assert queries[0] == "avg:firstlight.pond.do{env:demo,pond:bl-01-a3}", (
        "Datadog keeps tag values in lower case"
    )
    assert (
        postmortem["text"].startswith("## Aerator failure in BL-01-A3")
        and "- Repair AE-1" in postmortem["text"]
    )


def test_one_pond_is_one_pond_and_follow_ups_are_not_listed_twice() -> None:
    written = {
        "status": "done",
        "title": "Aerator failure in BL-01-A3",
        "postmortem_md": "### Summary\nThe standby took over.\n\n### Follow-ups\n- Repair AE-1",
        "follow_ups": ["Repair AE-1"],
    }
    incident = aerator_incident(postmortem=written, at_risk={"value_vnd": 600_000_000, "ponds": 1})
    summary, *_, postmortem = cells(notebook(incident, [], "demo", "ap1.datadoghq.com", None, 7))
    assert "shrimp in 1 pond |" in summary["text"]
    assert postmortem["text"].count("Repair AE-1") == 1 and "**Follow-ups**" not in postmortem["text"]


def test_a_data_path_incident_shows_what_ingest_stored() -> None:
    incident = aerator_incident(
        scope="estate",
        pond=None,
        ponds=["A"] * 200,
        postmortem={"status": "failed"},
        diagnosis={"cause": "ingest_regression", "confidence": 1.0},
        metrics={"mttd_s": 63, "mttr_min": 2.9, "blind_s": 181, "coverage": 0.256, "min_do": 4.3},
        at_risk={"value_vnd": 72_239_849_595, "ponds": 200},
    )
    body = notebook(incident, [], "demo", "ap1.datadoghq.com", None, 7)
    summary, *graphs = cells(body)
    assert body["data"]["attributes"]["name"].endswith("Backend stopped taking data · the estate, 200 ponds")
    assert "3.0 min, 26% of it recovered" in summary["text"] and "72.2 bn VND" in summary["text"]
    queries = [r["q"] for g in graphs for r in g["requests"]]
    assert "sum:firstlight.ingest.duplicates{env:demo}.as_count().rollup(sum, 60)" in queries
    assert len(graphs) == 3, "no postmortem cell when the postmortem failed"


def test_the_app_lives_on_app_for_the_first_sites_only() -> None:
    assert app_host("datadoghq.com") == "app.datadoghq.com"
    assert app_host("ap1.datadoghq.com") == "ap1.datadoghq.com"


async def test_each_closed_incident_gets_one_notebook(api: tuple[httpx.AsyncClient, Any]) -> None:
    _, db = api
    sent: list[dict[str, Any]] = []
    status = {"code": 400}

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(
            {
                "path": request.url.path,
                "key": request.headers["DD-APPLICATION-KEY"],
                **json.loads(request.read()),
            }
        )
        if status["code"] != 200:
            return httpx.Response(status["code"], json={"errors": ["bad cell"]})
        return httpx.Response(200, json={"data": {"id": 42}})

    client = httpx.AsyncClient(
        base_url="https://api.ap1.datadoghq.com", transport=httpx.MockTransport(handle)
    )
    writer = NotebookWriter(db, SETTINGS, client)
    waiting = aerator_incident(
        _id="INC-0002", postmortem={"status": "running"}, closed_at=NOW - timedelta(minutes=1)
    )
    await db.incidents.insert_many(
        [aerator_incident(), waiting, {**aerator_incident(_id="INC-0003"), "open": True}]
    )

    assert await writer.write_next(NOW), "Datadog refuses the first try"
    failed = await db.incidents.find_one({"_id": "INC-0001"})
    assert failed["notebook"]["status"] == "failed" and failed["notebook"]["attempts"] == 1
    status["code"] = 200
    assert await writer.write_next(NOW)
    written = await db.incidents.find_one({"_id": "INC-0001"})
    assert written["notebook"]["url"] == "https://ap1.datadoghq.com/notebook/42"
    assert written["timeline"][-1]["kind"] == "notebook" and sent[-1]["path"] == "/api/v1/notebooks"
    assert sent[-1]["key"] == "app"
    assert not await writer.write_next(NOW), (
        "the next waits for its postmortem, and an open one waits to close"
    )
    assert await writer.write_next(NOW + timedelta(minutes=10)), "or for 10 minutes"

    status["code"] = 500
    await db.incidents.insert_one(aerator_incident(_id="INC-0004"))
    for _ in range(ATTEMPTS + 2):
        await writer.write_next(NOW)
    assert (await db.incidents.find_one({"_id": "INC-0004"}))["notebook"]["attempts"] == ATTEMPTS
