"""Rilevatore persone YOLOv8n via ONNX Runtime (solo CPU).

Input: frame BGR (numpy). Output: lista di detection persona
(x1, y1, x2, y2, score) in coordinate PIXEL del frame originale.
"""

import time

import numpy as np

try:
    import cv2
except Exception:                      # pragma: no cover
    cv2 = None
try:
    import onnxruntime as ort
except Exception:                      # pragma: no cover
    ort = None

from app.config import Config


def letterbox(img, new_size):
    """Ridimensiona mantenendo aspect ratio + padding grigio fino a quadrato."""
    h, w = img.shape[:2]
    r = min(new_size / h, new_size / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((new_size, new_size, 3), 114, dtype=np.uint8)
    top = (new_size - nh) // 2
    left = (new_size - nw) // 2
    canvas[top:top + nh, left:left + nw] = resized
    return canvas, r, left, top


class YoloDetector:
    def __init__(self):
        if ort is None:
            raise RuntimeError("onnxruntime non installato")
        if cv2 is None:
            raise RuntimeError("opencv non installato")

        so = ort.SessionOptions()
        if Config.ORT_THREADS > 0:
            so.intra_op_num_threads = Config.ORT_THREADS
            so.inter_op_num_threads = 1
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        self.session = ort.InferenceSession(
            Config.MODEL_PATH,
            sess_options=so,
            providers=["CPUExecutionProvider"],
        )
        self.input_name = self.session.get_inputs()[0].name
        self.size = Config.DETECT_INPUT_SIZE
        self.last_ms = 0.0
        print(f"[detector] modello caricato: {Config.MODEL_PATH} "
              f"input={self.size} threads={Config.ORT_THREADS or 'auto'}",
              flush=True)

    def detect(self, frame_bgr):
        img, r, padx, pady = letterbox(frame_bgr, self.size)
        blob = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        blob = np.transpose(blob, (2, 0, 1))[None, ...]

        t0 = time.time()
        out = self.session.run(None, {self.input_name: blob})[0]
        self.last_ms = (time.time() - t0) * 1000.0

        return self._postprocess(
            out, r, padx, pady,
            frame_bgr.shape[1], frame_bgr.shape[0],
        )

    def _postprocess(self, out, r, padx, pady, ow, oh):
        out = np.squeeze(out)                      # (84,8400) o (8400,84)
        if out.ndim != 2:
            return []
        if out.shape[0] < out.shape[1]:
            out = out.T                            # -> (8400, 84)

        col = 4 + Config.PERSON_CLASS_ID
        scores = out[:, col]
        keep = scores > Config.DETECT_CONF
        out = out[keep]
        scores = scores[keep]
        if len(out) == 0:
            return []

        cx, cy, w, h = out[:, 0], out[:, 1], out[:, 2], out[:, 3]
        x1 = (cx - w / 2 - padx) / r
        y1 = (cy - h / 2 - pady) / r
        x2 = (cx + w / 2 - padx) / r
        y2 = (cy + h / 2 - pady) / r

        boxes_xywh = np.stack([x1, y1, x2 - x1, y2 - y1], axis=1)
        idxs = cv2.dnn.NMSBoxes(
            boxes_xywh.tolist(), scores.tolist(),
            Config.DETECT_CONF, Config.DETECT_IOU_NMS,
        )

        dets = []
        if len(idxs) > 0:
            for i in np.array(idxs).flatten():
                bx1 = float(max(0, min(ow - 1, x1[i])))
                by1 = float(max(0, min(oh - 1, y1[i])))
                bx2 = float(max(0, min(ow - 1, x2[i])))
                by2 = float(max(0, min(oh - 1, y2[i])))
                if bx2 - bx1 < 2 or by2 - by1 < 2:
                    continue
                dets.append((bx1, by1, bx2, by2, float(scores[i])))

        dets.sort(key=lambda d: d[4], reverse=True)
        return dets[:Config.MAX_DETECTIONS]
