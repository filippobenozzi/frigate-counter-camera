"""Flask app: dashboard + API + auth. Sorgente dati = eventi MQTT (ESP)."""

import csv
import io
import time
from datetime import date, datetime, timedelta

from flask import (Flask, Response, jsonify, redirect, render_template,
                   request, session, url_for)

from app import webhook as webhook_mod
from app.auth import credentials_match, login_required
from app.config import Config
from app.settings import Settings
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


def create_app(store, mqtt):
    app = Flask(__name__, template_folder="templates")
    app.secret_key = Config.SECRET_KEY
    app.permanent_session_lifetime = timedelta(days=Config.SESSION_DAYS)

    # ===================== AUTH =====================

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
                return redirect(request.args.get("next") or url_for("dashboard"))
            error = "Credenziali non valide"
        return render_template("login.html", error=error, camera=Config.CAMERA)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ===================== DASHBOARD =====================

    @app.route("/")
    @login_required
    def dashboard():
        day = _parse_day(request.args.get("day"))
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
        filtered = list(reversed(_filter_hour_range(events, h_from, h_to)))

        return render_template(
            "dashboard.html",
            camera=Config.CAMERA,
            snapshot=snapshot,
            day=day,
            prev_day=(day - timedelta(days=1)).isoformat(),
            next_day=(day + timedelta(days=1)).isoformat(),
            today_iso=today.isoformat(),
            is_today=(day == today),
            hourly=hourly,
            day_enter=day_enter,
            day_exit=day_exit,
            day_peak=day_peak,
            events=filtered,
            h_from=h_from if h_from is not None else 0,
            h_to=h_to if h_to is not None else 23,
            postgres_enabled=Config.postgres_enabled(),
            auth_enabled=Config.auth_enabled(),
            mqtt_connected=mqtt.connected,
        )

    # ===================== API dati =====================

    @app.route("/api/counts")
    @login_required
    def api_counts():
        with store.lock:
            return jsonify(store.snapshot())

    @app.route("/api/hourly")
    @login_required
    def api_hourly():
        day = _parse_day(request.args.get("day"))
        return jsonify({"day": day.isoformat(),
                        "hourly": summarize_hourly(store.get_events_for_day(day))})

    @app.route("/api/events")
    @login_required
    def api_events():
        day = _parse_day(request.args.get("day"))
        events = store.get_events_for_day(day)
        h_from = request.args.get("from", type=int)
        h_to = request.args.get("to", type=int)
        return jsonify({"day": day.isoformat(), "count": len(events),
                        "events": _filter_hour_range(events, h_from, h_to)})

    @app.route("/api/days")
    @login_required
    def api_days():
        return jsonify([d.isoformat() for d in store.get_available_days()])

    @app.route("/api/health")
    @login_required
    def api_health():
        return jsonify(mqtt.stats())

    # ===================== ADMIN reset =====================

    @app.route("/api/admin/reset-counters", methods=["POST"])
    @login_required
    def api_reset_counters():
        with store.lock:
            store.counts["enter"] = 0
            store.counts["exit"] = 0
            store.save_counts()
            snap = store.snapshot()
        print("[admin] reset cumulativi", flush=True)
        return jsonify({"ok": True, "action": "reset-counters", **snap})

    @app.route("/api/admin/reset-day", methods=["POST"])
    @login_required
    def api_reset_day():
        day_str = request.form.get("day") or request.args.get("day")
        if not day_str:
            return jsonify({"ok": False, "error": "missing day"}), 400
        try:
            day = datetime.strptime(day_str, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"ok": False, "error": "invalid day"}), 400
        with store.lock:
            ent_del, exi_del = store.delete_events_for_day(day)
            store.counts["enter"] = max(0, store.counts["enter"] - ent_del)
            store.counts["exit"] = max(0, store.counts["exit"] - exi_del)
            store.save_counts()
            snap = store.snapshot()
        print(f"[admin] reset day {day}: -{ent_del} enter, -{exi_del} exit",
              flush=True)
        return jsonify({"ok": True, "action": "reset-day", "day": day.isoformat(),
                        "deleted_enter": ent_del, "deleted_exit": exi_del, **snap})

    @app.route("/api/admin/reset-all", methods=["POST"])
    @login_required
    def api_reset_all():
        with store.lock:
            deleted_pg = store.delete_all_events()
            store.counts["enter"] = 0
            store.counts["exit"] = 0
            store.save_counts()
            snap = store.snapshot()
        print(f"[admin] WIPE totale (postgres: {deleted_pg} righe)", flush=True)
        return jsonify({"ok": True, "action": "reset-all",
                        "deleted_pg_rows": deleted_pg, **snap})

    @app.route("/api/reset", methods=["POST"])
    @login_required
    def api_reset_legacy():
        return api_reset_counters()

    # ===================== EXPORT =====================

    @app.route("/export.csv")
    @login_required
    def export_csv():
        day = _parse_day(request.args.get("day"))
        h_from = request.args.get("from", type=int)
        h_to = request.args.get("to", type=int)
        events = _filter_hour_range(store.get_events_for_day(day), h_from, h_to)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["datetime", "type", "method", "enter_after", "exit_after",
                    "occupancy_after", "reason"])
        for e in events:
            c = e.get("counts_after", {})
            w.writerow([e.get("datetime", ""), e.get("type", ""),
                        e.get("method", ""), c.get("enter", ""),
                        c.get("exit", ""), c.get("occupancy", ""),
                        e.get("reason", "")])
        return Response(buf.getvalue(), mimetype="text/csv", headers={
            "Content-Disposition":
                f'attachment; filename="counter_{Config.CAMERA}_{day}.csv"'})

    # ===================== SETTINGS =====================

    @app.route("/settings")
    @login_required
    def settings_page():
        with store.lock:
            snap = store.snapshot()
        return render_template(
            "settings.html",
            camera=Config.CAMERA,
            current=Settings.current(),
            snapshot=snap,
            stats=store.get_stats(),
            today_iso=date.today().isoformat(),
            postgres_enabled=Config.postgres_enabled(),
            mqtt_connected=mqtt.connected,
            auth_enabled=Config.auth_enabled(),
        )

    @app.route("/api/settings", methods=["GET"])
    @login_required
    def api_settings_get():
        return jsonify({"current": Settings.current(), "schema": Settings.schema(),
                        "postgres_connected": store.pg is not None})

    @app.route("/api/settings", methods=["POST"])
    @login_required
    def api_settings_post():
        payload = (request.get_json(silent=True) or {}) if request.is_json \
            else request.form.to_dict()
        try:
            result = Settings.update(payload)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        print(f"[settings] aggiornati: {result['changed']}", flush=True)
        pg_result = None
        if any(k.startswith("DB_") for k in result["changed"]):
            ok, msg = store.reconnect_postgres()
            pg_result = {"ok": ok, "message": msg}
        return jsonify({"ok": True, "changed": result["changed"],
                        "restart_needed": result["restart_needed"],
                        "postgres_reconnect": pg_result,
                        "current": Settings.current()})

    # ===================== DATABASE =====================

    @app.route("/api/db/test", methods=["POST"])
    @login_required
    def api_db_test():
        payload = request.get_json(silent=True) or {}

        def pick(key, default):
            v = payload.get(key)
            return default if v in (None, "", "***") else v

        host = pick("DB_HOST", Config.DB_HOST)
        port = int(pick("DB_PORT", Config.DB_PORT))
        name = pick("DB_NAME", Config.DB_NAME)
        user = pick("DB_USER", Config.DB_USER)
        pwd = payload.get("DB_PASS")
        if pwd in (None, "", "***"):
            pwd = Config.DB_PASS
        schema = pick("DB_SCHEMA", Config.DB_SCHEMA)
        table = pick("DB_TABLE", Config.DB_TABLE)
        sslmode = pick("DB_SSLMODE", Config.DB_SSLMODE)
        if not (host and name and user):
            return jsonify({"ok": False,
                            "error": "DB_HOST, DB_NAME, DB_USER obbligatori"}), 400
        return jsonify(Store.test_postgres_connection(
            host, port, name, user, pwd, schema, table, sslmode))

    @app.route("/api/db/sql")
    @login_required
    def api_db_sql():
        schema = Config.DB_SCHEMA or "public"
        table = Config.DB_TABLE or "counter_events"
        full = f'"{schema}"."{table}"'
        sql = f"""-- Schema PostgreSQL per Person Counter (eventi MQTT)
CREATE TABLE IF NOT EXISTS {full} (
    id              BIGSERIAL    PRIMARY KEY,
    event_id        TEXT         NOT NULL,
    camera          TEXT         NOT NULL,
    ts              TIMESTAMPTZ  NOT NULL,
    event_type      TEXT         NOT NULL CHECK (event_type IN ('enter','exit')),
    method          TEXT,                              -- 'mqtt'
    start_x REAL, start_y REAL, end_x REAL, end_y REAL,
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
"""
        return jsonify({"sql": sql, "table": full})

    # ===================== WEBHOOK =====================

    @app.route("/api/webhook/test", methods=["POST"])
    @login_required
    def api_webhook_test():
        if not Config.WEBHOOK_URL:
            return jsonify({"ok": False,
                            "error": "WEBHOOK_URL non configurata"}), 400
        payload = {
            "event": "enter", "camera": Config.CAMERA, "ts": time.time(),
            "datetime": time.strftime("%Y-%m-%d %H:%M:%S"),
            "occupancy": 0, "enter_total": 0, "exit_total": 0,
            "method": "test", "event_id": "test-event",
            "reason": "manual test from /settings", "_test": True,
        }
        try:
            status, body = webhook_mod._post_once(
                Config.WEBHOOK_URL, payload, Config.WEBHOOK_TIMEOUT)
            return jsonify({"ok": 200 <= status < 300, "status": status,
                            "body_preview": body.decode("utf-8", errors="replace")[:300],
                            "url": Config.WEBHOOK_URL})
        except Exception as e:
            return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}",
                            "url": Config.WEBHOOK_URL}), 502

    return app
