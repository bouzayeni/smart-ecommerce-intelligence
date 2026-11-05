"""Download the Olist dataset from Kaggle into data/raw and write a SHA-256 manifest.

Idempotent: if every file listed in the manifest is present with a matching hash, nothing
is downloaded. Source files are never modified after extraction.

Usage (from the repo root):
    uv run python -m data_engineering.scripts.download_dataset
    uv run python -m data_engineering.scripts.download_dataset --from-zip path/to/archive.zip
    uv run python -m data_engineering.scripts.download_dataset --force
"""

import argparse
import hashlib
import json
import logging
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from data_engineering.config import get_settings
from data_engineering.sources import KAGGLE_DOWNLOAD_URL, SOURCE_FILES, missing_files

log = logging.getLogger("download_dataset")

MANIFEST_NAME = "_manifest.json"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, dest: Path) -> None:
    if not url.startswith("https://"):  # no file:// or other schemes
        raise ValueError(f"Refusing non-HTTPS download URL: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "smart-ecommerce-intelligence"})
    with urllib.request.urlopen(request, timeout=120) as response, dest.open("wb") as fh:  # nosec B310
        shutil.copyfileobj(response, fh, length=1 << 20)


def extract_expected(zip_path: Path, raw_dir: Path) -> list[str]:
    """Extract only known source CSVs, flattened into raw_dir.

    Members are matched by basename and written to a fixed path, so archive entries
    such as "../x.csv" or unexpected files can never be written outside raw_dir.
    """
    wanted = {s.filename for s in SOURCE_FILES}
    extracted = []
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = Path(info.filename).name
            if info.is_dir() or name not in wanted or name in extracted:
                continue
            with zf.open(info) as src, (raw_dir / name).open("wb") as dst:
                shutil.copyfileobj(src, dst, length=1 << 20)
            extracted.append(name)
    return extracted


def build_manifest(raw_dir: Path, source: str) -> dict:
    files = {}
    for spec in SOURCE_FILES:
        path = raw_dir / spec.filename
        if path.is_file():
            files[spec.filename] = {"sha256": sha256_of(path), "bytes": path.stat().st_size}
    return {
        "source": source,
        "downloaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "files": files,
    }


def manifest_is_current(raw_dir: Path) -> bool:
    manifest_path = raw_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        return False
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files", {})
    if not files or missing_files(raw_dir)[0]:
        return False
    return all(
        (raw_dir / name).is_file() and sha256_of(raw_dir / name) == meta["sha256"]
        for name, meta in files.items()
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=get_settings().raw_dir)
    parser.add_argument("--from-zip", type=Path, help="use a local archive instead of Kaggle")
    parser.add_argument("--url", default=KAGGLE_DOWNLOAD_URL)
    parser.add_argument("--force", action="store_true", help="re-extract even if up to date")
    args = parser.parse_args(argv)

    raw_dir: Path = args.raw_dir
    raw_dir.mkdir(parents=True, exist_ok=True)

    if not args.force and manifest_is_current(raw_dir):
        log.info("Raw data in %s matches manifest; nothing to do (use --force to redo).", raw_dir)
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        if args.from_zip:
            zip_path, source = args.from_zip, f"local:{args.from_zip.name}"
        else:
            zip_path, source = Path(tmp) / "olist.zip", args.url
            log.info("Downloading %s ...", args.url)
            try:
                download(args.url, zip_path)
            except OSError as exc:
                log.error("Download failed: %s", exc)
                log.error("Download the archive manually from Kaggle and re-run with --from-zip.")
                return 1

        if not zipfile.is_zipfile(zip_path):
            # Kaggle returns an HTML/JSON error body when anonymous access is refused.
            log.error("%s is not a zip archive; Kaggle may require login.", zip_path)
            log.error("Download the archive manually from Kaggle and re-run with --from-zip.")
            return 1

        extracted = extract_expected(zip_path, raw_dir)
        log.info("Extracted %d file(s): %s", len(extracted), ", ".join(sorted(extracted)))

    missing_required, missing_optional = missing_files(raw_dir)
    for name in missing_optional:
        log.warning("Optional file missing: %s (dependent features will be disabled)", name)
    if missing_required:
        log.error("Required file(s) missing: %s", ", ".join(missing_required))
        return 1

    manifest = build_manifest(raw_dir, source)
    (raw_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log.info("Wrote %s with %d file hashes.", raw_dir / MANIFEST_NAME, len(manifest["files"]))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
