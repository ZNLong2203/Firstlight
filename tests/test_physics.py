import random
from datetime import UTC, datetime

from firstlight.core.models import GatewayManifest, PondReading
from firstlight.edge.farms import build_estate, build_farms
from firstlight.edge.physics import Pond, Probe

FARMS = build_farms(50, 4)
PONDS = [p for f in FARMS for p in f.ponds]


def settle(pond: Pond, rng: random.Random, hour: float = 2.0, minutes: int = 600) -> None:
    for _ in range(minutes):
        pond.step(hour, 60, rng)


def minutes_below(pond: Pond, rng: random.Random, target: float, limit: int = 240) -> int:
    for minute in range(1, limit + 1):
        pond.step(2.0, 60, rng)
        if pond.do < target:
            return minute
    return limit + 1


def test_the_simulated_estate_is_uneven_like_a_real_one() -> None:
    estate = build_estate(50)
    ponds = [p for f in estate for p in f.ponds]
    farms = {code: sum(1 for f in estate if f.id.startswith(code)) for code in ("CM", "BL", "ST", "BT", "KG")}
    assert farms == {"CM": 14, "BL": 12, "ST": 10, "BT": 8, "KG": 6}
    sizes = {len(f.ponds) for f in estate}
    assert min(sizes) >= 2 and max(sizes) <= 6 and len(sizes) > 2
    assert len(ponds) == 200 and len({p.id for p in ponds}) == 200
    again = [p.id for f in build_estate(50) for p in f.ponds]
    assert [p.id for p in ponds] == again, "the same estate every run"


def test_estate_layout() -> None:
    assert len(FARMS) == 50 and len(PONDS) == 200
    assert len({p.id for p in PONDS}) == 200
    aerator_ids = [a.id for p in PONDS for a in p.aerators]
    assert len(aerator_ids) == len(set(aerator_ids)), "aerator ids must be unique across the estate"
    assert FARMS[0].gateway == "GW-BL01-1" and FARMS[0].ponds[2].id == "BL-01-A3"
    for farm in FARMS:
        GatewayManifest.model_validate(farm.manifest().model_dump())


def test_night_oxygen_is_safe_with_every_aerator_running() -> None:
    rng = random.Random(1)
    for pond in PONDS:
        settle(pond, rng)
        assert 4.2 <= pond.do <= 6.0, pond.id


def test_daytime_photosynthesis_lifts_oxygen_above_night_levels() -> None:
    rng = random.Random(2)
    for pond in PONDS[:40]:
        settle(pond, rng, hour=2.0)
        night = pond.do
        settle(pond, rng, hour=12.5)
        assert pond.do > night + 1.0, pond.id


def test_power_cut_reaches_stress_level_within_an_hour() -> None:
    rng = random.Random(3)
    for pond in PONDS:
        settle(pond, rng)
        pond.powered = False
        assert minutes_below(pond, rng, 3.0) <= 60, pond.id
        pond.powered = True


def test_backup_aerator_recovers_a_pond_after_the_main_one_fails() -> None:
    rng = random.Random(4)
    for pond in PONDS:
        settle(pond, rng)
        pond.aerators[0].failed = True
        for _ in range(3):
            pond.step(2.0, 60, rng)
        pond.aerators[-1].on = True  # the standby aerator
        for _ in range(30):
            pond.step(2.0, 60, rng)
        assert pond.do >= 4.0, pond.id
        pond.aerators[0].failed = False
        pond.aerators[-1].on = False


def test_failed_aerator_draws_no_current_and_reading_validates() -> None:
    rng = random.Random(5)
    pond = PONDS[0]
    pond.aerators[0].failed = True
    reading = PondReading.model_validate(pond.reading(datetime.now(UTC), rng))
    pond.aerators[0].failed = False
    assert reading.aer[0].on and reading.aer[0].amp == 0.0
    assert all(a.amp > 0 for a in reading.aer[1:] if a.on)


def test_fouled_probe_reads_low_and_stuck_probe_reads_flat() -> None:
    rng = random.Random(6)
    fouled = Probe(id="DO-x", fouling=0.8)
    assert fouled.read(5.0, rng)[0] < 2.5
    stuck = Probe(id="DO-y", stuck_at=4.71)
    assert {stuck.read(v, rng)[0] for v in (3.0, 5.0, 7.0)} == {4.71}
