"""Incident memory: closed incidents, embedded with Gemini and searchable by meaning and by words.

Each closed incident gets a short text and a 768-dimension embedding. When a new incident opens, the
three most similar closed ones are found by hybrid search: Atlas Vector Search and Atlas Search, each
ranked, then merged with Reciprocal Rank Fusion. $rankFusion is not enabled on MongoDB 8.0, so the
fusion is written with $unionWith and runs on any 8.0 deployment, Atlas or atlas-local.

gemini-embedding-2 ignores the task type parameter, so the task goes into the text itself: documents as
"title: none | text: …" and queries as "task: search result | query: …".
"""

import logging
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import OperationFailure
from pymongo.operations import SearchIndexModel

from firstlight.ai.gemini import Gemini

log = logging.getLogger("firstlight.ai.memory")

Db = AsyncDatabase[dict[str, Any]]
DIMENSIONS = 768
RRF_K = 60  # the usual constant: rank 1 scores 1/61, rank 10 scores 1/70
CLOSED = ["resolved", "dismissed"]

SEARCH_INDEXES = [
    SearchIndexModel(
        name="incident_vectors",
        type="vectorSearch",
        definition={
            "fields": [
                {"type": "vector", "path": "embedding", "numDimensions": DIMENSIONS, "similarity": "cosine"},
                {"type": "filter", "path": "status"},
                {"type": "filter", "path": "diagnosis.cause"},
            ]
        },
    ),
    SearchIndexModel(
        name="incident_text",
        type="search",
        definition={"mappings": {"dynamic": False, "fields": {"memory_text": {"type": "string"}}}},
    ),
]


async def ensure_search_indexes(db: Db) -> bool:
    """Create the two search indexes if they are missing. False where search is not available."""
    try:
        existing = {index["name"] async for index in await db.incidents.list_search_indexes()}
        missing = [model for model in SEARCH_INDEXES if model.document["name"] not in existing]
        if missing:
            await db.incidents.create_search_indexes(missing)
            log.info(
                "search indexes created", extra={"ctx": {"names": [m.document["name"] for m in missing]}}
            )
        return True
    except OperationFailure as exc:
        log.warning("search indexes unavailable; incident memory is off", extra={"ctx": {"error": str(exc)}})
        return False


def memory_text(incident: dict[str, Any]) -> str:
    """What happened, in a few plain sentences: what a person would search for later."""
    diagnosis = incident.get("diagnosis") or {}
    parts = [
        f"{incident.get('scope', 'pond')} {incident.get('key')} on farm {incident.get('farm')}.",
        f"Signals: {', '.join(incident.get('signals', []))}.",
        f"Cause: {diagnosis.get('cause', 'unknown')}.",
    ]
    details = [e.get("detail", "") for e in incident.get("evidence", []) if e.get("verdict") == "support"]
    if details:
        parts.append("Evidence: " + "; ".join(details) + ".")
    actions = [
        a.get("text") or f"{a.get('action')} {a.get('device') or ''}".strip()
        for a in incident.get("actions", [])
    ]
    if actions:
        parts.append("Done: " + "; ".join(actions) + ".")
    metrics = incident.get("metrics") or {}
    if incident.get("status") == "dismissed":
        parts.append("Outcome: false alarm stopped, nobody woken.")
    elif metrics:
        parts.append(
            f"Outcome: {incident.get('status')}, lowest DO {metrics.get('min_do')} mg/L, "
            f"resolved in {metrics.get('mttr_min')} min."
        )
    summary = (incident.get("investigation") or {}).get("summary")
    if summary:
        parts.append(summary)
    return " ".join(parts)


async def embed_document(gemini: Gemini, text: str) -> list[float]:
    return (await gemini.embed([f"title: none | text: {text}"], DIMENSIONS))[0]


async def embed_query(gemini: Gemini, text: str) -> list[float]:
    return (await gemini.embed([f"task: search result | query: {text}"], DIMENSIONS))[0]


def _ranked() -> list[dict[str, Any]]:
    """Turn a list ordered by relevance into reciprocal-rank scores, 1 / (k + rank)."""
    return [
        {"$group": {"_id": None, "ids": {"$push": "$_id"}}},
        {"$unwind": {"path": "$ids", "includeArrayIndex": "rank"}},
        {"$project": {"_id": "$ids", "score": {"$divide": [1, {"$add": ["$rank", RRF_K + 1]}]}}},
    ]


def similar_pipeline(vector: list[float], text: str, exclude: str, limit: int = 3) -> list[dict[str, Any]]:
    closed = {"status": {"$in": CLOSED}, "_id": {"$ne": exclude}}
    return [
        {
            "$vectorSearch": {
                "index": "incident_vectors",
                "path": "embedding",
                "queryVector": vector,
                "numCandidates": 100,
                "limit": 10,
                "filter": {"status": {"$in": CLOSED}},
            }
        },
        {"$match": {"_id": {"$ne": exclude}}},
        *_ranked(),
        {
            "$unionWith": {
                "coll": "incidents",
                "pipeline": [
                    {"$search": {"index": "incident_text", "text": {"query": text, "path": "memory_text"}}},
                    {"$match": closed},
                    {"$limit": 10},
                    *_ranked(),
                ],
            }
        },
        {"$group": {"_id": "$_id", "score": {"$sum": "$score"}}},
        {"$sort": {"score": -1}},
        {"$limit": limit},
        {"$lookup": {"from": "incidents", "localField": "_id", "foreignField": "_id", "as": "incident"}},
        {"$unwind": "$incident"},
        {
            "$project": {
                "_id": 1,
                "score": {"$round": ["$score", 4]},
                "key": "$incident.key",
                "scope": "$incident.scope",
                "status": "$incident.status",
                "cause": "$incident.diagnosis.cause",
                "closed_at": "$incident.closed_at",
                "metrics": "$incident.metrics",
                "summary": "$incident.investigation.summary",
            }
        },
    ]


async def similar(
    db: Db, vector: list[float], text: str, exclude: str, limit: int = 3
) -> list[dict[str, Any]]:
    try:
        return await (await db.incidents.aggregate(similar_pipeline(vector, text, exclude, limit))).to_list()
    except OperationFailure as exc:  # no search indexes yet, or a deployment without search
        log.warning("incident memory search failed", extra={"ctx": {"error": str(exc)}})
        return []
