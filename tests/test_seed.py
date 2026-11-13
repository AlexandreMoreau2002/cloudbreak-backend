import json

from app.db import seed


def test_load_peaks_reads_json_file(tmp_path, monkeypatch) -> None:
    peaks_file = tmp_path / "peaks.json"
    peaks_file.write_text(
        json.dumps([{"id": "peak-1", "slug": "moucherotte"}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(seed, "PEAKS_FILE", peaks_file)

    assert seed.load_peaks() == [{"id": "peak-1", "slug": "moucherotte"}]


def test_seed_batch_size_is_positive() -> None:
    assert seed.BATCH_SIZE > 0
