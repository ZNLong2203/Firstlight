"""A 4G gateway: samples its ponds, batches every few seconds and stores-and-forwards when the link drops."""

import logging
import random
import secrets
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any

import httpx

from firstlight.edge.farms import Farm

log = logging.getLogger("firstlight.edge.gateway")

MAX_BUFFERED_BATCHES = 360  # one hour at a 10 s cadence


def _base36(n: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = digits[r] + out
    return out or "0"


class Gateway:
    def __init__(self, farm: Farm) -> None:
        self.farm = farm
        self.id = farm.gateway
        # A fresh boot id keeps batch ids unique across restarts, so deduplication never drops new data.
        # Time alone is not enough: two boots in the same millisecond would collide.
        self.boot = f"{_base36(int(time.time()))}{secrets.token_hex(3)}"
        self.seq = 0
        self.buffer: deque[dict[str, Any]] = deque(maxlen=MAX_BUFFERED_BATCHES)
        self.online = True  # the chaos panel cuts the 4G link by setting this to False
        self._failing = False

    def collect(self, ts: datetime, rng: random.Random) -> None:
        self.seq += 1
        self.buffer.append(
            {
                "gateway": self.id,
                "batch_id": f"{self.id}:{self.boot}:{self.seq:08d}",
                "seq": self.seq,
                "readings": [pond.reading(ts, rng) for pond in self.farm.ponds],
            }
        )

    async def flush(self, client: httpx.AsyncClient) -> None:
        """Send buffered batches oldest first; stop at the first failure and keep the rest."""
        while self.buffer:
            if not self.online:
                self._report_failure("4G link down")
                return
            batch = self.buffer[0]
            try:
                response = await client.post(
                    "/v1/ingest", json={**batch, "sent_at": datetime.now(UTC).isoformat()}
                )
            except httpx.HTTPError as exc:
                self._report_failure(type(exc).__name__)
                return
            if response.status_code >= 500 or response.status_code == 429:
                self._report_failure(f"HTTP {response.status_code}")
                return
            self.buffer.popleft()
            if response.status_code >= 400:
                log.error(
                    "batch rejected", extra={"ctx": {"gateway": self.id, "status_code": response.status_code}}
                )
                continue
            if self._failing:
                self._failing = False
                log.info("gateway reconnected", extra={"ctx": {"gateway": self.id, "evt": "reconnected"}})

    def _report_failure(self, reason: str) -> None:
        if not self._failing:
            log.warning(
                "gateway send failed",
                extra={"ctx": {"gateway": self.id, "evt": "reconnect_failed", "reason": reason}},
            )
        self._failing = True
