"""Flask app: dashboard + API + auth."""

import csv
import io
import time
from datetime import date, datetime, timedelta

from flask import (Flask, Response, jsonify, redirect, render_template,
                   request, session, url_for)

from app.auth import credentials_match, login_required
from app.config import Config
from app.storage import summarize_hourly


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

    @app.route("/api/reset", methods=["POST"])
    @login_required
    def api_reset():
        with store.lock:
            store.counts["enter"] = 0
            store.counts["exit"] = 0
            tracker.clear_all()
            store.save_counts()
            snap = store.snapshot()
        return jsonify({"ok": True, **snap})

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

    return app
