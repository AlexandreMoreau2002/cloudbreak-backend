import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "peak_region_enrichment.py"


def load_module():
    spec = importlib.util.spec_from_file_location("peak_region_enrichment_test", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_resolve_from_rules_handles_manual_override() -> None:
    module = load_module()

    region, source = module.resolve_from_rules(
        {
            "slug": "moucherotte",
            "lat": 45.16,
            "lng": 5.64,
            "altitude": 1901,
        }
    )

    assert region == "Massif du Vercors"
    assert source == "manual"


def test_extract_region_from_nominatim_prefers_city_for_low_altitude_peak() -> None:
    module = load_module()

    region = module.extract_region_from_nominatim(
        {"altitude": 400},
        {"address": {"city": "Grenoble", "county": "Isere"}},
    )

    assert region == "Grenoble"
