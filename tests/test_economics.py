from datetime import UTC, date, datetime, timedelta

import pytest

from firstlight.core import economics
from firstlight.core.economics import crop, interpolate, pond_crop

TODAY = date(2026, 10, 17)
STOCKED = 3000 * 150  # a 3,000 m2 pond at 150 post-larvae per m2


def test_interpolate_is_linear_between_points_and_flat_beyond() -> None:
    points = [(0.0, 0.0), (10.0, 100.0)]
    assert interpolate(points, -5) == 0.0
    assert interpolate(points, 2.5) == 25.0
    assert interpolate(points, 50) == 100.0


def test_a_young_crop_is_worth_what_was_spent_on_it() -> None:
    young = crop(3000, 150, TODAY - timedelta(days=30), TODAY)
    assert young.count_per_kg > economics.MARKET_MAX_COUNT and young.price_vnd_per_kg == 0
    biomass = STOCKED * 0.88 * 1.8 / 1000
    spent = STOCKED * economics.SEED_VND + biomass * economics.FCR * economics.FEED_VND_PER_KG
    assert young.basis == "cost" and young.value_vnd == pytest.approx(spent, rel=0.01)


def test_a_grown_crop_is_worth_its_farm_gate_price() -> None:
    grown = crop(3000, 150, TODAY - timedelta(days=90), TODAY)
    assert grown.abw_g == 17.0 and grown.count_per_kg == 59 and grown.basis == "market"
    assert 115_000 < grown.price_vnd_per_kg < 120_000  # between the quotes for 50 and 60 per kg
    biomass = STOCKED * 0.65 * 17.0 / 1000
    assert grown.value_vnd == pytest.approx(biomass * grown.price_vnd_per_kg, rel=0.01)
    assert grown.cost_vnd < grown.value_vnd


def test_value_never_falls_as_the_crop_grows() -> None:
    values = [crop(3000, 150, TODAY - timedelta(days=d), TODAY).value_vnd for d in range(130)]
    assert values == sorted(values)


def test_pond_crop_reads_the_stocking_a_gateway_reported() -> None:
    state = {
        "area_m2": 3000,
        "stock": {"stocked_on": datetime(2026, 7, 19, tzinfo=UTC), "density_per_m2": 150},
    }
    assert pond_crop(state, TODAY) == crop(3000, 150, date(2026, 7, 19), TODAY)
    assert pond_crop({"area_m2": 3000}, TODAY) is None
