"""Provjere koje dokazuju tvrdnje projekta.

Ništa se ne tvrdi bez brojke. Izlazni kod je različit od nule ako ijedna
provjera padne, a izvještaj (validation_report.txt) commita se uključujući
padove — ako nešto ne valja, to se vidi, ne skriva.

Provjera br. 4 (osobni podaci) je tvrdi prekid: ona sama ruši cijeli proces.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import config
import ingest
import normalise as N
import sanitise as S
import store
import track as T

REPORT = config.ROOT / "validation_report.txt"

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.results: list[tuple[str, str, str]] = []

    def head(self, text: str) -> None:
        self.lines += ["", "=" * 78, text, "=" * 78]

    def say(self, text: str = "") -> None:
        self.lines.append(text)

    def check(self, name: str, status: str, detail: str = "") -> None:
        self.results.append((name, status, detail))
        self.lines.append(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))

    @property
    def failed(self) -> list[tuple[str, str, str]]:
        return [r for r in self.results if r[1] == FAIL]

    def write(self) -> None:
        total = len(self.results)
        npass = sum(1 for r in self.results if r[1] == PASS)
        nwarn = sum(1 for r in self.results if r[1] == WARN)
        nfail = len(self.failed)
        header = [
            "LICITA — IZVJEŠTAJ VALIDACIJE",
            f"Generirano: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Rezultat:   {npass} PASS · {nwarn} WARN · {nfail} FAIL  (ukupno {total})",
        ]
        if nfail:
            header.append("")
            header.append("PALE SU PROVJERE:")
            header += [f"  - {n}: {d}" for n, _, d in self.failed]
        REPORT.write_text("\n".join(header + self.lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------

def load_source_independently() -> tuple[list[dict], str]:
    """Ponovno pročitaj sirovi službeni CSV, neovisno o pipelineu.

    Ovo je referentna istina za usporedbu — ne koristi se ništa iz baze.
    """
    path = config.RAW_DIR / "ponip_ocevidnik.csv"
    if not path.exists():
        raise SystemExit("Nema cache/raw/ponip_ocevidnik.csv — pokreni run.py najprije.")
    raw = path.read_bytes().decode("utf-8-sig")
    rows = [r for r in csv.DictReader(io.StringIO(raw), delimiter=";")
            if any((v or "").strip() for v in r.values())]
    return rows, ingest.snapshot_date(rows)


def main() -> int:
    rep = Report()
    src_rows, snapshot = load_source_independently()

    with store.connect() as conn:
        db_items = store.fetch_items(conn)
        db_counts = store.counts(conn)

        # ------------------------------------------------------------------
        rep.head("1. USKLAĐENJE BROJEVA — je li sve iz izvora stiglo u bazu")
        # Neovisno preračunaj ključeve iz sirovog CSV-a.
        recomputed = {}
        for r in src_rows:
            clean, _ = S.sanitise_row(r)
            it = N.normalise_item(clean)
            recomputed.setdefault(it["item_key"], 0)
            recomputed[it["item_key"]] += 1
        expected_unique = len(recomputed)
        dupes = sum(v - 1 for v in recomputed.values())

        rep.say(f"  redaka u službenom CSV-u:              {len(src_rows):,}")
        rep.say(f"  doslovnih duplikata (isti stabilni ključ): {dupes}")
        rep.say(f"  očekivano jedinstvenih stavki:         {expected_unique:,}")
        rep.say(f"  stavki u bazi:                         {len(db_items):,}")
        if len(db_items) == expected_unique:
            rep.check("Usklađenje broja stavki", PASS,
                      f"{len(db_items):,} = {len(src_rows):,} redaka − {dupes} duplikata")
        else:
            rep.check("Usklađenje broja stavki", FAIL,
                      f"baza {len(db_items):,} ≠ očekivano {expected_unique:,}")

        active = [i for i in db_items if i["status"] in ("najavljeno", "u_tijeku")]
        rep.say(f"  aktivnih nadmetanja (najavljeno + u tijeku): {len(active):,}")
        rep.say("  napomena: FINA navodi ~1 000 aktivnih stavki; izvoz je pun snimak")
        rep.say(f"           registra ({len(db_items):,} stavki) uključujući povijest.")
        by_status = Counter(i["status"] for i in db_items)
        for k, v in by_status.most_common():
            rep.say(f"    {k:<16} {v:,}")

        # ------------------------------------------------------------------
        rep.head("2. UZORAK ISTRE — vjernost prijenosa iz izvora u bazu")
        rep.say("  Interaktivna tražilica Očevidnika ima reCAPTCHA-u i NE dira se.")
        rep.say("  Zato se vjernost dokazuje usporedbom baze sa sirovom službenom")
        rep.say("  datotekom, polje po polje, na istarskim predmetima.")
        rep.say()

        istria_src = []
        for r in src_rows:
            clean, _ = S.sanitise_row(r)
            it = N.normalise_item(clean)
            if it.get("county") == "Istarska županija":
                istria_src.append(it)
        sample = sorted(istria_src, key=lambda x: x["item_key"])[:15]
        db_by_key = {i["item_key"]: i for i in db_items}

        compared = mismatch = 0
        fields = ["case_ref", "county", "city", "estimated_value_eur",
                  "opening_price_eur", "area_m2", "auction_start", "auction_end",
                  "property_type", "status"]
        for s in sample:
            d = db_by_key.get(s["item_key"])
            if not d:
                mismatch += 1
                rep.say(f"    NEDOSTAJE u bazi: {s['item_key']} ({s['case_ref']})")
                continue
            bad = []
            for f in fields:
                a, b = s.get(f), d.get(f)
                if not _same(a, b):
                    bad.append(f"{f}: izvor={a!r} baza={b!r}")
            compared += 1
            if bad:
                mismatch += 1
                rep.say(f"    RAZLIKA {s['case_ref']}: " + "; ".join(bad[:3]))
        rep.say(f"  usporedeno istarskih predmeta: {compared} (od {len(istria_src)} ukupno)")
        rep.say(f"  polja po predmetu: {len(fields)}")
        if sample:
            ex = sample[0]
            rep.say(f"  primjer: {ex['case_ref']} · {ex.get('city')} · "
                    f"{ex.get('area_m2')} m² · procjena {ex.get('estimated_value_eur')} € "
                    f"· početna {ex.get('opening_price_eur')} €")
        rep.check("Istra: vjernost prijenosa", PASS if mismatch == 0 else FAIL,
                  f"{compared} predmeta × {len(fields)} polja, {mismatch} razlika")

        # ------------------------------------------------------------------
        rep.head("3. POKRIVENOST NORMALIZACIJE")
        cov_fields = ["county", "city", "cadastral_municipality", "area_m2",
                      "estimated_value_eur", "opening_price_eur", "discount_pct",
                      "auction_id", "auction_start", "auction_end", "viewing_time",
                      "property_type", "procedure_type", "status"]
        n = len(db_items)
        for f in cov_fields:
            filled = sum(1 for i in db_items if i.get(f) not in (None, "", []))
            rep.say(f"  {f:<26} {filled:6,}/{n:,}  {100*filled/n:5.1f}%")

        conf = Counter(i.get("location_confidence") for i in db_items)
        rep.say()
        rep.say("  pouzdanost lokacije:")
        for k, v in conf.most_common():
            rep.say(f"    {str(k):<10} {v:6,}  {100*v/n:5.1f}%")

        unresolved = [i for i in db_items if not i.get("county")]
        rep.say()
        rep.say(f"  BEZ UTVRĐENE ŽUPANIJE: {len(unresolved):,} stavki "
                f"({100*len(unresolved)/n:.1f}%) — razlozi poimence:")
        why = Counter()
        for i in unresolved:
            why[i.get("issuer_type") or "nepoznato"] += 1
        for k, v in why.most_common():
            rep.say(f"    {k:<20} {v:6,}")
        rep.say("  Trgovački sudovi i bilježnici namjerno se NE koriste kao izvor")
        rep.say("  lokacije: stečajna masa može držati nekretnine bilo gdje u RH.")
        top_unres = Counter(i.get("issuer_name") for i in unresolved).most_common(8)
        rep.say("  najčešća tijela bez lokacije:")
        for name, cnt in top_unres:
            rep.say(f"    {cnt:5,}  {name}")
        rep.check("Pokrivenost lokacije prijavljena poimence", PASS,
                  f"{n - len(unresolved):,} sa županijom, {len(unresolved):,} bez")

        # ------------------------------------------------------------------
        rep.head("4. NULA OSOBNIH PODATAKA — tvrdi prekid")
        rep.say("  Skenira se SVAKO tekstualno polje u bazi i SVAKA generirana stranica.")
        rep.say()

        db_hits: list[str] = []
        text_fields = ["description", "issuer_name", "viewing_time", "location_raw",
                       "cadastral_municipality", "case_ref", "sale_method", "scope"]
        for i in db_items:
            for f in text_fields:
                v = i.get(f)
                if not isinstance(v, str):
                    continue
                for kind, hit in S.scan(v):
                    db_hits.append(f"{i['item_key']}.{f}: {kind} → {hit[:40]}")
        rep.say(f"  polja skenirana u bazi: {len(db_items):,} × {len(text_fields)}")
        rep.say(f"  pogodaka u bazi: {len(db_hits)}")
        for h in db_hits[:10]:
            rep.say(f"    {h}")

        residual = []
        for i in db_items:
            for nm in S.residual_person_names(i.get("description") or ""):
                residual.append(f"{i['item_key']}: {nm}")
        rep.say(f"  preostalih osobnih imena po rječniku: {len(residual)}")
        for r in residual[:10]:
            rep.say(f"    {r}")

        html_hits: list[str] = []
        pages = list(config.OUTPUT_DIR.rglob("*.html"))
        for p in pages:
            text = p.read_text(encoding="utf-8")
            body = re.sub(r"<script.*?</script>", " ", text, flags=re.S)
            visible = re.sub(r"<[^>]+>", " ", body)
            for kind, hit in S.scan(visible):
                # e-mail kontakta projekta je naša adresa, ne osobni podatak izvora
                if hit.strip().lower() == config.CONTACT_EMAIL.lower():
                    continue
                html_hits.append(f"{p.relative_to(config.OUTPUT_DIR)}: {kind} → {hit[:40]}")
        rep.say(f"  generiranih stranica skenirano: {len(pages):,}")
        rep.say(f"  pogodaka na stranicama: {len(html_hits)}")
        for h in html_hits[:10]:
            rep.say(f"    {h}")

        total_leaks = len(db_hits) + len(residual) + len(html_hits)
        rep.check("Nula osobnih podataka (baza + stranice)",
                  PASS if total_leaks == 0 else FAIL,
                  f"{total_leaks} pogodaka (baza {len(db_hits)}, imena {len(residual)}, "
                  f"HTML {len(html_hits)})")

        # kontrolni test detektora: mora pronaći podmetnuti podatak
        canary = ("Ovršenik Ivan Horvat, OIB: 12345678901, iz Zagreba, "
                  "Ilica 5, tel 098/123-456, mail ivan.horvat@example.com")
        found = {k for k, _ in S.scan(canary)}
        expect = {"oib_labelled", "oib_bare", "email", "phone_mobile"}
        rep.check("Detektor osobnih podataka radi (kontrolni uzorak)",
                  PASS if expect & found and len(found) >= 3 else FAIL,
                  f"pronađeno: {sorted(found)}")

        # ------------------------------------------------------------------
        rep.head("5. ISPRAVNOST IZRAČUNA POPUSTA")
        checked = bad = 0
        for i in db_items:
            est, op, disc = i.get("estimated_value_eur"), i.get("opening_price_eur"), i.get("discount_pct")
            if est is None or op is None or disc is None:
                continue
            checked += 1
            expected = round((float(est) - float(op)) / float(est) * 100, 2)
            if abs(expected - float(disc)) > 0.01:
                bad += 1
                if bad <= 5:
                    rep.say(f"    {i['case_ref']}: očekivano {expected}, u bazi {disc}")
        rep.say(f"  provjereno redaka: {checked:,}")
        rep.say(f"  odstupanja: {bad}")
        susp = [i for i in db_items if i.get("discount_suspicious")]
        rep.say(f"  označeno kao sumnjivo (ne prikazuje se kao prilika): {len(susp):,}")
        if susp:
            s0 = susp[0]
            rep.say(f"    primjer: {s0['case_ref']} procjena {s0['estimated_value_eur']} € "
                    f"→ početna {s0['opening_price_eur']} €")
            rep.say("    (0,13 € = 1 kuna po tečaju 7,53450 — zaostatak iz prijelaza na euro)")
        rep.check("Izračun popusta", PASS if bad == 0 else FAIL,
                  f"{checked:,} provjereno, {bad} odstupanja")

        # ------------------------------------------------------------------
        rep.head("6. POVEZIVANJE PONOVLJENIH DRAŽBI")
        groups = defaultdict(list)
        for i in db_items:
            if i.get("repeat_group"):
                groups[i["repeat_group"]].append(i)
        multi = {k: v for k, v in groups.items() if len(v) > 1}
        with_prog = {k: v for k, v in multi.items()
                     if len({x.get("auction_round") for x in v if x.get("auction_round")}) > 1}
        self_declared = [i for i in db_items if (i.get("auction_round_no") or 1) >= 2]

        rep.say(f"  povezanih skupina (ista nekretnina, više pokušaja): {len(multi):,}")
        rep.say(f"  skupina s napredovanjem dražbe (Prva→Druga→…):      {len(with_prog):,}")
        rep.say(f"  stavki koje SAME deklariraju ponovljenu dražbu (EJD ≥ Druga): "
                f"{len(self_declared):,}")
        rep.say()
        rep.say("  Poštena granica: izvoz je snimak. Raniji krug često više NIJE u")
        rep.say("  registru, pa se ne može povezati iako se zna da je postojao.")
        rep.say("  Zato se odvojeno prijavljuje 'povezano' i 'samodeklarirano'.")
        rep.say()

        known = [v for v in with_prog.values()
                 if any(x["case_ref"] == "OVR-12767/2016" for x in v)]
        if known:
            g = sorted(known[0], key=lambda x: x.get("repeat_seq") or 0)
            rep.say(f"  poznati slučaj OVR-12767/2016 (procjena {g[0]['estimated_value_eur']} €):")
            for x in g:
                rep.say(f"    {x.get('repeat_seq')}. {x.get('auction_round'):<8} "
                        f"početna {x.get('opening_price_eur')} € · {x.get('status')}")
            rep.check("Ponovljena dražba: poznati slučaj povezan", PASS,
                      f"OVR-12767/2016 — {len(g)} pokušaja, cijena pada")
        else:
            rep.check("Ponovljena dražba: poznati slučaj povezan", FAIL,
                      "OVR-12767/2016 nije pronađen kao povezana skupina")

        wrong = [k for k, v in multi.items() if len({x["case_ref"] for x in v}) > 1]
        rep.check("Nema pogrešnog spajanja različitih spisa", PASS if not wrong else FAIL,
                  f"{len(wrong)} skupina miješa spise")

        # ------------------------------------------------------------------
        rep.head("7. SEO IZLAZ")
        titles: Counter = Counter()
        metas: Counter = Counter()
        no_title = no_meta = no_canon = bad_h1 = bad_jsonld = 0
        diacritic_ok = 0
        page_paths = []

        for p in pages:
            html = p.read_text(encoding="utf-8")
            rel = "/" + str(p.relative_to(config.OUTPUT_DIR).parent).replace("\\", "/").strip(".")
            rel = (rel.rstrip("/") + "/").replace("//", "/")
            page_paths.append(rel)

            m = re.search(r"<title>(.*?)</title>", html, re.S)
            if not m or not m.group(1).strip():
                no_title += 1
            else:
                titles[m.group(1).strip()] += 1
            m = re.search(r'<meta name="description" content="(.*?)"', html, re.S)
            if not m or len(m.group(1).strip()) < 40:
                no_meta += 1
            else:
                metas[m.group(1).strip()] += 1
            if not re.search(r'<link rel="canonical" href="https?://', html):
                no_canon += 1
            if len(re.findall(r"<h1[ >]", html)) != 1:
                bad_h1 += 1
            for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>',
                                    html, re.S):
                try:
                    obj = json.loads(block)
                    if "@context" not in obj or "@type" not in obj:
                        bad_jsonld += 1
                except json.JSONDecodeError:
                    bad_jsonld += 1
            if any(c in html for c in "čćžšđČĆŽŠĐ"):
                diacritic_ok += 1

        dup_titles = {t: c for t, c in titles.items() if c > 1}
        dup_metas = {t: c for t, c in metas.items() if c > 1}

        rep.say(f"  stranica ukupno:              {len(pages):,}")
        rep.say(f"  bez <title>:                  {no_title}")
        rep.say(f"  ponovljenih <title>:          {len(dup_titles)}")
        for t, c in list(dup_titles.items())[:5]:
            rep.say(f"      {c}× {t[:80]}")
        rep.say(f"  bez / prekratkog meta opisa:  {no_meta}")
        rep.say(f"  ponovljenih meta opisa:       {len(dup_metas)}")
        for t, c in list(dup_metas.items())[:5]:
            rep.say(f"      {c}× {t[:80]}")
        rep.say(f"  bez canonical:                {no_canon}")
        rep.say(f"  bez točno jednog <h1>:        {bad_h1}")
        rep.say(f"  neispravnih JSON-LD blokova:  {bad_jsonld}")
        rep.say(f"  stranica s dijakritikom:      {diacritic_ok:,}/{len(pages):,}")

        sm = (config.OUTPUT_DIR / "sitemap.xml")
        sitemap_urls = set(re.findall(r"<loc>(.*?)</loc>", sm.read_text(encoding="utf-8"))) \
            if sm.exists() else set()
        sitemap_paths = {u.replace(config.SITE_URL, "") or "/" for u in sitemap_urls}
        missing = [p for p in page_paths if p not in sitemap_paths]
        rep.say(f"  URL-ova u sitemap.xml:        {len(sitemap_urls):,}")
        rep.say(f"  stranica koje nedostaju u sitemapu: {len(missing)}")
        for p in missing[:5]:
            rep.say(f"      {p}")

        seo_ok = (no_title == 0 and no_meta == 0 and no_canon == 0
                  and bad_h1 == 0 and bad_jsonld == 0 and not missing
                  and not dup_titles and not dup_metas)
        rep.check("SEO izlaz", PASS if seo_ok else FAIL,
                  f"{len(pages):,} stranica; {len(dup_titles)} duplih naslova, "
                  f"{no_meta} loših opisa, {bad_jsonld} loših JSON-LD, "
                  f"{len(missing)} izvan sitemapa")

        # dijakritika mora preživjeti do diska
        probe = config.OUTPUT_DIR / "index.html"
        if probe.exists():
            t = probe.read_text(encoding="utf-8")
            ok = "dražbi" in t or "dražba" in t.lower() or "županij" in t
            rep.check("Dijakritika ispravno zapisana", PASS if ok else FAIL,
                      "pronađeni hrvatski znakovi u početnoj stranici" if ok
                      else "hrvatski znakovi nisu pronađeni")

        # ------------------------------------------------------------------
        rep.head("8. INTEGRITET POVIJESTI CIJENA")
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM runs")
            n_runs = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM price_history")
            n_hist = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM item_events")
            n_events = cur.fetchone()[0]
            cur.execute(
                "SELECT item_key, field, old_value, new_value, pct_change "
                "FROM price_history ORDER BY id DESC LIMIT 5"
            )
            recent = cur.fetchall()

        rep.say(f"  pokretanja zabilježenih: {n_runs}")
        rep.say(f"  redaka u price_history:  {n_hist}")
        rep.say(f"  događaja:                {n_events}")
        for r in recent:
            rep.say(f"    {r[0]} {r[1]}: {r[2]} → {r[3]} ({r[4]} %)")

        # Kontrolirani test mehanizma: promijeni cijenu jedne stavke i dokaži
        # da se promjena zabilježi. Ovo dokazuje MEHANIZAM, ne protok vremena.
        probe_item = next((i for i in db_items if i.get("opening_price_eur")), None)
        mech_ok = False
        if probe_item:
            existing = {probe_item["item_key"]: {
                "status": probe_item["status"],
                "opening_price_eur": float(probe_item["opening_price_eur"]),
                "current_bid_eur": None,
                "estimated_value_eur": probe_item.get("estimated_value_eur"),
                "minimum_price_eur": probe_item.get("minimum_price_eur"),
            }}
            changed = dict(probe_item)
            changed["opening_price_eur"] = float(probe_item["opening_price_eur"]) * 0.8
            diff = T.diff_against_previous([changed], existing)
            mech_ok = any(c["field"] == "opening_price_eur" for c in diff["price_changes"])
            if mech_ok:
                c = diff["price_changes"][0]
                rep.say(f"  kontrolirani test: {c['field']} {c['old_value']} → "
                        f"{c['new_value']} ({c['pct_change']} %) — promjena uhvaćena")

        with conn.cursor() as cur:
            cur.execute("SELECT count(DISTINCT source_sha256) FROM runs "
                        "WHERE source_sha256 IS NOT NULL")
            distinct_sources = cur.fetchone()[0]

        rep.say()
        rep.say(f"  različitih verzija izvora među pokretanjima: {distinct_sources}")

        if n_runs < 2:
            rep.check("Povijest cijena kroz vrijeme", WARN,
                      f"samo {n_runs} pokretanje — promjena kroz vrijeme još nije "
                      f"opažena; mehanizam dokazan kontroliranim testom "
                      f"({'radi' if mech_ok else 'NE radi'})")
        elif distinct_sources < 2:
            rep.say("  Sva pokretanja koristila su ISTI snimak izvora (isti sha256),")
            rep.say("  pa je nula zabilježenih promjena ispravan rezultat, a ne propust.")
            rep.say("  Da je zabilježena promjena, to bi značilo da detektor lažno")
            rep.say("  prijavljuje — što je i bilo prije ispravka zaokruživanja.")
            rep.check("Povijest cijena: nema lažnih promjena nad istim izvorom",
                      PASS if n_hist == 0 else FAIL,
                      f"{n_runs} pokretanja nad istim sha256 → {n_hist} promjena "
                      f"(očekivano 0)")
            rep.check("Povijest cijena kroz vrijeme (stvarni protok dana)", WARN,
                      "još nije opažena promjena između DVA RAZLIČITA dnevna snimka — "
                      "za to treba pokretanje u dva različita dana; mehanizam je "
                      "dokazan kontroliranim testom")
        else:
            rep.check("Povijest cijena kroz vrijeme",
                      PASS if n_hist > 0 else WARN,
                      f"{n_hist} promjena kroz {n_runs} pokretanja "
                      f"({distinct_sources} različitih snimaka izvora)")
        rep.check("Mehanizam praćenja cijene radi", PASS if mech_ok else FAIL,
                  "kontrolirani test promjene cijene")

    # ----------------------------------------------------------------------
    rep.head("SAŽETAK")
    for name, status, detail in rep.results:
        rep.say(f"  {status:<5} {name}" + (f" — {detail}" if detail else ""))

    rep.write()
    nfail = len(rep.failed)
    print("\n".join(rep.lines[-(len(rep.results) + 3):]))
    print(f"\nIzvještaj zapisan u {REPORT}")
    if nfail:
        print(f"PALO {nfail} provjera.", file=sys.stderr)
        return 1
    return 0


def _same(a, b) -> bool:
    """Usporedba tolerantna na tip (Decimal iz baze vs float iz parsera)."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, (int, float)) or isinstance(b, (int, float)):
        try:
            return abs(float(a) - float(b)) < 0.01
        except (TypeError, ValueError):
            pass
    if isinstance(a, datetime) or isinstance(b, datetime):
        try:
            return str(a)[:19] == str(b)[:19]
        except Exception:
            return False
    return str(a).strip() == str(b).strip()


if __name__ == "__main__":
    config.load_dotenv()
    sys.exit(main())
