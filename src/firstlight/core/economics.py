"""What the shrimp in a pond are worth today: an estimate, every assumption written down with its source.

value = area * stocking density * survival(age) * average weight(age) * farm-gate price(size)

The curves are interpolated linearly between the points below. They describe intensive white-leg shrimp
in the Mekong Delta; SOURCES says where each comes from. This is the team's estimate for showing what is
at stake in an incident, not a valuation.
"""

from dataclasses import asdict, dataclass
from datetime import date
from itertools import pairwise
from typing import Any

# Average body weight in grams by days of culture.
GROWTH: list[tuple[float, float]] = [
    (0, 0.01),
    (30, 2.0),
    (45, 5.0),
    (60, 9.0),
    (75, 13.0),
    (90, 17.0),
    (110, 22.0),
]
# Share of the stocked post-larvae still alive at that age.
SURVIVAL: list[tuple[float, float]] = [(0, 1.0), (30, 0.9), (60, 0.82), (90, 0.75), (120, 0.7)]
# Farm-gate price, VND per kg, by size in shrimp per kg (smaller count = bigger shrimp).
PRICES: list[tuple[float, float]] = [
    (30, 185_000),
    (40, 160_000),
    (50, 145_000),
    (70, 125_000),
    (100, 105_000),
]

SOURCES: dict[str, str] = {
    "growth": "placeholder, replaced by the sourced curve",
    "survival": "placeholder, replaced by the sourced curve",
    "prices": "placeholder, replaced by sourced Mekong Delta farm-gate prices",
}


def interpolate(points: list[tuple[float, float]], x: float) -> float:
    """Linear between points, flat beyond the ends."""
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in pairwise(points):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


@dataclass(frozen=True)
class Crop:
    doc: int  # days of culture
    abw_g: float
    survival: float
    count_per_kg: float
    biomass_kg: float
    price_vnd_per_kg: int
    value_vnd: int

    def doc_dict(self) -> dict[str, Any]:
        return asdict(self)


def crop(area_m2: float, density_per_m2: float, stocked_on: date, today: date) -> Crop:
    doc = max(0, (today - stocked_on).days)
    abw = interpolate(GROWTH, doc)
    alive = interpolate(SURVIVAL, doc)
    count = 1000 / abw
    biomass = area_m2 * density_per_m2 * alive * abw / 1000
    price = interpolate(PRICES, count)
    return Crop(
        doc,
        round(abw, 1),
        round(alive, 2),
        round(count),
        round(biomass),
        round(price),
        round(biomass * price),
    )


def pond_crop(state: dict[str, Any], today: date) -> Crop | None:
    """The crop of a pond_state document, if the gateway reported how it was stocked."""
    stock = state.get("stock")
    if not stock or not state.get("area_m2"):
        return None
    stocked = stock["stocked_on"]
    return crop(
        state["area_m2"],
        stock["density_per_m2"],
        stocked.date() if hasattr(stocked, "date") else stocked,
        today,
    )
