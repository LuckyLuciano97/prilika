"""Generator statičkog sadržaja — SEO površina projekta.

Gradi:
  * stranicu po aktivnom predmetu prodaje  /nekretnine/{zupanija}/{grad}/{slug}/
  * stranicu po županiji i po gradu
  * kategorijske stranice (vrsta nekretnine, popusti, najjeftinije, uskoro)
  * blog s podacima izvedenim člancima
  * sitemap.xml i robots.txt

Sve je statički HTML bez ijednog vanjskog zahtjeva — brzo se učitava i
jeftino hosta.
"""
from __future__ import annotations

import json
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, select_autoescape

import config
import croatia
from normalise import (PROPERTY_TYPE_CATEGORY, PROPERTY_TYPE_LABELS,
                       STATUS_LABELS, slugify)

PROCEDURE_LABELS = {
    "ovrha": "Ovrha",
    "stecaj": "Stečaj",
    "osiguranje": "Osiguranje",
    "insolvencija": "Insolvencijski postupak",
    "ostalo": "Ostalo",
}

# Predmeti koji još nisu završeni dobivaju vlastitu stranicu.
# Završene dražbe ostaju u bazi zbog povijesti cijena, ali NE dobivaju
# stranicu — 8 600 stranica o dražbama iz 2016. je tanak sadržaj koji
# tražilice kažnjavaju, a korisniku ne koristi.
ACTIVE_STATUSES = ("najavljeno", "u_tijeku", "bez_termina")

UNKNOWN_COUNTY_SLUG = "nepoznata-lokacija"
UNKNOWN_CITY_SLUG = "ostalo"


# ---------------------------------------------------------------------------
# Filteri za predloške
# ---------------------------------------------------------------------------

def f_eur(v) -> str:
    if v is None:
        return "—"
    v = float(v)
    s = f"{v:,.2f}".replace(",", " ").replace(".", ",")
    if s.endswith(",00"):
        s = s[:-3]
    return f"{s} €"


def f_pct(v) -> str:
    return "—" if v is None else f"{float(v):.1f} %".replace(".", ",")


def f_pct_plain(v) -> str:
    return "—" if v is None else f"{float(v):.0f} %"


def f_area(v) -> str:
    if v is None:
        return "—"
    v = float(v)
    s = f"{v:,.0f}".replace(",", " ")
    return f"{s} m²"


def hr_plural(n: int, one: str, few: str, many: str) -> str:
    """Hrvatska sročnost uz broj.

    1, 21, 101      -> jednina        ("1 nekretnina")
    2-4, 22-24      -> paukal         ("3 nekretnine")
    5-20, 25-30 ... -> genitiv množine ("7 nekretnina")

    Bez ovoga stranice pišu "3 nekretnina", što odmah odaje strojni tekst.
    """
    n = abs(int(n))
    last_two = n % 100
    last = n % 10
    if 11 <= last_two <= 14:
        return many
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def f_items(n: int) -> str:
    return f"{n} {hr_plural(n, 'nekretnina', 'nekretnine', 'nekretnina')}"


def f_subjects(n: int) -> str:
    return f"{n} {hr_plural(n, 'predmet', 'predmeta', 'predmeta')}"


def f_days(n: int) -> str:
    return f"još {n} {hr_plural(n, 'dan', 'dana', 'dana')}"


def f_ppm(v) -> str:
    if v is None:
        return "—"
    s = f"{float(v):,.0f}".replace(",", " ")
    return f"{s} €/m²"


def f_dt(v) -> str:
    if not v:
        return "—"
    if isinstance(v, str):
        return v
    return v.strftime("%d.%m.%Y. u %H:%M")


def f_d(v) -> str:
    if not v:
        return "—"
    if isinstance(v, str):
        return v
    return v.strftime("%d.%m.%Y.")


# ---------------------------------------------------------------------------
# URL-ovi
# ---------------------------------------------------------------------------

def county_slug(item) -> str:
    return slugify(item.get("county")) if item.get("county") else UNKNOWN_COUNTY_SLUG


def city_slug(item) -> str:
    return slugify(item.get("city")) if item.get("city") else UNKNOWN_CITY_SLUG


MOVABLE_TYPES = ("pokretnina", "pravo")

# Ručno pisane priče: tijelo u site/content/{file}, brojke vrijede na datum
# objave (data_note kaže iz kojeg snimka dolaze) i namjerno se NE osvježavaju.
STORY_POSTS = [
    {"slug": "varazdinski-stecaj-20-milijuna",
     "h1": "Šesnaest nekretnina, 20 milijuna eura: najveći aktivni stečajni paket",
     "title": "Varaždinski stečaj: 16 nekretnina za 20 milijuna eura | Prilika",
     "meta": ("U jednom stečajnom spisu prodaje se 16 nekretnina ukupne procjene "
              "20,5 milijuna eura — a već zakazani listopadski krug kreće od "
              "četvrtine procjene."),
     "file": "prica-varazdinski-stecaj.html",
     "cover": "/static/covers/stecaj-paket.svg", "published": "2026-08-13",
     "data_note": "brojke iz službenog snimka od 12.8.2026."},
    {"slug": "drazba-udjela-zracna-luka-zagreb",
     "h1": "Na dražbi i udjel u koncesionaru Zračne luke Zagreb",
     "title": "Stečaj prodaje udjel u koncesionaru Zračne luke Zagreb | Prilika",
     "meta": ("Među predmetima jednog stečaja: udjeli u jedinom članu društva "
              "koncesionara zagrebačke zračne luke, procijenjeni na 7 milijuna "
              "eura — i 16 milijuna eura teretnih vozila."),
     "file": "prica-zracna-luka.html",
     "cover": "/static/covers/zracna-luka.svg", "published": "2026-08-13",
     "data_note": "brojke iz službenog snimka od 12.8.2026."},
    {"slug": "nekretnina-od-jednog-eura",
     "h1": "Procjena 10,2 milijuna, početna cijena: jedan euro",
     "title": "Predmet od 10 milijuna eura s početnom cijenom 1 € — što tu piše | Prilika",
     "meta": ("U registru stoji pravo građenja procijenjeno na 10,2 milijuna "
              "eura s početnom cijenom od jednog eura. Zašto takve stavke "
              "označavamo sumnjivima i što zapravo znače."),
     "file": "prica-jedan-euro.html",
     "cover": "/static/covers/jedan-euro.svg", "published": "2026-08-13",
     "data_note": "brojke iz službenog snimka od 12.8.2026."},
    {"slug": "hotel-bellevue-split-na-drazbi",
     "h1": "Dio splitskog hotela Bellevue čeka dražbu",
     "title": "Hotel Bellevue u Splitu: dio zgrade u stečajnoj prodaji | Prilika",
     "meta": ("Dio zgrade povijesnog hotela Bellevue na Prokurativama upisan je "
              "u stečajnu prodaju s procjenom od 9,3 milijuna eura — zasad bez "
              "termina nadmetanja."),
     "file": "prica-hotel-bellevue.html",
     "cover": "/static/covers/bellevue.svg", "published": "2026-08-13",
     "data_note": "brojke iz službenog snimka od 12.8.2026."},
    {"slug": "od-japanki-do-zracne-luke",
     "h1": "Od japanki do zračne luke: što sve Hrvatska prodaje na dražbi",
     "title": "Najneobičniji predmeti na hrvatskim dražbama | Prilika",
     "meta": ("338 pari japanki, motor broda \"Stočar\", šuma koja se devet puta "
              "vraćala na dražbu i udjel u zračnoj luci — najneobičniji predmeti "
              "službenog registra."),
     "file": "prica-od-japanki-do-zracne-luke.html",
     "cover": "/static/covers/kuriozitet.svg", "published": "2026-08-13",
     "data_note": "brojke iz službenog snimka od 12.8.2026."},
]

# Vodiči za strane kupce: jedna stranica po jeziku, hreflang klaster s
# hrvatskim vodičem /kako-sudjelovati/; x-default je engleska inačica.
GUIDES = [
    {"lang": "en", "og": "en_US", "path": "/en/croatian-property-auctions/",
     "file": "vodic-en.html",
     "h1": "Buying property at Croatian judicial auctions",
     "title": "Croatian Property Auctions — a Buyer's Guide | Prilika",
     "meta": ("How judicial auctions work in Croatia: why prices run 30–75% "
              "below appraisal, what foreign buyers need (OIB, deposit, FINA "
              "e-auction) and which risks to check first.")},
    {"lang": "de", "og": "de_DE", "path": "/de/zwangsversteigerungen-kroatien/",
     "file": "vodic-de.html",
     "h1": "Immobilien aus Zwangsversteigerungen in Kroatien kaufen",
     "title": "Zwangsversteigerungen in Kroatien — Leitfaden für Käufer | Prilika",
     "meta": ("Wie kroatische Zwangsversteigerungen funktionieren: warum die "
              "Preise 30–75 % unter dem Schätzwert liegen, was ausländische "
              "Käufer brauchen und welche Risiken zu prüfen sind.")},
    {"lang": "sl", "og": "sl_SI", "path": "/sl/drazbe-nepremicnin-na-hrvaskem/",
     "file": "vodic-sl.html",
     "h1": "Nakup nepremičnine na sodni dražbi na Hrvaškem",
     "title": "Dražbe nepremičnin na Hrvaškem — vodnik za kupce | Prilika",
     "meta": ("Kako delujejo hrvaške sodne dražbe: zakaj so cene 30–75 % pod "
              "oceno, kaj potrebujejo tuji kupci (OIB, varščina, FINA "
              "e-dražba) in katera tveganja preveriti.")},
    {"lang": "it", "og": "it_IT", "path": "/it/aste-immobiliari-in-croazia/",
     "file": "vodic-it.html",
     "h1": "Comprare immobili alle aste giudiziarie in Croazia",
     "title": "Aste immobiliari in Croazia — guida per gli acquirenti | Prilika",
     "meta": ("Come funzionano le aste giudiziarie croate: perché i prezzi sono "
              "del 30–75% sotto la stima, cosa serve agli acquirenti stranieri "
              "e quali rischi verificare prima di offrire.")},
]


def property_url(item) -> str:
    # Pokretnine i prava nemaju lokaciju po prirodi stvari — guranje stroja
    # pod "nepoznata lokacija" izgleda kao greška podataka, a nije. Zato žive
    # u vlastitom odjeljku, izvan zemljopisnog stabla.
    if item.get("property_type") in MOVABLE_TYPES:
        return f"/pokretnine/{item['slug']}/"
    return f"/nekretnine/{county_slug(item)}/{city_slug(item)}/{item['slug']}/"


def county_url(county: str | None) -> str:
    return f"/nekretnine/{slugify(county) if county else UNKNOWN_COUNTY_SLUG}/"


def city_url(county: str | None, city: str | None) -> str:
    return (f"/nekretnine/{slugify(county) if county else UNKNOWN_COUNTY_SLUG}/"
            f"{slugify(city) if city else UNKNOWN_CITY_SLUG}/")


def type_url(ptype: str) -> str:
    return f"/vrste/{ptype}/"


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class SiteBuilder:
    def __init__(self, out_dir: Path | None = None, site_url: str | None = None):
        self.out = Path(out_dir or config.OUTPUT_DIR)
        self.site_url = (site_url or config.SITE_URL).rstrip("/")
        self.env = Environment(
            loader=FileSystemLoader(str(config.TEMPLATE_DIR)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.env.filters.update(
            eur=f_eur, pct=f_pct, pct_plain=f_pct_plain,
            area=f_area, dt=f_dt, d=f_d, days=f_days, ppm=f_ppm,
        )
        self.pages: list[dict] = []   # za sitemap
        self._written: set[str] = set()
        self.duplicates_collapsed = 0
        self.snapshot = ""

    # -- pomoćno ----------------------------------------------------------
    def _abs(self, path: str) -> str:
        return f"{self.site_url}{path}"

    def _render(self, template: str, path: str, file_target: str | None = None,
                in_sitemap: bool = True, **ctx) -> None:
        ctx.setdefault("site_name", config.SITE_NAME)
        ctx.setdefault("contact_email", config.CONTACT_EMAIL)
        ctx.setdefault("source_name", config.SOURCE_NAME)
        ctx.setdefault("source_url", config.SOURCE_URL)
        ctx.setdefault("source_licence", config.SOURCE_LICENCE)
        ctx.setdefault("source_licence_url", config.SOURCE_LICENCE_URL)
        ctx.setdefault("snapshot_date", self.snapshot)
        ctx.setdefault("year", date.today().year)
        ctx.setdefault("og_image", self._abs("/static/og-image.png"))
        ctx["canonical"] = self._abs(path)
        ctx["rel"] = lambda p: p

        if path in self._written:
            raise RuntimeError(
                f"Dvije stranice pišu na isti put: {path}. To bi tiho prepisalo "
                f"sadržaj, pa se radije prekida."
            )
        self._written.add(path)

        html = self.env.get_template(template).render(**ctx)
        if file_target:
            # izravna datoteka (npr. 404.html) umjesto mape s index.html
            target = self.out / file_target
        else:
            target = self.out / path.strip("/") / "index.html" if path != "/" else self.out / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
        if in_sitemap:
            self.pages.append({
                "path": path,
                "priority": ctx.get("sitemap_priority", 0.5),
                "changefreq": ctx.get("sitemap_changefreq", "weekly"),
            })

    def _decorate(self, item: dict) -> dict:
        """Dodaj polja koja predlošci trebaju (oznake, URL-ovi, naslovi)."""
        d = dict(item)
        d["type_label"] = PROPERTY_TYPE_LABELS.get(d.get("property_type"), "Nekretnina")
        d["status_label"] = STATUS_LABELS.get(d.get("status"), d.get("status") or "")
        d["procedure_label"] = PROCEDURE_LABELS.get(d.get("procedure_type"), "Ostalo")
        d["url"] = property_url(d)
        d["county_url"] = county_url(d.get("county"))
        d["city_url"] = city_url(d.get("county"), d.get("city"))
        d["card_title"] = _card_title(d, _place_of(d))
        d["map_query"] = quote(f"{d['city']}, Hrvatska") if d.get("city") else ""

        # €/m² — samo kad postoje i cijena i smislena površina; kod sumnjivih
        # cijena se ne računa, da "0,13 €" ne proizvede lažni superlativ.
        d["price_per_m2"] = None
        if (d.get("opening_price_eur") and d.get("area_m2")
                and float(d["area_m2"]) >= 1
                and not d.get("discount_suspicious")):
            d["price_per_m2"] = round(float(d["opening_price_eur"]) / float(d["area_m2"]), 2)

        # odbrojavanje do kraja nadmetanja (računa se pri generiranju;
        # dnevna regeneracija ga drži točnim na dan)
        d["days_left"] = None
        if d.get("auction_end") and d.get("status") in ("najavljeno", "u_tijeku"):
            delta = (d["auction_end"].date() - datetime.now().date()).days
            if 0 <= delta <= 60:
                d["days_left"] = delta
        return d

    # -- glavni ulaz ------------------------------------------------------
    def build(self, items: list[dict], snapshot: str, run_stats: dict | None = None) -> dict:
        self.snapshot = snapshot or date.today().isoformat()
        run_stats = run_stats or {}

        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True, exist_ok=True)

        # statika
        static_src = config.SITE_DIR / "static"
        if static_src.exists():
            shutil.copytree(static_src, self.out / "static")

        # Ista stavka može doći dvaput ako je izvor ima kao doslovni duplikat.
        # Baza to riješi upsertom; generator mora sam, inače dvije stranice
        # pišu na isti put i tiho se prepisuju.
        unique: dict[str, dict] = {}
        for i in items:
            unique.setdefault(i["item_key"], i)
        self.duplicates_collapsed = len(items) - len(unique)

        decorated = [self._decorate(i) for i in unique.values()]
        active = [d for d in decorated if d.get("status") in ACTIVE_STATUSES]
        _assign_unique_titles(active)

        repeat_groups: dict[str, list[dict]] = defaultdict(list)
        for d in decorated:
            if d.get("repeat_group"):
                repeat_groups[d["repeat_group"]].append(d)
        for g in repeat_groups.values():
            g.sort(key=lambda x: x.get("repeat_seq") or 0)

        counts = {
            "property_pages": 0, "county_pages": 0, "city_pages": 0,
            "category_pages": 0, "blog_posts": 0, "static_pages": 0,
        }

        # 1. stranice po predmetu
        by_county_city: dict[tuple, list[dict]] = defaultdict(list)
        for d in active:
            by_county_city[(d.get("county"), d.get("city"))].append(d)

        for d in active:
            siblings = [
                s for s in active
                if s.get("county") == d.get("county") and s["item_key"] != d["item_key"]
            ][:6]
            group = repeat_groups.get(d.get("repeat_group") or "", [])
            self._property_page(d, related=siblings,
                                repeats=_meaningful_repeats(group))
            counts["property_pages"] += 1

        # 2. županije i gradovi — samo nekretnine; pokretnine imaju svoj odjeljak
        estate = [d for d in active if d["property_type"] not in MOVABLE_TYPES]
        movables = [d for d in active if d["property_type"] in MOVABLE_TYPES]
        by_county: dict[str | None, list[dict]] = defaultdict(list)
        for d in estate:
            by_county[d.get("county")].append(d)

        for county, group in sorted(by_county.items(), key=lambda kv: (kv[0] is None, kv[0] or "")):
            cities = defaultdict(list)
            for d in group:
                cities[d.get("city")].append(d)
            self._county_page(county, group, cities)
            counts["county_pages"] += 1
            for city, citems in cities.items():
                if not city:
                    continue
                self._city_page(county, city, citems)
                counts["city_pages"] += 1

        # 3. kategorije
        counts["category_pages"] += self._category_pages(active, by_county)
        self._movables_page(movables)
        counts["category_pages"] += 1

        # 4. blog
        counts["blog_posts"] += self._blog(active, by_county, run_stats,
                                           repeat_groups)

        # 5. statične stranice
        self._static_pages(len(active), run_stats)
        self._not_found_page()
        counts["static_pages"] += 3
        counts["static_pages"] += self._foreign_guides()

        # 5b. pretraga: indeks + stranica
        self._search(active)
        counts["static_pages"] += 1

        # 5c. najbolja vrijednost (€/m²), karta, RSS feed
        self._best_value(active)
        self._map(active, by_county)
        self._feed(active)
        counts["static_pages"] += 2

        # 6. početna
        self._home(active, by_county)

        # 7. sitemap + robots
        self._sitemap()
        self._robots()

        counts["total_pages"] = len(self.pages)
        return counts

    # -- pojedine stranice -------------------------------------------------
    def _property_page(self, item: dict, related: list[dict], repeats: list[dict] | None):
        url = item["url"]
        place = _place_of(item)
        h1 = item["h1"]                    # već razjednačen u _assign_unique_titles

        title_bits = [h1]
        if item.get("opening_price_eur"):
            title_bits.append(f_eur(item["opening_price_eur"]))
        page_title = " — ".join(title_bits) + " | Prilika"

        meta = _meta_description(item, place)
        if item.get("title_discriminator"):
            meta = f"{meta[:250].rstrip('.')}. Spis {item['title_discriminator']}."

        crumbs = [{"name": "Početna", "url": "/"},
                  {"name": "Nekretnine", "url": "/nekretnine/"}]
        if item.get("county"):
            crumbs.append({"name": item["county"], "url": item["county_url"]})
        if item.get("city"):
            crumbs.append({"name": item["city"], "url": item["city_url"]})
        crumbs.append({"name": h1, "url": url})

        self._render(
            "property.html", url,
            page_title=page_title, meta_description=meta, h1=h1,
            item=item, related=related, repeats=repeats,
            repeats_price_falls=_price_falls(repeats) if repeats else False,
            breadcrumbs=crumbs, og_type="article",
            jsonld=[self._jsonld_listing(item, h1, meta, url),
                    self._jsonld_breadcrumbs(crumbs)],
            sitemap_priority=0.8 if item.get("status") == "u_tijeku" else 0.7,
            sitemap_changefreq="daily" if item.get("status") == "u_tijeku" else "weekly",
        )

    def _county_page(self, county: str | None, items: list[dict], cities: dict):
        name = county or "Lokacija nije utvrđena"
        url = county_url(county)
        items = _sort_for_display(items)
        h1 = (f"Nekretnine na dražbi — {name}" if county
              else "Dražbe bez utvrđene lokacije")
        page_title = f"{h1} ({len(items)}) | Prilika"
        avg = _avg_discount(items)
        meta = (
            f"{f_items(len(items))} u ovrsi i stečaju na području "
            f"{name}. Prosječan popust na procijenjenu vrijednost {f_pct(avg)}. "
            f"Službeni podaci FINA Očevidnika, ažurirano {self.snapshot}."
        ) if county else (
            "Predmeti prodaje kojima lokacija nije utvrđena iz službenog opisa. "
            "Sjedište trgovačkog suda nije dokaz gdje se nekretnina nalazi, "
            "pa se ne pogađa."
        )

        children = sorted(
            ({"name": c, "url": city_url(county, c), "count": len(v)}
             for c, v in cities.items() if c),
            key=lambda x: -x["count"],
        )
        crumbs = [{"name": "Početna", "url": "/"},
                  {"name": "Nekretnine", "url": "/nekretnine/"},
                  {"name": name, "url": url}]

        self._render(
            "listing.html", url,
            page_title=page_title, meta_description=meta, h1=h1,
            intro=meta, cards=items[:120],
            filter_scope={"county": slugify(county) if county else UNKNOWN_COUNTY_SLUG,
                          "city": "", "type": ""},
            children=children, children_title="Gradovi i naselja",
            stats_row=_stats_row(items),
            breadcrumbs=crumbs,
            jsonld=[self._jsonld_collection(h1, meta, url, items),
                    self._jsonld_breadcrumbs(crumbs)],
            sitemap_priority=0.7, sitemap_changefreq="daily",
        )

    def _city_page(self, county: str | None, city: str, items: list[dict]):
        url = city_url(county, city)
        items = _sort_for_display(items)
        h1 = f"Nekretnine na dražbi — {city}"
        page_title = f"{h1} ({len(items)}) | Prilika"
        meta = (
            f"{f_items(len(items))} na sudskoj dražbi u mjestu {city}"
            f"{', ' + county if county else ''}. Procjena, početna cijena, "
            f"popust i rokovi iz službenog registra FINA-e."
        )
        crumbs = [{"name": "Početna", "url": "/"},
                  {"name": "Nekretnine", "url": "/nekretnine/"}]
        if county:
            crumbs.append({"name": county, "url": county_url(county)})
        crumbs.append({"name": city, "url": url})

        self._render(
            "listing.html", url,
            page_title=page_title, meta_description=meta, h1=h1,
            intro=meta, cards=items[:120], stats_row=_stats_row(items),
            filter_scope={"county": slugify(county) if county else UNKNOWN_COUNTY_SLUG,
                          "city": slugify(city), "type": ""},
            breadcrumbs=crumbs,
            jsonld=[self._jsonld_collection(h1, meta, url, items),
                    self._jsonld_breadcrumbs(crumbs)],
            sitemap_priority=0.7, sitemap_changefreq="daily",
        )

    def _category_pages(self, active: list[dict], by_county: dict) -> int:
        n = 0
        # index svih nekretnina
        counties = sorted(
            ({"name": c or "Lokacija nije utvrđena", "url": county_url(c), "count": len(v)}
             for c, v in by_county.items()),
            key=lambda x: -x["count"],
        )
        crumbs = [{"name": "Početna", "url": "/"},
                  {"name": "Nekretnine", "url": "/nekretnine/"}]
        self._render(
            "listing.html", "/nekretnine/",
            page_title=f"Nekretnine na dražbi u Hrvatskoj — {len(active)} aktivnih predmeta | Prilika",
            meta_description=(
                f"Svih {f_items(len(active))} koje se trenutno prodaju na sudskoj "
                f"dražbi u Hrvatskoj — po županijama, gradovima i vrsti. Službeni "
                f"podaci FINA Očevidnika, stanje {self.snapshot}."),
            h1="Nekretnine na dražbi u Hrvatskoj",
            intro=("Svi aktivni predmeti prodaje iz službenog registra FINA-e. "
                   "Odaberi županiju za uži pregled."),
            cards=_sort_for_display(active)[:60],
            filter_scope={"county": "", "city": "", "type": ""},
            children=counties, children_title="Po županijama",
            stats_row=_stats_row(active), breadcrumbs=crumbs,
            jsonld=[self._jsonld_collection("Nekretnine na dražbi u Hrvatskoj",
                                            "Aktivni predmeti prodaje", "/nekretnine/", active),
                    self._jsonld_breadcrumbs(crumbs)],
            sitemap_priority=0.9, sitemap_changefreq="daily",
        )
        n += 1

        # po vrsti
        by_type = defaultdict(list)
        for d in active:
            by_type[d["property_type"]].append(d)
        for ptype, group in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
            label = PROPERTY_TYPE_CATEGORY.get(ptype, "Nekretnine")
            url = type_url(ptype)
            group = _sort_for_display(group)
            h1 = f"{label} na dražbi u Hrvatskoj"
            meta = (f"{f_subjects(len(group))} u kategoriji {label.lower()} na sudskim "
                    f"dražbama. Prosječan popust {f_pct(_avg_discount(group))}. "
                    f"Podaci: FINA Očevidnik, {self.snapshot}.")
            crumbs = [{"name": "Početna", "url": "/"},
                      {"name": "Nekretnine", "url": "/nekretnine/"},
                      {"name": label, "url": url}]
            self._render(
                "listing.html", url,
                page_title=f"{h1} ({len(group)}) | Prilika",
                meta_description=meta, h1=h1, intro=meta,
                cards=group[:120], stats_row=_stats_row(group), breadcrumbs=crumbs,
                filter_scope={"county": "", "city": "", "type": ptype},
                jsonld=[self._jsonld_collection(h1, meta, url, group),
                        self._jsonld_breadcrumbs(crumbs)],
                sitemap_priority=0.7, sitemap_changefreq="daily",
            )
            n += 1

        # kuke: popusti, najjeftinije, uskoro završavaju
        hooks = [
            ("/najveci-popusti/", "Najveći popusti na procijenjenu vrijednost",
             "Predmeti čija je početna cijena najviše ispod službene procjene. "
             "Velik popust obično znači ponovljenu dražbu.",
             lambda xs: sorted(
                 [x for x in xs if x.get("discount_pct") is not None
                  and not x.get("discount_suspicious")],
                 key=lambda x: -float(x["discount_pct"]))),
            ("/najjeftinije/", "Najjeftinije nekretnine na dražbi",
             "Predmeti s najnižom početnom cijenom. Niska cijena često prati "
             "malu površinu ili suvlasnički udio — provjeri opis.",
             lambda xs: sorted(
                 [x for x in xs if x.get("opening_price_eur")
                  and float(x["opening_price_eur"]) >= 1],
                 key=lambda x: float(x["opening_price_eur"]))),
            ("/uskoro-zavrsavaju/", "Dražbe koje uskoro završavaju",
             "Nadmetanja s najbližim rokom završetka. Jamčevina se uplaćuje "
             "prije roka — provjeri datum valute.",
             lambda xs: sorted(
                 [x for x in xs if x.get("auction_end")
                  and x.get("status") in ("najavljeno", "u_tijeku")],
                 key=lambda x: x["auction_end"])),
        ]
        for url, h1, intro, sorter in hooks:
            group = sorter(active)[:120]
            crumbs = [{"name": "Početna", "url": "/"},
                      {"name": "Nekretnine", "url": "/nekretnine/"},
                      {"name": h1, "url": url}]
            meta = f"{intro} Ukupno {f_subjects(len(group))}, stanje {self.snapshot}."
            self._render(
                "listing.html", url,
                page_title=f"{h1} | Prilika", meta_description=meta[:300],
                h1=h1, intro=intro, cards=group, stats_row=_stats_row(group),
                breadcrumbs=crumbs,
                jsonld=[self._jsonld_collection(h1, intro, url, group),
                        self._jsonld_breadcrumbs(crumbs)],
                sitemap_priority=0.8, sitemap_changefreq="daily",
            )
            n += 1
        return n

    def _home(self, active: list[dict], by_county: dict):
        featured = sorted(
            [d for d in active if d.get("discount_pct") is not None
             and not d.get("discount_suspicious")],
            key=lambda x: -float(x["discount_pct"]),
        )[:6]
        counties = sorted(
            ({"name": c or "Lokacija nije utvrđena", "url": county_url(c), "count": len(v)}
             for c, v in by_county.items()),
            key=lambda x: -x["count"],
        )
        types = sorted(
            ({"name": PROPERTY_TYPE_LABELS.get(t, t), "url": type_url(t), "count": n}
             for t, n in Counter(d["property_type"] for d in active).items()),
            key=lambda x: -x["count"],
        )
        h1 = "Nekretnine na dražbi u Hrvatskoj — službeni podaci na jednom mjestu"
        meta = (
            f"{f_items(len(active))} u ovrsi i stečaju iz službenog registra "
            f"FINA-e. Procjena, početna cijena, popust i rokovi — po županiji, "
            f"gradu i vrsti. Bez ijednog osobnog podatka. Stanje {self.snapshot}."
        )
        self._render(
            "home.html", "/",
            page_title="Prilika — nekretnine na dražbi u Hrvatskoj",
            meta_description=meta, h1=h1,
            stats={
                "active": len(active),
                "counties": len([c for c in by_county if c]),
                "avg_discount": f_pct(_avg_discount(active)),
            },
            featured=featured, counties=counties, types=types,
            jsonld=[{
                "@context": "https://schema.org",
                "@type": "WebSite",
                "name": config.SITE_NAME,
                "url": self.site_url,
                "inLanguage": "hr-HR",
                "description": meta,
                "publisher": {"@type": "Organization", "name": config.SITE_NAME,
                              "url": self.site_url},
            }],
            sitemap_priority=1.0, sitemap_changefreq="daily",
        )

    def _static_pages(self, active_count: int, run_stats: dict):
        guide = """
<p>Nekretnine u ovršnom i stečajnom postupku u Hrvatskoj prodaju se najčešće
putem <strong>elektroničke javne dražbe (e-Dražba)</strong> koju provodi FINA.
Postupak je javan i svatko tko ispunjava uvjete može sudjelovati.</p>

<h2>1. Pronađi predmet i provjeri ga u izvoru</h2>
<p>Svaka stranica na Liciti navodi poslovni broj spisa i ID nadmetanja.
Prije bilo kakvog koraka provjeri stavku izravno u
<a href="https://ponip.fina.hr/ocevidnik-web/pocetna" rel="nofollow noopener" target="_blank">Očevidniku</a>
— tamo su i prilozi: zaključak o prodaji, procjembeni elaborat i fotografije.</p>

<h2>2. Pročitaj zaključak o prodaji</h2>
<p>Zaključak nosi uvjete koji nisu uvijek u sažetku: tereti koji ostaju na
nekretnini, prava trećih osoba, je li nekretnina slobodna od osoba i stvari.
Nekretnina koja nije prazna najveći je skriveni trošak — iseljenje je zaseban
postupak.</p>

<h2>3. Uplati jamčevinu na vrijeme</h2>
<p>Jamčevina je redovito 1/10 procijenjene vrijednosti i mora biti
<em>evidentirana</em> do datuma valute, ne samo poslana. Zakasnjela uplata
znači da ne možeš sudjelovati.</p>

<h2>4. Prijavi se s elektroničkim identitetom</h2>
<p>Za sudjelovanje treba vjerodajnica prihvaćena u sustavu e-Građani
odgovarajuće razine sigurnosti. To se ne rješava na dan dražbe — pripremi unaprijed.</p>

<h2>5. Nadmetanje</h2>
<p>Nadmetanje traje unaprijed određeno vrijeme. Ako netko stavi ponudu pri
samom kraju, nadmetanje se može produljiti za dodatnih 10 minuta — na stranici
predmeta piše je li produljenje moguće.</p>

<h2>6. Prva, druga i sljedeća dražba</h2>
<p>Na prvoj dražbi nekretnina se u pravilu ne može prodati ispod određenog
postotka procijenjene vrijednosti; na sljedećoj je prag niži. Zato ista
nekretnina zna proći kroz nekoliko dražbi po sve nižoj cijeni. Upravo su te
ponovljene dražbe najzanimljivije — Prilika ih povezuje i prikazuje redoslijed.</p>

<h2>7. Nakon dosude</h2>
<p>Kupac plaća kupovninu u roku iz zaključka. Porez na promet nekretnina i
troškove prijenosa u pravilu snosi kupac.</p>

<p class="muted"><strong>Napomena:</strong> ovo je opći pregled postupka, a ne
pravni savjet. Uvjeti se razlikuju od predmeta do predmeta i mjerodavan je
isključivo zaključak nadležnog tijela.</p>
"""
        self._render(
            "article.html", "/kako-sudjelovati/",
            page_title="Kako kupiti nekretninu na e-Dražbi — vodič korak po korak | Prilika",
            meta_description=("Kako sudjelovati na sudskoj dražbi nekretnine u Hrvatskoj: "
                              "provjera zaključka, jamčevina, e-Građani, tijek nadmetanja "
                              "i što slijedi nakon dosude."),
            h1="Kako kupiti nekretninu na e-Dražbi, korak po korak",
            body_html=guide, og_type="article",
            hreflangs=self._guide_hreflangs(),
            breadcrumbs=[{"name": "Početna", "url": "/"},
                         {"name": "Kako sudjelovati", "url": "/kako-sudjelovati/"}],
            jsonld=[self._jsonld_breadcrumbs(
                [{"name": "Početna", "url": "/"},
                 {"name": "Kako sudjelovati", "url": "/kako-sudjelovati/"}])],
            sitemap_priority=0.8, sitemap_changefreq="monthly",
        )

        red = run_stats.get("redactions") or {}
        red_rows = "".join(
            f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in sorted(
                red.items(), key=lambda kv: -kv[1])
        ) or "<tr><td>—</td><td>0</td></tr>"

        about = f"""
<p>Prilika koristi <strong>jedan jedini izvor</strong>: službeni CSV izvoz iz
<a href="{config.SOURCE_URL}" rel="nofollow noopener" target="_blank">Očevidnika
nekretnina i pokretnina</a> koji vodi FINA. Registar je po zakonu javan i
besplatan, a skup podataka objavljen je na portalu otvorenih podataka
Republike Hrvatske pod licencom
<a href="{config.SOURCE_LICENCE_URL}" rel="nofollow noopener" target="_blank">Otvorena dozvola</a>
i označen kao skup podataka visoke vrijednosti.</p>

<p>Ne koristi se nijedan privatni oglasnik. Ne zaobilazi se nikakva zaštita.
Interaktivna tražilica Očevidnika ima reCAPTCHA-u i ograničenje rezultata i
namjerno se <em>ne</em> dira — službeni izvoz sadrži sve što treba.</p>

<h2>Nijedan osobni podatak</h2>
<p>Ovo je najvažnije pravilo projekta i provodi se strojno, na svakom pokretanju.</p>
<p>Izvorni registar u slobodnim tekstualnim poljima <strong>sadrži</strong>
osobne podatke: imena ovršenika i stečajnih upravitelja, OIB-e, adrese
stanovanja, privatne e-mail adrese i mobitele. Provjera nad cijelim izvozom
našla je 222 OIB-a, 728 IBAN-a, 1 136 e-mail adresa i 2 505 telefonskih brojeva.</p>
<p>Zato se prije upisa u bazu primjenjuje redakcija po načelu <em>dopušteno je
samo ono što je izrijekom dopušteno</em>. Šest slobodnih polja iz izvora
uopće nema stupac u bazi, a polje opisa prolazi kroz uklanjanje identifikatora
i osobnih imena. Identitet ovršenika je zaštićen.</p>
<p>U posljednjem pokretanju uklonjeno je:</p>
<table><thead><tr><th>Vrsta podatka</th><th>Broj uklanjanja</th></tr></thead>
<tbody>{red_rows}</tbody></table>
<p>Provjera <code>validate.py</code> pretražuje bazu <em>i</em> svaku generiranu
stranicu i prekida objavu ako pronađe ijedan osobni podatak.</p>

<h2>Što izvor nema</h2>
<p>Radi poštenja: službeni izvoz nema stupac lokacije, površine, statusa ni
trenutne ponude. Županija se izvodi iz opisa ili iz nadležnog općinskog suda,
površina se čita iz teksta opisa, a status iz datuma nadmetanja.
<strong>Trenutna ponuda tijekom nadmetanja ne postoji u izvozu i nigdje se ne
prikazuje</strong> — ne procjenjuje se i ne izmišlja.</p>
<p>Sjedište trgovačkog suda ne koristi se kao lokacija nekretnine, jer stečajna
masa može držati imovinu bilo gdje u Hrvatskoj. Takvi predmeti ostaju
označeni kao lokacija neutvrđena.</p>

<h2>Ažuriranje</h2>
<p>Izvoz je dnevni snimak cijelog registra. Podaci na ovoj stranici odgovaraju
stanju na dan <strong>{self.snapshot}</strong>. Prilika bilježi promjene cijena i
statusa između pokretanja te povezuje ponovljene dražbe iste nekretnine.</p>

<p class="muted">Prilika nije FINA, nije sud i nije sudionik u postupku prodaje.
Podaci su informativni; mjerodavan je isključivo službeni registar.</p>
"""
        self._render(
            "article.html", "/o-podacima/",
            page_title="O podacima: izvor, licenca i zaštita osobnih podataka | Prilika",
            meta_description=("Odakle Liciti podaci, pod kojom licencom, i kako se "
                              "osobni podaci uklanjaju prije objave. Izvor: službeni "
                              "CSV izvoz FINA Očevidnika, Otvorena dozvola."),
            h1="O podacima", body_html=about, og_type="article",
            breadcrumbs=[{"name": "Početna", "url": "/"},
                         {"name": "O podacima", "url": "/o-podacima/"}],
            jsonld=[self._jsonld_breadcrumbs(
                [{"name": "Početna", "url": "/"},
                 {"name": "O podacima", "url": "/o-podacima/"}])],
            sitemap_priority=0.6, sitemap_changefreq="monthly",
        )

    def _guide_hreflangs(self) -> list[dict]:
        """Hreflang klaster vodiča: hr + četiri strana jezika + x-default."""
        alts = [{"lang": "hr", "url": self._abs("/kako-sudjelovati/")}]
        alts += [{"lang": g["lang"], "url": self._abs(g["path"])} for g in GUIDES]
        alts.append({"lang": "x-default",
                     "url": self._abs("/en/croatian-property-auctions/")})
        return alts

    def _foreign_guides(self) -> int:
        """Vodiči za strane kupce (EN/DE/SL/IT) iz site/content/.

        Namjerno se NE prevode stranice predmeta: mijenjaju se svakodnevno, a
        strani kupac postupak ionako ne može dovršiti bez hrvatskog. Jedan
        temeljit vodič po jeziku cilja upravo upite koje ti kupci traže.
        """
        n = 0
        for g in GUIDES:
            path = config.SITE_DIR / "content" / g["file"]
            if not path.exists():
                continue
            self._render(
                "article.html", g["path"],
                lang=g["lang"], og_locale=g["og"],
                hreflangs=self._guide_hreflangs(),
                page_title=g["title"], meta_description=g["meta"],
                h1=g["h1"], body_html=path.read_text(encoding="utf-8"),
                og_type="article",
                sitemap_priority=0.7, sitemap_changefreq="monthly",
            )
            n += 1
        return n

    def _not_found_page(self) -> None:
        """/404.html — poslužitelj ga vraća uz status 404.

        Dražbene stranice nestaju svakim danom kako nadmetanja završe (završeni
        predmeti namjerno nemaju stranicu), pa zastarjela poveznica iz
        tražilice nije rubni slučaj nego svakodnevica. Stranica ne ulazi u
        sitemap i nosi noindex.
        """
        body = """
<p>Ove stranice više nema — ili nikad nije postojala.</p>
<p>Najčešći razlog: <strong>dražba je završila.</strong> Završeni predmeti
namjerno nemaju stranicu — podatak ostaje u povijesti cijena, ali stranica o
prodaji iz prošlosti nikome ne pomaže.</p>
<p>Kamo dalje:</p>
<ul>
  <li><a href="/nekretnine/">Sve aktivne nekretnine</a></li>
  <li><a href="/trazi/">Pretraga po mjestu, k.o. ili broju spisa</a></li>
  <li><a href="/uskoro-zavrsavaju/">Dražbe koje uskoro završavaju</a></li>
  <li><a href="/">Početna</a></li>
</ul>
"""
        self._render(
            "article.html", "/404.html",
            file_target="404.html", in_sitemap=False,
            robots="noindex",
            page_title="Stranica ne postoji (404) | Prilika",
            meta_description="Tražena stranica ne postoji — dražba je "
                             "najvjerojatnije završila.",
            h1="Ova stranica ne postoji", body_html=body,
            breadcrumbs=[{"name": "Početna", "url": "/"}],
        )

    # -- pretraga ----------------------------------------------------------
    def _search(self, active: list[dict]) -> None:
        """Klijentska pretraga: JSON indeks + stranica /trazi/.

        Statička stranica ne može imati poslužiteljsku tražilicu, ali može
        posve solidnu klijentsku: indeks svih aktivnih predmeta (~300 KB)
        učita se jednom, pretraga radi trenutačno i dijakritički neosjetljivo,
        i ništa se nigdje ne šalje. Pokriva mjesto, k.o., spis, ID nadmetanja,
        vrstu i status — upravo polja po kojima se predmet stvarno traži.
        """
        index = []
        for d in active:
            index.append({
                # prikaz
                "n": d["card_title"],
                "u": d["url"],
                "g": d.get("city") or "",
                "z": d.get("county") or "",
                "k": d.get("cadastral_municipality") or "",
                "r": d.get("case_ref") or "",
                "i": d.get("auction_id") or "",
                "t": d.get("type_label") or "",
                "s": d.get("status_label") or "",
                "p": f_eur(d["opening_price_eur"]) if d.get("opening_price_eur") else "",
                "d": (f_pct_plain(d["discount_pct"])
                      if d.get("discount_pct") is not None
                      and not d.get("discount_suspicious") else ""),
                "a": f_area(d["area_m2"]) if d.get("area_m2") else "",
                "e": f_d(d["auction_end"]) if d.get("auction_end") else "",
                "pm": f_ppm(d["price_per_m2"]) if d.get("price_per_m2") else "",
                "dl": d.get("days_left"),
                # sirove vrijednosti za filtriranje/sortiranje na klijentu
                "ty": d.get("property_type") or "",
                "sk": d.get("status") or "",
                "pk": d.get("procedure_type") or "",
                "zs": county_slug(d),
                "gs": city_slug(d),
                "pn": float(d["opening_price_eur"]) if d.get("opening_price_eur") else None,
                "an": float(d["area_m2"]) if d.get("area_m2") else None,
                "dn": (float(d["discount_pct"])
                       if d.get("discount_pct") is not None
                       and not d.get("discount_suspicious") else None),
                "mn": d.get("price_per_m2"),
                "ei": _iso(d.get("auction_end"), date_only=True) or "",
                "lt": float(d["latitude"]) if d.get("latitude") else None,
                "ln": float(d["longitude"]) if d.get("longitude") else None,
            })
        (self.out / "search-index.json").write_text(
            json.dumps(index, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

        crumbs = [{"name": "Početna", "url": "/"}, {"name": "Traži", "url": "/trazi/"}]
        self._render(
            "search.html", "/trazi/",
            page_title="Traži nekretnine na dražbi | Prilika",
            meta_description=(f"Pretraži svih {len(active)} aktivnih predmeta prodaje "
                              f"po mjestu, katastarskoj općini, broju spisa ili vrsti "
                              f"nekretnine. Trenutačna pretraga, bez prijave."),
            total=len(active), breadcrumbs=crumbs,
            robots="noindex,follow",
            jsonld=[self._jsonld_breadcrumbs(crumbs)],
            sitemap_priority=0.4, sitemap_changefreq="daily",
        )

    def _movables_page(self, movables: list[dict]) -> None:
        """Pokretnine i prava: bez zemljopisa, s poštenim objašnjenjem."""
        url = "/pokretnine/"
        items = _sort_for_display(movables)
        crumbs = [{"name": "Početna", "url": "/"},
                  {"name": "Pokretnine i prava", "url": url}]
        meta = (f"{len(items)} pokretnina i prava u ovršnim i stečajnim "
                f"postupcima: vozila, strojevi, oprema, plovila, udjeli. "
                f"Službeni podaci FINA Očevidnika.")
        self._render(
            "listing.html", url,
            page_title=f"Pokretnine i prava na dražbi ({len(items)}) | Prilika",
            meta_description=meta,
            h1="Pokretnine i prava na dražbi",
            intro=("Vozila, strojevi, stoka, roba i poslovni udjeli iz ovrha i "
                   "stečajeva. Ovi predmeti nemaju adresu po prirodi stvari, pa "
                   "ne stoje u zemljopisnom pregledu — tko prodaje i dokle traje "
                   "nadmetanje piše na svakoj stavci."),
            cards=items[:200], stats_row=_stats_row(items),
            breadcrumbs=crumbs,
            jsonld=[self._jsonld_collection("Pokretnine i prava na dražbi",
                                            meta, url, items),
                    self._jsonld_breadcrumbs(crumbs)],
            sitemap_priority=0.6, sitemap_changefreq="daily",
        )

    # -- najbolja vrijednost (€/m²) ----------------------------------------
    def _best_value(self, active: list[dict]) -> None:
        """Rang po €/m². Zgrade i zemljišta se NE miješaju u istoj ljestvici —
        €/m² stana i €/m² oranice nisu usporedive veličine."""
        def usable(d, types, min_area):
            return (d.get("price_per_m2") and d["property_type"] in types
                    and float(d["area_m2"]) >= min_area
                    and float(d["opening_price_eur"]) >= 500)

        buildings = sorted(
            (d for d in active if usable(d, ("stan", "kuca", "poslovni-prostor"), 25)),
            key=lambda d: d["price_per_m2"])[:60]
        build_land = sorted(
            (d for d in active if usable(d, ("gradevinsko-zemljiste",), 100)),
            key=lambda d: d["price_per_m2"])[:60]
        farm_land = sorted(
            (d for d in active if usable(d, ("poljoprivredno-zemljiste", "zemljiste",
                                             "sumsko-zemljiste"), 500)),
            key=lambda d: d["price_per_m2"])[:60]

        url = "/najbolja-vrijednost/"
        h1 = "Najbolja vrijednost — cijena po kvadratu"
        crumbs = [{"name": "Početna", "url": "/"},
                  {"name": "Nekretnine", "url": "/nekretnine/"},
                  {"name": "Najbolja vrijednost", "url": url}]
        body = ""
        for title, group in (("Stanovi, kuće i poslovni prostori", buildings),
                             ("Građevinska zemljišta", build_land),
                             ("Poljoprivredna, šumska i ostala zemljišta", farm_land)):
            if not group:
                continue
            tmpl = self.env.get_template("_cards.html")
            cards_html = tmpl.render(cards=group[:24], rel=lambda p: p)
            body += f"<h2>{title}</h2>{cards_html}"
        meta = ("Aktivne dražbe rangirane po cijeni kvadrata: stanovi i kuće, "
                "građevinska i poljoprivredna zemljišta zasebno — jer njihovi "
                "€/m² nisu usporedivi. Službeni podaci FINA Očevidnika.")
        self._render(
            "listing.html", url,
            page_title=f"{h1} | Prilika",
            meta_description=meta, h1=h1,
            intro=("Najniža početna cijena po kvadratu među aktivnim dražbama. "
                   "Zgrade i zemljišta rangirani su odvojeno; premale površine i "
                   "nominalne cijene su isključene da ljestvicu ne iskrive."),
            cards=None, body_html=body, breadcrumbs=crumbs,
            jsonld=[self._jsonld_breadcrumbs(crumbs)],
            sitemap_priority=0.8, sitemap_changefreq="daily",
        )

    # -- karta -------------------------------------------------------------
    def _map(self, active: list[dict], by_county: dict) -> None:
        """Karta s pribadačama na razini katastarske općine.

        Markeri se grade u pregledniku iz search-index.json — istog indeksa
        koji pokreće filtre — pa karta i popis dijele jednu logiku filtriranja.
        Bez JS-a ostaje popis županija. Koordinate su službene referentne
        točke k.o. (DGU INSPIRE, Otvorena dozvola); OSM podloga je jedini
        vanjski zahtjev na stranici."""
        with_coords = sum(1 for d in active if d.get("latitude"))
        counties = []
        for county, group in sorted(by_county.items(),
                                    key=lambda kv: -len(kv[1])):
            counties.append({"name": county or "Lokacija nije utvrđena",
                             "url": county_url(county), "count": len(group)})
        crumbs = [{"name": "Početna", "url": "/"}, {"name": "Karta", "url": "/karta/"}]
        self._render(
            "map.html", "/karta/",
            page_title="Karta dražbi nekretnina po županijama | Prilika",
            meta_description=(f"Interaktivna karta s {with_coords} aktivnih "
                              f"dražbi s filtrima po vrsti, cijeni i statusu — točke "
                              f"katastarskih općina iz službenog DGU registra."),
            counties=counties, with_coords=with_coords, breadcrumbs=crumbs,
            jsonld=[self._jsonld_breadcrumbs(crumbs)],
            sitemap_priority=0.6, sitemap_changefreq="daily",
        )

    # -- RSS ---------------------------------------------------------------
    def _feed(self, active: list[dict]) -> None:
        """RSS 2.0 s nedavno objavljenim predmetima — preteča Phase 2
        obavijesti, a radi već sada u svakom čitaču feedova."""
        recent = sorted(
            (d for d in active if d.get("publish_start")),
            key=lambda d: d["publish_start"], reverse=True)[:50]
        items_xml = []
        for d in recent:
            title = d["card_title"]
            if d.get("opening_price_eur"):
                title += f" — {f_eur(d['opening_price_eur'])}"
            desc_bits = [d.get("type_label") or ""]
            if d.get("county"):
                desc_bits.append(d["county"])
            if d.get("discount_pct") is not None and not d.get("discount_suspicious"):
                desc_bits.append(f"{f_pct(d['discount_pct'])} ispod procjene")
            if d.get("auction_end"):
                desc_bits.append(f"nadmetanje do {f_d(d['auction_end'])}")
            pub = d["publish_start"].strftime("%a, %d %b %Y %H:%M:%S +0100")
            link = self._abs(d["url"])
            items_xml.append(
                "<item>"
                f"<title>{_xml(title)}</title>"
                f"<link>{_xml(link)}</link>"
                f"<guid isPermaLink=\"true\">{_xml(link)}</guid>"
                f"<pubDate>{pub}</pubDate>"
                f"<description>{_xml(' · '.join(b for b in desc_bits if b))}</description>"
                "</item>"
            )
        feed = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0"><channel>'
            f"<title>{config.SITE_NAME} — nove dražbe nekretnina</title>"
            f"<link>{self.site_url}/</link>"
            "<description>Novi predmeti prodaje u ovršnim i stečajnim postupcima, "
            "iz službenog registra FINA-e. Bez osobnih podataka.</description>"
            "<language>hr</language>"
            + "".join(items_xml) +
            "</channel></rss>\n"
        )
        (self.out / "feed.xml").write_text(feed, encoding="utf-8")

    # -- blog --------------------------------------------------------------
    def _blog(self, active: list[dict], by_county: dict, run_stats: dict,
              repeat_groups: dict[str, list[dict]] | None = None) -> int:
        posts = []

        # (a) mjesečni pregled tržišta
        month_names = ["siječnja", "veljače", "ožujka", "travnja", "svibnja", "lipnja",
                       "srpnja", "kolovoza", "rujna", "listopada", "studenoga", "prosinca"]
        today = date.fromisoformat(self.snapshot) if self.snapshot else date.today()
        mlabel = f"{month_names[today.month - 1]} {today.year}."
        top_counties = sorted(((c, len(v)) for c, v in by_county.items() if c),
                              key=lambda x: -x[1])[:5]
        best = sorted([d for d in active if d.get("discount_pct") is not None
                       and not d.get("discount_suspicious")],
                      key=lambda x: -float(x["discount_pct"]))[:5]
        rows = "".join(f"<tr><td>{c}</td><td>{n}</td></tr>" for c, n in top_counties)
        body = f"""
<p>Na dan {self.snapshot} u službenom registru FINA-e bilo je
<strong>{len(active)}</strong> aktivnih predmeta prodaje nekretnina i pokretnina
u ovršnom i stečajnom postupku.</p>
<h2>Gdje ih je najviše</h2>
<table><thead><tr><th>Županija</th><th>Aktivnih predmeta</th></tr></thead>
<tbody>{rows}</tbody></table>
<h2>Prosječan popust</h2>
<p>Prosječna početna cijena bila je <strong>{f_pct(_avg_discount(active))}</strong>
ispod službeno procijenjene vrijednosti. Najveći popusti gotovo uvijek pripadaju
ponovljenim dražbama — nekretnini koja se prodaje drugi, treći ili četvrti put,
svaki put po nižoj početnoj cijeni.</p>
<h2>Kako čitati velike popuste</h2>
<p>Popust od 60 % i više rijetko je "besplatan novac". Najčešći razlozi su
suvlasnički udio umjesto cijele nekretnine, teret koji ostaje upisan, ili
nekretnina koja nije slobodna od osoba i stvari. Zaključak o prodaji odgovara
na sva tri pitanja i vrijedi ga pročitati prije nego ponudu.</p>
"""
        posts.append({
            "slug": f"pregled-trzista-{today.year}-{today.month:02d}",
            "cover": "/static/covers/pregled.svg",
            "h1": f"Nekretnine na dražbi — pregled za {mlabel}",
            "title": f"Nekretnine na dražbi u Hrvatskoj: pregled za {mlabel} | Prilika",
            "meta": (f"Koliko je nekretnina na dražbi u {mlabel}, u kojim županijama, "
                     f"i koliki je prosječan popust na procjenu. Podaci iz službenog "
                     f"registra FINA-e."),
            "body": body, "cards": best, "cards_title": "Najveći popusti ovog mjeseca",
            "published": self.snapshot,
            "data_note": f"izvedeno iz {len(active)} aktivnih predmeta",
        })

        # (b) spotlight po županiji — tri najveće
        for county, n in top_counties[:3]:
            citems = _sort_for_display(by_county[county])
            cities = Counter(d["city"] for d in citems if d.get("city"))
            types = Counter(PROPERTY_TYPE_LABELS.get(d["property_type"], "Ostalo")
                            for d in citems)
            city_line = ", ".join(f"{c} ({k})" for c, k in cities.most_common(5)) or "—"
            type_line = ", ".join(f"{t.lower()} ({k})" for t, k in types.most_common(4))
            body = f"""
<p>U županiji {county} trenutno je <strong>{n}</strong> aktivnih predmeta prodaje
iz ovršnih i stečajnih postupaka.</p>
<h2>Gdje se nalaze</h2>
<p>Najviše ih je u ovim mjestima: {city_line}.</p>
<h2>Što se prodaje</h2>
<p>Po vrsti prevladavaju: {type_line}.</p>
<h2>Cijene</h2>
<p>Prosječan popust početne cijene u odnosu na procijenjenu vrijednost iznosi
<strong>{f_pct(_avg_discount(citems))}</strong>.</p>
<p>Popis se osvježava svakodnevno:
<a href="{county_url(county)}">sve dražbe u županiji {county}</a>.</p>
"""
            posts.append({
                "slug": f"drazbe-{slugify(county)}",
                "cover": "/static/covers/zupanija.svg",
                "h1": f"Dražbe nekretnina u županiji {county}",
                "title": f"Nekretnine na dražbi — {county} | Prilika",
                "meta": (f"Pregled {n} aktivnih dražbi nekretnina u županiji {county}: "
                         f"gdje su, što se prodaje i koliki je prosječan popust."),
                "body": body, "cards": citems[:6],
                "cards_title": f"Aktualni predmeti — {county}",
                "published": self.snapshot,
                "data_note": f"{n} aktivnih predmeta",
            })

        # (c) rang-liste koje se osvježavaju sa svakim pokretanjem — stabilan
        # URL skuplja poveznice, a sadržaj je svaki dan svjež
        rank_posts = []

        priciest = sorted((d for d in active if d.get("estimated_value_eur")),
                          key=lambda x: -float(x["estimated_value_eur"]))[:10]
        rows = "".join(
            f'<tr><td><a href="{d["url"]}">{escape(d["type_label"])}'
            f'</a></td><td>{escape(d.get("city") or d.get("county") or "—")}</td>'
            f'<td>{f_eur(d["estimated_value_eur"])}</td>'
            f'<td>{f_eur(d["opening_price_eur"]) if d.get("opening_price_eur") else "—"}</td></tr>'
            for d in priciest)
        body = f"""
<p>Deset trenutačno najvrjednijih aktivnih predmeta u službenom registru,
poredanih po procijenjenoj vrijednosti. Popis se osvježava svakodnevno iz
službenog snimka.</p>
<table><thead><tr><th>Predmet</th><th>Mjesto</th><th>Procjena</th>
<th>Početna cijena</th></tr></thead><tbody>{rows}</tbody></table>
<p><strong>Prije oduševljenja brojkama:</strong> velike procjene često znače
suvlasničke udjele, pravo građenja umjesto vlasništva, ili terete koji ostaju
upisani. Što se točno prodaje piše u zaključku o prodaji — poveznica na
službeni registar stoji na svakoj stranici predmeta.</p>
"""
        rank_posts.append({
            "slug": "najskuplje-na-drazbi",
            "cover": "/static/covers/rang-najskuplje.svg",
            "h1": "Najskuplje na dražbi upravo sada",
            "title": "Najskuplje nekretnine i imovina na dražbi u Hrvatskoj | Prilika",
            "meta": ("Deset najvrjednijih aktivnih predmeta u službenom registru "
                     "dražbi — s procjenama, početnim cijenama i upozorenjima na "
                     "što paziti. Osvježava se svakodnevno."),
            "body": body, "cards": priciest[:6],
            "cards_title": "Najvrjedniji aktivni predmeti",
            "published": self.snapshot, "changefreq": "daily",
            "data_note": "osvježava se svakodnevno",
        })

        if repeat_groups:
            stubborn = []
            for group in repeat_groups.values():
                if len(group) < 3:
                    continue
                live = next((m for m in group if m.get("status") != "zavrseno"), None)
                opens = [float(m["opening_price_eur"]) for m in group
                         if m.get("opening_price_eur")]
                drop = (round((1 - opens[-1] / opens[0]) * 100)
                        if len(opens) >= 2 and opens[0] > opens[-1] > 0 else None)
                stubborn.append({"n": len(group), "live": live, "drop": drop,
                                 "title": (live or group[-1])["card_title"]})
            stubborn.sort(key=lambda s: -s["n"])
            stubborn = stubborn[:8]
            if stubborn:
                rows = "".join(
                    "<tr><td>" + (f'<a href="{s["live"]["url"]}">{escape(s["title"])}</a>'
                                  if s["live"] else escape(s["title"])) + "</td>"
                    f'<td>{s["n"]}</td>'
                    f'<td>{str(s["drop"]) + " %" if s["drop"] else "—"}</td></tr>'
                    for s in stubborn)
                body = f"""
<p>Neki se predmeti na dražbu vraćaju tri, pet, pa i devet puta — i svaki
povratak u pravilu znači nižu početnu cijenu. Ovo su trenutačni rekorderi po
broju pojavljivanja u registru, izvedeno iz povezanih ponovljenih dražbi.</p>
<table><thead><tr><th>Predmet</th><th>Pojavljivanja</th>
<th>Pad početne cijene</th></tr></thead><tbody>{rows}</tbody></table>
<p>Zašto se ne prodaju? Ponekad je razlog očit iz opisa (suvlasnički udio,
specifična oprema), ponekad tek iz zaključka o prodaji. Ali upravo među
ovakvim predmetima nastaju najveći popusti u registru — pregled po visini
popusta: <a href="/najveci-popusti/">najveći popusti</a>.</p>
"""
                rank_posts.append({
                    "slug": "predmeti-koje-nitko-ne-zeli",
                    "cover": "/static/covers/rang-ponovljene.svg",
                    "h1": "Predmeti koje (zasad) nitko ne želi",
                    "title": "Dražbe koje se ponavljaju najviše puta | Prilika",
                    "meta": ("Predmeti s najviše ponovljenih dražbi u službenom "
                             "registru i koliko im je pala početna cijena. "
                             "Osvježava se svakodnevno."),
                    "body": body, "published": self.snapshot, "changefreq": "daily",
                    "data_note": "izvedeno iz povezanih ponovljenih dražbi",
                })

        week_end = today + timedelta(days=7)
        ending = sorted((d for d in active
                         if d.get("status") == "u_tijeku" and d.get("auction_end")
                         and d["auction_end"].date() <= week_end
                         and float(d.get("estimated_value_eur") or 0) >= 50000),
                        key=lambda d: d["auction_end"])[:10]
        if ending:
            rows = "".join(
                f'<tr><td><a href="{d["url"]}">{escape(d["card_title"])}</a></td>'
                f'<td>{f_eur(d["estimated_value_eur"])}</td>'
                f'<td>{f_eur(d["opening_price_eur"]) if d.get("opening_price_eur") else "—"}</td>'
                f'<td>{f_d(d["auction_end"])}</td></tr>'
                for d in ending)
            body = f"""
<p>Nadmetanja vrijednija od 50.000 € koja završavaju u sljedećih sedam dana,
poredana po roku. Tko želi sudjelovati, jamčevinu mora uplatiti prije
završetka — rokovi stoje u zaključku o prodaji svakog predmeta.</p>
<table><thead><tr><th>Predmet</th><th>Procjena</th><th>Početna cijena</th>
<th>Završava</th></tr></thead><tbody>{rows}</tbody></table>
<p>Cijeli pregled, uključujući manje vrijedne predmete:
<a href="/uskoro-zavrsavaju/">dražbe koje uskoro završavaju</a>.</p>
"""
            rank_posts.append({
                "slug": "zavrsavaju-ovaj-tjedan",
                "cover": "/static/covers/rang-rok.svg",
                "h1": "Vrijedne dražbe koje završavaju ovaj tjedan",
                "title": "Dražbe iznad 50.000 € koje završavaju ovaj tjedan | Prilika",
                "meta": ("Nadmetanja procijenjena iznad 50.000 € koja završavaju "
                         "u sljedećih sedam dana — s rokovima i početnim "
                         "cijenama. Osvježava se svakodnevno."),
                "body": body, "cards": ending[:6],
                "cards_title": "Završavaju uskoro",
                "published": self.snapshot, "changefreq": "daily",
                "data_note": "osvježava se svakodnevno",
            })

        # (d) ručno pisane priče — statični tekstovi iz site/content/, s
        # brojkama na datum objave (data_note kaže iz kojeg su snimka)
        story_posts = []
        for meta in STORY_POSTS:
            path = config.SITE_DIR / "content" / meta["file"]
            if path.exists():
                story_posts.append({**meta, "body": path.read_text(encoding="utf-8")})

        posts = story_posts + rank_posts + posts

        for p in posts:
            url = f"/blog/{p['slug']}/"
            crumbs = [{"name": "Početna", "url": "/"},
                      {"name": "Blog", "url": "/blog/"},
                      {"name": p["h1"], "url": url}]
            self._render(
                "article.html", url,
                page_title=p["title"], meta_description=p["meta"], h1=p["h1"],
                body_html=p["body"], cards=p.get("cards"),
                cover=p.get("cover"),
                cards_title=p.get("cards_title"), published=p["published"],
                data_note=p.get("data_note"), og_type="article",
                breadcrumbs=crumbs,
                jsonld=[{
                    "@context": "https://schema.org", "@type": "BlogPosting",
                    "headline": p["h1"][:110], "description": p["meta"],
                    "inLanguage": "hr-HR", "datePublished": p["published"],
                    "dateModified": p["published"],
                    "mainEntityOfPage": self._abs(url),
                    "author": {"@type": "Organization", "name": config.SITE_NAME},
                    "publisher": {"@type": "Organization", "name": config.SITE_NAME},
                }, self._jsonld_breadcrumbs(crumbs)],
                sitemap_priority=0.6,
                sitemap_changefreq=p.get("changefreq", "monthly"),
            )

        crumbs = [{"name": "Početna", "url": "/"}, {"name": "Blog", "url": "/blog/"}]
        listing = "".join(
            f'''<article class="bpost">
  <a class="bpost-cover" href="/blog/{p["slug"]}/" tabindex="-1" aria-hidden="true">
    <img src="{p.get("cover") or "/static/covers/pregled.svg"}" alt="" loading="lazy" width="640" height="360">
  </a>
  <div class="bpost-body">
    <p class="bpost-date">{p["published"]}{" · " + p["data_note"] if p.get("data_note") else ""}</p>
    <h2><a href="/blog/{p["slug"]}/">{escape(p["h1"])}</a></h2>
    <p>{escape(p["meta"])}</p>
    <p class="bpost-more"><a href="/blog/{p["slug"]}/">Pročitaj →</a></p>
  </div>
</article>''' for p in posts
        )
        self._render(
            "article.html", "/blog/",
            page_title="Blog — priče i analize s hrvatskih dražbi | Prilika",
            meta_description=("Priče iz službenog registra dražbi, rang-liste koje se "
                              "osvježavaju svakodnevno, mjesečni pregledi tržišta i "
                              "analize po županijama."),
            h1="Blog", body_html=f'<div class="blog-grid">{listing}</div>',
            breadcrumbs=crumbs, jsonld=[self._jsonld_breadcrumbs(crumbs)],
            sitemap_priority=0.6, sitemap_changefreq="daily",
        )
        return len(posts)

    # -- JSON-LD -----------------------------------------------------------
    def _jsonld_listing(self, item: dict, name: str, desc: str, url: str) -> dict:
        price = item.get("opening_price_eur") or item.get("estimated_value_eur")
        availability = {
            "u_tijeku": "https://schema.org/InStock",
            "najavljeno": "https://schema.org/PreOrder",
            "zavrseno": "https://schema.org/SoldOut",
        }.get(item.get("status"), "https://schema.org/LimitedAvailability")

        data: dict = {
            "@context": "https://schema.org",
            "@type": ("Product" if item.get("property_type") in MOVABLE_TYPES
                      else "RealEstateListing"),
            "name": name,
            "description": desc,
            "url": self._abs(url),
            "inLanguage": "hr-HR",
            "datePosted": _iso(item.get("publish_start")) or self.snapshot,
        }
        if item.get("auction_end"):
            data["expires"] = _iso(item["auction_end"])

        addr: dict = {"@type": "PostalAddress", "addressCountry": "HR"}
        if item.get("city"):
            addr["addressLocality"] = item["city"]
        if item.get("county"):
            addr["addressRegion"] = item["county"]
        data["address"] = addr

        offer: dict = {
            "@type": "Offer",
            "availability": availability,
            "priceCurrency": "EUR",
            "url": self._abs(url),
            "seller": {"@type": "Organization", "name": item.get("issuer_name") or "Sud"},
        }
        if price:
            offer["price"] = f"{float(price):.2f}"
        if item.get("auction_end"):
            offer["priceValidUntil"] = _iso(item["auction_end"], date_only=True)
        data["offers"] = offer

        if item.get("area_m2"):
            data["floorSize"] = {
                "@type": "QuantitativeValue",
                "value": float(item["area_m2"]),
                "unitCode": "MTK",
            }
        return data

    def _jsonld_collection(self, name: str, desc: str, url: str, items: list[dict]) -> dict:
        return {
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": name,
            "description": desc,
            "url": self._abs(url),
            "inLanguage": "hr-HR",
            "mainEntity": {
                "@type": "ItemList",
                "numberOfItems": len(items),
                "itemListElement": [
                    {"@type": "ListItem", "position": i,
                     "url": self._abs(d["url"]), "name": d["card_title"]}
                    for i, d in enumerate(items[:25], start=1)
                ],
            },
        }

    def _jsonld_breadcrumbs(self, crumbs: list[dict]) -> dict:
        return {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": i, "name": c["name"],
                 "item": self._abs(c["url"])}
                for i, c in enumerate(crumbs, start=1)
            ],
        }

    # -- sitemap / robots --------------------------------------------------
    def _sitemap(self) -> None:
        today = self.snapshot or date.today().isoformat()
        parts = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        seen = set()
        for p in self.pages:
            if p["path"] in seen:
                continue
            seen.add(p["path"])
            parts.append(
                f"  <url><loc>{_xml(self._abs(p['path']))}</loc>"
                f"<lastmod>{today}</lastmod>"
                f"<changefreq>{p['changefreq']}</changefreq>"
                f"<priority>{p['priority']:.1f}</priority></url>"
            )
        parts.append("</urlset>")
        (self.out / "sitemap.xml").write_text("\n".join(parts), encoding="utf-8")

    def _robots(self) -> None:
        (self.out / "robots.txt").write_text(
            "User-agent: *\n"
            "Allow: /\n\n"
            f"Sitemap: {self.site_url}/sitemap.xml\n",
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# Pomoćne funkcije
# ---------------------------------------------------------------------------

def _meaningful_repeats(group: list[dict]) -> list[dict] | None:
    """Prikaži ranije dražbe samo ako se doista nešto razlikuje.

    Registar zna istu dražbu voditi u dva retka (isti krug, ista cijena).
    Prikazati to kao "ponovljenu dražbu po sve nižoj cijeni" bila bi tvrdnja
    koju podaci ne potkrepljuju, pa se takva skupina ne prikazuje.
    """
    if not group or len(group) < 2:
        return None
    rounds = {g.get("auction_round") for g in group}
    prices = {round(float(g["opening_price_eur"]), 2) for g in group
              if g.get("opening_price_eur")}
    if len(rounds) > 1 or len(prices) > 1:
        return group
    return None


def _price_falls(group: list[dict]) -> bool:
    prices = [(g.get("repeat_seq") or 0, float(g["opening_price_eur"]))
              for g in group if g.get("opening_price_eur")]
    prices.sort()
    return len(prices) >= 2 and prices[-1][1] < prices[0][1]


def _place_of(item: dict) -> str:
    """Jedno pravilo za mjesto, isto u naslovu, kartici i slugu."""
    return (item.get("city") or item.get("cadastral_municipality")
            or item.get("county") or "Hrvatska")


def _assign_unique_titles(items: list[dict]) -> None:
    """Zajamči da svaka stranica ima svoj naslov.

    Predmeti bez površine, cijene i naselja (tipično pokretnine i prava)
    inače dobiju identičan naslov — provjera je našla 964 takve stranice pod
    86 naslova, npr. 626× "Pokretnina — Hrvatska". Za tražilice je to
    duplicirani sadržaj, a za čitatelja beskorisno.

    Razjednačuje se poslovnim brojem spisa, koji je i sam koristan podatak
    (po njemu se predmet traži u Očevidniku). Ako ni to nije dovoljno,
    dodaje se ID nadmetanja.
    """
    base: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        it["h1"] = _card_title(it, _place_of(it))
        it["title_discriminator"] = ""
        base[it["h1"]].append(it)

    for title, group in base.items():
        if len(group) == 1:
            continue
        for it in group:
            disc = it.get("case_ref") or ""
            it["title_discriminator"] = disc
            it["h1"] = f"{title} · {disc}" if disc else title

    for it in items:
        it["card_title"] = it["h1"]

    # drugi prolaz: isti spis zna imati više predmeta prodaje
    second: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        second[it["h1"]].append(it)
    for title, group in second.items():
        if len(group) == 1:
            continue
        for i, it in enumerate(group, start=1):
            extra = it.get("auction_id") or f"{i}"
            it["title_discriminator"] = (
                f"{it.get('case_ref','')} / {extra}".strip(" /"))
            it["h1"] = f"{title} / {extra}"
            it["card_title"] = it["h1"]


def _card_title(item: dict, place: str | None) -> str:
    label = PROPERTY_TYPE_LABELS.get(item.get("property_type"), "Nekretnina")
    bits = [label]
    if item.get("area_m2"):
        bits.append(f"{float(item['area_m2']):,.0f} m²".replace(",", " "))
    if place:
        bits.append(f"— {place}")
    return " ".join(bits)


def _meta_description(item: dict, place: str) -> str:
    """Jedinstveni, čitljivi meta opis. Rečenice se spajaju točkom, ne zarezom,
    da ne nastane 'Sudska dražba, Ovrha., Službeni podaci'."""
    clause = [PROPERTY_TYPE_LABELS.get(item.get("property_type"), "Nekretnina")]
    if item.get("area_m2"):
        clause.append(f_area(item["area_m2"]))
    clause.append(f"u mjestu {place}" if item.get("city") else f"— {place}")
    if item.get("opening_price_eur"):
        clause.append(f"početna cijena {f_eur(item['opening_price_eur'])}")
    if item.get("discount_pct") is not None and not item.get("discount_suspicious"):
        clause.append(f"{f_pct(item['discount_pct'])} ispod procjene")

    procedure = PROCEDURE_LABELS.get(item.get("procedure_type"), "").lower()
    sentences = [
        ", ".join(clause),
        f"Sudska dražba ({procedure})" if procedure and procedure != "ostalo"
        else "Sudska dražba",
        "Službeni podaci FINA Očevidnika",
    ]
    return (". ".join(s.strip(" .,") for s in sentences if s.strip(" .,")) + ".")[:300]


def _sort_for_display(items: list[dict]) -> list[dict]:
    order = {"u_tijeku": 0, "najavljeno": 1, "bez_termina": 2, "zavrseno": 3}
    return sorted(
        items,
        key=lambda x: (
            order.get(x.get("status"), 9),
            -(float(x["discount_pct"]) if x.get("discount_pct") is not None
              and not x.get("discount_suspicious") else -1),
        ),
    )


def _avg_discount(items: list[dict]) -> float | None:
    vals = [float(d["discount_pct"]) for d in items
            if d.get("discount_pct") is not None and not d.get("discount_suspicious")]
    return round(sum(vals) / len(vals), 1) if vals else None


def _stats_row(items: list[dict]) -> list[dict]:
    live = sum(1 for d in items if d.get("status") == "u_tijeku")
    avg = _avg_discount(items)
    prices = [float(d["opening_price_eur"]) for d in items if d.get("opening_price_eur")]
    row = [{"label": "Predmeta", "value": len(items)}]
    if live:
        row.append({"label": "U tijeku", "value": live})
    if avg is not None:
        row.append({"label": "Prosječan popust", "value": f_pct(avg)})
    if prices:
        row.append({"label": "Najniža početna cijena", "value": f_eur(min(prices))})
    return row


def _iso(v, date_only: bool = False) -> str | None:
    if not v:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, datetime):
        return v.date().isoformat() if date_only else v.isoformat()
    return v.isoformat()


def _xml(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))
