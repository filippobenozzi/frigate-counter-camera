"""Subscriber MQTT: consuma gli eventi enter/exit dell'ESP people counter.

Parser tollerante: riconosce enter/exit guardando, in ordine:
  1. l'ultimo segmento del TOPIC (es. people_counter/ingresso/enter)
  2. il PAYLOAD come stringa (es. "enter", "in", "uscita")
  3. il PAYLOAD JSON, nei campi event/direction/type/action/state
       (es. {"event": "exit"}  oppure  {"direction": "in"})

I token che identificano enter/exit sono configurabili (MQTT_ENTER_TOKENS /
MQTT_EXIT_TOKENS), così funziona con firmware diversi senza toccare il codice.
"""

import json
import threading
import time

try:
    import paho.mqtt.client as mqtt
except Exception:                      # pragma: no cover
    mqtt = None

from app import webhook
from app.config import Config


# suffissi di telemetria dell'ESP: non sono eventi, non contarli tra gli "ignorati"
_TELEMETRY = {"count", "distance", "availability", "status", "rssi", "uptime"}


def _tokens(csv):
    return {t.strip().lower() for t in csv.split(",") if t.strip()}


def _match(value, tokens):
    return value is not None and str(value).strip().lower() in tokens


class MqttIn:
    def __init__(self, store):
        self.store = store
        self.client = None
        self.connected = False
        self.last_event_ts = None
        self.last_topic = None
        self.messages = 0
        self.ignored = 0
        self.passages = 0
        self._seq = 0
        self._toggle = True        # alternate: True -> prossimo passaggio = enter

    # ---------------- avvio ----------------

    def start(self):
        if mqtt is None:
            print("[mqtt-in] paho non installato", flush=True)
            return
        threading.Thread(target=self._run, daemon=True,
                         name="mqtt-in").start()

    def _make(self):
        try:
            return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except Exception:
            return mqtt.Client()

    def _run(self):
        self.client = self._make()
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        if Config.MQTT_USER:
            self.client.username_pw_set(Config.MQTT_USER, Config.MQTT_PASS)

        while True:
            try:
                print(f"[mqtt-in] connessione a {Config.MQTT_HOST}:"
                      f"{Config.MQTT_PORT}", flush=True)
                self.client.connect(Config.MQTT_HOST, Config.MQTT_PORT, 60)
                self.client.loop_forever()
            except Exception as e:
                self.connected = False
                print(f"[mqtt-in] errore connessione: {e}, retry 5s", flush=True)
                time.sleep(5)

    # ---------------- callback ----------------

    def _on_connect(self, client, *_args):
        self.connected = True
        topic = Config.MQTT_TOPIC
        client.subscribe(topic)
        print(f"[mqtt-in] connesso, sottoscritto a '{topic}'", flush=True)

    def _on_disconnect(self, *_args):
        self.connected = False
        print("[mqtt-in] disconnesso", flush=True)

    def _on_message(self, _client, _userdata, msg):
        self.messages += 1
        topic = msg.topic
        try:
            payload = msg.payload.decode("utf-8", errors="replace").strip()
        except Exception:
            payload = ""

        kind = self._classify(topic, payload)     # enter | exit | pass | None
        if kind == "pass":
            self.passages += 1
            event = self._passage_dir()
        else:
            event = kind

        if Config.DEBUG:
            extra = f" -> {event}" if kind == "pass" else ""
            print(f"[mqtt-in] {topic} = {payload!r} -> {kind or 'ignorato'}{extra}",
                  flush=True)

        if event is None:
            seg = topic.rsplit("/", 1)[-1].lower()
            if seg not in _TELEMETRY:      # telemetria (count/distance/...) non è un errore
                self.ignored += 1
            return
        self._record(event, topic, payload)

    def _passage_dir(self):
        """Mappa un passaggio (raggio singolo, niente direzione) in enter/exit."""
        mode = Config.PASSAGE_MODE
        if mode == "enter":
            return "enter"
        if mode == "exit":
            return "exit"
        # alternate: alterna così entrate ≈ uscite ≈ passaggi/2
        d = "enter" if self._toggle else "exit"
        self._toggle = not self._toggle
        return d

    # ---------------- parsing ----------------

    def _classify(self, topic, payload):
        enter = _tokens(Config.MQTT_ENTER_TOKENS)
        exit_ = _tokens(Config.MQTT_EXIT_TOKENS)
        passt = _tokens(Config.MQTT_PASS_TOKENS)

        def lookup(val):
            if _match(val, enter):
                return "enter"
            if _match(val, exit_):
                return "exit"
            if _match(val, passt):
                return "pass"
            return None

        # 1) ultimo segmento del topic (es. .../enter, .../event con payload pass)
        r = lookup(topic.rsplit("/", 1)[-1])
        if r:
            return r
        # 2) payload come stringa semplice (es. "pass", "enter", "in")
        r = lookup(payload)
        if r:
            return r
        # 3) payload JSON
        if payload[:1] in ("{", "["):
            try:
                data = json.loads(payload)
            except Exception:
                data = None
            if isinstance(data, dict):
                for field in ("event", "direction", "type", "action",
                              "state", "dir"):
                    r = lookup(data.get(field))
                    if r:
                        return r
        return None

    # ---------------- registrazione ----------------

    def _record(self, event, topic, payload):
        with self.store.lock:
            self.store.counts[event] += 1
            ts = time.time()
            snap = self.store.snapshot()
            self.store.save_counts()
            self._seq += 1
            event_id = f"{ts:.3f}-{self._seq}"
            reason = f"mqtt topic={topic} payload={payload[:80]}"
            self.store.insert_event(
                event_id=event_id, ts=ts, event_type=event, method="mqtt",
                start_xy=(0.0, 0.0), end_xy=(0.0, 0.0),
                reason=reason, snapshot=snap,
            )
        self.last_event_ts = ts
        self.last_topic = topic
        print(f"[count] {event.upper()} da MQTT -> {snap}", flush=True)

        webhook.notify({
            "event": event, "camera": Config.CAMERA, "ts": ts,
            "datetime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
            "occupancy": snap["occupancy"], "enter_total": snap["enter"],
            "exit_total": snap["exit"], "method": "mqtt",
            "event_id": event_id, "topic": topic, "reason": reason,
        })

    # ---------------- stato (per /api/health) ----------------

    def stats(self):
        age = (time.time() - self.last_event_ts) if self.last_event_ts else None
        return {
            "connected": self.connected,
            "host": f"{Config.MQTT_HOST}:{Config.MQTT_PORT}",
            "topic": Config.MQTT_TOPIC,
            "messages": self.messages,
            "passages": self.passages,
            "passage_mode": Config.PASSAGE_MODE,
            "ignored": self.ignored,
            "last_topic": self.last_topic,
            "last_event_age": round(age, 1) if age is not None else None,
        }
