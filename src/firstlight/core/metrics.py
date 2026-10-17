"""DogStatsD metrics; a no-op unless the Datadog Agent is part of the deployment."""

from datadog.dogstatsd.base import DogStatsd

from firstlight.core.config import Settings


class Metrics:
    def __init__(self, settings: Settings) -> None:
        self._statsd: DogStatsd | None = None
        if settings.dd_trace_enabled:
            self._statsd = DogStatsd(
                host=settings.dd_agent_host,
                port=settings.dd_dogstatsd_port,
                constant_tags=[f"env:{settings.dd_env}", f"version:{settings.dd_version}"],
            )

    def gauge(self, name: str, value: float, tags: list[str]) -> None:
        if self._statsd:
            self._statsd.gauge(name, value, tags=tags)

    def count(self, name: str, value: int, tags: list[str] | None = None) -> None:
        if self._statsd:
            self._statsd.increment(name, value, tags=tags)

    def distribution(self, name: str, value: float, tags: list[str] | None = None) -> None:
        if self._statsd:
            self._statsd.distribution(name, value, tags=tags)
