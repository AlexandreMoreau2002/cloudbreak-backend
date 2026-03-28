"""
Tests de qualité des données peaks_data.json.

Vérifie que :
  - Le fichier existe et contient un minimum de sommets
  - Les spots sensibles (urbains, volcans, cols manuels) sont présents
  - Chaque entrée respecte le schéma minimal attendu

Lancer avec : make validate  (ou pytest tests/test_peaks_data.py)
"""

import os
import json
import pytest
from pathlib import Path

_default = Path(__file__).parent.parent / "app" / "db" / "peaks_data.json"
PEAKS_FILE = Path(os.environ.get("PEAKS_FILE", _default))

# Seuil minimum acceptable — en dessous = régression de génération
MIN_PEAK_COUNT = 20_000

# Slugs obligatoires — spots sensibles qui doivent toujours être présents
# Classés par catégorie pour des messages d'erreur lisibles
REQUIRED_SLUGS: dict[str, list[str]] = {
    "Sommets majeurs": [
        "mont-blanc",
        "puy-de-dome",  # natural=volcano dans OSM — pas natural=peak
        "grand-ballon",
        "champ-du-feu",
    ],
    "Cols manuels": [
        "col-de-la-croix-fry",
    ],
    "Viewpoints urbains": [
        "la-bastille",  # Grenoble, 476m
        "colline-de-fourviere",  # Lyon, 295m
        "mont-saint-clair",  # Sète, 176m
        "butte-montmartre",  # Paris, 130m
        "sacre-coeur",  # Paris Montmartre, 130m — spot naturel n°1 Paris
        "colline-du-chateau",  # Nice, 92m
    ],
}

EXPECTED_REGIONS: dict[str, str] = {
    "mont-blanc": "Massif du Mont-Blanc",
    "moucherotte": "Massif du Vercors",
    "la-bastille": "Grenoble",
}


@pytest.fixture(scope="module")
def peaks() -> list[dict]:
    assert PEAKS_FILE.exists(), f"peaks_data.json introuvable : {PEAKS_FILE}"
    with PEAKS_FILE.open(encoding="utf-8") as f:
        data: list[dict] = json.load(f)
    return data


@pytest.fixture(scope="module")
def slugs(peaks: list[dict]) -> set[str]:
    return {p["slug"] for p in peaks}


def test_minimum_count(peaks: list[dict]) -> None:
    """Le fichier doit contenir au moins MIN_PEAK_COUNT entrées."""
    assert len(peaks) >= MIN_PEAK_COUNT, (
        f"Seulement {len(peaks)} sommets — seuil minimum : {MIN_PEAK_COUNT}. "
        "Relancer generate_peaks.py (possible rate-limit Open-Meteo)."
    )


@pytest.mark.parametrize("category,slug_list", REQUIRED_SLUGS.items())
def test_required_slugs_by_category(category: str, slug_list: list[str], slugs: set[str]) -> None:
    """Chaque slug sensible doit être présent dans le fichier généré."""
    missing = [s for s in slug_list if s not in slugs]
    assert not missing, (
        f"[{category}] slugs manquants : {missing}. "
        "Vérifier MANUAL_ENTRIES ou la requête Overpass."
    )


def test_schema(peaks: list[dict]) -> None:
    """Chaque entrée doit avoir les champs obligatoires avec les bons types."""
    required_fields = {"id", "name", "slug", "lat", "lng", "altitude", "region"}
    errors: list[str] = []

    for p in peaks[:500]:  # échantillon — pas besoin de tout vérifier
        missing = required_fields - p.keys()
        if missing:
            errors.append(f"{p.get('slug', '?')} — champs manquants : {missing}")
            continue
        if not isinstance(p["altitude"], int):
            errors.append(f"{p['slug']} — altitude doit être int, got {type(p['altitude'])}")
        if not isinstance(p["lat"], float):
            errors.append(f"{p['slug']} — lat doit être float")
        if not isinstance(p["lng"], float):
            errors.append(f"{p['slug']} — lng doit être float")
        if p["region"] is not None and not isinstance(p["region"], str):
            errors.append(f"{p['slug']} — region doit être str | null")

    assert not errors, f"{len(errors)} erreurs de schéma :\n" + "\n".join(errors[:10])


def test_no_duplicate_slugs(peaks: list[dict]) -> None:
    """Pas de doublons de slug — la déduplication doit avoir fonctionné."""
    all_slugs = [p["slug"] for p in peaks]
    duplicates = [s for s in set(all_slugs) if all_slugs.count(s) > 1]
    assert not duplicates, f"Slugs en doublon : {duplicates[:10]}"


def test_expected_regions(peaks: list[dict]) -> None:
    """Les sommets de référence doivent avoir la bonne région."""
    by_slug = {peak["slug"]: peak for peak in peaks}
    for slug, expected_region in EXPECTED_REGIONS.items():
        assert by_slug[slug]["region"] == expected_region


def test_region_coverage(peaks: list[dict]) -> None:
    """La majorité du dataset doit être enrichie avec une region non nulle."""
    enriched = sum(1 for peak in peaks if peak.get("region"))
    assert enriched / len(peaks) >= 0.8, "Moins de 80% des peaks ont une region"
