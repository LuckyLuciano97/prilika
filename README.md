# Licita — Croatia's foreclosure & auction property deal flow, in one place

Every property sold at judicial auction in Croatia — in enforcement (*ovrha*) and
bankruptcy (*stečaj*) proceedings — is published in an official public registry.
That registry is legally public, free, and machine-readable. It is also close to
unusable: no location column, no area column, no status, no property type, a
free-text description field, and a web app behind a reCAPTCHA with a 100-result cap.

Licita turns it into something you can actually search: **11,089 sale items**,
normalised, deduplicated, geocoded to county and town, with discount-vs-appraisal
computed and repeat auctions linked — regenerated daily into a fast static site of
**2,926 pages**, all in Croatian, with **zero personal data**.

The public site is in Croatian (`licita.hr`); this README is in English.

```bash
pip install -r requirements.txt
cp .env.example .env          # add your PostgreSQL connection string
createdb -U postgres licita
python run.py                 # ingest -> redact -> normalise -> track -> store -> build
python validate.py            # 12 checks, exits non-zero on failure
```

---

## Numbers from the last real run

Source snapshot **2026-08-05**, official CSV export, `sha256 06013bb9c325…`,
**10,329,500 bytes**, fetched in 0.46 s. Full pipeline: **17.2 s**.

| | |
|---|---|
| Rows in official CSV | 11,091 |
| Distinct sale items after dedup | **11,089** (2 byte-level duplicates collapsed) |
| Active (not finished) | **2,462** |
| — live auctions right now | **136** |
| — announced | 551 |
| — no auction window set | 1,775 |
| Finished (kept for price history) | 8,627 |
| Counties covered | **21 of 21** |
| Items with a resolved county | 9,727 (87.7%) |
| Average discount vs appraisal (all items) | **32.22%** |
| Repeat-auction groups linked | 95 |
| Pages generated | **2,926** |
| Personal data points removed | 417 |

Property mix: 3,412 agricultural land · 2,514 houses · 1,499 apartments ·
901 land · 815 commercial · 687 movables · 387 garages · 341 other ·
309 forest land · 166 building land · 58 rights.

---

## The data source, and why reuse is permitted

**FINA — Očevidnik nekretnina i pokretnina** (`ponip.fina.hr`), the official
registry of property sold in enforcement and bankruptcy proceedings.

Phase 0 verified this before a line of pipeline code was written
([docs/source-notes.md](docs/source-notes.md)):

- **Official CSV export** at `/ocevidnik-web/preuzmi/csv` — HTTP 200,
  `text/csv;charset=UTF-8`, 10.3 MB, **no authentication, no CAPTCHA**, one plain GET.
- **Licence: "Otvorena dozvola (OD)"** — published by FINA on
  [data.gov.hr](https://data.gov.hr/ckan/hr/dataset/ocevidnik-nekretnina-i-pokretnina),
  classified as an EU **high-value dataset**. Reuse, including commercial reuse, is permitted.
- `robots.txt` returns 404 — no crawl directives declared.
- The registry is free to all: *"svim zainteresiranim osobama bez naknade"*.

**The interactive search is never touched.** It has a reCAPTCHA and a 100-result
cap; the CSV export covers everything needed, so there is nothing to bypass and
nothing is bypassed. One GET per day, descriptive User-Agent, halt-and-report on
403/429/503.

---

## Zero personal data — the rule this project is built around

**The build spec assumed the export contains no personal data. That assumption was
wrong, and finding out was the most important result of Phase 0.**

Scanning all 26 columns × 11,091 rows of the official export found:

| Pattern | Hits | Worst column |
|---|---|---|
| **OIB** (national ID number) | 222 | `Opis`, `Napomena uz uvjete prodaje` |
| **IBAN** | 728 | `Ostali uvjeti za jamčevinu` (292) |
| **Email addresses** | 1,136 | `Razgledavanje` (1,074) |
| **Phone numbers** | 2,505 | `Razgledavanje` (2,480) |

Real rows contain things like a pledge creditor's *name + national ID + home
address*, and a bankruptcy trustee's *personal Gmail and mobile*. The column the
spec described as "institution, not a person" contains **46 named public notaries**.

So "zero personal data" is **not a property of the source** — it has to be enforced.
[`sanitise.py`](sanitise.py) runs *before* anything reaches the database, on a
**whitelist** basis:

- **Six free-text columns are dropped entirely** and have **no column in the schema**,
  so they cannot be written by accident.
- `Opis` is kept — it is the only source of location and area — but redacted:
  OIB, IBAN, email, phone, person names tied to a role, and the **debtor's home
  address clause** (`iz [town], [street and number]`) are removed.
- Notary names collapse to the role, `Javni bilježnik`.
- A Croatian given-name gazetteer runs as a second pass, deliberately skipping
  street contexts — Croatian streets are named after people, and the *property's*
  address is exactly what makes a listing useful.

**The debtor's identity is protected. That is the point, and it is checked
mechanically on every run:** `validate.py` scans every text column in the database
*and* the visible text of all 2,926 generated pages, and **hard-fails** on a single hit.

Latest run: **0 hits in the database, 0 residual names, 0 hits across all pages.**

---

## What the source does not contain

Stated plainly, because inventing these would be worse than lacking them:

| Field | Reality |
|---|---|
| county / city / settlement | **No such column exists.** Derived from four fallible signals and graded by whether two of them agree (see below). High 6,749 · medium 2,724 · **low/conflicting 254** · unresolved 1,362, reported by name. |
| `area_m2` | No column. Parsed from description text — 9,834 of 11,089 items (88.7%), including `čhv` and `ha` conversion. |
| `status` | No column. Derived from auction start/end vs snapshot date. |
| **`current_bid_eur`** | **Not in the export at all** — visible only in the live app. Stored as `NULL`, shown nowhere, never estimated. |
| per-item deep link | Does not exist. Four URL patterns tested, all HTTP 404 — the app is session-based. Pages link to the registry and cite the auction ID for manual lookup. |

**Commercial-court seats are deliberately not used as property locations.** A
bankruptcy estate can hold property anywhere in Croatia, so inferring location from
the court would be invented precision. Those items stay "location not established"
and are counted.

**That choice costs more than the headline suggests, so here is the uncomfortable
number.** Location is unresolved for 12.3% of all items — but for **36.8% of
*active* ones** (902 of 2,448), because active listings skew heavily towards
bankruptcy sales run by commercial courts. `Lokacija nije utvrđena` is therefore the
largest bucket on the homepage. Filling it by falling back to the court's seat would
make the site look complete and be wrong; the honest version is visible instead.

### Location confidence is earned by agreement, not by which rule fired

There are four signals, each fallible: an explicit settlement mention in the prose,
the cadastral-municipality name, the land-registry department, and the municipal
court's seat. **Where the k.o. name and the court can both be derived, they
contradict each other 6.4% of the time** — so trusting whichever fired first
produced confident errors.

Grading now depends on corroboration: `visoka` for an explicit settlement mention
or two agreeing signals, `srednja` for a single uncorroborated one, and **`niska`
when signals actively conflict** — those pages carry a visible warning telling the
reader to verify against the registry rather than quietly picking a winner.

The name lookup itself is backed by an **official, licensed register**: the DZS
2021 census table of all 6,357 Croatian settlements with municipality, county and
population (`data/naselja.csv`, regenerated by `tools/build_naselja.py`; Otvorena
dozvola, provenance in that script's header). Census population also settles
same-name ties, but only at overwhelming odds: `Dugopolje` near Split (3,248
people) beats the hamlet near Gračac (17) at 191:1 — below a 20:1 ratio nothing
is guessed. A ready-made City of Zagreb cadastral CSV was still **rejected**
because its CKAN record carries `license_id: ""`; unlicensed data stays out no
matter how convenient. Still open: purely cadastral names that are no settlement
at all (`Vrapče Novo`, `Blato Novo`) resolve only when a land-registry or court
anchor corroborates them, and items whose description names nothing stay
unresolved and counted.

---

## Four bugs worth naming

Found by validation and by looking at the output, not by luck. All four are the kind
a reviewer would spot:

0. **Confidently wrong counties.** A fallback in the town resolver dropped the last
   word of a name, so the cadastral municipality `Velika Mlaka` matched the town
   `Velika` (Požeško-slavonska — it is actually Zagrebačka), `Blato Novo` matched
   `Blato` on Korčula (it is Zagreb), and `Sesvete Novo` matched `Sesvete`. These
   were published as **high** confidence. The fallback is gone, only a trailing
   ordinal may be stripped (`Novalja I` → `Novalja`), and confidence is now earned
   by agreement between signals rather than by which rule happened to fire.

1. **A 1000× price error.** The `Minimalna zakonska cijena` column is not
   consistently numeric — it mixes `39816.84`, Croatian `32.805,00`, dual-currency
   `59.725,26 EUR (449.999,97 HRK)`, and prose. Naive comma-stripping turned
   €32,805.00 into €32.81. **122 values were wrong by three orders of magnitude and
   1,112 were silently dropped**; the rewritten parser takes the EUR figure, treats
   the *last* separator as decimal, and returns `None` for prose rather than a guess.
2. **Phantom price changes.** Two runs over a byte-identical source reported 4 price
   changes. Cause: `NUMERIC(16,2)` rounds half-away-from-zero, Python `round()` rounds
   half-to-even, so 32.805 stored as 32.81 read back as a change. Money is now
   quantised at parse time. Two runs over the same snapshot now produce **exactly 0**
   changes — which is the real proof that a reported change means something.
3. **964 duplicate page titles.** Items with no area, price, or town collapsed to one
   title — 626 pages titled `Pokretnina — Hrvatska`. Titles are now disambiguated by
   case reference, which is also what you need to find the item in the registry.

An earlier repeat-auction fingerprint truncated descriptions to 220 characters and
merged distinct parcels from one bankruptcy, inventing "97% price drops" between
unrelated properties. It now uses the full description.

---

## How it works

```
run.py          ingest -> redact -> normalise -> link repeats -> store -> build site
ingest.py       official CSV export loader; halt-and-report, size/row floors
sanitise.py     personal-data redaction (whitelist). Runs FIRST, always.
normalise.py    location, area, money, discount, status, property type, stable keys
croatia.py      21 counties, ~700 towns, 145 issuing bodies -> county mapping
track.py        new/changed detection, price_history, repeat-auction linking
store.py        PostgreSQL upsert + history (only writer of the items table)
generate_site.py static site: property/county/city/category/blog + sitemap
site/           Jinja2 templates and CSS (no external requests at all)
validate.py     13 checks; exits non-zero; report committed including failures
```

`generate_site.py` sits at the top level rather than inside `site/` because `site`
is a Python standard-library module name and shadowing it breaks imports.

**Stable item keys.** `ID nadmetanja` alone is not unique — 10 cases share an ID
across genuinely different items. Keys combine case reference, auction ID,
description, appraisal, round, decision date and scope: everything stable, nothing
that legitimately changes. A price change must never look like a new listing.

---

## SEO surface

2,926 pages, every one with a unique title and meta description, one `<h1>`,
canonical URL, Open Graph tags, and valid JSON-LD — verified, not asserted.

- `RealEstateListing` + `Offer` per property (price, currency, availability,
  `floorSize` in `MTK`), `BreadcrumbList` on every page, `CollectionPage` +
  `ItemList` on listings, `BlogPosting` on articles.
- URLs: `/nekretnine/{županija}/{grad}/{slug}/`, ASCII-slugged, content in full
  Croatian diacritics.
- `sitemap.xml` regenerated each run and covering **every** page (0 missing).
- Croatian numeral agreement is handled (`1 nekretnina` / `3 nekretnine` /
  `7 nekretnina`) — the tell of machine-written Croatian is getting this wrong.
- Finished auctions stay in the database for price history but get **no page** —
  8,600 pages about 2016 auctions is thin content that helps nobody.

---

## Validation

`python validate.py` — output committed verbatim to
[validation_report.txt](validation_report.txt), including the warning.

| # | Check | Result |
|---|---|---|
| 1 | Count reconciliation | PASS — 11,089 = 11,091 rows − 2 duplicates |
| 2 | Istria spot check, field by field | PASS — 15 items × 10 fields, 0 differences |
| 3 | Normalisation coverage | PASS — unresolved listed by name and count |
| 4 | **Zero personal data (DB + every page)** | **PASS — 0 hits** |
| 5 | Detector canary | PASS — planted record is caught |
| 6 | Discount arithmetic | PASS — 9,672 rows, 0 deviations |
| 7 | Repeat auction linked | PASS — `OVR-12767/2016`, price falls |
| 8 | No cross-case merging | PASS — 0 groups mix case files |
| 9 | SEO output | PASS — 2,926 pages, 0 duplicate titles, 0 bad JSON-LD, 0 missing from sitemap |
| 10 | Diacritics on disk | PASS |
| 11 | No phantom price changes | PASS — 2 runs, same source, 0 changes |
| 12 | Price-tracking mechanism | PASS — controlled test |
| 13 | Price change across real days | **WARN — not yet observed** |

**On check 13, honestly:** proving a price change between two *different* daily
snapshots requires runs on two different days. That has not happened yet. The
mechanism is proven by a controlled test and by the absence of false positives, and
the check will stay a WARN until a real multi-day change is recorded. It is not
marked PASS in the meantime.

Check 2 compares the database against the raw official file field by field. It is
not a second scrape of the web app: that would mean touching the reCAPTCHA-protected
search, which this project does not do.

---

## Roadmap

Operational cadence, the staleness limit and the reasoning behind both are in
[docs/operations.md](docs/operations.md).

- **Phase 2 — alerts and subscriptions.** Email alerts on new items by county, type
  and discount threshold. The hooks are placed on every page; no payment wall,
  no accounts yet.
- **Phase 3 — market context.** Porezna transaction trends and the Eurostat house
  price index alongside auction prices, to show discount against *market* value
  rather than only against the court's appraisal.

Non-goals, deliberately: no private-portal scraping (Njuškalo and similar), no
CAPTCHA solving, no anti-bot evasion, no debtor-identifying data. The legal
cleanliness is a feature, not an accident.

---

## Working together

I build data pipelines that hold up when someone checks them: legal-first sourcing,
personal-data handling that survives scrutiny, and validation that proves the claims
instead of restating them. If you have a public or semi-public dataset that would be
worth more as a product than as a download, I can help.

**Nexi Studio** — [support@nexistudio.dev](mailto:support@nexistudio.dev)

MIT licensed. Source data © FINA, reused under
[Otvorena dozvola](http://data.gov.hr/otvorena-dozvola). Licita is not affiliated
with FINA and is not a party to any sale proceeding.
