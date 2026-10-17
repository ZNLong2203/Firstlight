"""Runs the AI investigator beside the brain's loop, never inside it.

Each cycle claims at most one diagnosed incident to investigate and one closed incident to write a
postmortem for. The claim is an atomic update, so a restart or a second brain never doubles the work,
and a claim left behind by a crash is taken again after a few minutes.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from ddtrace.llmobs import LLMObs
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from firstlight.ai import evals
from firstlight.ai.gemini import Gemini
from firstlight.ai.investigator import investigate, postmortem
from firstlight.core.metrics import Metrics

log = logging.getLogger("firstlight.brain.ai")

Doc = dict[str, Any]
TIMEOUT_S = 90
STALE_CLAIM = timedelta(minutes=5)
RECENT = timedelta(hours=6)  # older incidents are history, not work


class AiWorker:
    def __init__(self, db: AsyncDatabase[Doc], gemini: Gemini, metrics: Metrics) -> None:
        self.db, self.gemini, self.metrics = db, gemini, metrics
        self._slot = asyncio.Semaphore(1)  # one model conversation at a time keeps us inside the quota
        self._tasks: set[asyncio.Task[None]] = set()

    def _start(self, work: Any) -> None:
        task = asyncio.create_task(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def cycle(self, now: datetime) -> None:
        if not self.gemini.enabled or any(not task.done() for task in self._tasks):
            return
        recent = {"$gte": now - RECENT}
        free = {
            "$or": [
                {"investigation": {"$exists": False}},
                {"investigation.status": "running", "investigation.at": {"$lt": now - STALE_CLAIM}},
            ]
        }
        incident = await self.db.incidents.find_one_and_update(
            {"opened_at": recent, "diagnosis.cause": {"$exists": True}, **free},
            {"$set": {"investigation": {"status": "running", "at": now}}},
            sort=[("opened_at", 1)],
            return_document=ReturnDocument.AFTER,
        )
        if incident:
            self._start(self._investigate(incident))
            return
        closed = await self.db.incidents.find_one_and_update(
            {
                "closed_at": recent,
                "open": {"$exists": False},
                "investigation.status": "done",
                "$or": [
                    {"postmortem": {"$exists": False}},
                    {"postmortem.status": "running", "postmortem.at": {"$lt": now - STALE_CLAIM}},
                ],
            },
            {"$set": {"postmortem": {"status": "running", "at": now}}},
            sort=[("closed_at", 1)],
            return_document=ReturnDocument.AFTER,
        )
        if closed:
            self._start(self._postmortem(closed))

    async def _investigate(self, incident: Doc) -> None:
        async with self._slot:
            try:
                result = await asyncio.wait_for(investigate(self.gemini, self.db, incident), TIMEOUT_S)
            except Exception as exc:
                log.exception("investigation failed", extra={"ctx": {"incident": incident["_id"]}})
                await self.db.incidents.update_one(
                    {"_id": incident["_id"]},
                    {
                        "$set": {
                            "investigation": {
                                "status": "failed",
                                "error": type(exc).__name__,
                                "at": incident["investigation"]["at"],
                            }
                        }
                    },
                )
                self.metrics.count("firstlight.ai.investigations", 1, ["status:failed"])
                return
            scores = evals.scored(result, incident)
            entry = {
                "t": result.get("at") or incident["investigation"]["at"],
                "kind": "ai_investigation",
                "cause": result.get("cause"),
                "agrees": scores["agrees_with_rules"],
            }
            await self.db.incidents.update_one(
                {"_id": incident["_id"]},
                {
                    "$set": {"investigation": {**result, "status": "done"}, "evals": scores},
                    "$push": {"timeline": entry},
                },
            )
            self._submit(result.get("span"), scores)
            tags = [f"model:{result.get('model')}", "status:done"]
            self.metrics.count("firstlight.ai.investigations", 1, tags)
            self.metrics.distribution("firstlight.ai.latency_ms", result.get("latency_ms", 0), tags)
            log.info(
                "investigation done",
                extra={"ctx": {"incident": incident["_id"], "cause": result.get("cause"), **scores}},
            )

    async def _postmortem(self, incident: Doc) -> None:
        async with self._slot:
            truth = await evals.ground_truth(self.db, incident)
            ai_cause = (incident.get("investigation") or {}).get("cause")
            rules_cause = (incident.get("diagnosis") or {}).get("cause")
            scores: Doc = {}
            if truth:
                scores = {
                    "truth": truth,
                    "rca_correct": ai_cause == truth,
                    "rules_correct": rules_cause == truth,
                }
            try:
                written = await asyncio.wait_for(postmortem(self.gemini, incident), TIMEOUT_S)
                update: Doc = {"postmortem": {**written, "status": "done"}}
            except Exception as exc:
                log.exception("postmortem failed", extra={"ctx": {"incident": incident["_id"]}})
                update = {"postmortem": {"status": "failed", "error": type(exc).__name__}}
            if scores:
                update |= {f"evals.{k}": v for k, v in scores.items()}
            await self.db.incidents.update_one({"_id": incident["_id"]}, {"$set": update})
            if scores:
                self._submit(
                    (incident.get("investigation") or {}).get("span"), {"rca_correct": scores["rca_correct"]}
                )
                result = "correct" if scores["rca_correct"] else "incorrect"
                self.metrics.count("firstlight.ai.rca", 1, [f"result:{result}", f"truth:{truth}"])

    @staticmethod
    def _submit(span: Any, scores: Doc) -> None:
        """Scores become LLM Observability evaluations on the investigator's span."""
        if not span or not LLMObs.enabled:
            return
        for label, value in scores.items():
            if isinstance(value, bool):
                LLMObs.submit_evaluation(
                    label=label, metric_type="categorical", value="yes" if value else "no", span=span
                )
            elif isinstance(value, int | float):
                LLMObs.submit_evaluation(label=label, metric_type="score", value=float(value), span=span)
