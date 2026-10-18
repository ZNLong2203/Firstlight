"""The simulated estate: farms across five Mekong Delta provinces, each with its ponds and one 4G gateway."""

import random
import zlib
from dataclasses import dataclass

from firstlight.core.models import AeratorSpec, GatewayManifest, PondSpec, ProbeSpec
from firstlight.edge.physics import Pond, make_pond

PROVINCES = [
    ("BL", "Bạc Liêu", 105.72, 9.29),
    ("ST", "Sóc Trăng", 105.97, 9.60),
    ("CM", "Cà Mau", 105.15, 9.18),
    ("BT", "Bến Tre", 106.38, 10.24),
    ("KG", "Kiên Giang", 105.08, 10.01),
]
# Shrimp farms are not spread evenly: Cà Mau and Bạc Liêu raise most of the Delta's shrimp, Kiên Giang the
# least of these five. The estate's farms follow that order.
SHARE = {"CM": 0.28, "BL": 0.24, "ST": 0.20, "BT": 0.16, "KG": 0.12}
# Ponds per farm: four is typical, some farms have two or three, a few five or six. Lined-pond
# households average 4.5 (Hien et al., VJAST 2021). Farms are paired, and whatever one has fewer its
# partner has more, so the estate keeps four ponds per farm overall: the demo's 50 farms have 200.
POND_SHIFTS = [0, 0, 1, 1, 2]


@dataclass
class Farm:
    id: str
    province: str
    gateway: str
    lon: float
    lat: float
    ponds: list[Pond]
    grid: bool = True  # mains power; the chaos panel can cut it
    generator_running: bool = False

    def step(self, hour: float, dt_s: float, rng: random.Random) -> None:
        powered = self.grid or self.generator_running
        for pond in self.ponds:
            pond.powered = powered
            pond.step(hour, dt_s, rng)

    def manifest(self) -> GatewayManifest:
        return GatewayManifest(
            gateway=self.gateway,
            farm=self.id,
            province=self.province,
            lon=self.lon,
            lat=self.lat,
            ponds=[
                PondSpec(
                    id=p.id,
                    area_m2=p.area_m2,
                    aerators=[AeratorSpec(id=a.id, kw=a.kw, standby=a.standby) for a in p.aerators],
                    probe=ProbeSpec(id=p.probe.id, model=p.probe.model),
                    stocked_on=p.stocked_on,
                    density_per_m2=p.density_per_m2,
                )
                for p in self.ponds
            ],
        )


def farm_counts(n_farms: int) -> dict[str, int]:
    """Farms per province for an estate of n farms, by largest remainder so the counts add up exactly."""
    exact = {code: share * n_farms for code, share in SHARE.items()}
    counts = {code: int(value) for code, value in exact.items()}
    short = n_farms - sum(counts.values())
    for code in sorted(exact, key=lambda c: exact[c] - counts[c], reverse=True)[:short]:
        counts[code] += 1
    return counts


def _farm(code: str, province: str, lon: float, lat: float, number: int, ponds: int) -> Farm:
    farm_id = f"{code}-{number:02d}"
    gateway = f"GW-{farm_id.replace('-', '')}-1"
    jitter = random.Random(zlib.crc32(farm_id.encode()))
    return Farm(
        id=farm_id,
        province=province,
        gateway=gateway,
        lon=round(lon + jitter.uniform(-0.08, 0.08), 5),
        lat=round(lat + jitter.uniform(-0.08, 0.08), 5),
        ponds=[make_pond(f"{farm_id}-A{j + 1}", farm_id, gateway) for j in range(ponds)],
    )


def build_farms(n_farms: int, ponds_per_farm: int) -> list[Farm]:
    """A uniform estate, provinces in turn and the same number of ponds everywhere: what tests need."""
    n = len(PROVINCES)
    return [_farm(*PROVINCES[i % n], i // n + 1, ponds_per_farm) for i in range(n_farms)]


def pond_counts(n_farms: int) -> list[int]:
    """Two to six ponds for each of n farms, four on average. Always the same for the same n."""
    rng = random.Random(7)
    counts = [4] * n_farms
    order = list(range(n_farms))
    rng.shuffle(order)
    for fewer, more in zip(order[0::2], order[1::2], strict=False):
        shift = rng.choice(POND_SHIFTS)
        counts[fewer] -= shift
        counts[more] += shift
    return counts


def build_estate(n_farms: int) -> list[Farm]:
    """The simulated estate: more farms where more shrimp are raised, two to six ponds to a farm. Each
    pond's physics depends only on its id, so a pond behaves the same from one run to the next."""
    per_province = farm_counts(n_farms)
    ponds = iter(pond_counts(n_farms))
    return [
        _farm(code, province, lon, lat, number, next(ponds))
        for code, province, lon, lat in PROVINCES
        for number in range(1, per_province[code] + 1)
    ]
