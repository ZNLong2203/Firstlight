import asyncio
import json
import logging

from firstlight.core.logging import JsonFormatter, ShutdownCancellations


def test_json_log_carries_trace_ids_and_context() -> None:
    record = logging.LogRecord("firstlight.api", logging.INFO, __file__, 1, "batch stored", None, None)
    record.__dict__["dd.trace_id"] = "123"
    record.__dict__["dd.span_id"] = "456"
    record.ctx = {"pond": "BL-01-A3"}
    entry = json.loads(JsonFormatter().format(record))
    assert entry["message"] == "batch stored"
    assert entry["status"] == "info"
    assert entry["dd.trace_id"] == "123"
    assert entry["pond"] == "BL-01-A3"


def test_context_cannot_overwrite_reserved_fields() -> None:
    record = logging.LogRecord("firstlight.brain", logging.WARNING, __file__, 1, "forecast done", None, None)
    record.ctx = {"status": {"ok": 200}, "message": "other"}
    entry = json.loads(JsonFormatter().format(record))
    assert entry["status"] == "warning" and entry["message"] == "forecast done"
    assert entry["ctx.status"] == {"ok": 200}


def test_connections_closed_by_a_restart_are_not_errors() -> None:
    try:
        raise asyncio.CancelledError("Task cancelled, timeout graceful shutdown exceeded")
    except asyncio.CancelledError as exc:
        cancelled = (type(exc), exc, exc.__traceback__)
    record = logging.LogRecord(
        "uvicorn.error", logging.ERROR, __file__, 1, "Exception in ASGI application\n", (), cancelled
    )
    summary = logging.LogRecord(
        "uvicorn.error",
        logging.ERROR,
        __file__,
        1,
        "Cancel %s running task(s), timeout graceful shutdown exceeded",
        (50,),
        None,
    )
    crash = logging.LogRecord(
        "uvicorn.error", logging.ERROR, __file__, 1, "Exception in ASGI application\n", (), None
    )
    for r in (record, summary, crash):
        ShutdownCancellations().filter(r)
    entries = [json.loads(JsonFormatter().format(r)) for r in (record, summary, crash)]
    assert entries[0]["status"] == "info" and entries[0]["message"] == "connection closed by shutdown"
    assert "error.stack" not in entries[0]
    assert entries[1]["status"] == "info"
    assert entries[2]["status"] == "error", "a real exception stays an error"
