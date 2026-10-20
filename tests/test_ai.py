"""The investigator with a scripted model: tool calls, the answer, scores, and the brain's worker."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from google.genai import types

from firstlight.ai import evals
from firstlight.ai.investigator import investigate
from firstlight.brain.ai_worker import AiWorker
from firstlight.core.config import get_settings
from firstlight.core.metrics import Metrics

REPORT = {
    "cause": "aerator_failure",
    "confidence": 0.9,
    "summary": "Aerator AE-BL-01-A3-1 stopped at 15:19; the standby AE-BL-01-A3-S took over.",
    "farmer_message_vi": "Ao BL-01-A3: quạt AE-BL-01-A3-1 ngừng quay, Firstlight đã bật quạt dự phòng.",
    "next_steps": ["Repair AE-BL-01-A3-1"],
    "checked": ["pond_readings"],
}


def reply(*parts: types.Part) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))]
    )


class ScriptedGemini:
    """Asks for the pond's readings once, then answers with REPORT."""

    enabled = True

    def __init__(self) -> None:
        self.calls = 0
        self.seen_tool_result: dict[str, Any] | None = None

    async def generate(self, contents: list[types.Content], config: Any) -> tuple[Any, str]:
        self.calls += 1
        if self.calls == 1:
            call = types.FunctionCall(name="pond_readings", args={"pond": "BL-01-A3", "minutes": 10})
            return reply(types.Part(function_call=call)), "scripted"
        response = contents[-1].parts[0].function_response if contents[-1].parts else None
        self.seen_tool_result = response.response if response else None
        return reply(types.Part(text=json.dumps(REPORT, ensure_ascii=False))), "scripted"


def incident(**extra: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "_id": "INC-0001",
        "key": "BL-01-A3",
        "scope": "pond",
        "pond": "BL-01-A3",
        "ponds": ["BL-01-A3"],
        "farm": "BL-01",
        "gateway": "GW-BL01-1",
        "status": "verifying",
        "open": True,
        "opened_at": now,
        "diagnosis": {"cause": "aerator_failure", "confidence": 0.85, "device": "AE-BL-01-A3-1"},
        "evidence": [{"check": "aerator_current_drop", "detail": "AE-BL-01-A3-1 drew 9.0 A, then 0 A"}],
        "actions": [{"kind": "command", "action": "aerator.on", "device": "AE-BL-01-A3-S"}],
        "timeline": [{"t": now, "kind": "detected"}],
        **extra,
    }


def test_scores_need_real_names_and_a_plain_vietnamese_message() -> None:
    case = incident()
    assert evals.scored(REPORT, case) == {
        "agrees_with_rules": True,
        "grounded": 1.0,
        "farmer_message_ok": True,
    }
    invented = {**REPORT, "summary": "AE-BL-01-A3-7 failed", "cause": "power_outage"}
    assert (
        evals.scored(invented, case)["grounded"] < 1.0
        and not evals.scored(invented, case)["agrees_with_rules"]
    )
    assert not evals.farmer_message_ok("Incident INC-0001: aerator down", case), "English and internal ids"
    assert not evals.farmer_message_ok("Ao BL-01-A3: " + "quá dài " * 60, case), "too long for a phone screen"

    # A name one of its tools returned is grounded, and an answer where the rules had none is not a
    # disagreement: it is the AI explaining what the rules could not, for a person to check.
    unexplained = incident(diagnosis={"cause": "unknown", "confidence": 0.0})
    from_tools = {**REPORT, "summary": "Probe DO-ST-01-A2 was being cleaned.", "seen": ["DO-ST-01-A2"]}
    assert evals.scored(from_tools, unexplained) == {
        "grounded": 1.0,
        "farmer_message_ok": True,
        "explained_unknown": True,
    }


async def test_investigator_calls_a_tool_then_answers(api: tuple[httpx.AsyncClient, Any]) -> None:
    _, db = api
    await db.readings.insert_one(
        {
            "ts": datetime.now(UTC) - timedelta(minutes=2),
            "meta": {"farm": "BL-01", "pond": "BL-01-A3", "gateway": "GW-BL01-1"},
            "do": 4.6,
            "ph": 7.9,
            "aer": [{"id": "AE-BL-01-A3-1", "on": True, "amp": 0.0}],
            "probe": {"id": "DO-BL-01-A3", "q": 1.0},
        }
    )
    gemini = ScriptedGemini()
    result = await investigate(gemini, db, incident())  # type: ignore[arg-type]
    assert result["cause"] == "aerator_failure" and result["rounds"] == 2
    assert result["tool_calls"] == [{"tool": "pond_readings", "args": {"pond": "BL-01-A3", "minutes": 10}}]
    minutes = gemini.seen_tool_result["result"]["minutes"]  # type: ignore[index]
    assert minutes[0]["do"] == 4.6 and minutes[0]["aerators_turning"] == 0


async def test_worker_investigates_once_then_writes_the_postmortem_and_scores_it(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    _, db = api
    case = incident()
    await db.incidents.insert_one(case)
    await db.chaos.insert_one(
        {
            "_id": "CH-1",
            "kind": "aerator_trip",
            "pond": "BL-01-A3",
            "started_at": case["opened_at"] - timedelta(seconds=5),
        }
    )
    worker = AiWorker(db, ScriptedGemini(), Metrics(get_settings()))  # type: ignore[arg-type]

    async def settle() -> None:
        await worker.cycle(datetime.now(UTC))
        await asyncio.gather(*list(worker._tasks))

    await settle()
    investigated = await db.incidents.find_one({"_id": "INC-0001"})
    assert investigated["investigation"]["status"] == "done" and investigated["evals"]["agrees_with_rules"]
    assert investigated["timeline"][-1] == {
        **investigated["timeline"][-1],
        "kind": "ai_investigation",
        "agrees": True,
    }

    await settle()  # still open: nothing more to do, and it is not investigated twice
    assert (await db.incidents.find_one({"_id": "INC-0001"}))["investigation"]["rounds"] == 2

    await db.incidents.update_one(
        {"_id": "INC-0001"},
        {"$set": {"status": "resolved", "closed_at": datetime.now(UTC)}, "$unset": {"open": ""}},
    )
    worker.gemini = ScriptedPostmortem()  # type: ignore[assignment]
    await settle()
    closed = await db.incidents.find_one({"_id": "INC-0001"})
    assert closed["postmortem"]["status"] == "done" and closed["postmortem"]["title"] == "Aerator failure"
    assert closed["evals"]["truth"] == "aerator_failure" and closed["evals"]["rca_correct"]
    assert closed["evals"]["rules_correct"]


class ScriptedPostmortem:
    enabled = True

    async def generate(self, contents: list[types.Content], config: Any) -> tuple[Any, str]:
        written = {
            "title": "Aerator failure",
            "postmortem_md": "### Summary\nThe standby took over.",
            "follow_ups": [],
        }
        return reply(types.Part(text=json.dumps(written))), "scripted"


async def test_the_truth_is_the_fault_still_in_place_or_the_release_after_it(
    api: tuple[httpx.AsyncClient, Any],
) -> None:
    _, db = api
    now = datetime.now(UTC)
    estate = {"_id": "INC-0070", "scope": "estate", "ponds": ["ST-03-A1", "BL-03-A3"], "opened_at": now}
    await db.chaos.insert_one(
        {
            "_id": "CH-old",
            "kind": "probe_fouling",
            "pond": "ST-03-A1",
            "started_at": now - timedelta(minutes=7),
            "cleared_at": now - timedelta(minutes=3),
        }
    )
    await db.deployments.insert_one(
        {
            "service": "firstlight-api",
            "version": "1.4",
            "started_at": now - timedelta(minutes=1),
            "config": {"ingest_duplicate_check": "fields"},
        }
    )
    assert await evals.ground_truth(db, estate) == "ingest_regression", "a probe cleaned before is history"

    await db.chaos.insert_one(
        {
            "_id": "CH-now",
            "kind": "aerator_trip",
            "pond": "BL-03-A3",
            "started_at": now - timedelta(seconds=20),
        }
    )
    assert await evals.ground_truth(db, estate) == "aerator_failure", "the fault in place, closer to it, wins"
