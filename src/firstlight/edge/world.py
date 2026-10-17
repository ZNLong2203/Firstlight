"""The simulated world as one object: farms, ponds, gateways, and the faults injected into them."""

from dataclasses import dataclass
from datetime import datetime

from firstlight.core.models import FaultRequest, FaultView
from firstlight.edge.farms import Farm
from firstlight.edge.gateway import Gateway
from firstlight.edge.physics import Aerator, Pond

FOULING_PER_MIN = 0.2  # a probe goes from clean to almost blind in about five minutes


class UnknownTarget(LookupError):
    pass


@dataclass
class _Applied:
    view: FaultView
    farm: Farm
    pond: Pond | None
    gateway: Gateway
    aerator: Aerator | None


class World:
    def __init__(self, farms: list[Farm], gateways: list[Gateway]) -> None:
        self.farms = {f.id: f for f in farms}
        self.ponds = {p.id: p for f in farms for p in f.ponds}
        self.gateways = {g.id: g for g in gateways}
        self._faults: dict[str, _Applied] = {}

    @property
    def faults(self) -> list[FaultView]:
        return [applied.view for applied in self._faults.values()]

    def apply(self, request: FaultRequest, now: datetime) -> FaultView:
        """Inject a fault. Applying the same id twice changes nothing, so the API can retry."""
        if request.id in self._faults:
            return self._faults[request.id].view
        pond = self._pond(request.pond) if request.pond else None
        farm = self._farm(request.farm) if request.farm else self._farm(pond.farm) if pond else None
        gateway = self._gateway(request.gateway) if request.gateway else None
        if farm is None and gateway is not None:
            farm = gateway.farm
        if farm is None:
            raise UnknownTarget("a fault needs a pond, a gateway or a farm")
        gateway = gateway or self.gateways[farm.gateway]

        aerator = None
        match request.kind:
            case "aerator_trip":
                pond = self._require(pond, "aerator_trip needs a pond")
                aerator = self._aerator(pond, request.device)
                aerator.failed = True
            case "probe_fouling":
                pond = self._require(pond, "probe_fouling needs a pond")
                pond.probe.fouling_per_min = FOULING_PER_MIN
            case "gateway_offline":
                gateway.online = False
            case "power_outage":
                farm.grid = False

        device = aerator.id if aerator else None
        if request.kind == "probe_fouling" and pond:
            device = pond.probe.id
        view = FaultView(
            id=request.id,
            kind=request.kind,
            farm=farm.id,
            pond=pond.id if pond else None,
            gateway=gateway.id,
            device=device,
            started_at=now,
        )
        self._faults[request.id] = _Applied(view, farm, pond, gateway, aerator)
        return view

    def clear(self, fault_id: str) -> FaultView | None:
        """Undo a fault the way a technician would: repair it and put the pond back as it was."""
        applied = self._faults.pop(fault_id, None)
        if applied is None:
            return None
        pond = applied.pond
        match applied.view.kind:
            case "aerator_trip" if applied.aerator and pond:
                applied.aerator.failed = False
                for aerator in pond.aerators:
                    if aerator.standby:
                        aerator.on = False  # the standby goes back to waiting once the main one runs
            case "probe_fouling" if pond:
                pond.probe.fouling = 0.0
                pond.probe.fouling_per_min = 0.0
            case "gateway_offline":
                applied.gateway.online = True
            case "power_outage":
                applied.farm.grid = True
                applied.farm.generator_running = False
        return applied.view

    def _pond(self, pond_id: str) -> Pond:
        if pond_id not in self.ponds:
            raise UnknownTarget(f"no pond {pond_id}")
        return self.ponds[pond_id]

    def _farm(self, farm_id: str) -> Farm:
        if farm_id not in self.farms:
            raise UnknownTarget(f"no farm {farm_id}")
        return self.farms[farm_id]

    def _gateway(self, gateway_id: str) -> Gateway:
        if gateway_id not in self.gateways:
            raise UnknownTarget(f"no gateway {gateway_id}")
        return self.gateways[gateway_id]

    @staticmethod
    def _require(pond: Pond | None, message: str) -> Pond:
        if pond is None:
            raise UnknownTarget(message)
        return pond

    @staticmethod
    def _aerator(pond: Pond, device: str | None) -> Aerator:
        if device:
            for aerator in pond.aerators:
                if aerator.id == device:
                    return aerator
            raise UnknownTarget(f"no aerator {device} in {pond.id}")
        # By default the largest aerator that is running fails: the case that matters most at night.
        running = [a for a in pond.aerators if a.on and not a.failed]
        if not running:
            raise UnknownTarget(f"no running aerator in {pond.id}")
        return max(running, key=lambda a: a.kla)
