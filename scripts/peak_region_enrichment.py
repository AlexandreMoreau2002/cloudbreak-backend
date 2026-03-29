"""
Logique partagée d'enrichissement du champ region pour les peaks.
"""

from __future__ import annotations

import time
import httpx
from typing import Any
from dataclasses import dataclass

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_HEADERS = {
    "User-Agent": "Cloudbreak/1.0 contact@cloudbreak.app",
    "accept-language": "fr",
}


@dataclass(frozen=True)
class RegionRule:
    label: str
    south: float
    west: float
    north: float
    east: float
    max_altitude: int | None = None

    def matches(self, *, lat: float, lng: float, altitude: int) -> bool:
        if self.max_altitude is not None and altitude > self.max_altitude:
            return False
        return self.south <= lat <= self.north and self.west <= lng <= self.east


MANUAL_REGION_OVERRIDES = {
    "aiguille-du-midi": "Massif du Mont-Blanc",
    "butte-montmartre": "Paris",
    "chamechaude": "Massif de la Chartreuse",
    "col-de-la-croix-fry": "Massif des Aravis",
    "colline-de-fourviere": "Lyon",
    "colline-du-chateau": "Nice",
    "croix-de-chamrousse": "Massif de Belledonne",
    "dent-de-crolles": "Massif de la Chartreuse",
    "grand-veymont": "Massif du Vercors",
    "la-bastille": "Grenoble",
    "mont-blanc": "Massif du Mont-Blanc",
    "mont-saint-clair": "Sete",
    "moucherotte": "Massif du Vercors",
    "puy-de-dome": "Chaine des Puys",
    "sacre-coeur": "Paris",
    "tour-eiffel": "Paris",
}

CITY_RULES = [
    RegionRule("Paris", 48.80, 2.20, 48.91, 2.48, max_altitude=700),
    RegionRule("Grenoble", 45.15, 5.67, 45.22, 5.76, max_altitude=700),
    RegionRule("Lyon", 45.72, 4.78, 45.80, 4.87, max_altitude=700),
    RegionRule("Nice", 43.67, 7.24, 43.73, 7.31, max_altitude=700),
    RegionRule("Sete", 43.38, 3.66, 43.43, 3.74, max_altitude=700),
]

MASSIF_RULES = [
    RegionRule("Massif du Vercors", 44.70, 5.10, 45.35, 5.95),
    RegionRule("Massif de la Chartreuse", 45.23, 5.60, 45.55, 6.08),
    RegionRule("Massif de Belledonne", 45.02, 5.82, 45.42, 6.28),
    RegionRule("Massif des Bauges", 45.52, 5.80, 45.84, 6.28),
    RegionRule("Massif des Aravis", 45.80, 6.22, 46.05, 6.78),
    RegionRule("Massif du Chablais", 46.10, 6.45, 46.45, 7.10),
    RegionRule("Massif du Mont-Blanc", 45.73, 6.68, 46.08, 7.12),
    RegionRule("Massif de la Vanoise", 45.18, 6.58, 45.66, 7.18),
    RegionRule("Massif des Ecrins", 44.58, 5.95, 45.28, 6.68),
    RegionRule("Massif du Devoluy", 44.55, 5.72, 44.98, 6.22),
    RegionRule("Massif du Queyras", 44.56, 6.60, 44.98, 7.22),
    RegionRule("Mercantour", 43.72, 6.72, 44.36, 7.55),
    RegionRule("Jura", 46.00, 5.35, 47.55, 6.55),
    RegionRule("Vosges", 47.68, 6.58, 48.82, 7.45),
    RegionRule("Pyrenees", 42.35, -2.00, 43.55, 3.35),
    RegionRule("Massif Central", 44.40, 2.20, 46.35, 4.55),
    RegionRule("Bretagne/Normandie", 47.00, -5.60, 50.05, -0.40),
    RegionRule("Ile-de-France/Centre", 47.45, 0.95, 49.55, 4.05),
    RegionRule("Provence/Cote", 43.00, 4.45, 44.55, 7.55),
]


def resolve_from_rules(peak: dict[str, Any]) -> tuple[str | None, str | None]:
    slug = peak["slug"]
    lat = float(peak["lat"])
    lng = float(peak["lng"])
    altitude = int(peak["altitude"])

    manual = MANUAL_REGION_OVERRIDES.get(slug)
    if manual:
        return manual, "manual"

    for rule in CITY_RULES:
        if rule.matches(lat=lat, lng=lng, altitude=altitude):
            return rule.label, "city_bbox"

    for rule in MASSIF_RULES:
        if rule.matches(lat=lat, lng=lng, altitude=altitude):
            return rule.label, "massif_bbox"

    return None, None


def extract_region_from_nominatim(peak: dict[str, Any], payload: dict[str, Any]) -> str | None:
    address = payload.get("address", {})
    altitude = int(peak["altitude"])

    if altitude <= 700:
        for key in ("city", "town", "village", "municipality"):
            value = address.get(key)
            if isinstance(value, str) and value:
                return value

    for key in ("county", "state_district", "state"):
        value = address.get(key)
        if isinstance(value, str) and value and value != "France metropolitaine":
            return value

    return None


def fetch_region_from_nominatim(
    peak: dict[str, Any], client: httpx.Client, last_request_at: float | None
) -> tuple[str | None, float]:
    now = time.monotonic()
    if last_request_at is not None:
        elapsed = now - last_request_at
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)

    response = client.get(
        NOMINATIM_URL,
        params={
            "format": "jsonv2",
            "lat": peak["lat"],
            "lon": peak["lng"],
            "zoom": 18,
            "addressdetails": 1,
            "extratags": 1,
        },
    )
    response.raise_for_status()
    return extract_region_from_nominatim(peak, response.json()), time.monotonic()


def enrich_peaks(
    peaks: list[dict[str, Any]],
    *,
    overwrite_existing: bool,
    use_nominatim: bool,
    nominatim_limit: int | None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    stats = {
        "manual": 0,
        "city_bbox": 0,
        "massif_bbox": 0,
        "nominatim": 0,
        "preserved": 0,
        "unresolved": 0,
    }
    remaining_nominatim = nominatim_limit
    last_request_at: float | None = None

    with httpx.Client(headers=NOMINATIM_HEADERS, timeout=20.0) as client:
        for peak in peaks:
            existing = peak.get("region")
            if existing and not overwrite_existing:
                stats["preserved"] += 1
                continue

            region, source = resolve_from_rules(peak)
            if region:
                peak["region"] = region
                stats[source] += 1
                continue

            if use_nominatim and (remaining_nominatim is None or remaining_nominatim > 0):
                region, last_request_at = fetch_region_from_nominatim(peak, client, last_request_at)
                if remaining_nominatim is not None:
                    remaining_nominatim -= 1
                if region:
                    peak["region"] = region
                    stats["nominatim"] += 1
                    continue

            peak["region"] = None
            stats["unresolved"] += 1

    return peaks, stats
