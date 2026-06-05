"""Cattura RTSP/RTSPS robusta con riconnessione automatica.

Un thread legge in continuazione dallo stream e conserva SOLO l'ultimo frame
(buffer=1) per evitare accumulo di latenza. Espone latest() thread-safe e
statistiche di salute (fps, età ultimo frame, riconnessioni).
"""

import os
import threading
import time

try:
    import cv2
except Exception:                      # pragma: no cover
    cv2 = None

from app.config import Config


class RtspCapture:
    def __init__(self):
        self._lock = threading.Lock()
        self._frame = None
        self._frame_ts = 0.0
        self._seq = 0
        self._running = False
        self._thread = None
        self.reconnects = 0
        self.opened = False
        self._fps_ema = 0.0
        self._last_read = 0.0

    # ---------- API pubblica ----------

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="rtsp-capture")
        self._thread.start()

    def stop(self):
        self._running = False

    def latest(self):
        """Ritorna (frame_copy, seq) oppure (None, 0)."""
        with self._lock:
            if self._frame is None:
                return None, 0
            return self._frame.copy(), self._seq

    def stats(self):
        age = (time.time() - self._frame_ts) if self._frame_ts else None
        return {
            "opened": self.opened,
            "reconnects": self.reconnects,
            "fps": round(self._fps_ema, 2),
            "last_frame_age": round(age, 2) if age is not None else None,
            "url_set": bool(Config.RTSP_URL),
        }

    # ---------- interno ----------

    def _open(self):
        # opzioni FFmpeg: transport TCP/UDP + timeout lettura (microsecondi)
        opts = (f"rtsp_transport;{Config.RTSP_TRANSPORT}"
                f"|stimeout;{int(Config.CAPTURE_TIMEOUT_SEC * 1_000_000)}")
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = opts
        cap = cv2.VideoCapture(Config.RTSP_URL, cv2.CAP_FFMPEG)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        return cap

    def _loop(self):
        if cv2 is None:
            print("[capture] opencv non disponibile", flush=True)
            return

        while self._running:
            if not Config.RTSP_URL:
                time.sleep(1.0)
                continue

            print(f"[capture] apro stream {Config.RTSP_URL} "
                  f"({Config.RTSP_TRANSPORT})", flush=True)
            cap = self._open()
            if not cap or not cap.isOpened():
                self.opened = False
                self.reconnects += 1
                print("[capture] apertura fallita, retry "
                      f"tra {Config.CAPTURE_RECONNECT_SEC}s", flush=True)
                time.sleep(Config.CAPTURE_RECONNECT_SEC)
                continue

            self.opened = True
            fail = 0
            while self._running:
                ok, frame = cap.read()
                now = time.time()
                if not ok or frame is None:
                    fail += 1
                    if fail >= 30:
                        print("[capture] troppi frame falliti, riconnetto",
                              flush=True)
                        break
                    time.sleep(0.05)
                    continue
                fail = 0

                if self._last_read:
                    dt = now - self._last_read
                    if dt > 0:
                        inst = 1.0 / dt
                        self._fps_ema = (0.9 * self._fps_ema + 0.1 * inst
                                         if self._fps_ema else inst)
                self._last_read = now

                with self._lock:
                    self._frame = frame
                    self._frame_ts = now
                    self._seq += 1

            cap.release()
            self.opened = False
            if self._running:
                self.reconnects += 1
                time.sleep(Config.CAPTURE_RECONNECT_SEC)
