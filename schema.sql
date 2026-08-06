-- Licita — PostgreSQL shema
--
-- Načelo: u bazu ulaze SAMO polja koja su prošla sanitise.py.
-- Slobodna tekstualna polja iz izvora koja sadrže osobne podatke
-- (Razgledavanje, Napomena uz uvjete prodaje, Ostali uvjeti za jamčevinu,
-- Napomena uz detalje, Ostali uvjeti prodaje, Rok za polaganje kupovnine)
-- namjerno NEMAJU stupac u ovoj shemi — da ih se ne može slučajno upisati.
-- Vidi docs/source-notes.md §3.

CREATE TABLE IF NOT EXISTS runs (
    run_id                BIGSERIAL PRIMARY KEY,
    started_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at           TIMESTAMPTZ,
    source_url            TEXT        NOT NULL,
    source_bytes          BIGINT,
    source_sha256         TEXT,
    snapshot_date         DATE,
    rows_in_csv           INTEGER,
    items_total           INTEGER,
    items_new             INTEGER,
    items_changed         INTEGER,
    duplicate_rows        INTEGER,
    redactions            JSONB,
    ok                    BOOLEAN     NOT NULL DEFAULT FALSE,
    notes                 TEXT
);

CREATE TABLE IF NOT EXISTS items (
    item_key                 TEXT PRIMARY KEY,
    case_ref                 TEXT NOT NULL,
    auction_id               TEXT,

    issuer_type              TEXT,
    issuer_name              TEXT,        -- institucija; imena osoba uklonjena
    description              TEXT,        -- REDIGIRAN opis predmeta prodaje

    property_type            TEXT,
    procedure_type           TEXT,
    sale_method              TEXT,
    scope                    TEXT,

    county                   TEXT,
    city                     TEXT,
    cadastral_municipality   TEXT,
    location_confidence      TEXT,        -- visoka | srednja | nema
    location_raw             TEXT,

    estimated_value_eur      NUMERIC(16,2),
    opening_price_eur        NUMERIC(16,2),
    minimum_price_eur        NUMERIC(16,2),
    deposit_eur              NUMERIC(16,2),
    bid_step_eur             NUMERIC(16,2),
    current_bid_eur          NUMERIC(16,2),   -- nije u CSV exportu; ostaje NULL
    discount_pct             NUMERIC(7,2),
    discount_suspicious      BOOLEAN NOT NULL DEFAULT FALSE,

    area_m2                  NUMERIC(16,2),
    area_unit_source         TEXT,

    auction_round            TEXT,            -- Prva / Druga / Treća / Četvrta
    auction_round_no         SMALLINT,
    decision_date            DATE,
    publish_start            TIMESTAMP,
    auction_start            TIMESTAMP,
    auction_end              TIMESTAMP,
    extendable               BOOLEAN,
    deposit_value_date       TIMESTAMP,
    viewing_time             TEXT,            -- samo izvedeni termin, bez kontakata

    status                   TEXT,            -- najavljeno | u_tijeku | zavrseno | bez_termina
    slug                     TEXT,

    repeat_group             TEXT,            -- veže ponovljene dražbe iste nekretnine
    repeat_seq               SMALLINT,

    source_snapshot_date     DATE,
    first_seen               TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen                TIMESTAMPTZ NOT NULL DEFAULT now(),
    times_seen               INTEGER NOT NULL DEFAULT 1
);

-- Koordinate referentne točke katastarske općine (DGU INSPIRE, Otvorena
-- dozvola). Razina k.o., NE parcele — coord_source to i kaže.
ALTER TABLE items ADD COLUMN IF NOT EXISTS latitude  NUMERIC(10,7);
ALTER TABLE items ADD COLUMN IF NOT EXISTS longitude NUMERIC(10,7);
ALTER TABLE items ADD COLUMN IF NOT EXISTS coord_source TEXT;

CREATE INDEX IF NOT EXISTS idx_items_county        ON items (county);
CREATE INDEX IF NOT EXISTS idx_items_city          ON items (city);
CREATE INDEX IF NOT EXISTS idx_items_status        ON items (status);
CREATE INDEX IF NOT EXISTS idx_items_type          ON items (property_type);
CREATE INDEX IF NOT EXISTS idx_items_discount      ON items (discount_pct DESC);
CREATE INDEX IF NOT EXISTS idx_items_case_ref      ON items (case_ref);
CREATE INDEX IF NOT EXISTS idx_items_repeat_group  ON items (repeat_group);
CREATE INDEX IF NOT EXISTS idx_items_auction_end   ON items (auction_end);
CREATE UNIQUE INDEX IF NOT EXISTS idx_items_slug   ON items (slug);

-- Povijest cijena: jedan redak po promjeni, ne po pokretanju.
CREATE TABLE IF NOT EXISTS price_history (
    id            BIGSERIAL PRIMARY KEY,
    item_key      TEXT NOT NULL REFERENCES items(item_key) ON DELETE CASCADE,
    run_id        BIGINT REFERENCES runs(run_id),
    observed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    snapshot_date DATE,
    field         TEXT NOT NULL,           -- opening_price_eur | current_bid_eur | ...
    old_value     NUMERIC(16,2),
    new_value     NUMERIC(16,2),
    pct_change    NUMERIC(9,2)
);

CREATE INDEX IF NOT EXISTS idx_price_history_item ON price_history (item_key, observed_at DESC);

-- Događaji: nova stavka, promjena statusa, ponovljena dražba.
CREATE TABLE IF NOT EXISTS item_events (
    id           BIGSERIAL PRIMARY KEY,
    item_key     TEXT NOT NULL REFERENCES items(item_key) ON DELETE CASCADE,
    run_id       BIGINT REFERENCES runs(run_id),
    observed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type   TEXT NOT NULL,            -- nova | status | cijena | ponovljena_drazba
    detail       JSONB
);

CREATE INDEX IF NOT EXISTS idx_item_events_item ON item_events (item_key, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_item_events_type ON item_events (event_type, observed_at DESC);

-- Neriješene lokacije se ne skrivaju iza postotka — vode se poimence.
CREATE TABLE IF NOT EXISTS unresolved_locations (
    id            BIGSERIAL PRIMARY KEY,
    run_id        BIGINT REFERENCES runs(run_id),
    item_key      TEXT,
    issuer_name   TEXT,
    raw_hint      TEXT,
    reason        TEXT,
    observed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_unresolved_run ON unresolved_locations (run_id);
