"""
Génère peaks_data.json pour seed.py via Overpass API (OpenStreetMap).

Tags OSM interrogés :
  - natural=peak     → sommets (ele >= 500m, depuis OSM)
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
    # Écrit directement app/db/peaks_data.json

Prérequis :
    pip install httpx  (déjà dans requirements)
"""

import json
import re
import sys
import time
import uuid
import httpx
import unicodedata
from pathlib import Path
from typing import Any

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
OUTPUT_FILE = Path(__file__).parent.parent / "app" / "db" / "peaks_data.json"

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

# Cols obligatoires absents du tag natural=peak dans OSM (mountain_pass)
MANUAL_ENTRIES: list[dict[str, Any]] = [
    {
        "name": "Col de la Croix-Fry",
        "slug": "col-de-la-croix-fry",
        "lat": 45.9075,
        "lng": 6.5015,
        "altitude": 1477,
    },
]


def make_id(slug: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"cloudbreak:peak:{slug}"))


def slugify(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^\w\s-]", "", ascii_str.lower())
    return re.sub(r"[-\s]+", "-", slug).strip("-")


def query_peaks_saddles(bbox: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    """Requête peaks + saddles avec [ele] dans OSM."""
    south, west, north, east = bbox
    query = f"""
[out:json][timeout:60];
(
  node["natural"="peak"]["name"]["ele"]({south},{west},{north},{east});
  node["natural"="saddle"]["name"]["ele"]({south},{west},{north},{east});
);
out body;
"""
    response = httpx.post(OVERPASS_URL, data={"data": query}, timeout=70)
    response.raise_for_status()
    data = response.json()

    if "timed out" in data.get("remark", ""):
        print("    ⚠️  timeout peaks/saddles", file=sys.stderr)
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

        if tags.get("natural") == "peak":
            if altitude < MIN_ALT_PEAK:
                continue
            node_type = "natural=peak"
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
[out:json][timeout:60];
node["tourism"="viewpoint"]["name"]({south},{west},{north},{east});
out body;
"""
    response = httpx.post(OVERPASS_URL, data={"data": query}, timeout=70)
    response.raise_for_status()
    data = response.json()

    if "timed out" in data.get("remark", ""):
        print("    ⚠️  timeout viewpoints", file=sys.stderr)
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

        try:
            resp = httpx.get(
                ELEVATION_URL,
                params={"latitude": lats, "longitude": lngs},
                timeout=30,
            )
            resp.raise_for_status()
            elevations: list[float] = resp.json().get("elevation", [])
        except Exception as e:
            print(f"    ⚠️  Open-Meteo elevation batch {i//batch_size + 1} : {e}", file=sys.stderr)
            elevations = [0.0] * len(batch)

        for point, elev in zip(batch, elevations):
            altitude = int(elev) if elev is not None else 0
            if altitude >= MIN_ALT_VIEWPOINT:
                enriched.append({**point, "altitude": altitude})

        if i + batch_size < total:
            time.sleep(0.5)  # légère pause entre les batches Open-Meteo

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
        time.sleep(5)

        # --- Viewpoints (sans ele dans OSM) ---
        try:
            vp = query_viewpoints(region["bbox"])  # type: ignore[arg-type]
            print(f"    ✅ viewpoints bruts : {len(vp)}", file=sys.stderr)
            all_viewpoints_raw.extend(vp)
        except Exception as e:
            print(f"    ❌ viewpoints : {e}", file=sys.stderr)
        time.sleep(7)

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

    peaks.sort(key=lambda p: -p["altitude"])

    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(peaks, f, ensure_ascii=False, indent=2)

    print(f"\n✅ {len(peaks)} entrées → {OUTPUT_FILE}", file=sys.stderr)

    print("\nVérification des spots clés :", file=sys.stderr)
    slugs = {p["slug"] for p in peaks}
    key_spots = [
        "mont-blanc",
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
