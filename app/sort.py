"""SORT — Simple Online Realtime Tracking (Kalman + IoU greedy).

Implementazione compatta in numpy, senza filterpy/scipy. Mantiene l'identità
delle persone tra un frame e l'altro così il conteggio resta stabile anche se
due persone si incrociano. Adatto a CPU: pochi oggetti, costo trascurabile.
"""

import numpy as np


def iou_batch(bb_test, bb_gt):
    """IoU tra due insiemi di box [x1,y1,x2,y2]. Ritorna matrice NxM."""
    bb_gt = np.expand_dims(bb_gt, 0)
    bb_test = np.expand_dims(bb_test, 1)

    xx1 = np.maximum(bb_test[..., 0], bb_gt[..., 0])
    yy1 = np.maximum(bb_test[..., 1], bb_gt[..., 1])
    xx2 = np.minimum(bb_test[..., 2], bb_gt[..., 2])
    yy2 = np.minimum(bb_test[..., 3], bb_gt[..., 3])
    w = np.maximum(0.0, xx2 - xx1)
    h = np.maximum(0.0, yy2 - yy1)
    inter = w * h
    area_t = ((bb_test[..., 2] - bb_test[..., 0]) *
              (bb_test[..., 3] - bb_test[..., 1]))
    area_g = ((bb_gt[..., 2] - bb_gt[..., 0]) *
              (bb_gt[..., 3] - bb_gt[..., 1]))
    union = area_t + area_g - inter
    return np.where(union > 0, inter / union, 0.0)


def _to_z(bbox):
    """[x1,y1,x2,y2] -> [cx,cy,s,r] (s=area, r=aspect)."""
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    cx = bbox[0] + w / 2.0
    cy = bbox[1] + h / 2.0
    s = w * h
    r = w / float(h) if h > 0 else 1.0
    return np.array([cx, cy, s, r], dtype=np.float64).reshape((4, 1))


def _to_bbox(x):
    """[cx,cy,s,r,...] -> [x1,y1,x2,y2]."""
    s = max(x[2, 0], 1e-6)
    r = max(x[3, 0], 1e-6)
    w = np.sqrt(s * r)
    h = s / w if w > 0 else 0.0
    cx, cy = x[0, 0], x[1, 0]
    return np.array([cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0])


class KalmanBoxTracker:
    count = 0

    def __init__(self, bbox):
        # stato: [cx, cy, s, r, vcx, vcy, vs]
        self.F = np.eye(7)
        for i, j in ((0, 4), (1, 5), (2, 6)):
            self.F[i, j] = 1.0
        self.H = np.zeros((4, 7))
        self.H[0, 0] = self.H[1, 1] = self.H[2, 2] = self.H[3, 3] = 1.0

        self.R = np.eye(4)
        self.R[2:, 2:] *= 10.0
        self.P = np.eye(7)
        self.P[4:, 4:] *= 1000.0
        self.P *= 10.0
        self.Q = np.eye(7)
        self.Q[-1, -1] *= 0.01
        self.Q[4:, 4:] *= 0.01

        self.x = np.zeros((7, 1))
        self.x[:4] = _to_z(bbox)

        self.id = KalmanBoxTracker.count
        KalmanBoxTracker.count += 1
        self.time_since_update = 0
        self.hits = 0
        self.hit_streak = 0
        self.age = 0

    def predict(self):
        if (self.x[6, 0] + self.x[2, 0]) <= 0:
            self.x[6, 0] = 0.0
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        self.age += 1
        if self.time_since_update > 0:
            self.hit_streak = 0
        self.time_since_update += 1
        return _to_bbox(self.x)

    def update(self, bbox):
        self.time_since_update = 0
        self.hits += 1
        self.hit_streak += 1
        z = _to_z(bbox)
        y = z - self.H @ self.x
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        self.P = (np.eye(7) - K @ self.H) @ self.P

    def get_state(self):
        return _to_bbox(self.x)


class Sort:
    def __init__(self, max_age=15, min_hits=3, iou_threshold=0.3):
        self.max_age = max_age
        self.min_hits = min_hits
        self.iou_threshold = iou_threshold
        self.trackers = []
        self.frame_count = 0

    def _match(self, dets, trks):
        """Greedy IoU matching. Ritorna (matches, unmatched_dets, unmatched_trks)."""
        if len(trks) == 0 or len(dets) == 0:
            return [], list(range(len(dets))), list(range(len(trks)))

        iou = iou_batch(dets[:, :4], trks)
        matches = []
        used_d, used_t = set(), set()

        # ordina le coppie per IoU decrescente
        pairs = []
        for d in range(iou.shape[0]):
            for t in range(iou.shape[1]):
                pairs.append((iou[d, t], d, t))
        pairs.sort(reverse=True)

        for score, d, t in pairs:
            if score < self.iou_threshold:
                break
            if d in used_d or t in used_t:
                continue
            used_d.add(d)
            used_t.add(t)
            matches.append((d, t))

        unmatched_d = [d for d in range(len(dets)) if d not in used_d]
        unmatched_t = [t for t in range(len(trks)) if t not in used_t]
        return matches, unmatched_d, unmatched_t

    def update(self, dets):
        """dets: ndarray Nx5 [x1,y1,x2,y2,score]. Ritorna lista di dict
        {id, bbox, hits, time_since_update, confirmed}."""
        self.frame_count += 1

        trks = np.zeros((len(self.trackers), 4))
        to_del = []
        for i, t in enumerate(self.trackers):
            pos = t.predict()
            trks[i] = pos
            if np.any(np.isnan(pos)):
                to_del.append(i)
        for i in reversed(to_del):
            self.trackers.pop(i)
            trks = np.delete(trks, i, axis=0)

        if dets is None or len(dets) == 0:
            dets = np.empty((0, 5))

        matches, unmatched_d, _ = self._match(dets, trks)

        for d, t in matches:
            self.trackers[t].update(dets[d, :4])
        for d in unmatched_d:
            self.trackers.append(KalmanBoxTracker(dets[d, :4]))

        out = []
        for t in reversed(range(len(self.trackers))):
            trk = self.trackers[t]
            bbox = trk.get_state()
            confirmed = (
                trk.hits >= self.min_hits
                or self.frame_count <= self.min_hits
            )
            if trk.time_since_update < 1 and confirmed:
                out.append({
                    "id": trk.id,
                    "bbox": bbox,
                    "hits": trk.hits,
                    "time_since_update": trk.time_since_update,
                    "confirmed": trk.hits >= self.min_hits,
                })
            if trk.time_since_update > self.max_age:
                self.trackers.pop(t)
        return out

    def active_ids(self):
        return {t.id for t in self.trackers}
