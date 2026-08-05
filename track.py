"""Praćenje kroz vrijeme: nove stavke, promjene statusa i cijene, ponovljene dražbe.

Ovo je ono što skup podataka pretvara u živ proizvod. Snimak sam za sebe kaže
što je danas na prodaju; povijest kaže **što se mijenja** — a upravo pad cijene
kroz ponovljene dražbe je signal koji investitora zanima.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from normalise import fold

# ---------------------------------------------------------------------------
# Ponovljene dražbe
# ---------------------------------------------------------------------------

_NOISE = re.compile(r"[\s.,;:()\[\]\-/]+")


def property_fingerprint(item: dict) -> str:
    """Otisak *nekretnine*, neovisan o rednom broju dražbe i cijeni.

    Zašto ne samo `case_ref`: jedan stečajni spis zna imati i 150 različitih
    predmeta prodaje (recon: ST-6578/2016). Broj spisa sam po sebi dakle NIJE
    dokaz da je riječ o istoj nekretnini — to bi lažno povezalo stotine
    nepovezanih stavki.

    Zato se otisak gradi iz spisa **i** normaliziranog opisa. Opis ponovljene
    dražbe iste nekretnine ostaje praktički identičan; mijenja se cijena i
    oznaka EJD, a to se u otisak namjerno ne uzima.

    Koristi se CIJELI opis, ne prvih N znakova. Skraćivanje na 220 znakova
    testirano je i lažno spaja različite čestice iz istog stečaja, jer im je
    uvodni dio opisa doslovno isti ("Predmet prodaje su nekretnine neupisane
    u zemljišne knjige, koje se nalaze u k.o. …"); razlikuju se tek kasnije
    u broju čestice. To je proizvodilo izmišljene "padove cijene od 97 %"
    između dviju posve različitih nekretnina.
    """
    desc = fold(item.get("description") or "")
    desc = _NOISE.sub(" ", desc).strip()
    basis = f"{item.get('case_ref','')}|{desc}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def link_repeat_auctions(items: list[dict]) -> dict[str, int]:
    """Poveži ponovljene pokušaje prodaje iste nekretnine.

    Postavlja `repeat_group` i `repeat_seq` na svakoj stavci.
    Redoslijed: prvo po rednom broju dražbe (Prva→Četvrta), pa po datumu
    odluke — jer izvor katkad ostavi EJD prazan.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        fp = property_fingerprint(it)
        it["repeat_group"] = fp
        groups[fp].append(it)

    stats = {
        "linked_groups": 0,        # povezane ponovljene dražbe (isti opis, isti spis)
        "items_in_repeats": 0,
        "max_attempts": 0,
        "groups_with_ejd_progression": 0,  # Prva -> Druga -> ... unutar grupe
        "self_declared_repeats": 0,        # EJD >= Druga, neovisno o povezivanju
    }
    for fp, group in groups.items():
        group.sort(key=lambda x: (
            x.get("auction_round_no") or 99,
            x.get("decision_date") or x.get("publish_start") or _MIN,
        ))
        for seq, it in enumerate(group, start=1):
            it["repeat_seq"] = seq
        if len(group) > 1:
            stats["linked_groups"] += 1
            stats["items_in_repeats"] += len(group)
            stats["max_attempts"] = max(stats["max_attempts"], len(group))
            rounds = {x.get("auction_round") for x in group if x.get("auction_round")}
            if len(rounds) > 1:
                stats["groups_with_ejd_progression"] += 1

    stats["self_declared_repeats"] = sum(
        1 for it in items if (it.get("auction_round_no") or 1) >= 2
    )
    return stats


class _Min:
    def __lt__(self, other):
        return True

    def __gt__(self, other):
        return False

    def __eq__(self, other):
        return isinstance(other, _Min)


_MIN = _Min()


def repeat_price_drop(group: list[dict]) -> float | None:
    """Postotni pad početne cijene od prvog do zadnjeg pokušaja."""
    prices = [(g.get("repeat_seq"), g.get("opening_price_eur")) for g in group]
    prices = [(s, p) for s, p in prices if p]
    if len(prices) < 2:
        return None
    prices.sort()
    first, last = prices[0][1], prices[-1][1]
    if not first or first <= 0:
        return None
    return round((first - last) / first * 100.0, 2)


# ---------------------------------------------------------------------------
# Usporedba s prethodnim pokretanjem
# ---------------------------------------------------------------------------

TRACKED_FIELDS = ["opening_price_eur", "current_bid_eur",
                  "estimated_value_eur", "minimum_price_eur"]


def diff_against_previous(items: list[dict], existing: dict[str, dict]) -> dict:
    """Usporedi današnji snimak sa stanjem u bazi.

    Vraća nove stavke, promjene statusa i promjene cijena.
    Prvo pokretanje nema s čim usporediti — to se javlja, ne izmišlja.
    """
    new_items: list[dict] = []
    status_changes: list[dict] = []
    price_changes: list[dict] = []
    events: list[dict] = []

    first_run = not existing

    for it in items:
        key = it["item_key"]
        prev = existing.get(key)
        if prev is None:
            new_items.append(it)
            if not first_run:
                events.append({
                    "item_key": key,
                    "event_type": "nova",
                    "detail": {
                        "county": it.get("county"),
                        "property_type": it.get("property_type"),
                        "opening_price_eur": _num(it.get("opening_price_eur")),
                        "discount_pct": _num(it.get("discount_pct")),
                    },
                })
            continue

        if prev.get("status") != it.get("status"):
            status_changes.append({
                "item_key": key,
                "from": prev.get("status"),
                "to": it.get("status"),
            })
            events.append({
                "item_key": key,
                "event_type": "status",
                "detail": {"iz": prev.get("status"), "u": it.get("status")},
            })

        for field in TRACKED_FIELDS:
            # Usporedba mora ići na PRECIZNOSTI KOJU BAZA ČUVA (NUMERIC(16,2)).
            # Inače vrijednost poput 32.815 pri upisu postane 32.81, a pri
            # sljedećem pokretanju se razlika od 0.005 pročita kao "promjena
            # cijene" iako se ništa nije dogodilo. To je stvarno zapaženo:
            # dva pokretanja nad bajt-identičnim izvorom proizvela su 4 lažne
            # promjene u kojima su stara i nova vrijednost bile jednake.
            old = _num(prev.get(field))
            new = _num(it.get(field))
            if old is None and new is None:
                continue
            if old is None or new is None:
                continue
            old, new = round(old, 2), round(new, 2)
            if old == new:
                continue
            pct = round((new - old) / old * 100.0, 2) if old else None
            price_changes.append({
                "item_key": key,
                "field": field,
                "old_value": old,
                "new_value": new,
                "pct_change": pct,
                "snapshot_date": it.get("snapshot_date"),
            })
            events.append({
                "item_key": key,
                "event_type": "cijena",
                "detail": {"polje": field, "staro": old, "novo": new, "promjena_pct": pct},
            })

    return {
        "first_run": first_run,
        "new_items": new_items,
        "status_changes": status_changes,
        "price_changes": price_changes,
        "events": events,
        "disappeared": [k for k in existing if k not in {i["item_key"] for i in items}],
    }


def _num(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def collect_unresolved(items: list[dict]) -> list[dict]:
    """Stavke bez utvrđene županije — vode se poimence, ne kao postotak."""
    out = []
    for it in items:
        if it.get("county"):
            continue
        out.append({
            "item_key": it["item_key"],
            "issuer_name": it.get("issuer_name"),
            "raw_hint": (it.get("location_raw") or it.get("cadastral_municipality") or "")[:200],
            "reason": (
                "trgovački sud / bilježnik — sjedište nije dokaz lokacije nekretnine"
                if it.get("issuer_type") in ("trgovacki_sud", "javni_biljeznik",
                                             "ostalo", "nepoznato")
                else "naselje nije prepoznato u opisu"
            ),
        })
    return out
