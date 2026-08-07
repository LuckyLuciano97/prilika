"""Jedna ulazna točka koju cron poziva.

  preuzmi -> redigiraj -> normaliziraj -> poveži -> upiši -> generiraj stranice

Redoslijed nije proizvoljan: redakcija osobnih podataka ide PRIJE svega
ostaloga, tako da nijedan kasniji korak nikad ne vidi sirovi tekst.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import date, datetime

import config
import ingest
import normalise as N
import sanitise as S
import store
import track as T
from generate_site import ACTIVE_STATUSES, SiteBuilder


def main() -> int:
    ap = argparse.ArgumentParser(description="Prilika — dnevni pipeline")
    ap.add_argument("--force", action="store_true", help="ignoriraj cache, preuzmi ponovno")
    ap.add_argument("--skip-site", action="store_true", help="samo podaci, bez generiranja stranica")
    ap.add_argument("--no-db", action="store_true",
                    help="preskoči bazu (samo za provjeru obrade i stranica)")
    ap.add_argument("--rebuild-only", action="store_true",
                    help="ne dohvaćaj izvor; osvježi status prema sadašnjem "
                         "trenutku i ponovno generiraj stranice iz cachea")
    ap.add_argument("--allow-stale", action="store_true",
                    help="dopusti generiranje i kad je snimak stariji od granice")
    args = ap.parse_args()

    config.load_dotenv()
    t0 = time.time()
    print("=" * 70)
    print("PRILIKA — dnevni pipeline")
    print("=" * 70)

    # ---- 1. preuzimanje -------------------------------------------------
    print("\n[1/6] Preuzimanje službenog CSV izvoza")
    if args.rebuild_only:
        print("  --rebuild-only: izvor se NE dohvaća, koristi se lokalni cache")
    try:
        blob, meta = ingest.download(
            force=args.force,
            cache_hours=10 ** 6 if args.rebuild_only else 6,
        )
        rows = ingest.parse(blob)
    except ingest.SourceError as exc:
        print(f"\nGREŠKA IZVORA — pipeline staje:\n  {exc}", file=sys.stderr)
        return 2
    snapshot = ingest.snapshot_date(rows)
    print(f"  redaka: {len(rows):,} · stanje na dan: {snapshot}")

    # ---- 2. redakcija ---------------------------------------------------
    print("\n[2/6] Redakcija osobnih podataka (prije svega ostaloga)")
    cleaned, removals = [], []
    for r in rows:
        clean, removed = S.sanitise_row(r)
        clean["_viewing"] = S.viewing_window(r.get("Razgledavanje") or "")
        cleaned.append(clean)
        removals.extend(removed)
    red_summary = S.summarise_removals(removals)
    print(f"  uklonjeno: {sum(red_summary.values()):,} podataka u "
          f"{len(red_summary)} kategorija")
    for k, v in list(red_summary.items())[:6]:
        print(f"    {k:<26} {v:,}")
    print(f"  odbačenih polja iz izvora: {len(S.DROPPED)} (nemaju stupac u bazi)")

    # ---- 3. normalizacija ------------------------------------------------
    print("\n[3/6] Normalizacija (lokacija, površina, popust, status)")
    as_of = datetime.now()
    items_all = [N.normalise_item(c, c.get("_viewing", ""), as_of=as_of)
                 for c in cleaned]
    unique: dict[str, dict] = {}
    for it in items_all:
        unique.setdefault(it["item_key"], it)
    items = list(unique.values())
    dup_rows = len(items_all) - len(items)
    with_county = sum(1 for i in items if i.get("county"))
    print(f"  stavki: {len(items):,} (spojeno {dup_rows} doslovnih duplikata)")
    print(f"  sa županijom: {with_county:,} ({100*with_county/len(items):.1f} %)")
    print(f"  s površinom:  {sum(1 for i in items if i.get('area_m2')):,}")

    # ---- 4. ponovljene dražbe -------------------------------------------
    print("\n[4/6] Povezivanje ponovljenih dražbi")
    rstats = T.link_repeat_auctions(items)
    print(f"  povezanih skupina: {rstats['linked_groups']:,} · "
          f"s napredovanjem EJD: {rstats['groups_with_ejd_progression']} · "
          f"samodeklariranih ponavljanja: {rstats['self_declared_repeats']:,}")

    # ---- 5. baza ---------------------------------------------------------
    diff = {"first_run": True, "new_items": items, "status_changes": [],
            "price_changes": [], "events": [], "disappeared": []}
    if args.no_db:
        print("\n[5/6] Baza preskočena (--no-db)")
    else:
        print("\n[5/6] Upis u PostgreSQL")
        with store.connect() as conn:
            store.init_schema(conn)
            run_id = store.start_run(conn, meta, snapshot, len(rows))
            existing = store.load_existing(conn)
            diff = T.diff_against_previous(items, existing)

            store.upsert_items(conn, items, run_id)
            n_hist = store.record_price_changes(conn, diff["price_changes"], run_id)
            n_ev = store.record_events(conn, diff["events"], run_id)
            unres = T.collect_unresolved(items)
            store.record_unresolved(conn, unres, run_id)

            store.finish_run(
                conn, run_id, items_total=len(items),
                items_new=len(diff["new_items"]),
                items_changed=len(diff["status_changes"]) + len(diff["price_changes"]),
                duplicate_rows=dup_rows, redactions=red_summary, ok=True,
                notes=f"snapshot {snapshot}; {rstats['linked_groups']} repeat groups",
            )
            print(f"  run_id {run_id} · novih {len(diff['new_items']):,} · "
                  f"promjena statusa {len(diff['status_changes']):,} · "
                  f"promjena cijene {n_hist:,} · događaja {n_ev:,}")
            if diff["first_run"]:
                print("  (prvo pokretanje — nema s čim usporediti, promjene se")
                print("   bilježe od sljedećeg pokretanja)")
            db_counts = store.counts(conn)

    # ---- staleness guard --------------------------------------------------
    # Izvor je dnevni snimak; prosječno 15 nadmetanja završi svaki dan. Ako je
    # snimak prestar, stranice bi tvrdile da su zatvorene dražbe još otvorene.
    snap_dt = datetime.strptime(snapshot, "%Y-%m-%d") if snapshot else None
    age_h = ((datetime.now() - snap_dt).total_seconds() / 3600) if snap_dt else None
    if age_h is not None:
        print(f"\n[starost snimka] {age_h:.1f} h "
              f"(granica {config.MAX_SNAPSHOT_AGE_HOURS} h)")
        if age_h > config.MAX_SNAPSHOT_AGE_HOURS and not args.skip_site:
            if args.allow_stale:
                print("  UPOZORENJE: snimak je prestar, ali --allow-stale je zadan.")
            else:
                print(
                    f"\nGREŠKA: snimak je star {age_h:.1f} h, granica je "
                    f"{config.MAX_SNAPSHOT_AGE_HOURS} h.\n"
                    f"  Stranice se NE generiraju — radije nema objave nego "
                    f"netočni rokovi.\n"
                    f"  Pokreni bez --rebuild-only da se dohvati svjež izvoz, "
                    f"ili dodaj --allow-stale.",
                    file=sys.stderr,
                )
                return 3

    # ---- 6. stranice ------------------------------------------------------
    pages = {}
    if args.skip_site:
        print("\n[6/6] Generiranje stranica preskočeno (--skip-site)")
    else:
        print("\n[6/6] Generiranje statičkih stranica")
        builder = SiteBuilder()
        pages = builder.build(items, snapshot, {"redactions": red_summary})
        for k, v in pages.items():
            print(f"  {k:<18} {v:,}")

    # ---- sažetak ----------------------------------------------------------
    active = [i for i in items if i["status"] in ACTIVE_STATUSES]
    live = [i for i in items if i["status"] == "u_tijeku"]
    discounts = [i["discount_pct"] for i in items
                 if i.get("discount_pct") is not None and not i.get("discount_suspicious")]
    summary = {
        "generirano": date.today().isoformat(),
        "stanje_na_dan": snapshot,
        "starost_snimka_h": round(age_h, 1) if age_h is not None else None,
        "izvor": {
            "url": config.CSV_URL,
            "bajtova": meta["bytes"],
            "sha256": meta["sha256"],
            "licenca": config.SOURCE_LICENCE,
        },
        "redaka_u_csv": len(rows),
        "stavki": len(items),
        "duplikata_spojeno": dup_rows,
        "aktivnih": len(active),
        "u_tijeku": len(live),
        "po_statusu": dict(Counter(i["status"] for i in items)),
        "po_zupaniji": dict(Counter(i.get("county") or "Nepoznato" for i in items)),
        "po_vrsti": dict(Counter(i["property_type"] for i in items)),
        "prosjecan_popust_pct": round(sum(discounts) / len(discounts), 2) if discounts else None,
        "sumnjivih_popusta": sum(1 for i in items if i.get("discount_suspicious")),
        "lokacija_pouzdanost": dict(Counter(i["location_confidence"] for i in items)),
        "ponovljene_drazbe": rstats,
        "uklonjeni_osobni_podaci": red_summary,
        "odbacena_polja": {k: v for k, v in S.DROPPED.items()},
        "stranica": pages,
        "trajanje_s": round(time.time() - t0, 1),
    }
    (config.ROOT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 70)
    print(f"GOTOVO za {summary['trajanje_s']} s")
    print(f"  stavki {len(items):,} · aktivnih {len(active):,} · u tijeku {len(live):,}")
    if discounts:
        print(f"  prosječan popust {summary['prosjecan_popust_pct']} %")
    if pages:
        print(f"  stranica {pages.get('total_pages', 0):,} u {config.OUTPUT_DIR}")
    print(f"  sažetak: summary.json")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
