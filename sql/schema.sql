-- ============================================================================
-- Schema Postgres per Frigate Person Counter
--
-- Una sola tabella `counter_events`: ogni riga = un attraversamento confermato
-- (enter o exit). Da qui si ricavano i totali, il grafico orario e
-- l'occupancy via view.
--
-- Carica con:   psql -U counter -d frigate_counter -f sql/schema.sql
-- ============================================================================

CREATE TABLE IF NOT EXISTS counter_events (
    id              BIGSERIAL    PRIMARY KEY,
    event_id        TEXT         NOT NULL,                    -- id Frigate
    camera          TEXT         NOT NULL,
    ts              TIMESTAMPTZ  NOT NULL,                    -- istante conteggio
    event_type      TEXT         NOT NULL
                                  CHECK (event_type IN ('enter','exit')),
    method          TEXT,                                     -- es. 'full_motion'

    -- punto iniziale e finale del bounding box (normalizzati 0..1)
    start_x         REAL,
    start_y         REAL,
    end_x           REAL,
    end_y           REAL,

    -- diagnosi del classificatore (delta_y, span_y, net_ratio, ...)
    reason          TEXT,

    -- snapshot dei contatori DOPO questo evento
    enter_total     INTEGER      NOT NULL DEFAULT 0,
    exit_total      INTEGER      NOT NULL DEFAULT 0,
    occupancy       INTEGER      NOT NULL DEFAULT 0,

    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    -- evita doppi conteggi se l'app rinvia lo stesso evento
    UNIQUE (event_id, event_type)
);

CREATE INDEX IF NOT EXISTS idx_counter_events_camera_ts
    ON counter_events (camera, ts DESC);

CREATE INDEX IF NOT EXISTS idx_counter_events_ts
    ON counter_events (ts DESC);

CREATE INDEX IF NOT EXISTS idx_counter_events_type
    ON counter_events (event_type);


-- ----------------------------------------------------------------------------
-- View: riepilogo giornaliero (utile per export e statistiche)
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW counter_daily_summary AS
SELECT
    camera,
    (ts AT TIME ZONE 'UTC')::date                                 AS day,
    COUNT(*) FILTER (WHERE event_type = 'enter')                  AS enter_count,
    COUNT(*) FILTER (WHERE event_type = 'exit')                   AS exit_count,
    MAX(occupancy)                                                AS peak_occupancy,
    MIN(ts)                                                       AS first_event,
    MAX(ts)                                                       AS last_event
FROM counter_events
GROUP BY camera, (ts AT TIME ZONE 'UTC')::date;


-- ----------------------------------------------------------------------------
-- View: riepilogo orario (24 bucket per giorno e camera)
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW counter_hourly_summary AS
SELECT
    camera,
    date_trunc('hour', ts)                                        AS hour,
    COUNT(*) FILTER (WHERE event_type = 'enter')                  AS enter_count,
    COUNT(*) FILTER (WHERE event_type = 'exit')                   AS exit_count
FROM counter_events
GROUP BY camera, date_trunc('hour', ts);
