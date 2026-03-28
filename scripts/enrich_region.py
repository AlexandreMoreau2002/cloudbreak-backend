"""
Enrichit app/db/peaks_data.json avec le champ region sans relancer generate_peaks.py.

Le script applique d'abord des règles locales rapides :
  1. overrides manuels pour les spots critiques
  2. boîtes englobantes pour les villes / massifs principaux

En option, il peut appeler Nominatim en dernier recours pour les entrées restantes.
Le fichier source est sauvegardé avant écriture dans .tmp/peaks_data_backup.json.

Usage :
    python scripts/enrich_region.py
    python scripts/enrich_region.py --use-nominatim
    python scripts/enrich_region.py --dry-run
"""

from __future__ import annotations

import json
import shutil
import argparse
from typing import Any
from pathlib import Path
from peak_region_enrichment import enrich_peaks

ROOT_DIR = Path(__file__).resolve().parent.parent
INPUT_FILE = ROOT_DIR / "app" / "db" / "peaks_data.json"
BACKUP_FILE = ROOT_DIR / ".tmp" / "peaks_data_backup.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT_FILE)
    parser.add_argument("--backup", type=Path, default=BACKUP_FILE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--use-nominatim", action="store_true")
    parser.add_argument(
        "--nominatim-limit",
        type=int,
        default=None,
        help="limite le nombre d'appels Nominatim pour les dry-runs",
    )
    parser.add_argument(
        "--overwrite-existing",
        action="store_true",
        help="recalcule aussi les regions deja presentes",
    )
    return parser.parse_args()


def load_peaks(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_backup(source: Path, backup: Path) -> None:
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup)


def save_peaks(path: Path, peaks: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(peaks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    peaks = load_peaks(args.input)
    enriched_peaks, stats = enrich_peaks(
        peaks,
        overwrite_existing=args.overwrite_existing,
        use_nominatim=args.use_nominatim,
        nominatim_limit=args.nominatim_limit,
    )

    resolved_count = sum(1 for peak in enriched_peaks if peak.get("region"))
    total = len(enriched_peaks)

    print(f"Peaks enrichis: {resolved_count}/{total} ({resolved_count / total:.1%})")
    for key, value in stats.items():
        print(f"  - {key}: {value}")

    if args.dry_run:
        return

    write_backup(args.input, args.backup)
    save_peaks(args.input, enriched_peaks)
    print(f"Backup ecrit dans {args.backup}")
    print(f"Fichier mis a jour: {args.input}")


if __name__ == "__main__":
    main()
