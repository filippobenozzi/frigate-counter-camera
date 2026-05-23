"""Logica pura di classificazione del movimento (no I/O, no stato globale)."""

from app.config import Config


def clamp(value, lo=0.0, hi=1.0):
    return max(lo, min(hi, value))


def distance(p1, p2):
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    return (dx * dx + dy * dy) ** 0.5


def median(values):
    if not values:
        return None
    values = sorted(values)
    mid = len(values) // 2
    if len(values) % 2 == 1:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2.0


def median_point(points):
    if not points:
        return None
    return median([p[0] for p in points]), median([p[1] for p in points])


def point_from_box(box):
    """Bounding box Frigate -> punto normalizzato (cx, cy) in 0..1."""
    if not box or len(box) < 4:
        return None

    x1, y1, x2, y2 = [float(v) for v in box[:4]]

    if max(x1, y1, x2, y2) <= 1.5:
        nx1, ny1, nx2, ny2 = x1, y1, x2, y2
    else:
        nx1 = x1 / Config.FRAME_W
        ny1 = y1 / Config.FRAME_H
        nx2 = x2 / Config.FRAME_W
        ny2 = y2 / Config.FRAME_H

    cx = (nx1 + nx2) / 2.0
    cy = (ny1 + ny2) / 2.0 if Config.POINT_MODE == "center" else ny2

    return clamp(cx), clamp(cy)


def clean_points(points):
    cleaned = []
    for p in points:
        if not cleaned or distance(cleaned[-1], p) >= Config.JITTER_DISTANCE:
            cleaned.append(p)
    return cleaned


def filter_motion_roi(points):
    return [
        p for p in points
        if Config.MOTION_X1 <= p[0] <= Config.MOTION_X2
        and Config.MOTION_Y1 <= p[1] <= Config.MOTION_Y2
    ]


def classify_full_motion(points):
    """Analizza tutti i punti del track e decide enter / exit / None."""
    if len(points) < Config.MOTION_MIN_POINTS:
        return None, f"too_few_points raw={len(points)}"

    cleaned = clean_points(points)
    roi = filter_motion_roi(cleaned)

    if len(roi) < Config.MOTION_MIN_POINTS:
        return None, (
            f"too_few_roi_points raw={len(points)} "
            f"cleaned={len(cleaned)} roi={len(roi)}"
        )

    sample = max(2, min(5, len(roi) // 3))
    first = median_point(roi[:sample])
    last = median_point(roi[-sample:])
    if not first or not last:
        return None, "invalid_median"

    ys = [p[1] for p in roi]
    span_y = max(ys) - min(ys)
    delta_y = last[1] - first[1]

    if span_y < Config.MOTION_MIN_SPAN_Y:
        return None, (
            f"span_y_too_small span_y={span_y:.3f} "
            f"delta_y={delta_y:.3f} roi={len(roi)}"
        )

    if abs(delta_y) < Config.MOTION_MIN_DELTA_Y:
        return None, (
            f"delta_y_too_small delta_y={delta_y:.3f} "
            f"span_y={span_y:.3f} roi={len(roi)}"
        )

    net_ratio = abs(delta_y) / span_y if span_y > 0 else 0
    if net_ratio < Config.MOTION_MIN_NET_RATIO:
        return None, (
            f"net_ratio_too_small net_ratio={net_ratio:.3f} "
            f"delta_y={delta_y:.3f} span_y={span_y:.3f}"
        )

    movement = "up" if delta_y < 0 else "down"
    result = "enter" if movement == Config.ENTER_DIRECTION else "exit"

    reason = (
        f"movement={movement} "
        f"first=({first[0]:.3f},{first[1]:.3f}) "
        f"last=({last[0]:.3f},{last[1]:.3f}) "
        f"delta_y={delta_y:.3f} span_y={span_y:.3f} net_ratio={net_ratio:.3f} "
        f"raw={len(points)} cleaned={len(cleaned)} roi={len(roi)}"
    )

    return result, reason
