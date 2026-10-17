"""What the shrimp in a pond are worth today: an estimate, every assumption written down with its source.

    market = post-larvae stocked * survival(age) * average weight(age) * farm-gate price(size)
    cost   = post-larvae stocked * their price + feed eaten so far * feed price
    value  = the larger of the two

Shrimp smaller than about 6.7 g (150 to the kilogram) have no farm-gate price, so a young crop is worth
what has been spent on it: losing it means losing the seed and the feed. The curves are interpolated
linearly between the points below and describe lined, intensive white-leg shrimp ponds in the Mekong
Delta; SOURCES says where each number comes from. This is the team's estimate of what an incident puts
at stake, not a valuation.
"""

from dataclasses import asdict, dataclass
from datetime import date
from itertools import pairwise
from typing import Any

# Average body weight in grams by days of culture.
GROWTH: list[tuple[float, float]] = [
    (0, 0.01),
    (30, 1.8),
    (45, 4.5),
    (60, 8.0),
    (75, 12.5),
    (90, 17.0),
    (110, 22.5),
]
# Share of the stocked post-larvae still alive at that age. Losses come early: disease strikes in the
# first 60 days.
SURVIVAL: list[tuple[float, float]] = [
    (0, 1.0),
    (30, 0.88),
    (45, 0.80),
    (60, 0.74),
    (75, 0.69),
    (90, 0.65),
    (110, 0.62),
]
# Farm-gate price, VND per kg, by size in shrimp per kg (a smaller count means bigger shrimp).
PRICES: list[tuple[float, float]] = [
    (20, 190_000),
    (30, 155_000),
    (40, 130_000),
    (50, 120_000),
    (60, 115_000),
    (70, 112_000),
    (80, 110_000),
    (90, 104_000),
    (100, 93_000),
    (150, 64_000),
]
MARKET_MAX_COUNT = 150  # no price is quoted for smaller shrimp
SEED_VND = 70  # one PL12 post-larva
FEED_VND_PER_KG = 34_000
FCR = 1.3  # kg of feed per kg of shrimp, taken as constant over the crop

SOURCES: dict[str, str] = {
    "prices": (
        "Farm-gate prices of white-leg shrimp by size, dealer quotes collected by tepbac.com on "
        "16/10/2026, mostly in Ca Mau: https://tepbac.com/gia-thuy-san/gia-loai/tom-the-chan-trang. "
        "One aggregator, not an official statistic; during 2026 prices moved by about 30% either way."
    ),
    "growth": (
        "Team curve between the harvest weights surveyed in lined Mekong ponds, 16.1-16.2 g at 89-93 "
        "days (FAO Fisheries and Aquaculture Circular 1194, 2019; Hien et al., VJAST 5(126), 2021), and "
        "the Can Tho University biofloc guide, 16-20 g at days 81-90."
    ),
    "survival": (
        "Team path to 65% at day 90, inside the 57-76% surveyed in lined ponds (Vo Nam Son et al., "
        "CTU Journal of Science 55(1B), 2019; Si et al. 2024), with losses front-loaded because AHPND and "
        "white spot strike within the first 60 days (FAO 2019)."
    ),
    "density": (
        "Lined intensive ponds stock 157 +/- 38 post-larvae per m2 (Hien et al. 2021, 178 households); "
        "the simulator draws 100-250."
    ),
    "area": "Ponds average 0.4 +/- 0.3 ha (Hien et al. 2021); the simulator draws 2,000-5,000 m2.",
    "cost": (
        "PL12 post-larvae at 70 VND each and feed at 34,000 VND/kg (tepbac.com, October 2026); a feed "
        "conversion ratio of 1.3 (Hien et al. 2021)."
    ),
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
    price_vnd_per_kg: int  # 0 while the shrimp are too small to sell
    value_vnd: int
    basis: str  # "market": at today's farm-gate price; "cost": what seed and feed have cost so far
    cost_vnd: int

    def doc_dict(self) -> dict[str, Any]:
        return asdict(self)


def crop(area_m2: float, density_per_m2: float, stocked_on: date, today: date) -> Crop:
    doc = max(0, (today - stocked_on).days)
    abw = interpolate(GROWTH, doc)
    alive = interpolate(SURVIVAL, doc)
    count = 1000 / abw
    stocked = area_m2 * density_per_m2
    biomass = stocked * alive * abw / 1000
    price = interpolate(PRICES, count) if count <= MARKET_MAX_COUNT else 0.0
    market = biomass * price
    cost = stocked * SEED_VND + biomass * FCR * FEED_VND_PER_KG
    value, basis = (market, "market") if market >= cost else (cost, "cost")
    return Crop(
        doc,
        round(abw, 1),
        round(alive, 2),
        round(count),
        round(biomass),
        round(price),
        round(value),
        basis,
        round(cost),
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
