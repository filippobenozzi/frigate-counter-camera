"""Stato in-memory dei track attivi (deve essere protetto da store.lock)."""

import time
from collections import deque

from app.config import Config


class Tracker:
    def __init__(self):
        self.tracks = {}
        self.counted_ids = {}
        self.recent = deque(maxlen=100)

    def cleanup(self, now):
        for k in list(self.tracks.keys()):
            if now - self.tracks[k]["last_seen"] > Config.TRACK_TTL:
                del self.tracks[k]
        for k in list(self.counted_ids.keys()):
            if now - self.counted_ids[k] > Config.TRACK_TTL:
                del self.counted_ids[k]

    def start_or_update(self, evt_id, point, now):
        if evt_id not in self.tracks:
            self.tracks[evt_id] = {
                "first": point,
                "last": point,
                "last_seen": now,
                "points": deque([point], maxlen=Config.TRACK_POINTS_MAX),
            }
            return None
        t = self.tracks[evt_id]
        prev = t["last"]
        t["last"] = point
        t["last_seen"] = now
        t["points"].append(point)
        return prev

    def end_track(self, evt_id):
        self.tracks.pop(evt_id, None)

    def is_counted(self, evt_id):
        return evt_id in self.counted_ids

    def mark_counted(self, evt_id):
        self.counted_ids[evt_id] = time.time()

    def clear_all(self):
        self.tracks.clear()
        self.counted_ids.clear()
        self.recent.clear()
