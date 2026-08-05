"""Redakcija osobnih podataka — pravno nosivi sloj.

Zašto ovaj modul postoji
------------------------
Phase 0 recon (docs/source-notes.md, §3) pokazao je da službeni CSV export
FINA Očevidnika **sadrži osobne podatke** u slobodnim tekstualnim poljima:

    222 OIB-a · 728 IBAN-a · 1 136 e-mail adresa · 2 505 telefonskih brojeva

Oblik retka koji se stvarno pojavljuje (vrijednosti maskirane — ni ovaj
docstring ne smije biti mjesto kroz koje osobni podatak procuri):
    "Založni vjerovnik - [Ime Prezime], OIB: [11 znamenki], iz [Grad], [Ulica]"

Očevidnik štiti identitet dužnika u svom *sučelju*, ali slobodna polja koja
unose sudovi i stečajni upravitelji sadrže imena, OIB-e, kućne adrese,
privatne e-mailove i mobitele trećih osoba (vjerovnika, upravitelja,
ovršitelja, bilježnika).

Zato ovaj modul radi po načelu **whitelist, ne blacklist**:
u bazu ulaze samo izrijekom dopuštena polja, i ona prolaze kroz redakciju.

Isti detektori koje ovdje koristimo koristi i `validate.py` (provjera br. 4)
kao tvrdi prekid — dakle redakcija i provjera ne mogu se razići.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable

# ---------------------------------------------------------------------------
# 1. Whitelist: koja izvorna polja uopće smiju dalje
# ---------------------------------------------------------------------------

PUBLISHABLE = {
    "Nadležno tijelo",            # institucija; imena bilježnika se uklanjaju
    "Poslovni broj spisa",
    "Opis",                       # redigira se — jedini izvor lokacije i površine
    "Vrsta predmeta prodaje",
    "Složenost PP / opseg imovine",
    "Utvrđena vrijednost",
    "Način prodaje",
    "ID nadmetanja",
    "Oznaka EJD",
    "Datum odluke o prodaji",
    "Datum i vrijeme početka",
    "Datum i vrijeme početka nadmetanja",
    "Datum i vrijeme završetka nadmetanja",
    "Mogućnost produljenja nadmetanja (za dodatnih 10 minuta)",
    "Minimalna zakonska cijena ispod koje se predmet prodaje ne može prodati",
    "Početna cijena za nadmetanje",
    "Iznos dražbenog koraka",
    "Iznos jamčevine",
    "Stanje na dan",
    "Datum valute jamčevine",
}

# Polja koja se odbacuju, s razlogom. Razlog se ispisuje u izvještaju —
# ne skriva se iza postotka.
DROPPED = {
    "Napomena uz detalje predmeta prodaje":
        "54 OIB-a, 68 IBAN-a, kontakti upravitelja; nije nužno za proizvod",
    "Ostali uvjeti prodaje":
        "OIB-i, IBAN-i, privatni e-mailovi i telefoni",
    "Ostali uvjeti za jamčevinu":
        "292 IBAN-a (računi stečajnih masa i fizičkih osoba)",
    "Napomena uz uvjete prodaje":
        "68 OIB-a, 152 IBAN-a, imena založnih vjerovnika s adresom stanovanja",
    "Rok u kojem je kupac dužan položiti kupovninu":
        "47 IBAN-a; pravni rok se izvodi zasebno bez broja računa",
    "Razgledavanje":
        "1 074 e-mailova i 2 480 telefona osobnih kontakata; "
        "zadržava se samo izvedeni obrazac termina, bez kontakt-podataka",
}

# ---------------------------------------------------------------------------
# 2. Detektori. Dijele se s validate.py — jedna definicija istine.
# ---------------------------------------------------------------------------

PATTERNS: dict[str, re.Pattern[str]] = {
    # OIB je 11 znamenki. Traži se i s oznakom i samostalno.
    "oib_labelled": re.compile(r"\bOIB[\s:.\-]*\d{11}\b", re.IGNORECASE),
    "oib_bare": re.compile(r"(?<![\d.,/])\d{11}(?![\d.,/])"),
    # Hrvatski IBAN: HR + 19 znamenki, s mogućim razmacima.
    "iban": re.compile(r"\bHR\s?\d{2}(?:[\s\-]?\d{4}){4}[\s\-]?\d{1,3}\b", re.IGNORECASE),
    "email": re.compile(r"\b[\w.+\-]+@[\w\-]+\.[A-Za-z]{2,}\b"),
    # Mobiteli 09x i međunarodni +385. Ne dira katastarske oznake (npr. 3437/102).
    "phone_mobile": re.compile(r"(?<!\d)09\d[\s\-/.]?\d{3}[\s\-/.]?\d{3,4}(?!\d)"),
    "phone_intl": re.compile(r"\+385[\s\-/.]?\d[\d\s\-/.]{6,12}\d"),
    # Telefon naveden uz oznaku (hvata i fiksne brojeve tipa 047/819-146).
    "phone_labelled": re.compile(
        r"\b(?:tel|telefon|mob|mobitel|kontakt|gsm)[\s.:]*\+?[\d][\d\s\-/.()]{5,}\d",
        re.IGNORECASE,
    ),
}

# Uloge iza kojih u izvoru redovito slijedi ime fizičke osobe.
#
# Ključno: prve dvije skupine (ovršenik, dužnik) su OSOBA NAD KOJOM SE PROVODI
# OVRHA. Očevidnik štiti njezin identitet i mi ga moramo štititi jednako.
# Recon je pokazao stvarne retke oblika
#     "Nekretnine ovršenika [Ime Prezime] iz [Grad], [Ulica i kbr.]"
# — ime + mjesto + kućna adresa dužnika. To ne smije nikamo dalje.
ROLE_WORDS = (
    # dužnik / ovršenik — najosjetljivije
    r"ovršenik\w*",
    r"ovršenic\w*",
    r"stečajn\w*\s+dužnik\w*",
    r"dužnik\w*",
    r"protivnik\w*\s+osiguranja",
    r"prodavatelj\w*",
    # sudionici postupka
    r"stečajn\w*\s+upravitelj\w*",
    r"upravitelj\w*",
    r"upraviteljic\w*",
    r"sudsk\w*\s+ovršitelj\w*",
    r"ovršitelj\w*",
    r"založn\w*\s+vjerovnik\w*",
    r"vjerovnik\w*",
    r"predlagatelj\w*",
    r"javn\w*\s+bilježnik\w*",
    r"bilježnik\w*",
    r"povjerenik\w*",
    r"likvidator\w*",
    # vlasništvo fizičke osobe
    r"vlasnik\w*",
    r"suvlasnik\w*",
    r"vl\.\s*obrta",
    r"vlasnik\w*\s+obrta",
)

# Ime osobe: podržava i "Ivana Horvata" i "IVAN HORVAT" (verzalom).
_TOK_TITLE = r"[A-ZČĆĐŠŽ][a-zčćđšž\-]+"
_TOK_UPPER = r"[A-ZČĆĐŠŽ]{2,}"
_TOK = rf"(?:{_TOK_TITLE}|{_TOK_UPPER})"
_NAME = rf"{_TOK}(?:\s+{_TOK}){{1,2}}"

# Klauzula prebivališta koja u izvoru redovito slijedi ime dužnika:
#   " iz [Grad], [Ulica i kbr.]"
_RESIDENCE = (
    r"(?:\s*,?\s*iz\s+[A-ZČĆĐŠŽ][\wčćđšžČĆĐŠŽ\-]+(?:\s+[A-ZČĆĐŠŽ][\wčćđšž\-]+)?"
    r"(?:\s*,\s*[A-ZČĆĐŠŽ][\wčćđšžČĆĐŠŽ\-\.]*(?:\s+[A-ZČĆĐŠŽa-zčćđšž][\wčćđšž\-\.]*)*"
    r"\s*\d+[a-zA-Z]?)?)?"
)

# VAŽNO: zastavica IGNORECASE smije vrijediti SAMO za nazive uloga.
# Ako se primijeni na cijeli izraz, `[A-ZČĆĐŠŽ]` počne hvatati i mala slova,
# pa `_NAME` proguta veznike ("Ivana Horvata iz") i klauzula prebivališta
# ostane neredigirana. Zato se koristi lokalna zastavica `(?i:...)`.
_ROLE_ALT = "(?i:" + "|".join(ROLE_WORDS) + ")"

# Oblik 1: ULOGA pa IME  ("ovršenika Ivana Horvata iz [Grad], ...")
ROLE_NAME_RE = re.compile(
    r"(?P<role>" + _ROLE_ALT + r")"
    r"(?P<sep>[\s:,\-]+(?i:je\s+|gosp\.?\s+|gđa\.?\s+|g\.\s+)?)"
    r"(?P<name>" + _NAME + r")"
    r"(?P<res>" + _RESIDENCE + r")"
)

# Oblik 2: IME pa ULOGA  ("IVAN HORVAT, vl. obrta ...")
NAME_ROLE_RE = re.compile(
    r"(?P<name>" + _NAME + r")"
    r"(?P<sep>\s*,\s*)"
    r"(?P<role>(?i:vl\.\s*obrta|vlasnik\w*\s+obrta|vlasnik\w*|obrtnik\w*))"
)

REDACTION = {
    "oib": "[OIB uklonjen]",
    "iban": "[IBAN uklonjen]",
    "email": "[e-mail uklonjen]",
    "phone": "[telefon uklonjen]",
    "name": "[ime uklonjeno]",
}


def scan(text: str) -> list[tuple[str, str]]:
    """Vrati listu (vrsta_uzorka, pogođeni_tekst) za dani tekst.

    Koristi ga i redakcija i validacija.
    """
    if not text:
        return []
    found: list[tuple[str, str]] = []
    for name, pat in PATTERNS.items():
        for m in pat.finditer(text):
            found.append((name, m.group(0)))
    return found


def redact(text: str) -> tuple[str, list[str]]:
    """Ukloni osobne podatke iz slobodnog teksta.

    Vraća (očišćeni_tekst, popis_vrsta_uklonjenog).
    Redoslijed je bitan: dulji uzorci (IBAN, e-mail) prije kraćih (OIB, telefon),
    inače bi se npr. znamenke IBAN-a djelomično pojele kao OIB.
    """
    if not text:
        return "", []
    removed: list[str] = []
    out = text

    # 1. Imena vezana uz ulogu — prvo, dok je kontekst još netaknut.
    #    Uz ime se uklanja i klauzula prebivališta ("iz [Grad], [Ulica
    #    i kbr.]"), jer adresa stanovanja identificira jednako kao ime.
    def _role_name_sub(m: re.Match[str]) -> str:
        removed.append("person_name")
        if (m.group("res") or "").strip():
            removed.append("person_address")
        return f"{m.group('role')}{m.group('sep')}{REDACTION['name']}"

    out = ROLE_NAME_RE.sub(_role_name_sub, out)

    def _name_role_sub(m: re.Match[str]) -> str:
        removed.append("person_name")
        return f"{REDACTION['name']}{m.group('sep')}{m.group('role')}"

    out = NAME_ROLE_RE.sub(_name_role_sub, out)

    # 2. Strukturirani identifikatori, od najduljeg prema najkraćem.
    for key, token in (
        ("iban", "iban"),
        ("email", "email"),
        ("phone_labelled", "phone"),
        ("phone_intl", "phone"),
        ("phone_mobile", "phone"),
        ("oib_labelled", "oib"),
        ("oib_bare", "oib"),
    ):
        pat = PATTERNS[key]

        def _sub(m: re.Match[str], _k=key, _t=token) -> str:
            removed.append(_k)
            return REDACTION[_t]

        out = pat.sub(_sub, out)

    # 3. Rječnik osobnih imena — hvata imena bez oznake uloge
    #    ("IVAN HORVAT, ...", "Nekretnina Ivana Horvata ...").
    matches = _gazetteer_matches(out)
    for m in reversed(matches):  # unatrag, da se offseti ne pomaknu
        removed.append("person_name_gazetteer")
        out = out[: m.start()] + REDACTION["name"] + out[m.end():]

    # 4. Uredi razmake nastale redakcijom.
    out = re.sub(r"\s{2,}", " ", out).strip()
    out = re.sub(r"[,;]\s*([,;])", r"\1", out)
    return out, removed


# ---------------------------------------------------------------------------
# 3. Nadležno tijelo: institucija, nikad imenovana osoba
# ---------------------------------------------------------------------------

NOTARY_RE = re.compile(r"^\s*javn\w*\s+bilježnik\w*\b", re.IGNORECASE)


def normalise_issuer(value: str) -> tuple[str, str]:
    """Vrati (tip_tijela, naziv_tijela) bez osobnih imena.

    Javni bilježnici u izvoru stoje punim imenom i prezimenom
    (46 različitih osoba na 120 redaka). Ime se uklanja — ostaje uloga.
    """
    v = (value or "").strip()
    if not v:
        return "nepoznato", "Nepoznato tijelo"
    if NOTARY_RE.match(v):
        return "javni_biljeznik", "Javni bilježnik"
    low = _fold(v)
    if "trgovacki sud" in low:
        return "trgovacki_sud", v
    if "opcinski" in low and "sud" in low:
        return "opcinski_sud", v
    if "sud" in low:
        return "sud", v
    if "fina" in low:
        return "fina", v
    return "ostalo", v


def _fold(s: str) -> str:
    """Male slove + makni dijakritiku (samo za usporedbu, nikad za prikaz)."""
    s = s.lower()
    s = s.replace("đ", "d")
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


# ---------------------------------------------------------------------------
# 4. Redakcija cijelog retka
# ---------------------------------------------------------------------------

FREE_TEXT_PUBLISHED = ("Opis",)


def sanitise_row(row: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Primijeni whitelist + redakciju na jedan CSV redak.

    Vraća (čisti_redak, popis_uklonjenih_vrsta).
    """
    clean: dict[str, str] = {}
    removed: list[str] = []

    for key in PUBLISHABLE:
        value = (row.get(key) or "").strip()
        if key in FREE_TEXT_PUBLISHED:
            value, rem = redact(value)
            removed.extend(rem)
        clean[key] = value

    issuer_type, issuer_name = normalise_issuer(clean.get("Nadležno tijelo", ""))
    if issuer_name != clean.get("Nadležno tijelo", ""):
        removed.append("notary_name")
    clean["Nadležno tijelo"] = issuer_name
    clean["_issuer_type"] = issuer_type

    return clean, removed


def viewing_window(raw_viewing: str) -> str:
    """Izvuci SAMO obrazac termina razgledavanja, bez ijednog kontakt-podatka.

    Izvorno polje `Razgledavanje` je minsko polje (1 074 e-mailova,
    2 480 telefona), pa se ne objavljuje. Korisniku je ipak korisno znati
    *kada* se može razgledati, pa se izvlači isključivo vremenski izraz.
    """
    if not raw_viewing:
        return ""
    text = raw_viewing
    # Dan u tjednu + sat, npr. "Svakog četvrtka od 13,00 do 14,00 sati"
    m = re.search(
        r"\b(ponedjelj\w+|utor\w+|srijed\w+|četvrt\w+|petak\w*|petk\w+|subot\w+|nedjelj\w+)"
        r"[^.;\n]{0,60}?(\d{1,2}[.,:]\d{2}|\d{1,2}\s*(?:h|sati))"
        r"[^.;\n]{0,40}?(?:do\s*(\d{1,2}[.,:]\d{2}|\d{1,2}\s*(?:h|sati)))?",
        text,
        re.IGNORECASE,
    )
    if m:
        out = m.group(0).strip(" .,;")
    else:
        m2 = re.search(r"\bpo\s+dogovoru\b", text, re.IGNORECASE)
        out = "Po dogovoru" if m2 else ""
    if not out:
        return ""
    # Dvostruka brava: čak i izvedeni izraz prolazi kroz redakciju.
    out, _ = redact(out)
    return out if not scan(out) else ""


# ---------------------------------------------------------------------------
# 5. Druga linija obrane: rječnik osobnih imena
# ---------------------------------------------------------------------------
#
# Uloga ne stoji uvijek uz ime. Zato se dodatno traži obrazac
# "OsobnoIme Prezime" po rječniku čestih hrvatskih osobnih imena.
#
# Oprez: hrvatske ulice vrlo često nose osobna imena ("Ljudevita Gaja 8" je
# ULICA, ne osoba;
# "Ante Starčevića 12"). Adresa *nekretnine* je korisna i ostaje; briše se
# samo ime koje NIJE u uličnom kontekstu. Zato detektor preskače pogotke
# koji slijede oznaku ulice ili koje slijedi kućni broj.

GIVEN_NAMES = {
    # muška
    "ante", "anto", "boris", "božidar", "branko", "damir", "danijel", "dario",
    "darko", "davor", "denis", "dinko", "domagoj", "dragan", "dražen", "duje",
    "emil", "filip", "franjo", "goran", "hrvoje", "igor", "ilija", "ivan",
    "ivica", "jakov", "josip", "jozo", "jure", "karlo", "krešimir", "ladislav",
    "lovro", "luka", "marin", "marijan", "mario", "marko", "martin", "mate",
    "matej", "mihael", "milan", "mirko", "miroslav", "mladen", "nenad",
    "neven", "nikola", "ozren", "pavao", "petar", "predrag", "rade", "ranko",
    "robert", "roko", "sanjin", "saša", "silvio", "siniša", "slaven", "slavko",
    "srećko", "stanko", "stipe", "stjepan", "tihomir", "tomislav", "toni",
    "vedran", "velimir", "vinko", "vjekoslav", "vladimir", "vlado", "zdravko",
    "zlatko", "zoran", "zvonimir", "željko", "berislav", "borna", "bruno",
    "dalibor", "dean", "dejan", "drago", "edo", "fabijan", "gordan", "ivo",
    "krunoslav", "leon", "matko", "miljenko", "nikša", "patrik", "ratko",
    "sven", "tin", "viktor", "zdenko",
    # ženska
    "ana", "andreja", "anita", "antonija", "barbara", "biljana", "blanka",
    "bojana", "branka", "dubravka", "đurđica", "gordana", "helena", "ines",
    "irena", "iva", "ivana", "ivanka", "jadranka", "jasna", "jelena", "karmen",
    "katarina", "klara", "kristina", "lana", "lidija", "ljiljana", "maja",
    "mara", "marija", "marina", "marta", "martina", "melanija", "melita",
    "mia", "mirjana", "nada", "nadija", "nataša", "nevenka", "nikolina",
    "nina", "olga", "petra", "ranka", "renata", "ruža", "sanja", "sandra",
    "silvana", "slavica", "snježana", "sonja", "suzana", "tanja", "tatjana",
    "tea", "tihana", "valentina", "vanja", "vesna", "vlatka", "zdenka",
    "zrinka", "željka", "dijana", "danica", "verica", "zorica", "milka",
}

# Nastavci hrvatske deklinacije osobnih imena (Mladen -> Mladena, Marku, ...).
_INFLECT = r"(?:om|em|ova|eva|inu|in|a|u|e|i|o)?"

_STREET_MARKER = re.compile(
    r"\b(?:ulic\w*|ul\.|trg\w*|put\b|puta\b|avenij\w*|obala\b|obali\b|"
    r"šetališt\w*|cest\w*|odvojak|naselj\w*|kbr\.?|k\.?br\.?)\s*$",
    re.IGNORECASE,
)


def _gazetteer_matches(text: str) -> list[re.Match[str]]:
    """Pronađi "Ime Prezime" po rječniku, preskačući ulične kontekste."""
    out: list[re.Match[str]] = []
    if not text:
        return out
    pat = re.compile(
        rf"\b({_TOK})\s+({_TOK})(?:\s+({_TOK}))?", re.UNICODE
    )
    for m in pat.finditer(text):
        first = _fold(m.group(1))
        base = re.sub(_INFLECT + r"$", "", first) or first
        if first not in GIVEN_NAMES and base not in GIVEN_NAMES:
            continue
        # ulični kontekst prije imena?
        if _STREET_MARKER.search(text[max(0, m.start() - 24): m.start()]):
            continue
        # kućni broj odmah iza -> gotovo sigurno adresa, ne osoba
        if re.match(r"\s*\d+\s*[a-zA-Z]?\b", text[m.end(): m.end() + 6]):
            continue
        # tvrtka -> pravna osoba, nije osobni podatak
        if re.match(r"\s*(?:d\.o\.o|j\.d\.o\.o|d\.d|obrt|k\.d)\b", text[m.end(): m.end() + 10],
                    re.IGNORECASE):
            continue
        out.append(m)
    return out


def residual_person_names(text: str) -> list[str]:
    """Imena koja su preživjela redakciju — za pošteno izvještavanje."""
    return [m.group(0) for m in _gazetteer_matches(text)]


def summarise_removals(all_removed: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in all_removed:
        counts[r] = counts.get(r, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
