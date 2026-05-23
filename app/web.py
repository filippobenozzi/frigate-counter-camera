"""Flask app: dashboard + API + auth."""

import csv
import io
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

from flask import (Flask, Response, jsonify, redirect, render_template,
                   request, session, url_for)

from app import webhook as webhook_mod
from app.auth import credentials_match, login_required
from app.config import Config
from app.settings import EDITABLE, Settings
from app.storage import Store, summarize_hourly


def _parse_day(day_str):
    if not day_str:
        return date.today()
    try:
        return datetime.strptime(day_str, "%Y-%m-%d").date()
    except ValueError:
        return date.today()


def _filter_hour_range(events, h_from, h_to):
    out = []
    for e in events:
        ts = e.get("ts")
        if not ts:
            continue
        h = time.localtime(ts).tm_hour
        if h_from is not None and h < h_from:
            continue
        if h_to is not None and h > h_to:
            continue
        out.append(e)
    return out


def create_app(store, tracker):
    app = Flask(__name__, template_folder="templates")
    app.secret_key = Config.SECRET_KEY
    app.permanent_session_lifetime = timedelta(days=Config.SESSION_DAYS)

    # -------- AUTH --------

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not Config.auth_enabled():
            return redirect(url_for("dashboard"))
        error = None
        if request.method == "POST":
            user = request.form.get("username", "")
            pwd = request.form.get("password", "")
            if credentials_match(user, pwd):
                session.permanent = True
                session["auth_user"] = user
                nxt = request.args.get("next") or url_for("dashboard")
                return redirect(nxt)
            error = "Credenziali non valide"
        return render_template("login.html",
                               error=error,
                               camera=Config.CAMERA)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # -------- DASHBOARD --------

    @app.route("/")
    @login_required
    def dashboard():
        day = _parse_day(request.args.get("day"))
        prev_day = (day - timedelta(days=1)).isoformat()
        next_day = (day + timedelta(days=1)).isoformat()
        today = date.today()

        h_from = request.args.get("from", type=int)
        h_to = request.args.get("to", type=int)

        with store.lock:
            snapshot = store.snapshot()

        events = store.get_events_for_day(day)
        hourly = summarize_hourly(events)

        day_enter = sum(b["enter"] for b in hourly)
        day_exit = sum(b["exit"] for b in hourly)
        day_peak = max((b["occupancy"] for b in hourly), default=0)

        filtered_events = _filter_hour_range(events, h_from, h_to)
        # tabella ordinata dal più recente
        filtered_events = list(reversed(filtered_events))

        return render_template(
            "dashboard.html",
            camera=Config.CAMERA,
            snapshot=snapshot,
            day=day,
            prev_day=prev_day,
            next_day=next_day,
            today_iso=today.isoformat(),
            is_today=(day == today),
            hourly=hourly,
            day_enter=day_enter,
            day_exit=day_exit,
            day_peak=day_peak,
            events=filtered_events,
            h_from=h_from if h_from is not None else 0,
            h_to=h_to if h_to is not None else 23,
            postgres_enabled=Config.postgres_enabled(),
            auth_enabled=Config.auth_enabled(),
            enter_direction=Config.ENTER_DIRECTION,
            point_mode=Config.POINT_MODE,
        )

    # -------- API --------

    @app.route("/api/counts")
    @login_required
    def api_counts():
        with store.lock:
            return jsonify(store.snapshot())

    @app.route("/api/hourly")
    @login_required
    def api_hourly():
        day = _parse_day(request.args.get("day"))
        events = store.get_events_for_day(day)
        return jsonify({
            "day": day.isoformat(),
            "hourly": summarize_hourly(events),
        })

    @app.route("/api/events")
    @login_required
    def api_events():
        day = _parse_day(request.args.get("day"))
        events = store.get_events_for_day(day)
        h_from = request.args.get("from", type=int)
        h_to = request.args.get("to", type=int)
        return jsonify({
            "day": day.isoformat(),
            "count": len(events),
            "events": _filter_hour_range(events, h_from, h_to),
        })

    @app.route("/api/days")
    @login_required
    def api_days():
        return jsonify([d.isoformat() for d in store.get_available_days()])

    @app.route("/api/tracks")
    @login_required
    def api_tracks():
        with store.lock:
            data = {
                evt_id: {
                    "first": t["first"],
                    "last": t["last"],
                    "last_seen": t["last_seen"],
                    "points": list(t.get("points", [])),
                    "counted": tracker.is_counted(evt_id),
                }
                for evt_id, t in tracker.tracks.items()
            }
        return jsonify(data)

    # -------- ADMIN (vecchia pagina → ora unificata in /settings) --------

    @app.route("/admin")
    @login_required
    def admin():
        return redirect(url_for("settings_page"))

    @app.route("/api/admin/reset-counters", methods=["POST"])
    @login_required
    def api_reset_counters():
        """Azzera solo i contatori cumulativi. Non tocca lo storico."""
        with store.lock:
            store.counts["enter"] = 0
            store.counts["exit"] = 0
            tracker.clear_all()
            store.save_counts()
            snap = store.snapshot()
        print("[admin] reset cumulativi", flush=True)
        return jsonify({"ok": True, "action": "reset-counters", **snap})

    @app.route("/api/admin/reset-day", methods=["POST"])
    @login_required
    def api_reset_day():
        """Cancella eventi del giorno e sottrae quei conteggi dai cumulativi."""
        day_str = request.form.get("day") or request.args.get("day")
        if not day_str:
            return jsonify({"ok": False, "error": "missing day"}), 400
        try:
            day = datetime.strptime(day_str, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"ok": False, "error": "invalid day"}), 400

        with store.lock:
            ent_del, exi_del = store.delete_events_for_day(day)
            # mantieni consistenza dei cumulativi (non sotto zero)
            store.counts["enter"] = max(0, store.counts["enter"] - ent_del)
            store.counts["exit"]  = max(0, store.counts["exit"]  - exi_del)
            store.save_counts()
            snap = store.snapshot()
        print(f"[admin] reset day {day}: -{ent_del} enter, -{exi_del} exit",
              flush=True)
        return jsonify({
            "ok": True, "action": "reset-day", "day": day.isoformat(),
            "deleted_enter": ent_del, "deleted_exit": exi_del,
            **snap,
        })

    @app.route("/api/admin/reset-all", methods=["POST"])
    @login_required
    def api_reset_all():
        """Cancella TUTTO: cumulativi + storico (jsonl + Postgres)."""
        with store.lock:
            deleted_pg = store.delete_all_events()
            store.counts["enter"] = 0
            store.counts["exit"] = 0
            tracker.clear_all()
            store.save_counts()
            snap = store.snapshot()
        print(f"[admin] WIPE totale (postgres: {deleted_pg} righe)", flush=True)
        return jsonify({
            "ok": True, "action": "reset-all",
            "deleted_pg_rows": deleted_pg, **snap,
        })

    # ---- alias retrocompatibile con il vecchio /api/reset ----
    @app.route("/api/reset", methods=["POST"])
    @login_required
    def api_reset_legacy():
        return api_reset_counters()

    @app.route("/export.csv")
    @login_required
    def export_csv():
        day = _parse_day(request.args.get("day"))
        h_from = request.args.get("from", type=int)
        h_to = request.args.get("to", type=int)
        events = _filter_hour_range(store.get_events_for_day(day), h_from, h_to)

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([
            "datetime", "type", "method",
            "start_x", "start_y", "end_x", "end_y",
            "enter_after", "exit_after", "occupancy_after", "reason",
        ])
        for e in events:
            c = e.get("counts_after", {})
            w.writerow([
                e.get("datetime", ""),
                e.get("type", ""),
                e.get("method", ""),
                e.get("start", {}).get("x", ""),
                e.get("start", {}).get("y", ""),
                e.get("end", {}).get("x", ""),
                e.get("end", {}).get("y", ""),
                c.get("enter", ""),
                c.get("exit", ""),
                c.get("occupancy", ""),
                e.get("reason", ""),
            ])

        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={
                "Content-Disposition":
                    f'attachment; filename="counter_{Config.CAMERA}_{day}.csv"',
            },
        )

    # -------- SETTINGS --------

    @app.route("/settings")
    @login_required
    def settings_page():
        with store.lock:
            snap = store.snapshot()
        stats = store.get_stats()
        return render_template(
            "settings.html",
            camera=Config.CAMERA,
            current=Settings.current(),
            snapshot=snap,
            stats=stats,
            today_iso=date.today().isoformat(),
            postgres_enabled=Config.postgres_enabled(),
            frigate_url_set=bool(Config.FRIGATE_URL),
            snapshot_refresh=Config.SNAPSHOT_REFRESH_SEC,
            auth_enabled=Config.auth_enabled(),
        )

    @app.route("/api/settings", methods=["GET"])
    @login_required
    def api_settings_get():
        return jsonify({
            "current": Settings.current(),       # secrets mascherati
            "schema": Settings.schema(),
            "frigate_url_set": bool(Config.FRIGATE_URL),
            "postgres_connected": store.pg is not None,
        })

    @app.route("/api/settings", methods=["POST"])
    @login_required
    def api_settings_post():
        if request.is_json:
            payload = request.get_json(silent=True) or {}
        else:
            payload = request.form.to_dict()
        try:
            result = Settings.update(payload)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        print(f"[settings] aggiornati: {result['changed']}", flush=True)

        # Se sono cambiate le DB_*, riconnetti il Postgres in caldo
        pg_changed = any(k.startswith("DB_") for k in result["changed"])
        pg_result = None
        if pg_changed:
            ok, msg = store.reconnect_postgres()
            pg_result = {"ok": ok, "message": msg}

        return jsonify({
            "ok": True,
            "changed": result["changed"],
            "restart_needed": result["restart_needed"],
            "postgres_reconnect": pg_result,
            "current": Settings.current(),
        })

    # -------- DATABASE --------

    @app.route("/api/db/test", methods=["POST"])
    @login_required
    def api_db_test():
        """Testa connessione PG SENZA salvare nulla.

        Accetta i parametri DB_* nel body; se vuoti/'***' usa quelli correnti.
        """
        payload = request.get_json(silent=True) or {}

        def pick(key, default):
            v = payload.get(key)
            if v is None or v == "" or v == "***":
                return default
            return v

        host = pick("DB_HOST", Config.DB_HOST)
        port = int(pick("DB_PORT", Config.DB_PORT))
        name = pick("DB_NAME", Config.DB_NAME)
        user = pick("DB_USER", Config.DB_USER)
        # password: stringa vuota o '***' = usa quella attuale
        pwd = payload.get("DB_PASS")
        if pwd in (None, "", "***"):
            pwd = Config.DB_PASS
        schema = pick("DB_SCHEMA", Config.DB_SCHEMA)
        table = pick("DB_TABLE", Config.DB_TABLE)
        sslmode = pick("DB_SSLMODE", Config.DB_SSLMODE)

        if not (host and name and user):
            return jsonify({"ok": False,
                            "error": "DB_HOST, DB_NAME, DB_USER obbligatori"}), 400

        result = Store.test_postgres_connection(
            host, port, name, user, pwd, schema, table, sslmode,
        )
        return jsonify(result)

    @app.route("/api/db/sql")
    @login_required
    def api_db_sql():
        """Restituisce il comando SQL CREATE TABLE con i nomi correnti."""
        schema = Config.DB_SCHEMA or "public"
        table = Config.DB_TABLE or "counter_events"
        full = f'"{schema}"."{table}"'
        sql = f"""-- Schema PostgreSQL per Frigate Person Counter
-- Genera ed esegue automaticamente dall'app al primo avvio se l'utente DB
-- ha permessi di CREATE. Eseguilo manualmente solo se serve un setup esplicito.

CREATE TABLE IF NOT EXISTS {full} (
    id              BIGSERIAL    PRIMARY KEY,
    event_id        TEXT         NOT NULL,             -- id Frigate
    camera          TEXT         NOT NULL,
    ts              TIMESTAMPTZ  NOT NULL,             -- istante conteggio
    event_type      TEXT         NOT NULL CHECK (event_type IN ('enter','exit')),
    method          TEXT,                              -- es. 'line_cross'
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

CREATE INDEX IF NOT EXISTS idx_{table}_camera_ts ON {full} (camera, ts DESC);
CREATE INDEX IF NOT EXISTS idx_{table}_ts        ON {full} (ts DESC);
CREATE INDEX IF NOT EXISTS idx_{table}_type      ON {full} (event_type);

-- View opzionali (riepilogo giornaliero / orario)
CREATE OR REPLACE VIEW {schema}.counter_daily_summary AS
SELECT
    camera,
    (ts AT TIME ZONE 'UTC')::date                       AS day,
    COUNT(*) FILTER (WHERE event_type = 'enter')        AS enter_count,
    COUNT(*) FILTER (WHERE event_type = 'exit')         AS exit_count,
    MAX(occupancy)                                      AS peak_occupancy
FROM {full}
GROUP BY camera, (ts AT TIME ZONE 'UTC')::date;

CREATE OR REPLACE VIEW {schema}.counter_hourly_summary AS
SELECT
    camera,
    date_trunc('hour', ts)                              AS hour,
    COUNT(*) FILTER (WHERE event_type = 'enter')        AS enter_count,
    COUNT(*) FILTER (WHERE event_type = 'exit')         AS exit_count
FROM {full}
GROUP BY camera, date_trunc('hour', ts);
"""
        return jsonify({"sql": sql, "table": full})

    # -------- WEBHOOK --------

    @app.route("/api/webhook/test", methods=["POST"])
    @login_required
    def api_webhook_test():
        """Invia un evento finto al webhook configurato e ritorna l'esito."""
        if not Config.WEBHOOK_URL:
            return jsonify({"ok": False,
                            "error": "WEBHOOK_URL non configurata"}), 400
        payload = {
            "event":       "enter",
            "camera":      Config.CAMERA,
            "ts":          time.time(),
            "datetime":    time.strftime("%Y-%m-%d %H:%M:%S"),
            "occupancy":   0,
            "enter_total": 0,
            "exit_total":  0,
            "method":      "test",
            "event_id":    "test-event",
            "start":       {"x": 0.50, "y": 0.10},
            "end":         {"x": 0.50, "y": 0.90},
            "reason":      "manual test from /settings",
            "_test":       True,
        }
        try:
            status, body = webhook_mod._post_once(
                Config.WEBHOOK_URL, payload, Config.WEBHOOK_TIMEOUT)
            return jsonify({
                "ok": 200 <= status < 300,
                "status": status,
                "body_preview": body.decode("utf-8", errors="replace")[:300],
                "url": Config.WEBHOOK_URL,
            })
        except Exception as e:
            return jsonify({
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "url": Config.WEBHOOK_URL,
            }), 502

    # -------- CAMERE FRIGATE (per il dropdown della UI) --------

    @app.route("/api/frigate/cameras")
    @login_required
    def api_frigate_cameras():
        if not Config.FRIGATE_URL:
            return jsonify({"ok": False, "error": "FRIGATE_URL non configurata",
                            "cameras": []}), 503
        status, ctype, data, err, url = _fetch_frigate("/api/config")
        if err or status != 200 or not data:
            return jsonify({"ok": False, "error": err or f"HTTP {status}",
                            "cameras": []}), 502
        try:
            cfg = __import__("json").loads(data.decode("utf-8"))
            cams = sorted((cfg.get("cameras") or {}).keys())
        except Exception as e:
            return jsonify({"ok": False, "error": str(e),
                            "cameras": []}), 500
        return jsonify({"ok": True, "cameras": cams,
                        "current": Config.CAMERA})

    def _fetch_frigate(path):
        """Tenta una GET verso Frigate e ritorna (status, content_type, data, error)."""
        url = f"{Config.FRIGATE_URL}{path}"
        req = urllib.request.Request(
            url, headers={"User-Agent": "frigate-counter"})
        try:
            with urllib.request.urlopen(req, timeout=4) as r:
                return r.status, r.headers.get("Content-Type", ""), r.read(), None, url
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read(512).decode("utf-8", errors="replace")
            except Exception:
                pass
            return e.code, "", b"", f"HTTP {e.code} {e.reason}: {body}", url
        except urllib.error.URLError as e:
            return 0, "", b"", f"network: {e.reason}", url
        except Exception as e:
            return 0, "", b"", f"{type(e).__name__}: {e}", url

    @app.route("/api/snapshot")
    @login_required
    def api_snapshot():
        """Proxy verso Frigate latest.jpg, evita CORS e tiene l'auth lato server."""
        if not Config.FRIGATE_URL:
            return jsonify({
                "ok": False,
                "error": "FRIGATE_URL non configurata (vedi env del container)",
                "hint": "Es: FRIGATE_URL=http://192.168.1.10:5000",
            }), 503

        # Frigate cambia path tra versioni. Proviamo i due più comuni in ordine.
        candidates = [
            f"/api/{Config.CAMERA}/latest.jpg",     # storico, Frigate 0.10+
            f"/api/{Config.CAMERA}/snapshot.jpg",   # alcuni setup
        ]
        errors = []
        for path in candidates:
            status, ctype, data, err, full_url = _fetch_frigate(path)
            if err is None and status == 200 and data:
                return Response(data, mimetype=ctype or "image/jpeg",
                                headers={"Cache-Control": "no-store"})
            print(f"[snapshot] FAIL {full_url} -> "
                  f"status={status} err={err}", flush=True)
            errors.append({"url": full_url, "status": status, "error": err})

        # Tutti i tentativi falliti
        last = errors[-1]
        body = {
            "ok": False,
            "error": last["error"] or f"HTTP {last['status']}",
            "tried": errors,
            "frigate_url": Config.FRIGATE_URL,
            "camera": Config.CAMERA,
            "hint": _snapshot_hint(errors),
        }
        # 502 se è errore rete, 404/etc passa attraverso
        status_out = 502 if last["status"] == 0 else last["status"]
        return jsonify(body), status_out

    def _snapshot_hint(errors):
        """Suggerimento testuale in base al tipo di errore."""
        last = errors[-1]
        s, e = last["status"], (last["error"] or "")
        if "Connection refused" in e:
            return ("Connection refused: il container counter raggiunge il "
                    "FRIGATE_URL ma sulla porta non risponde nessuno. "
                    "Verifica che Frigate sia in ascolto su quella porta.")
        if "Name or service not known" in e or "nodename nor servname" in e:
            return ("DNS / hostname non risolto. Se Frigate è in un altro "
                    "container, usa il nome del servizio Docker "
                    "(es. http://frigate:5000) e mettilo nella stessa "
                    "network del compose.")
        if "timed out" in e or "timeout" in e.lower():
            return ("Timeout: il container vede l'IP ma la risposta non "
                    "arriva entro 4s. Controlla firewall, VPN, IP corretto.")
        if s == 404:
            return (f"Frigate risponde, ma 404 sulla camera '{Config.CAMERA}'. "
                    "Controlla che CAMERA_NAME corrisponda ESATTAMENTE al nome "
                    "in Frigate (case-sensitive, niente spazi).")
        if s == 401 or s == 403:
            return ("Frigate richiede autenticazione. Questa funzione non "
                    "supporta auth Frigate al momento — disabilitala in "
                    "Frigate o esponi un endpoint interno aperto.")
        if s in (502, 503, 504):
            return "Frigate non pronto / reverse proxy a vuoto."
        return ("Apri il container counter (docker exec -it ...) e prova: "
                f"curl -v {Config.FRIGATE_URL}/api/{Config.CAMERA}/latest.jpg")

    @app.route("/api/snapshot/diag")
    @login_required
    def api_snapshot_diag():
        """Diagnostica passo-passo per debug della connessione a Frigate."""
        if not Config.FRIGATE_URL:
            return jsonify({"ok": False, "error": "FRIGATE_URL vuota"}), 503

        steps = []
        # 1) /api/version (presente in tutte le versioni di Frigate)
        s, ct, d, err, url = _fetch_frigate("/api/version")
        steps.append({
            "step": "frigate /api/version",
            "url": url, "status": s, "content_type": ct, "error": err,
            "body": d[:200].decode("utf-8", errors="replace") if d else "",
        })
        # 2) /api/config (per leggere le camere disponibili)
        s, ct, d, err, url = _fetch_frigate("/api/config")
        cams = []
        if d and not err:
            try:
                import json as _json
                cfg = _json.loads(d.decode("utf-8", errors="replace"))
                cams = list((cfg.get("cameras") or {}).keys())
            except Exception:
                pass
        steps.append({
            "step": "frigate /api/config (cameras list)",
            "url": url, "status": s, "error": err, "cameras_found": cams,
        })
        # 3) latest.jpg
        s, ct, d, err, url = _fetch_frigate(
            f"/api/{Config.CAMERA}/latest.jpg")
        steps.append({
            "step": "snapshot latest.jpg",
            "url": url, "status": s, "content_type": ct, "error": err,
            "bytes": len(d),
        })
        return jsonify({
            "ok": all(st.get("error") is None and (st.get("status") or 0) < 400
                      for st in steps),
            "frigate_url": Config.FRIGATE_URL,
            "configured_camera": Config.CAMERA,
            "steps": steps,
        })

    return app
