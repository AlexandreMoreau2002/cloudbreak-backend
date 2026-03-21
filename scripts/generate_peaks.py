"""
Génère la liste PEAKS pour seed.py via Overpass API (OpenStreetMap).

Usage :
    python scripts/generate_peaks.py

Prérequis :
    pip install httpx  (déjà dans requirements)

Résultat : affiche le bloc PEAKS prêt à coller dans app/db/seed.py
"""

import re
import sys
import time
import uuid
import httpx
import unicodedata
from typing import Any

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Zones géographiques prioritaires pour la mer de nuage
REGIONS = [
    {
        "name": "Alpes françaises (Nord)",
        "bbox": (45.5, 5.5, 46.5, 7.5),
        "min_alt": 800,
    },
    {
        "name": "Alpes françaises (Sud)",
        "bbox": (44.0, 5.5, 45.5, 7.5),
        "min_alt": 800,
    },
    {
        "name": "Vosges",
        "bbox": (47.7, 6.6, 48.8, 7.4),
        "min_alt": 700,
    },
    {
        "name": "Massif Central",
        "bbox": (44.5, 2.3, 46.2, 4.5),
        "min_alt": 700,
    },
    {
        "name": "Jura",
        "bbox": (46.0, 5.4, 47.5, 6.5),
        "min_alt": 700,
    },
    {
        "name": "Pyrénées françaises",
        "bbox": (42.4, -2.0, 43.5, 3.3),
        "min_alt": 1500,
    },
]

# Sommets obligatoires (ACs story 3.2)
REQUIRED_SLUGS = {"col-de-la-croix-fry", "mont-blanc", "champ-du-feu"}


def slugify(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^\w\s-]", "", ascii_str.lower())
    slug = re.sub(r"[-\s]+", "-", slug).strip("-")
    return slug


def query_region(bbox: tuple[float, float, float, float], min_alt: int) -> list[dict[str, Any]]:
    south, west, north, east = bbox
    query = f"""
[out:json][timeout:30];
node["natural"="peak"]["name"]["ele"]({south},{west},{north},{east});
out body;
"""
    response = httpx.post(OVERPASS_URL, data={"data": query}, timeout=40)
    response.raise_for_status()
    elements = response.json().get("elements", [])

    peaks = []
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name:fr") or tags.get("name", "")
        ele_str = tags.get("ele", "")

        if not name or not ele_str:
            continue

        try:
            altitude = int(float(ele_str))
        except ValueError:
            continue

        if altitude < min_alt:
            continue

        peaks.append(
            {
                "name": name,
                "slug": slugify(name),
                "lat": round(el["lat"], 6),
                "lng": round(el["lon"], 6),
                "altitude": altitude,
                "osm_id": el["id"],
            }
        )

    return peaks


def main() -> None:
    all_peaks: dict[str, dict[str, Any]] = {}

    for region in REGIONS:
        print(f"  Interrogation : {region['name']}...", file=sys.stderr)
        try:
            peaks = query_region(region["bbox"], region["min_alt"])
            for p in peaks:
                slug = p["slug"]
                # Garder le sommet le plus haut si doublon de slug
                if slug not in all_peaks or p["altitude"] > all_peaks[slug]["altitude"]:
                    all_peaks[slug] = p
            print(f"    → {len(peaks)} sommets trouvés", file=sys.stderr)
        except Exception as e:
            print(f"    ⚠️  Erreur : {e}", file=sys.stderr)
        time.sleep(1)  # Respect rate-limit Overpass

    # Trier par altitude décroissante
    sorted_peaks = sorted(all_peaks.values(), key=lambda p: -p["altitude"])

    print(f"\nTotal : {len(sorted_peaks)} sommets uniques\n", file=sys.stderr)

    # Vérifier les sommets obligatoires
    found_slugs = {p["slug"] for p in sorted_peaks}
    for required in REQUIRED_SLUGS:
        if required not in found_slugs:
            print(f"⚠️  Sommet obligatoire manquant : {required}", file=sys.stderr)

    # Générer le bloc Python
    print("PEAKS = [")
    for i, p in enumerate(sorted_peaks):
        uid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"cloudbreak:peak:{p['slug']}"))
        print("    {")
        print(f'        "id": "{uid}",')
        print(f'        "name": "{p["name"]}",')
        print(f'        "slug": "{p["slug"]}",')
        print(f'        "lat": {p["lat"]},')
        print(f'        "lng": {p["lng"]},')
        print(f'        "altitude": {p["altitude"]},')
        print(f'    }}{"," if i < len(sorted_peaks) - 1 else ""}')
    print("]")
    print(f"\n# {len(sorted_peaks)} sommets générés via Overpass API (OSM)", file=sys.stderr)


if __name__ == "__main__":
    main()
