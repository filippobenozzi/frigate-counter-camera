"""MQTT listener: ascolta Frigate, classifica e salva via Store/Tracker."""

import json
import time

import paho.mqtt.client as mqtt

from app.config import Config
from app.motion import classify_full_motion, point_from_box


def zones_match(after) -> bool:
    if not Config.REQUIRED_ZONE:
        return True
    cur = after.get("current_zones") or []
    ent = after.get("entered_zones") or []
    return Config.REQUIRED_ZONE in cur or Config.REQUIRED_ZONE in ent


def _make_client():
    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except Exception:
        return mqtt.Client()


def _publish_counts(client, snap):
    client.publish(f"counter/{Config.CAMERA}/enter",     snap["enter"],     retain=True)
    client.publish(f"counter/{Config.CAMERA}/exit",      snap["exit"],      retain=True)
    client.publish(f"counter/{Config.CAMERA}/occupancy", snap["occupancy"], retain=True)


def run(store, tracker):
    """Loop di consumo eventi Frigate."""

    def register_count(client, evt_id, result, start_pt, end_pt, reason):
        store.counts[result] += 1
        tracker.mark_counted(evt_id)
        snap = store.snapshot()
        ts = time.time()
        store.save_counts()
        store.insert_event(
            event_id=evt_id, ts=ts, event_type=result,
            method="full_motion",
            start_xy=start_pt, end_xy=end_pt,
            reason=reason, snapshot=snap,
        )
        tracker.recent.appendleft({
            "id": evt_id, "ts": ts, "type": result,
            "start": start_pt, "end": end_pt,
            "method": "full_motion", "reason": reason,
        })
        return snap

    def on_connect(client, *_args):
        print(f"[mqtt] connesso a {Config.MQTT_HOST}:{Config.MQTT_PORT}", flush=True)
        client.subscribe("frigate/events")
        with store.lock:
            _publish_counts(client, store.snapshot())

    def on_message(client, _u, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except Exception as e:
            print(f"[mqtt] payload non-json: {e}", flush=True)
            return

        msg_type = payload.get("type")
        if msg_type not in ("new", "update", "end"):
            return

        after = payload.get("after") or {}
        if after.get("camera") != Config.CAMERA:
            return
        if after.get("label") != "person":
            return
        if after.get("false_positive"):
            return
        if not zones_match(after):
            return

        evt_id = after.get("id")
        if not evt_id:
            return

        point = point_from_box(after.get("box"))
        if point is None:
            return

        now = time.time()
        snap_to_publish = None

        with store.lock:
            tracker.cleanup(now)
            tracker.start_or_update(evt_id, point, now)
            t = tracker.tracks.get(evt_id)

            if Config.DEBUG:
                print(
                    f"[evt] {evt_id} {msg_type} "
                    f"point=({point[0]:.3f},{point[1]:.3f}) "
                    f"points={len(t['points']) if t else 0} "
                    f"counted={tracker.is_counted(evt_id)}",
                    flush=True,
                )

            if msg_type == "end" and t and not tracker.is_counted(evt_id):
                result, reason = classify_full_motion(list(t["points"]))
                print(f"[motion] {evt_id}: {reason}", flush=True)
                if result:
                    snap_to_publish = register_count(
                        client, evt_id, result, t["first"], point, reason,
                    )
                    print(
                        f"[count] {evt_id} -> {result.upper()} "
                        f"totali={snap_to_publish}",
                        flush=True,
                    )

            if msg_type == "end":
                tracker.end_track(evt_id)

        if snap_to_publish:
            _publish_counts(client, snap_to_publish)

    client = _make_client()
    client.on_connect = on_connect
    client.on_message = on_message
    if Config.MQTT_USER:
        client.username_pw_set(Config.MQTT_USER, Config.MQTT_PASS)

    while True:
        try:
            print(f"[mqtt] connessione a {Config.MQTT_HOST}:{Config.MQTT_PORT}",
                  flush=True)
            client.connect(Config.MQTT_HOST, Config.MQTT_PORT, 60)
            client.loop_forever()
        except Exception as e:
            print(f"[mqtt] errore connessione: {e}, retry tra 5s", flush=True)
            time.sleep(5)
