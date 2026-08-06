"""PostgreSQL sloj: shema, upsert, povijest.

Sve pisanje ide kroz `upsert_items`, koje je jedino mjesto koje dira tablicu
`items`. Tako je zajamčeno da ništa ne zaobiđe redakciju osobnih podataka.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterable, Iterator

import psycopg2
import psycopg2.extras

import config

# Stupci koji se upisuju. Namjerno eksplicitno — ako netko doda polje u
# normalise.py koje nije ovdje, neće se tiho pojaviti u bazi.
ITEM_COLUMNS = [
    "item_key", "case_ref", "auction_id",
    "issuer_type", "issuer_name", "description",
    "property_type", "procedure_type", "sale_method", "scope",
    "county", "city", "cadastral_municipality", "location_confidence", "location_raw",
    "estimated_value_eur", "opening_price_eur", "minimum_price_eur",
    "deposit_eur", "bid_step_eur", "current_bid_eur",
    "discount_pct", "discount_suspicious",
    "area_m2", "area_unit_source",
    "auction_round", "auction_round_no",
    "decision_date", "publish_start", "auction_start", "auction_end",
    "extendable", "deposit_value_date", "viewing_time",
    "status", "slug", "repeat_group", "repeat_seq", "source_snapshot_date",
    "latitude", "longitude", "coord_source",
]

# Polja koja se prate kroz vrijeme.
TRACKED_NUMERIC = ["opening_price_eur", "current_bid_eur", "estimated_value_eur",
                   "minimum_price_eur"]


@contextmanager
def connect(dsn: str | None = None) -> Iterator[psycopg2.extensions.connection]:
    dsn = dsn or config.database_url()
    conn = psycopg2.connect(dsn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema(conn) -> None:
    sql = (config.ROOT / "schema.sql").read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)


def start_run(conn, meta: dict, snapshot: str, rows_in_csv: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO runs (source_url, source_bytes, source_sha256,
                              snapshot_date, rows_in_csv)
            VALUES (%s, %s, %s, %s, %s) RETURNING run_id
            """,
            (meta["url"], meta["bytes"], meta["sha256"], snapshot or None, rows_in_csv),
        )
        return cur.fetchone()[0]


def finish_run(conn, run_id: int, **fields) -> None:
    sets, vals = [], []
    for k, v in fields.items():
        sets.append(f"{k} = %s")
        vals.append(json.dumps(v) if isinstance(v, (dict, list)) else v)
    sets.append("finished_at = %s")
    vals.append(datetime.now(timezone.utc))
    vals.append(run_id)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE runs SET {', '.join(sets)} WHERE run_id = %s", vals)


def load_existing(conn) -> dict[str, dict]:
    """Trenutno stanje u bazi — osnovica za usporedbu (track.py)."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT item_key, status, opening_price_eur, current_bid_eur,
                   estimated_value_eur, minimum_price_eur, first_seen, times_seen
            FROM items
            """
        )
        return {r["item_key"]: dict(r) for r in cur.fetchall()}


def upsert_items(conn, items: Iterable[dict], run_id: int) -> int:
    """Ubaci ili osvježi stavke. `first_seen` se nikad ne prepisuje."""
    cols = ", ".join(ITEM_COLUMNS)
    placeholders = ", ".join(["%s"] * len(ITEM_COLUMNS))
    updates = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in ITEM_COLUMNS if c != "item_key"
    )
    sql = f"""
        INSERT INTO items ({cols}, first_seen, last_seen, times_seen)
        VALUES ({placeholders}, now(), now(), 1)
        ON CONFLICT (item_key) DO UPDATE SET
            {updates},
            last_seen = now(),
            times_seen = items.times_seen + 1
    """
    rows = [tuple(_coerce(it.get(c)) for c in ITEM_COLUMNS) for it in items]
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, rows, page_size=500)
    return len(rows)


def _coerce(v):
    if isinstance(v, bool) or v is None:
        return v
    return v


def record_price_changes(conn, changes: list[dict], run_id: int) -> int:
    if not changes:
        return 0
    sql = """
        INSERT INTO price_history
            (item_key, run_id, snapshot_date, field, old_value, new_value, pct_change)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    rows = [
        (c["item_key"], run_id, c.get("snapshot_date"), c["field"],
         c.get("old_value"), c.get("new_value"), c.get("pct_change"))
        for c in changes
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, rows, page_size=500)
    return len(rows)


def record_events(conn, events: list[dict], run_id: int) -> int:
    if not events:
        return 0
    sql = """
        INSERT INTO item_events (item_key, run_id, event_type, detail)
        VALUES (%s, %s, %s, %s)
    """
    rows = [
        (e["item_key"], run_id, e["event_type"], json.dumps(e.get("detail") or {},
                                                            ensure_ascii=False))
        for e in events
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, rows, page_size=500)
    return len(rows)


def record_unresolved(conn, rows: list[dict], run_id: int) -> int:
    if not rows:
        return 0
    sql = """
        INSERT INTO unresolved_locations (run_id, item_key, issuer_name, raw_hint, reason)
        VALUES (%s, %s, %s, %s, %s)
    """
    payload = [
        (run_id, r.get("item_key"), r.get("issuer_name"), r.get("raw_hint"), r.get("reason"))
        for r in rows
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, payload, page_size=500)
    return len(payload)


def fetch_items(conn, where: str = "", params: tuple = ()) -> list[dict]:
    sql = "SELECT * FROM items"
    if where:
        sql += f" WHERE {where}"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def counts(conn) -> dict:
    out: dict[str, object] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM items")
        out["items"] = cur.fetchone()[0]
        cur.execute("SELECT status, count(*) FROM items GROUP BY status ORDER BY 2 DESC")
        out["by_status"] = dict(cur.fetchall())
        cur.execute(
            "SELECT coalesce(county,'Nepoznato'), count(*) FROM items "
            "GROUP BY 1 ORDER BY 2 DESC"
        )
        out["by_county"] = dict(cur.fetchall())
        cur.execute(
            "SELECT property_type, count(*) FROM items GROUP BY 1 ORDER BY 2 DESC"
        )
        out["by_type"] = dict(cur.fetchall())
        cur.execute(
            "SELECT round(avg(discount_pct),2) FROM items "
            "WHERE discount_pct IS NOT NULL AND NOT discount_suspicious"
        )
        out["avg_discount_pct"] = float(cur.fetchone()[0] or 0)
        cur.execute("SELECT count(*) FROM price_history")
        out["price_history_rows"] = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM item_events")
        out["events"] = cur.fetchone()[0]
        cur.execute("SELECT count(DISTINCT repeat_group) FROM items WHERE repeat_seq > 1")
        out["repeat_groups"] = cur.fetchone()[0]
    return out
