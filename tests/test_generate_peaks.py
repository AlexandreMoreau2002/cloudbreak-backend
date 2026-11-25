import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "generate_peaks.py"
SCRIPTS_DIR = SCRIPT_PATH.parent


def load_module():
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        spec = importlib.util.spec_from_file_location("generate_peaks_test", SCRIPT_PATH)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path = [path for path in sys.path if path != str(SCRIPTS_DIR)]


def test_slugify_normalizes_accents_and_spaces() -> None:
    module = load_module()

    assert module.slugify("Mont Saint-Clair") == "mont-saint-clair"
    assert module.slugify("Butte Montmartre — Sacré-Cœur") == "butte-montmartre-sacre-coeur"


def test_make_id_is_deterministic() -> None:
    module = load_module()

    assert module.make_id("moucherotte") == module.make_id("moucherotte")
