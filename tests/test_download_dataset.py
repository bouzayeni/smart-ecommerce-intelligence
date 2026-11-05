import json
import zipfile
from pathlib import Path

import pytest

from data_engineering.scripts import download_dataset as dd
from data_engineering.sources import SOURCE_FILES


def make_zip(path: Path, skip: set[str] = frozenset(), extra: dict[str, str] | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for spec in SOURCE_FILES:
            if spec.filename not in skip:
                # Nested folder, as some Kaggle mirrors produce.
                zf.writestr(f"olist/{spec.filename}", f"col\n{spec.table}\n")
        for name, content in (extra or {}).items():
            zf.writestr(name, content)
    return path


@pytest.fixture
def raw_dir(tmp_path: Path) -> Path:
    return tmp_path / "raw"


def test_extract_writes_all_files_and_manifest(tmp_path, raw_dir):
    archive = make_zip(tmp_path / "a.zip")
    assert dd.main(["--raw-dir", str(raw_dir), "--from-zip", str(archive)]) == 0

    manifest = json.loads((raw_dir / dd.MANIFEST_NAME).read_text())
    assert set(manifest["files"]) == {s.filename for s in SOURCE_FILES}
    for name, meta in manifest["files"].items():
        assert meta["sha256"] == dd.sha256_of(raw_dir / name)


def test_unexpected_and_traversal_entries_are_not_extracted(tmp_path, raw_dir):
    archive = make_zip(
        tmp_path / "a.zip", extra={"../evil.csv": "x", "notes.txt": "x", "../../x.py": "x"}
    )
    assert dd.main(["--raw-dir", str(raw_dir), "--from-zip", str(archive)]) == 0
    assert not (tmp_path / "evil.csv").exists()
    written = {p.name for p in raw_dir.iterdir()}
    assert written == {s.filename for s in SOURCE_FILES} | {dd.MANIFEST_NAME}


def test_second_run_is_noop_when_manifest_matches(tmp_path, raw_dir, caplog):
    archive = make_zip(tmp_path / "a.zip")
    dd.main(["--raw-dir", str(raw_dir), "--from-zip", str(archive)])
    caplog.set_level("INFO")
    assert dd.main(["--raw-dir", str(raw_dir), "--from-zip", str(tmp_path / "missing.zip")]) == 0
    assert "nothing to do" in caplog.text


def test_tampered_file_invalidates_manifest(tmp_path, raw_dir):
    archive = make_zip(tmp_path / "a.zip")
    dd.main(["--raw-dir", str(raw_dir), "--from-zip", str(archive)])
    (raw_dir / SOURCE_FILES[0].filename).write_text("tampered")
    assert not dd.manifest_is_current(raw_dir)


def test_missing_required_file_fails(tmp_path, raw_dir):
    archive = make_zip(tmp_path / "a.zip", skip={"olist_orders_dataset.csv"})
    assert dd.main(["--raw-dir", str(raw_dir), "--from-zip", str(archive)]) == 1
    assert not (raw_dir / dd.MANIFEST_NAME).exists()


def test_missing_optional_file_warns_but_succeeds(tmp_path, raw_dir, caplog):
    archive = make_zip(tmp_path / "a.zip", skip={"olist_geolocation_dataset.csv"})
    assert dd.main(["--raw-dir", str(raw_dir), "--from-zip", str(archive)]) == 0
    assert "Optional file missing: olist_geolocation_dataset.csv" in caplog.text


def test_non_zip_payload_fails_cleanly(tmp_path, raw_dir):
    fake = tmp_path / "login.html"
    fake.write_text("<html>Please sign in</html>")
    assert dd.main(["--raw-dir", str(raw_dir), "--from-zip", str(fake)]) == 1
