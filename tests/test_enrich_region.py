import importlib.util
import json
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "enrich_region.py"
SCRIPTS_DIR = SCRIPT_PATH.parent


def load_module():
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        spec = importlib.util.spec_from_file_location("enrich_region_test", SCRIPT_PATH)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path = [path for path in sys.path if path != str(SCRIPTS_DIR)]


def test_load_and_save_peaks_round_trip(tmp_path) -> None:
    module = load_module()
    path = tmp_path / "peaks.json"
    peaks = [{"slug": "moucherotte", "region": "Massif du Vercors"}]

    module.save_peaks(path, peaks)

    assert module.load_peaks(path) == peaks


def test_write_backup_copies_source_file(tmp_path) -> None:
    module = load_module()
    source = tmp_path / "source.json"
    backup = tmp_path / "backup.json"
    source.write_text(json.dumps([{"slug": "mont-blanc"}]), encoding="utf-8")

    module.write_backup(source, backup)

    assert backup.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
