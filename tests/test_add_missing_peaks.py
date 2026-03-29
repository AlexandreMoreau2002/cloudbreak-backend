from scripts.add_missing_peaks import make_id, slugify


def test_slugify_strips_accents_and_symbols() -> None:
    assert slugify("Colline de Fourvière") == "colline-de-fourviere"
    assert slugify("Mont Saint-Clair") == "mont-saint-clair"


def test_make_id_is_stable() -> None:
    assert make_id("la-bastille") == make_id("la-bastille")
