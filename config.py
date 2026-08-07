"""Središnja konfiguracija za Prilika pipeline.

Sve postavke dolaze iz okoline (.env), s razumnim zadanim vrijednostima.
Nema tajni u kodu.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_dotenv(path: Path | None = None) -> None:
    """Minimalni .env loader — bez vanjskih ovisnosti.

    Postojeće varijable okoline imaju prednost pred .env datotekom.
    Poziva se ODMAH pri uvozu: konstante niže u ovoj datoteci čitaju
    okolinu u trenutku uvoza, pa .env mora biti učitan prije njih —
    inače PRILIKA_SITE_URL iz .env nikad ne bi dospio u canonicale.
    """
    path = path or (ROOT / ".env")
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()

# --- Izvor podataka -------------------------------------------------------
# Službeni CSV export FINA Očevidnika. Potvrđen u Phase 0 (docs/source-notes.md).
CSV_URL = "https://ponip.fina.hr/ocevidnik-web/preuzmi/csv"

# Opisni User-Agent — izvor mora moći vidjeti tko smo i kako nas kontaktirati.
USER_AGENT = (
    "PrilikaBot/1.0 (+https://prilika.net; kontakt: support@nexistudio.dev) "
    "koristi sluzbeni CSV export uz Otvorenu dozvolu"
)

HTTP_TIMEOUT = int(os.environ.get("PRILIKA_HTTP_TIMEOUT", "180"))

# Najveća dopuštena starost snimka pri generiranju stranica.
# Izvor je DNEVNI snimak, pa je sve preko 48 h zastarjelo: prosječno 15
# nadmetanja završi svaki dan (13.8.2026. čak 76), a zastarjela stranica ih
# prikazuje kao otvorena. Radije se ne objavi nego da se laže o rokovima.
MAX_SNAPSHOT_AGE_HOURS = int(os.environ.get("PRILIKA_MAX_SNAPSHOT_AGE_H", "48"))

# Sigurnosna granica: ako export naglo padne ispod ovoga, nešto ne valja.
MIN_EXPECTED_BYTES = int(os.environ.get("PRILIKA_MIN_BYTES", "1_000_000".replace("_", "")))
MIN_EXPECTED_ROWS = int(os.environ.get("PRILIKA_MIN_ROWS", "500"))

# --- Putanje --------------------------------------------------------------
CACHE_DIR = ROOT / "cache"
RAW_DIR = CACHE_DIR / "raw"
SITE_DIR = ROOT / "site"
TEMPLATE_DIR = SITE_DIR / "templates"
OUTPUT_DIR = ROOT / "public"
DOCS_DIR = ROOT / "docs"

# --- Baza -----------------------------------------------------------------
# Postavi u .env; nikad ne commitaj stvarne vrijednosti.
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# --- Sadržaj / SEO --------------------------------------------------------
SITE_URL = os.environ.get("PRILIKA_SITE_URL", "https://prilika.net").rstrip("/")
SITE_NAME = "Prilika"
SITE_TAGLINE = "Nekretnine na dražbi u Hrvatskoj — službeni podaci, na jednom mjestu"
CONTACT_EMAIL = "support@nexistudio.dev"

SOURCE_NAME = "FINA — Očevidnik nekretnina i pokretnina"
SOURCE_URL = "https://ponip.fina.hr/ocevidnik-web/pocetna"
SOURCE_LICENCE = "Otvorena dozvola (OD)"
SOURCE_LICENCE_URL = "http://data.gov.hr/otvorena-dozvola"

# Prag iz Zakona: očevidnik pokriva imovinu procijenjenu iznad ovog iznosa.
VALUE_THRESHOLD_EUR = 6630.00


def database_url() -> str:
    """Vrati DATABASE_URL ili objasni točno što nedostaje."""
    load_dotenv()
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise SystemExit(
            "GREŠKA: DATABASE_URL nije postavljen.\n"
            "  Kopiraj .env.example u .env i upiši podatke za PostgreSQL, npr.\n"
            "  DATABASE_URL=postgresql://postgres:LOZINKA@localhost:5432/licita\n"
        )
    return url
