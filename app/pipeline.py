"""Pipeline video: cattura -> detection -> tracking -> conteggio -> storage.

Gira in un thread dedicato a FPS configurabile. Mantiene l'ultimo frame
annotato (JPEG) per la dashboard e lo snapshot delle impostazioni.
"""

import threading
import time
from collections import deque

import numpy as np

try:
    import cv2
except Exception:                      # pragma: no cover
    cv2 = None

from app import webhook
from app.capture import RtspCapture
from app.config import Config
from app.counting import LineCounter
from app.detector import YoloDetector
from app.sort import Sort


class Pipeline:
    def __init__(self, store, mqtt_pub=None):
        self.store = store
        self.mqtt = mqtt_pub
        self.capture = RtspCapture()
        self.detector = None
        self.tracker = Sort(
            max_age=Config.TRACK_MAX_AGE,
            min_hits=Config.TRACK_MIN_HITS,
            iou_threshold=Config.TRACK_IOU,
        )
        self.counters = {}             # track_id -> LineCounter
        self.recent = deque(maxlen=100)
        self.tracks = {}               # snapshot per /api/tracks
        self._latest_jpeg = None
        self._jpeg_lock = threading.Lock()
        self._running = False
        self._stats = {"detect_ms": 0.0, "proc_fps": 0.0, "detections": 0}
        # overlay solo se qualcuno guarda lo snapshot (risparmio CPU)
        self._last_snap_request = 0.0
        self._render_min_period = 0.2          # max ~5 fps di overlay

    # ---------------- avvio ----------------

    def start(self):
        self.capture.start()
        self._running = True
        threading.Thread(target=self._load_and_run, daemon=True,
                         name="pipeline").start()

    def _load_and_run(self):
        # carica il modello (può richiedere un attimo) senza bloccare il web
        try:
            self.detector = YoloDetector()
        except Exception as e:
            print(f"[pipeline] ERRORE caricamento detector: {e}", flush=True)
            return
        self._run()

    # ---------------- loop principale ----------------

    def note_snapshot_request(self):
        """Segnala che qualcuno sta guardando lo snapshot (attiva l'overlay)."""
        self._last_snap_request = time.time()

    def _run(self):
        last_seq = -1
        last_render = 0.0
        proc_ema = 0.0

        while self._running:
            period = 1.0 / max(1.0, Config.DETECT_FPS)   # live da settings
            t0 = time.time()
            frame, seq = self.capture.latest()
            if frame is None or seq == last_seq:
                time.sleep(0.01)
                continue
            last_seq = seq

            h, w = frame.shape[:2]

            try:
                dets = self.detector.detect(frame)
            except Exception as e:
                print(f"[pipeline] detect error: {e}", flush=True)
                time.sleep(0.1)
                continue

            arr = (np.array([[d[0], d[1], d[2], d[3], d[4]] for d in dets])
                   if dets else np.empty((0, 5)))
            tracked = self.tracker.update(arr)

            self._process_tracks(tracked, w, h)

            # overlay+JPEG solo se qualcuno guarda lo snapshot (ultimi 10s),
            # throttlato a ~5 fps: quando nessuno è sulle impostazioni, niente
            # costo di disegno/encode
            now = time.time()
            if (Config.DRAW_OVERLAY
                    and now - self._last_snap_request < 10.0
                    and now - last_render >= self._render_min_period):
                self._render(frame, dets, tracked)
                last_render = now

            # statistiche
            dt = time.time() - t0
            inst = 1.0 / dt if dt > 0 else 0.0
            proc_ema = 0.9 * proc_ema + 0.1 * inst if proc_ema else inst
            self._stats = {
                "detect_ms": round(self.detector.last_ms, 1),
                "proc_fps": round(proc_ema, 2),
                "detections": len(dets),
                "tracks": len(tracked),
            }

            # mantieni il FPS target
            sleep = period - (time.time() - t0)
            if sleep > 0:
                time.sleep(sleep)

    # ---------------- conteggio ----------------

    def _process_tracks(self, tracked, w, h):
        snap = {}
        alive = set()
        with self.store.lock:
            for tr in tracked:
                tid = tr["id"]
                alive.add(tid)
                x1, y1, x2, y2 = tr["bbox"]
                cxn = ((x1 + x2) / 2.0) / w
                if Config.POINT_MODE == "center":
                    yn = ((y1 + y2) / 2.0) / h
                else:
                    yn = y2 / h
                cxn = min(max(cxn, 0.0), 1.0)
                yn = min(max(yn, 0.0), 1.0)

                snap[tid] = {
                    "bbox_norm": [x1 / w, y1 / h, x2 / w, y2 / h],
                    "point": [round(cxn, 4), round(yn, 4)],
                    "confirmed": tr["confirmed"],
                }

                if not tr["confirmed"]:
                    continue
                lc = self.counters.get(tid)
                if lc is None:
                    lc = LineCounter()
                    self.counters[tid] = lc
                event, reason, start_pt = lc.update(cxn, yn)
                if event:
                    self._register(tid, event, start_pt, (cxn, yn), reason)

            # pulizia contatori di id non più attivi (dentro il lock)
            for dead in list(self.counters.keys()):
                if dead not in alive:
                    self.counters.pop(dead, None)

        self.tracks = snap

    def _register(self, tid, event, start_pt, end_pt, reason):
        """Chiamato con self.store.lock già acquisito."""
        self.store.counts[event] += 1
        ts = time.time()
        snap = self.store.snapshot()
        self.store.save_counts()
        event_id = f"{int(ts)}-{tid}"
        self.store.insert_event(
            event_id=event_id, ts=ts, event_type=event, method="yolo_line",
            start_xy=start_pt, end_xy=end_pt, reason=reason, snapshot=snap,
        )
        self.recent.appendleft({
            "id": event_id, "ts": ts, "type": event,
            "start": list(start_pt), "end": list(end_pt),
            "method": "yolo_line", "reason": reason,
        })
        print(f"[count] track={tid} -> {event.upper()} {reason} "
              f"totali={snap}", flush=True)

        if self.mqtt:
            self.mqtt.publish_counts(snap)
        webhook.notify({
            "event": event, "camera": Config.CAMERA, "ts": ts,
            "datetime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
            "occupancy": snap["occupancy"], "enter_total": snap["enter"],
            "exit_total": snap["exit"], "method": "yolo_line",
            "event_id": event_id,
            "start": {"x": round(start_pt[0], 4), "y": round(start_pt[1], 4)},
            "end": {"x": round(end_pt[0], 4), "y": round(end_pt[1], 4)},
            "reason": reason,
        })

    # ---------------- rendering overlay ----------------

    def _render(self, frame, dets, tracked):
        if cv2 is None or not Config.DRAW_OVERLAY:
            return
        h, w = frame.shape[:2]
        img = frame

        # ROI (azzurro)
        rx1, ry1 = int(Config.MOTION_X1 * w), int(Config.MOTION_Y1 * h)
        rx2, ry2 = int(Config.MOTION_X2 * w), int(Config.MOTION_Y2 * h)
        cv2.rectangle(img, (rx1, ry1), (rx2, ry2), (247, 195, 79), 1)

        # linea + margine (giallo)
        ly = int(Config.LINE_Y * h)
        mtop = int((Config.LINE_Y - Config.LINE_MARGIN) * h)
        mbot = int((Config.LINE_Y + Config.LINE_MARGIN) * h)
        cv2.line(img, (0, ly), (w, ly), (0, 235, 255), 2)
        cv2.line(img, (0, mtop), (w, mtop), (0, 235, 255), 1)
        cv2.line(img, (0, mbot), (w, mbot), (0, 235, 255), 1)

        # box persone (bianco)
        for tr in tracked:
            x1, y1, x2, y2 = [int(v) for v in tr["bbox"]]
            col = (255, 255, 255) if tr["confirmed"] else (140, 140, 140)
            cv2.rectangle(img, (x1, y1), (x2, y2), col, 2)
            cv2.putText(img, f"#{tr['id']}", (x1, max(0, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1, cv2.LINE_AA)

        # contatori in alto a sinistra
        snap = self.store.snapshot()
        txt = (f"ENTER {snap['enter']}  EXIT {snap['exit']}  "
               f"PRESENTI {snap['occupancy']}")
        cv2.rectangle(img, (0, 0), (max(260, 12 * len(txt)), 26), (0, 0, 0), -1)
        cv2.putText(img, txt, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (255, 255, 255), 1, cv2.LINE_AA)

        ok, buf = cv2.imencode(".jpg", img,
                               [int(cv2.IMWRITE_JPEG_QUALITY),
                                Config.JPEG_QUALITY])
        if ok:
            with self._jpeg_lock:
                self._latest_jpeg = buf.tobytes()

    # ---------------- API per il web ----------------

    def latest_jpeg(self):
        with self._jpeg_lock:
            return self._latest_jpeg

    def stats(self):
        s = dict(self._stats)
        s.update(self.capture.stats())
        s["model_loaded"] = self.detector is not None
        return s
