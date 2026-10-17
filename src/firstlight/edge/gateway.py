"""A 4G gateway: samples its ponds, batches every few seconds and stores-and-forwards when the link drops.

It also holds a command channel open to the cloud, runs what it receives on the farm's devices and
acknowledges it. When the cloud cannot be reached, a local failsafe protects the ponds on its own.
"""

import asyncio
import json
import logging
import random
import secrets
import time
from collections import OrderedDict, deque
from datetime import UTC, datetime
from typing import Any

import httpx

from firstlight.edge.farms import Farm

log = logging.getLogger("firstlight.edge.gateway")

MAX_BUFFERED_BATCHES = 360  # one hour at a 10 s cadence
FAILSAFE_DO = 3.5  # mg/L: below this, with no cloud, the gateway starts the standby aerator itself
REMEMBERED_COMMANDS = 200
CHANNEL_TIMEOUT = httpx.Timeout(5.0, read=30.0)  # the API sends a heartbeat every 10 s


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
        self._events: list[dict[str, Any]] = []
        self._executed: OrderedDict[str, dict[str, Any]] = OrderedDict()

    @property
    def cloud_reachable(self) -> bool:
        return self.online and not self._failing

    def collect(self, ts: datetime, rng: random.Random) -> None:
        readings = [pond.reading(ts, rng) for pond in self.farm.ponds]
        if not self.cloud_reachable:
            self._failsafe(ts, readings)
        self.seq += 1
        self.buffer.append(
            {
                "gateway": self.id,
                "batch_id": f"{self.id}:{self.boot}:{self.seq:08d}",
                "seq": self.seq,
                "readings": readings,
                "events": self._events,
            }
        )
        self._events = []

    def _failsafe(self, ts: datetime, readings: list[dict[str, Any]]) -> None:
        """Without the cloud, a pond whose oxygen reads below 3.5 mg/L gets its standby aerator."""
        for pond, reading in zip(self.farm.ponds, readings, strict=True):
            if reading["do"] >= FAILSAFE_DO:
                continue
            standby = next((a for a in pond.aerators if a.standby and not a.on), None)
            if standby is None:
                continue
            standby.on = True
            self._events.append(
                {
                    "ts": ts.isoformat(),
                    "kind": "failsafe",
                    "pond": pond.id,
                    "device": standby.id,
                    "detail": {"do": reading["do"], "threshold": FAILSAFE_DO},
                }
            )
            log.warning(
                "failsafe started the standby aerator",
                extra={"ctx": {"gateway": self.id, "pond": pond.id, "device": standby.id, "evt": "failsafe"}},
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

    def execute(self, command: dict[str, Any]) -> dict[str, Any]:
        """Run one command on the farm's devices. A command seen before returns its first result."""
        if command["id"] in self._executed:
            return self._executed[command["id"]]
        status, detail = self._run(command)
        result = {"status": status, "detail": detail, "executed_at": datetime.now(UTC).isoformat()}
        self._executed[command["id"]] = result
        while len(self._executed) > REMEMBERED_COMMANDS:
            self._executed.popitem(last=False)
        context = {"gateway": self.id, "command": command["id"], "action": command["action"], **detail}
        log.info("command executed", extra={"ctx": context})
        return result

    def _run(self, command: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        action = command["action"]
        if action in ("aerator.on", "aerator.off"):
            pond = next((p for p in self.farm.ponds if p.id == command.get("pond")), None)
            aerators = pond.aerators if pond else []
            aerator = next((a for a in aerators if a.id == command.get("device")), None)
            if pond is None or aerator is None:
                return "failed", {"reason": "unknown device", "device": command.get("device")}
            aerator.on = action == "aerator.on"
            turning = aerator.turning(pond.powered)
            return "done", {"device": aerator.id, "on": aerator.on, "turning": turning}
        if action in ("generator.start", "generator.stop"):
            self.farm.generator_running = action == "generator.start"
            return "done", {"generator": self.farm.generator_running}
        return "failed", {"reason": f"unsupported action {action}"}

    async def listen(self, client: httpx.AsyncClient, stop: asyncio.Event | None = None) -> None:
        """Keep the command channel open while the link is up; reconnect with backoff when it drops."""
        stop = stop or asyncio.Event()
        backoff = 1.0
        while not stop.is_set():
            if not self.online:
                await asyncio.sleep(1)
                continue
            try:
                async with client.stream(
                    "GET", f"/v1/gateways/{self.id}/commands", timeout=CHANNEL_TIMEOUT
                ) as response:
                    if response.status_code == 200:
                        backoff = 1.0
                        await self._read_channel(client, response, stop)
                    else:
                        log.warning(
                            "command channel refused",
                            extra={"ctx": {"gateway": self.id, "status_code": response.status_code}},
                        )
            except httpx.HTTPError as exc:
                log.debug("command channel dropped", extra={"ctx": {"gateway": self.id, "reason": str(exc)}})
            if stop.is_set():
                return
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    async def _read_channel(
        self, client: httpx.AsyncClient, response: httpx.Response, stop: asyncio.Event
    ) -> None:
        event = ""
        async for line in response.aiter_lines():
            if not self.online or stop.is_set():
                return  # the link just went down: nothing more arrives
            if line.startswith("event:"):
                event = line.removeprefix("event:").strip()
            elif line.startswith("data:") and event == "command":
                command = json.loads(line.removeprefix("data:"))
                await self._acknowledge(client, command["id"], self.execute(command))
            elif not line:
                event = ""

    async def _acknowledge(self, client: httpx.AsyncClient, command_id: str, result: dict[str, Any]) -> None:
        for attempt in range(3):
            try:
                body = {"gateway": self.id, **result}
                response = await client.post(f"/v1/commands/{command_id}/ack", json=body)
                if response.status_code < 500:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1 + attempt)
        # Not acknowledged: the cloud sends the command again and gets the remembered result.
        log.warning("command ack failed", extra={"ctx": {"gateway": self.id, "command": command_id}})
