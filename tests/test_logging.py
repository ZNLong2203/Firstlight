import json
import logging

from firstlight.core.logging import JsonFormatter


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
