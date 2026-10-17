import asyncio
from typing import Any

import httpx

from firstlight.ai import memory


def one_hot(i: int) -> list[float]:
    vector = [0.0] * memory.DIMENSIONS
    vector[i] = 1.0
    return vector


def test_memory_text_reads_like_what_someone_would_search_for() -> None:
    text = memory.memory_text(
        {
            "scope": "pond",
            "key": "BL-01-A3",
            "farm": "BL-01",
            "status": "resolved",
            "signals": ["aerator_down"],
            "diagnosis": {"cause": "aerator_failure"},
            "evidence": [
                {"verdict": "support", "detail": "AE-BL-01-A3-1 drew 9.0 A, then 0 A"},
                {"verdict": "against", "detail": "the probe reports signal quality 1.00"},
            ],
            "actions": [{"kind": "command", "action": "aerator.on", "device": "AE-BL-01-A3-S"}],
            "metrics": {"min_do": 4.55, "mttr_min": 2.2},
            "investigation": {"summary": "The standby took over within a second."},
        }
    )
    assert "Cause: aerator_failure." in text and "AE-BL-01-A3-1 drew 9.0 A, then 0 A" in text
    assert "aerator.on AE-BL-01-A3-S" in text and "lowest DO 4.55 mg/L" in text
    assert "signal quality" not in text, "evidence against a cause is not what happened"


async def test_hybrid_search_finds_the_closest_closed_incident(api: tuple[httpx.AsyncClient, Any]) -> None:
    _, db = api
    assert await memory.ensure_search_indexes(db)
    assert await memory.ensure_search_indexes(db), "running it twice changes nothing"
    await db.incidents.insert_many(
        [
            {
                "_id": "INC-0101",
                "key": "BL-01-A3",
                "status": "resolved",
                "diagnosis": {"cause": "aerator_failure"},
                "memory_text": "pond BL-01-A3: aerator AE-BL-01-A3-1 drew 9 A then 0 A; the standby started",
                "embedding": one_hot(0),
            },
            {
                "_id": "INC-0102",
                "key": "ST-01-A2",
                "status": "dismissed",
                "diagnosis": {"cause": "sensor_fault"},
                "memory_text": "probe DO-ST-01-A2 fouled: DO fell faster than water can lose oxygen",
                "embedding": one_hot(1),
            },
            {
                "_id": "INC-0103",
                "key": "BL-02-A1",
                "open": True,
                "status": "verifying",  # still open: not memory yet
                "diagnosis": {"cause": "aerator_failure"},
                "memory_text": "pond BL-02-A1: aerator stopped",
                "embedding": one_hot(0),
            },
        ]
    )
    found: list[dict[str, Any]] = []
    for _ in range(60):  # the search indexes build and sync in the background
        found = await memory.similar(db, one_hot(0), "aerator stopped drawing current", exclude="INC-0200")
        if found and found[0]["_id"] == "INC-0101" and len(found) == 2:
            break
        await asyncio.sleep(2)
    assert [f["_id"] for f in found] == ["INC-0101", "INC-0102"], found
    assert found[0]["cause"] == "aerator_failure" and found[0]["score"] > found[1]["score"]
    assert not await memory.similar(db, one_hot(0), "aerator", exclude="INC-0101") or all(
        f["_id"] != "INC-0101" for f in await memory.similar(db, one_hot(0), "aerator", exclude="INC-0101")
    ), "an incident is never its own precedent"
