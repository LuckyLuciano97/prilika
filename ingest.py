"""Preuzimanje i čitanje službenog CSV exporta FINA Očevidnika.

Ovo je JEDINI put do podataka. Interaktivna tražilica (reCAPTCHA, limit od
100 rezultata) se ne dira — v. docs/source-notes.md §1 i §7.
"""
from __future__ import annotations

import csv
import hashlib
import io
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

import config

CSV_DELIMITER = ";"


class SourceError(RuntimeError):
    """Izvor je odgovorio neočekivano — staje se i prijavljuje, ne pokušava dalje."""


def download(force: bool = False, cache_hours: int = 6) -> tuple[bytes, dict]:
    """Preuzmi CSV export. Vraća (sadržaj, metapodaci).

    Cache postoji da se izvor ne opterećuje bez potrebe. Jedan zahtjev
    dnevno je sasvim dovoljan — export je dnevni snimak.
    """
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    cached = config.RAW_DIR / "ponip_ocevidnik.csv"

    if not force and cached.exists():
        age_h = (datetime.now().timestamp() - cached.stat().st_mtime) / 3600
        if age_h < cache_hours:
            data = cached.read_bytes()
            print(f"  [cache] {cached.name} star {age_h:.1f} h, {len(data):,} B")
            return data, _meta(data, cached, from_cache=True)

    print(f"  [GET] {config.CSV_URL}")
    try:
        resp = requests.get(
            config.CSV_URL,
            headers={"User-Agent": config.USER_AGENT, "Accept": "text/csv,*/*"},
            timeout=config.HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise SourceError(f"Mrežna greška pri dohvatu izvora: {exc}") from exc

    # Halt-and-report: nikakvo zaobilaženje, nikakvo ponavljanje u petlji.
    if resp.status_code in (403, 429, 503):
        raise SourceError(
            f"Izvor je vratio HTTP {resp.status_code}. Pipeline STAJE.\n"
            f"  Ovo se ne zaobilazi. Provjeri ručno: {config.CSV_URL}"
        )
    if resp.status_code != 200:
        raise SourceError(f"Neočekivan HTTP {resp.status_code} s {config.CSV_URL}")

    ctype = resp.headers.get("Content-Type", "")
    if "csv" not in ctype.lower():
        raise SourceError(
            f"Očekivan text/csv, dobiven {ctype!r}. "
            "Izvor je vjerojatno vratio HTML stranicu s greškom."
        )

    data = resp.content
    if len(data) < config.MIN_EXPECTED_BYTES:
        raise SourceError(
            f"Export je sumnjivo malen: {len(data):,} B "
            f"(očekivano ≥ {config.MIN_EXPECTED_BYTES:,} B). Pipeline STAJE."
        )

    cached.write_bytes(data)
    print(f"  [ok] {len(data):,} B -> {cached}")
    return data, _meta(data, cached, from_cache=False)


def _meta(data: bytes, path: Path, from_cache: bool) -> dict:
    return {
        "url": config.CSV_URL,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "path": str(path),
        "from_cache": from_cache,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def parse(data: bytes) -> list[dict[str, str]]:
    """Razdvoji CSV u retke.

    Export je UTF-8 s BOM-om i točkom-zarezom kao separatorom (Phase 0).
    """
    text = data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text), delimiter=CSV_DELIMITER)
    rows = [r for r in reader if any((v or "").strip() for v in r.values())]
    if len(rows) < config.MIN_EXPECTED_ROWS:
        raise SourceError(
            f"Samo {len(rows)} redaka u exportu (očekivano ≥ "
            f"{config.MIN_EXPECTED_ROWS}). Pipeline STAJE."
        )
    return rows


def snapshot_date(rows: list[dict[str, str]]) -> str:
    """`Stanje na dan` je isti za sve retke — to je datum snimka."""
    for r in rows:
        v = (r.get("Stanje na dan") or "").strip()
        if v:
            return v
    return datetime.now().strftime("%Y-%m-%d")


if __name__ == "__main__":
    try:
        blob, meta = download(force="--force" in sys.argv)
        items = parse(blob)
        print(f"redaka: {len(items):,}  stupaca: {len(items[0])}")
        print(f"stanje na dan: {snapshot_date(items)}")
        print(f"sha256: {meta['sha256'][:16]}…")
    except SourceError as exc:
        print(f"GREŠKA: {exc}", file=sys.stderr)
        sys.exit(1)
