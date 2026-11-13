"""
Génère peaks_data.json pour seed.py via Overpass API (OpenStreetMap).

Tags OSM interrogés :
  - natural=peak     → sommets (ele >= 500m, depuis OSM)
  - natural=volcano  → volcans (ele >= 500m) — ex: Puy de Dôme, Chaîne des Puys, La Réunion
  - natural=saddle   → cols/passages (ele >= 500m, depuis OSM)
  - tourism=viewpoint → belvédères (ele non requis — altitude via Open-Meteo)
    → filtre : elevation >= 80m (capture La Bastille, Fourvière, Mont Saint-Clair…)

Stratégie viewpoints :
  Les viewpoints OSM n'ont souvent pas de tag `ele`. On les récupère tous
  (avec un nom), puis on enrichit leur altitude via l'API Open-Meteo Elevation
  (gratuite, 100 coordonnées par appel, pas de clé requise).

Stratégie générale :
  Requêtes par région (bounding box) avec délai entre chaque pour respecter
  le rate-limit Overpass API.

Usage :
    python scripts/generate_peaks.py
    # Écrit app/db/peaks_data_new.json déjà enrichi avec region

Prérequis :
    pip install httpx  (déjà dans requirements)
"""

import re
import sys
import json
import time
import uuid
import httpx
import argparse
import unicodedata
from typing import Any
from pathlib import Path
from peak_region_enrichment import enrich_peaks

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
OUTPUT_FILE = Path(__file__).parent.parent / "app" / "db" / "peaks_data.json"
OUTPUT_FILE_TMP = Path(__file__).parent.parent / "app" / "db" / "peaks_data_new.json"

Bbox = tuple[float, float, float, float]

REGIONS: list[dict[str, str | Bbox]] = [
    {"name": "Alpes Nord", "bbox": (45.5, 5.5, 46.5, 7.5)},
    {"name": "Alpes Sud", "bbox": (44.0, 5.5, 45.5, 7.5)},
    {"name": "Vosges", "bbox": (47.7, 6.6, 48.8, 7.4)},
    {"name": "Massif Central", "bbox": (44.5, 2.3, 46.2, 4.5)},
    {"name": "Jura", "bbox": (46.0, 5.4, 47.5, 6.5)},
    {"name": "Pyrénées", "bbox": (42.4, -2.0, 43.5, 3.3)},
    {"name": "Provence/Côte", "bbox": (43.0, 4.5, 44.5, 7.5)},
    {"name": "Bretagne/Normandie", "bbox": (47.0, -5.5, 50.0, -0.5)},
    {"name": "Île-de-France/Centre", "bbox": (47.5, 1.0, 49.5, 4.0)},
]

# Seuils altitude pour peaks/saddles (OSM a l'altitude dans ele)
MIN_ALT_PEAK = 500
MIN_ALT_SADDLE = 500
# Seuil pour viewpoints (altitude enrichie via Open-Meteo)
MIN_ALT_VIEWPOINT = 80

# Entrées manuelles : cols absents d'OSM natural=peak + viewpoints urbains iconiques
# (les viewpoints OSM peuvent être perdus lors d'un rate-limit Open-Meteo)
MANUAL_ENTRIES: list[dict[str, Any]] = [
    {
        "name": "Col de la Croix-Fry",
        "slug": "col-de-la-croix-fry",
        "lat": 45.9075,
        "lng": 6.5015,
        "altitude": 1477,
    },
    # Viewpoints urbains iconiques — filet de sécurité anti rate-limit
    {
        "name": "La Bastille",
        "slug": "la-bastille",
        "lat": 45.1947,
        "lng": 5.7230,
        "altitude": 476,
    },
    {
        "name": "Colline de Fourvière",
        "slug": "colline-de-fourviere",
        "lat": 45.7613,
        "lng": 4.8221,
        "altitude": 295,
    },
    {
        "name": "Mont Saint-Clair",
        "slug": "mont-saint-clair",
        "lat": 43.3993,
        "lng": 3.6988,
        "altitude": 176,
    },
    {
        "name": "Butte Montmartre",
        "slug": "butte-montmartre",
        "lat": 48.8867,
        "lng": 2.3431,
        "altitude": 130,
    },
    {
        "name": "Colline du Château",
        "slug": "colline-du-chateau",
        "lat": 43.6963,
        "lng": 7.2767,
        "altitude": 92,
    },
    {
        "name": "Butte Montmartre — Sacré-Cœur",
        "slug": "sacre-coeur",
        "lat": 48.8867,
        "lng": 2.3431,
        "altitude": 130,
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--use-nominatim",
        action="store_true",
        help="Enrichit aussi region via Nominatim pour les peaks hors couverture locale.",
    )
    parser.add_argument(
        "--nominatim-limit",
        type=int,
        default=None,
        help="Limite le nombre d'appels Nominatim pour un run de test.",
    )
    return parser.parse_args()


def make_id(slug: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"cloudbreak:peak:{slug}"))


def slugify(name: str) -> str:
    name = name.replace("œ", "oe").replace("Œ", "Oe").replace("æ", "ae").replace("Æ", "Ae")
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^\w\s-]", "", ascii_str.lower())
    return re.sub(r"[-\s]+", "-", slug).strip("-")


def _fetch_overpass_with_retry(query: str, label: str) -> dict[str, Any]:
    """Appel Overpass avec retry exponentiel (3 tentatives max)."""
    for attempt in range(3):
        try:
            response = httpx.post(OVERPASS_URL, data={"data": query}, timeout=100)
            if response.status_code in (429, 504):
                wait = 60 * (2**attempt)  # 60s, 120s, 240s
                print(
                    f"    ⏳ {response.status_code} {label} — attente {wait}s"
                    f" (tentative {attempt + 1}/3)",
                    file=sys.stderr,
                )
                time.sleep(wait)
                continue
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]
        except httpx.TimeoutException:
            wait = 30 * (2**attempt)
            print(
                f"    ⏳ timeout réseau {label} — attente {wait}s" f" (tentative {attempt + 1}/3)",
                file=sys.stderr,
            )
            if attempt < 2:
                time.sleep(wait)
    return {}


def query_peaks_saddles(bbox: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    """Requête peaks + volcans + saddles avec [ele] dans OSM."""
    south, west, north, east = bbox
    query = f"""
[out:json][timeout:90];
(
  node["natural"="peak"]["name"]["ele"]({south},{west},{north},{east});
  node["natural"="volcano"]["name"]["ele"]({south},{west},{north},{east});
  node["natural"="saddle"]["name"]["ele"]({south},{west},{north},{east});
);
out body;
"""
    data = _fetch_overpass_with_retry(query, "peaks/saddles")

    if not data:
        print("    ⚠️  échec peaks/saddles après 3 tentatives", file=sys.stderr)
        return []

    if "timed out" in data.get("remark", ""):
        print("    ⚠️  timeout Overpass peaks/saddles", file=sys.stderr)
        return []

    results = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name:fr") or tags.get("name", "")
        ele_str = tags.get("ele", "")
        if not name or not ele_str:
            continue
        try:
            altitude = int(float(ele_str))
        except ValueError:
            continue

        natural = tags.get("natural")
        if natural in ("peak", "volcano"):
            if altitude < MIN_ALT_PEAK:
                continue
            node_type = f"natural={natural}"
        else:
            if altitude < MIN_ALT_SADDLE:
                continue
            node_type = "natural=saddle"

        results.append(
            {
                "name": name,
                "slug": slugify(name),
                "lat": round(el["lat"], 6),
                "lng": round(el["lon"], 6),
                "altitude": altitude,
                "type": node_type,
            }
        )

    return results


def query_viewpoints(bbox: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    """Requête viewpoints sans filtre [ele] — altitude enrichie après via Open-Meteo."""
    south, west, north, east = bbox
    query = f"""
[out:json][timeout:90];
node["tourism"="viewpoint"]["name"]({south},{west},{north},{east});
out body;
"""
    data = _fetch_overpass_with_retry(query, "viewpoints")

    if not data:
        print("    ⚠️  échec viewpoints après 3 tentatives", file=sys.stderr)
        return []

    if "timed out" in data.get("remark", ""):
        print("    ⚠️  timeout Overpass viewpoints", file=sys.stderr)
        return []

    results = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name:fr") or tags.get("name", "")
        if not name:
            continue
        results.append(
            {
                "name": name,
                "slug": slugify(name),
                "lat": round(el["lat"], 6),
                "lng": round(el["lon"], 6),
                "altitude": 0,  # sera enrichi par Open-Meteo
                "type": "tourism=viewpoint",
            }
        )

    return results


def _fetch_elevations_with_retry(lats: str, lngs: str, batch_num: int) -> list[float]:
    """Appel Open-Meteo avec retry exponentiel (3 tentatives max)."""
    for attempt in range(3):
        try:
            resp = httpx.get(
                ELEVATION_URL,
                params={"latitude": lats, "longitude": lngs},
                timeout=30,
            )
            if resp.status_code == 429:
                wait = 30 * (2**attempt)  # 30s, 60s, 120s
                print(
                    f"    ⏳ 429 batch {batch_num} — attente {wait}s"
                    f" (tentative {attempt + 1}/3)",
                    file=sys.stderr,
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()
            result: list[float] = resp.json().get("elevation", [])
            return result
        except Exception as e:
            print(
                f"    ⚠️  Open-Meteo batch {batch_num} tentative {attempt + 1}/3 : {e}",
                file=sys.stderr,
            )
            if attempt < 2:
                time.sleep(15)
    return []


def enrich_elevations(viewpoints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enrichit l'altitude des viewpoints via Open-Meteo Elevation API (batch 100)."""
    if not viewpoints:
        return []

    enriched = []
    batch_size = 100
    total = len(viewpoints)

    for i in range(0, total, batch_size):
        batch = viewpoints[i : i + batch_size]
        lats = ",".join(str(p["lat"]) for p in batch)
        lngs = ",".join(str(p["lng"]) for p in batch)

        elevations = _fetch_elevations_with_retry(lats, lngs, batch_num=i // batch_size + 1)

        for point, elev in zip(batch, elevations):
            altitude = int(elev) if elev is not None else 0
            if altitude >= MIN_ALT_VIEWPOINT:
                enriched.append({**point, "altitude": altitude})

        if i + batch_size < total:
            time.sleep(2)  # pause entre les batches Open-Meteo (évite le 429)

    print(
        f"    → viewpoints enrichis : {len(enriched)}/{total} ≥ {MIN_ALT_VIEWPOINT}m",
        file=sys.stderr,
    )
    return enriched


def deduplicate(peaks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_slug: dict[str, dict[str, Any]] = {}
    for p in peaks:
        slug = p["slug"]
        if slug not in by_slug or p["altitude"] > by_slug[slug]["altitude"]:
            by_slug[slug] = p
    return sorted(by_slug.values(), key=lambda p: -p["altitude"])


def main() -> None:
    args = parse_args()
    all_peaks_saddles: list[dict[str, Any]] = []
    all_viewpoints_raw: list[dict[str, Any]] = []

    for region in REGIONS:
        label = region["name"]
        print(f"  → {label}...", file=sys.stderr, flush=True)

        # --- Peaks + saddles (avec ele dans OSM) ---
        try:
            ps = query_peaks_saddles(region["bbox"])  # type: ignore[arg-type]
            by_type: dict[str, int] = {}
            for p in ps:
                by_type[p["type"]] = by_type.get(p["type"], 0) + 1
            summary = ", ".join(f"{v} {k.split('=')[1]}" for k, v in by_type.items())
            print(f"    ✅ peaks/saddles : {len(ps)} ({summary})", file=sys.stderr)
            all_peaks_saddles.extend(ps)
        except Exception as e:
            print(f"    ❌ peaks/saddles : {e}", file=sys.stderr)
        time.sleep(15)  # pause généreuse entre peaks et viewpoints

        # --- Viewpoints (sans ele dans OSM) ---
        try:
            vp = query_viewpoints(region["bbox"])  # type: ignore[arg-type]
            print(f"    ✅ viewpoints bruts : {len(vp)}", file=sys.stderr)
            all_viewpoints_raw.extend(vp)
        except Exception as e:
            print(f"    ❌ viewpoints : {e}", file=sys.stderr)
        time.sleep(20)  # pause généreuse entre régions

    # Enrichir les altitudes des viewpoints via Open-Meteo
    print(
        f"\n  → Enrichissement altitude de {len(all_viewpoints_raw)} viewpoints (Open-Meteo)…",
        file=sys.stderr,
        flush=True,
    )
    all_viewpoints = enrich_elevations(all_viewpoints_raw)

    # Fusion + déduplication
    all_raw = all_peaks_saddles + all_viewpoints
    peaks = deduplicate(all_raw)

    # Ajouter les entrées manuelles (cols absents d'OSM natural=peak)
    existing = {p["slug"] for p in peaks}
    for entry in MANUAL_ENTRIES:
        if entry["slug"] not in existing:
            peaks.append({**entry, "id": make_id(entry["slug"]), "type": "manual"})
            print(f"  + manuel : {entry['name']}", file=sys.stderr)

    # Ajouter les IDs et retirer le champ type (pas dans le schéma DB)
    for p in peaks:
        p["id"] = make_id(p["slug"])
        p.pop("type", None)

    peaks, region_stats = enrich_peaks(
        peaks,
        overwrite_existing=True,
        use_nominatim=args.use_nominatim,
        nominatim_limit=args.nominatim_limit,
    )

    peaks.sort(key=lambda p: -p["altitude"])

    with OUTPUT_FILE_TMP.open("w", encoding="utf-8") as f:
        json.dump(peaks, f, ensure_ascii=False, indent=2)

    print(f"\n✅ {len(peaks)} entrées → {OUTPUT_FILE_TMP}", file=sys.stderr)
    print(
        "\n⚠️  Fichier écrit dans peaks_data_new.json — PAS encore dans peaks_data.json."
        "\n   Vérifier avec : pytest tests/test_peaks_data.py --peaks-file=peaks_data_new.json"
        "\n   Puis valider  : mv app/db/peaks_data_new.json app/db/peaks_data.json",
        file=sys.stderr,
    )
    enriched_regions = sum(1 for peak in peaks if peak.get("region"))
    print(
        f"\n📍 region enrichie : {enriched_regions}/{len(peaks)} "
        f"({enriched_regions / len(peaks):.1%})",
        file=sys.stderr,
    )
    for key, value in region_stats.items():
        print(f"   - {key}: {value}", file=sys.stderr)

    print("\nVérification des spots clés :", file=sys.stderr)
    slugs = {p["slug"] for p in peaks}
    key_spots = [
        "mont-blanc",
        "puy-de-dome",
        "col-de-la-croix-fry",
        "champ-du-feu",
        "la-bastille",
        "colline-de-fourviere",
        "mont-saint-clair",
        "sacre-coeur",
        "colline-du-chateau",
    ]
    for s in key_spots:
        status = "✅" if s in slugs else "❌ absent"
        print(f"  {status}  {s}", file=sys.stderr)


if __name__ == "__main__":
    main()
