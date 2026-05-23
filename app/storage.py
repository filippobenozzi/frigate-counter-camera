"""Storage layer.

Scrive sempre su JSON (`counts.json` + `events.jsonl`) come backup locale.
Se le DB_* sono configurate, scrive *anche* su Postgres e legge da Postgres
gli eventi storici (molto più veloce dei file con tanti eventi).
"""

import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from app.config import Config


# =============================================================================
# Helpers JSON
# =============================================================================

def atomic_write_json(path, data):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def summarize_hourly(events):
    """24 bucket: per ogni ora -> enter, exit, occupancy a fine ora."""
    buckets = [{"hour": h, "enter": 0, "exit": 0, "occupancy": 0}
               for h in range(24)]
    for evt in events:
        ts = evt.get("ts")
        if not ts:
            continue
        h = time.localtime(ts).tm_hour
        t = evt.get("type")
        if t in ("enter", "exit"):
            buckets[h][t] += 1

    # occupancy running cumulativa
    running = 0
    for b in buckets:
        running += b["enter"] - b["exit"]
        b["occupancy"] = running
    return buckets


# =============================================================================
# PostgresStore
# =============================================================================

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS {table} (
    id              BIGSERIAL    PRIMARY KEY,
    event_id        TEXT         NOT NULL,
    camera          TEXT         NOT NULL,
    ts              TIMESTAMPTZ  NOT NULL,
    event_type      TEXT         NOT NULL CHECK (event_type IN ('enter','exit')),
    method          TEXT,
    start_x         REAL,
    start_y         REAL,
    end_x           REAL,
    end_y           REAL,
    reason          TEXT,
    enter_total     INTEGER      NOT NULL DEFAULT 0,
    exit_total      INTEGER      NOT NULL DEFAULT 0,
    occupancy       INTEGER      NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (event_id, event_type)
);
CREATE INDEX IF NOT EXISTS idx_{tbl_plain}_camera_ts ON {table} (camera, ts DESC);
CREATE INDEX IF NOT EXISTS idx_{tbl_plain}_ts        ON {table} (ts DESC);
CREATE INDEX IF NOT EXISTS idx_{tbl_plain}_type      ON {table} (event_type);
"""


class PostgresStore:
    def __init__(self):
        import psycopg2
        from psycopg2 import pool

        self.pool = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=5,
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            dbname=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASS,
            sslmode=Config.DB_SSLMODE,
        )
        self.table = f'"{Config.DB_SCHEMA}"."{Config.DB_TABLE}"'
        self._ensure_schema()

    @contextmanager
    def _conn(self):
        c = self.pool.getconn()
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            self.pool.putconn(c)

    def _ensure_schema(self):
        try:
            with self._conn() as c, c.cursor() as cur:
                cur.execute(SCHEMA_SQL.format(
                    table=self.table,
                    tbl_plain=Config.DB_TABLE.replace('"', ''),
                ))
            print("[postgres] schema verificato/creato", flush=True)
        except Exception as e:
            print(f"[postgres] errore creazione schema: {e}", flush=True)

    def insert_event(self, event_id, ts, event_type, method,
                     start_xy, end_xy, reason, snapshot):
        try:
            with self._conn() as c, c.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {self.table}
                        (event_id, camera, ts, event_type, method,
                         start_x, start_y, end_x, end_y, reason,
                         enter_total, exit_total, occupancy)
                    VALUES (%s, %s, to_timestamp(%s), %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, %s)
                    ON CONFLICT (event_id, event_type) DO NOTHING
                    """,
                    (
                        event_id, Config.CAMERA, ts, event_type, method,
                        start_xy[0], start_xy[1], end_xy[0], end_xy[1], reason,
                        snapshot["enter"], snapshot["exit"], snapshot["occupancy"],
                    ),
                )
        except Exception as e:
            print(f"[postgres] errore insert: {e}", flush=True)

    def get_events_for_day(self, day: date):
        start = datetime(day.year, day.month, day.day)
        end = start + timedelta(days=1)
        try:
            with self._conn() as c, c.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT event_id,
                           EXTRACT(epoch FROM ts),
                           event_type, method,
                           start_x, start_y, end_x, end_y, reason,
                           enter_total, exit_total, occupancy, camera
                    FROM {self.table}
                    WHERE camera = %s AND ts >= %s AND ts < %s
                    ORDER BY ts ASC
                    """,
                    (Config.CAMERA, start, end),
                )
                rows = cur.fetchall()
        except Exception as e:
            print(f"[postgres] errore query: {e}", flush=True)
            return []

        out = []
        for r in rows:
            ts = float(r[1])
            out.append({
                "id": r[0],
                "ts": ts,
                "datetime": time.strftime("%Y-%m-%d %H:%M:%S",
                                          time.localtime(ts)),
                "type": r[2],
                "method": r[3] or "",
                "start": {"x": r[4], "y": r[5]},
                "end": {"x": r[6], "y": r[7]},
                "reason": r[8] or "",
                "counts_after": {
                    "enter": r[9], "exit": r[10], "occupancy": r[11],
                },
                "camera": r[12],
            })
        return out

    def get_available_days(self, limit=60):
        try:
            with self._conn() as c, c.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT DISTINCT (ts AT TIME ZONE 'UTC')::date AS d
                    FROM {self.table}
                    WHERE camera = %s
                    ORDER BY d DESC
                    LIMIT %s
                    """,
                    (Config.CAMERA, limit),
                )
                return [r[0] for r in cur.fetchall()]
        except Exception as e:
            print(f"[postgres] errore days: {e}", flush=True)
            return []

    def delete_day(self, day: date):
        """Cancella eventi del giorno e ritorna (enter_deleted, exit_deleted)."""
        start = datetime(day.year, day.month, day.day)
        end = start + timedelta(days=1)
        try:
            with self._conn() as c, c.cursor() as cur:
                cur.execute(
                    f"""
                    DELETE FROM {self.table}
                    WHERE camera = %s AND ts >= %s AND ts < %s
                    RETURNING event_type
                    """,
                    (Config.CAMERA, start, end),
                )
                rows = cur.fetchall()
            ent = sum(1 for r in rows if r[0] == "enter")
            exi = sum(1 for r in rows if r[0] == "exit")
            return ent, exi
        except Exception as e:
            print(f"[postgres] errore delete_day: {e}", flush=True)
            return 0, 0

    def delete_all(self):
        """Cancella TUTTI gli eventi della camera corrente."""
        try:
            with self._conn() as c, c.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {self.table} WHERE camera = %s",
                    (Config.CAMERA,),
                )
                return cur.rowcount or 0
        except Exception as e:
            print(f"[postgres] errore delete_all: {e}", flush=True)
            return 0

    def get_stats(self):
        try:
            with self._conn() as c, c.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT COUNT(*),
                           EXTRACT(epoch FROM MAX(ts)),
                           COUNT(DISTINCT (ts AT TIME ZONE 'UTC')::date),
                           MIN(ts), MAX(ts)
                    FROM {self.table}
                    WHERE camera = %s
                    """,
                    (Config.CAMERA,),
                )
                row = cur.fetchone()
            if not row:
                return {}
            return {
                "events_count": int(row[0] or 0),
                "last_event_ts": float(row[1]) if row[1] is not None else None,
                "days_count": int(row[2] or 0),
                "first_event": row[3].isoformat() if row[3] else None,
                "last_event": row[4].isoformat() if row[4] else None,
            }
        except Exception as e:
            print(f"[postgres] errore stats: {e}", flush=True)
            return {}


# =============================================================================
# Store (orchestratore JSON + Postgres)
# =============================================================================

class Store:
    def __init__(self):
        os.makedirs(Config.LOG_DIR, exist_ok=True)
        self.lock = threading.Lock()
        self.counts = self._load_counts()
        self.pg = None
        if Config.postgres_enabled():
            try:
                self.pg = PostgresStore()
                print("[storage] Postgres attivo", flush=True)
            except Exception as e:
                print(f"[storage] Postgres NON disponibile, "
                      f"fallback solo JSON: {e}", flush=True)
                self.pg = None
        else:
            print("[storage] Postgres non configurato, uso solo JSON",
                  flush=True)

    # ---- counts cumulativi ----

    def _load_counts(self):
        if not os.path.exists(Config.COUNTS_FILE):
            return {"enter": 0, "exit": 0}
        try:
            with open(Config.COUNTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                "enter": int(data.get("enter", 0)),
                "exit": int(data.get("exit", 0)),
            }
        except Exception as e:
            print(f"[storage] errore lettura counts: {e}", flush=True)
            return {"enter": 0, "exit": 0}

    def snapshot(self):
        return {
            "enter": self.counts["enter"],
            "exit": self.counts["exit"],
            "occupancy": self.counts["enter"] - self.counts["exit"],
        }

    def save_counts(self):
        snap = self.snapshot()
        payload = {
            "camera": Config.CAMERA,
            **snap,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_ts": time.time(),
        }
        try:
            atomic_write_json(Config.COUNTS_FILE, payload)
        except Exception as e:
            print(f"[storage] errore salvataggio counts: {e}", flush=True)

    # ---- eventi ----

    def _append_jsonl(self, event):
        try:
            with open(Config.EVENTS_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[storage] errore salvataggio evento: {e}", flush=True)

    def insert_event(self, event_id, ts, event_type, method,
                     start_xy, end_xy, reason, snapshot):
        evt = {
            "id": event_id,
            "ts": ts,
            "datetime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
            "camera": Config.CAMERA,
            "type": event_type,
            "method": method,
            "start": {"x": round(start_xy[0], 4), "y": round(start_xy[1], 4)},
            "end": {"x": round(end_xy[0], 4), "y": round(end_xy[1], 4)},
            "reason": reason,
            "counts_after": snapshot,
        }
        self._append_jsonl(evt)
        if self.pg:
            self.pg.insert_event(event_id, ts, event_type, method,
                                 start_xy, end_xy, reason, snapshot)

    # ---- query storiche ----

    def get_events_for_day(self, day: date):
        if self.pg:
            return self.pg.get_events_for_day(day)
        return self._jsonl_events_for_day(day)

    def _jsonl_events_for_day(self, day: date):
        if not os.path.exists(Config.EVENTS_FILE):
            return []
        out = []
        day_str = day.strftime("%Y-%m-%d")
        try:
            with open(Config.EVENTS_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except Exception:
                        continue
                    if evt.get("datetime", "").startswith(day_str):
                        out.append(evt)
        except Exception as e:
            print(f"[storage] errore lettura jsonl: {e}", flush=True)
        # ordina per timestamp ASC
        out.sort(key=lambda e: e.get("ts", 0))
        return out

    def get_available_days(self, limit=60):
        if self.pg:
            return self.pg.get_available_days(limit)
        return self._jsonl_available_days(limit)

    # ---- delete / stats ----

    def delete_events_for_day(self, day: date):
        """Cancella gli eventi del giorno e ritorna (enter_del, exit_del)."""
        ent_jsonl, exi_jsonl = self._jsonl_delete_day(day)
        if self.pg:
            ent_pg, exi_pg = self.pg.delete_day(day)
            # in dual-write i due numeri devono coincidere; prendiamo il PG
            return ent_pg, exi_pg
        return ent_jsonl, exi_jsonl

    def delete_all_events(self):
        """Cancella tutto lo storico (jsonl + Postgres se presente)."""
        deleted_pg = 0
        try:
            if os.path.exists(Config.EVENTS_FILE):
                with open(Config.EVENTS_FILE, "w", encoding="utf-8") as f:
                    f.write("")
        except Exception as e:
            print(f"[storage] errore wipe jsonl: {e}", flush=True)
        if self.pg:
            deleted_pg = self.pg.delete_all()
        return deleted_pg

    def get_stats(self):
        """Statistiche per la pagina admin."""
        stats = {
            "events_count": 0,
            "days_count": 0,
            "last_event_ts": None,
            "first_event": None,
            "last_event": None,
            "jsonl_size": 0,
        }
        if os.path.exists(Config.EVENTS_FILE):
            try:
                stats["jsonl_size"] = os.path.getsize(Config.EVENTS_FILE)
            except Exception:
                pass
        if self.pg:
            stats.update(self.pg.get_stats())
        else:
            # conta dal jsonl
            days = set()
            count = 0
            last_ts = None
            if os.path.exists(Config.EVENTS_FILE):
                try:
                    with open(Config.EVENTS_FILE, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                evt = json.loads(line)
                            except Exception:
                                continue
                            count += 1
                            dt = evt.get("datetime", "")
                            if len(dt) >= 10:
                                days.add(dt[:10])
                            ts = evt.get("ts")
                            if ts and (last_ts is None or ts > last_ts):
                                last_ts = ts
                except Exception as e:
                    print(f"[storage] errore stats: {e}", flush=True)
            stats["events_count"] = count
            stats["days_count"] = len(days)
            stats["last_event_ts"] = last_ts
        return stats

    def _jsonl_delete_day(self, day: date):
        if not os.path.exists(Config.EVENTS_FILE):
            return 0, 0
        day_str = day.strftime("%Y-%m-%d")
        tmp = Config.EVENTS_FILE + ".tmp"
        ent = exi = 0
        try:
            with open(Config.EVENTS_FILE, "r", encoding="utf-8") as src, \
                 open(tmp, "w", encoding="utf-8") as dst:
                for line in src:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        evt = json.loads(stripped)
                    except Exception:
                        # riga corrotta -> scarto
                        continue
                    if evt.get("datetime", "").startswith(day_str):
                        if evt.get("type") == "enter":
                            ent += 1
                        elif evt.get("type") == "exit":
                            exi += 1
                        continue
                    dst.write(stripped + "\n")
            os.replace(tmp, Config.EVENTS_FILE)
        except Exception as e:
            print(f"[storage] errore delete_day jsonl: {e}", flush=True)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
        return ent, exi

    def _jsonl_available_days(self, limit=60):
        if not os.path.exists(Config.EVENTS_FILE):
            return []
        days = set()
        try:
            with open(Config.EVENTS_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except Exception:
                        continue
                    dt = evt.get("datetime", "")
                    if len(dt) >= 10:
                        days.add(dt[:10])
        except Exception as e:
            print(f"[storage] errore lettura days: {e}", flush=True)
        days = sorted(days, reverse=True)[:limit]
        out = []
        for d in days:
            try:
                out.append(datetime.strptime(d, "%Y-%m-%d").date())
            except ValueError:
                pass
        return out
