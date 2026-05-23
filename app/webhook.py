"""Webhook fire-and-forget: notifica un URL esterno per ogni enter/exit.

Disaccoppiato dal listener MQTT tramite una queue: il listener fa
`webhook.notify(payload)` e torna subito; un worker thread consuma la queue
e fa le HTTP POST con eventuali retry. Errori loggati ma mai propagati.

Payload inviato (JSON):
{
  "event":          "enter" | "exit",
  "camera":         "ingresso",
  "ts":             1716470000.123,        // unix timestamp
  "datetime":       "2026-05-23 18:42:13",
  "occupancy":      4,                     // presenti dopo l'evento
  "enter_total":    1247,
  "exit_total":     1243,
  "method":         "line_cross",
  "event_id":       "1716...some-id",
  "start":          {"x": 0.45, "y": 0.10},
  "end":            {"x": 0.43, "y": 0.88},
  "reason":         "line_cross movement=down ..."
}
"""

import json
import threading
import time
import urllib.error
import urllib.request
from queue import Empty, Queue

from app.config import Config


_queue: "Queue[dict]" = Queue(maxsize=500)
_started = False


def notify(event_data: dict):
    """Mette il payload in coda. Non blocca mai il chiamante."""
    if not Config.WEBHOOK_ENABLED or not Config.WEBHOOK_URL:
        return
    try:
        _queue.put_nowait(event_data)
    except Exception as e:
        print(f"[webhook] queue full, scarto evento: {e}", flush=True)


def _build_headers():
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "frigate-counter-webhook/1.0",
    }
    raw = (Config.WEBHOOK_HEADERS or "").strip()
    if not raw:
        return headers
    try:
        extra = json.loads(raw)
        if isinstance(extra, dict):
            for k, v in extra.items():
                headers[str(k)] = str(v)
    except Exception as e:
        print(f"[webhook] WEBHOOK_HEADERS non è JSON valido: {e}", flush=True)
    return headers


def _post_once(url, payload, timeout):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST", headers=_build_headers(),
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read(256)


def _worker():
    while True:
        try:
            payload = _queue.get(timeout=1)
        except Empty:
            continue

        if not Config.WEBHOOK_ENABLED or not Config.WEBHOOK_URL:
            # disabilitato mentre era in coda: scarto silenziosamente
            continue

        url = Config.WEBHOOK_URL
        timeout = Config.WEBHOOK_TIMEOUT
        attempts = max(1, Config.WEBHOOK_RETRY + 1)

        for attempt in range(1, attempts + 1):
            try:
                status, _body = _post_once(url, payload, timeout)
                if 200 <= status < 300:
                    print(f"[webhook] {payload.get('event')} -> {url} "
                          f"[{status}] (try {attempt})", flush=True)
                    break
                print(f"[webhook] {url} HTTP {status} (try {attempt}/"
                      f"{attempts})", flush=True)
            except urllib.error.HTTPError as e:
                print(f"[webhook] {url} HTTP {e.code} (try {attempt}/"
                      f"{attempts})", flush=True)
            except urllib.error.URLError as e:
                print(f"[webhook] {url} unreachable: {e.reason} "
                      f"(try {attempt}/{attempts})", flush=True)
            except Exception as e:
                print(f"[webhook] {url} error: {e} (try {attempt}/"
                      f"{attempts})", flush=True)
            if attempt < attempts:
                time.sleep(min(2 ** attempt, 5))


def start():
    """Avvia il worker thread (idempotente)."""
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_worker, daemon=True, name="webhook").start()
    print("[webhook] worker avviato", flush=True)
