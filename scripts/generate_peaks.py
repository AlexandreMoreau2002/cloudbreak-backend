"""
Génère la liste PEAKS pour seed.py via Overpass API (OpenStreetMap).

Stratégie : une seule requête sur toute la France métropolitaine,
filtrage par altitude minimale (500m) pour exclure les collines.

Usage :
    python scripts/generate_peaks.py > /tmp/peaks_block.py
    # Puis remplacer PEAKS = [...] dans app/db/seed.py

Prérequis :
    pip install httpx  (déjà dans requirements)
"""

import re
import sys
import uuid
import httpx
import unicodedata
from typing import Any

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Altitude minimale — exclut les collines sans intérêt pour la mer de nuage
MIN_ALTITUDE = 500

# France métropolitaine bounding box
FRANCE_BBOX = (41.3, -5.2, 51.1, 9.6)

# Sommets obligatoires (ACs story 3.2)
REQUIRED_SLUGS = {"col-de-la-croix-fry", "mont-blanc", "champ-du-feu"}


def slugify(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^\w\s-]", "", ascii_str.lower())
    slug = re.sub(r"[-\s]+", "-", slug).strip("-")
    return slug


def query_france() -> list[dict[str, Any]]:
    south, west, north, east = FRANCE_BBOX
    # Une seule requête couvrant toute la France — évite le rate-limit
    query = f"""
[out:json][timeout:90];
node["natural"="peak"]["name"]["ele"]({south},{west},{north},{east});
out body;
"""
    print("  Interrogation Overpass API — France entière...", file=sys.stderr)
    response = httpx.post(OVERPASS_URL, data={"data": query}, timeout=100)
    response.raise_for_status()
    elements = response.json().get("elements", [])
    print(f"  → {len(elements)} nœuds OSM reçus", file=sys.stderr)

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

        if altitude < MIN_ALTITUDE:
            continue

        peaks.append(
            {
                "name": name,
                "slug": slugify(name),
                "lat": round(el["lat"], 6),
                "lng": round(el["lon"], 6),
                "altitude": altitude,
            }
        )

    return peaks


def deduplicate(peaks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Garde le sommet le plus haut en cas de slug identique."""
    by_slug: dict[str, dict[str, Any]] = {}
    for p in peaks:
        slug = p["slug"]
        if slug not in by_slug or p["altitude"] > by_slug[slug]["altitude"]:
            by_slug[slug] = p
    return sorted(by_slug.values(), key=lambda p: -p["altitude"])


def main() -> None:
    try:
        raw = query_france()
    except Exception as e:
        print(f"❌ Erreur Overpass : {e}", file=sys.stderr)
        sys.exit(1)

    peaks = deduplicate(raw)
    print(f"  → {len(peaks)} sommets uniques après dédoublonnage\n", file=sys.stderr)

    # Vérifier les sommets obligatoires
    found_slugs = {p["slug"] for p in peaks}
    for required in REQUIRED_SLUGS:
        status = "✅" if required in found_slugs else "⚠️  MANQUANT"
        print(f"  {status} {required}", file=sys.stderr)

    # Générer le bloc Python
    print("PEAKS = [")
    for i, p in enumerate(peaks):
        uid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"cloudbreak:peak:{p['slug']}"))
        comma = "," if i < len(peaks) - 1 else ""
        print("    {")
        print(f'        "id": "{uid}",')
        print(f'        "name": "{p["name"]}",')
        print(f'        "slug": "{p["slug"]}",')
        print(f'        "lat": {p["lat"]},')
        print(f'        "lng": {p["lng"]},')
        print(f'        "altitude": {p["altitude"]},')
        print(f"    }}{comma}")
    print("]")
    print(f"\n# {len(peaks)} sommets générés via Overpass API (OSM)", file=sys.stderr)


if __name__ == "__main__":
    main()
