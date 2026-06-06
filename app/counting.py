"""Conteggio per attraversamento linea, a macchina a stati per ogni persona.

Supporta due orientamenti (Config.LINE_ORIENTATION):

  horizontal -> linea orizzontale a y=LINE_Y, conta su/giù
                zona "above": y <= LINE_Y - margin
                zona "below": y >= LINE_Y + margin
                movimento up (below->above) / down (above->below)

  vertical   -> linea verticale a x=LINE_X, conta sinistra/destra
                zona "left":  x <= LINE_X - margin
                zona "right": x >= LINE_X + margin
                movimento left (right->left) / right (left->right)

In mezzo c'è una "zona morta" (margine): chi non la supera da un lato all'altro
non viene contato. Conta solo l'attraversamento completo dentro la ROI.
"""

from app.config import Config


def point_in_roi(x, y):
    return (Config.MOTION_X1 <= x <= Config.MOTION_X2 and
            Config.MOTION_Y1 <= y <= Config.MOTION_Y2)


class LineCounter:
    """Stato di attraversamento per UNA persona (un id di tracking)."""

    def __init__(self):
        self.side = None          # above/below | left/right | None
        self.last_point = None

    def update(self, x, y):
        """Ritorna (event, reason, start_point) con event ∈ {enter,exit,None}."""
        prev = self.last_point
        self.last_point = (x, y)

        inside = point_in_roi(x, y)
        m = Config.LINE_MARGIN
        vertical = Config.LINE_ORIENTATION == "vertical"

        if vertical:
            coord, line = x, Config.LINE_X
            lo, hi = "left", "right"
            enter_dir = (Config.ENTER_DIRECTION
                         if Config.ENTER_DIRECTION in ("left", "right") else "right")
        else:
            coord, line = y, Config.LINE_Y
            lo, hi = "above", "below"
            enter_dir = (Config.ENTER_DIRECTION
                         if Config.ENTER_DIRECTION in ("up", "down") else "up")

        if coord <= line - m:
            new_side = lo
        elif coord >= line + m:
            new_side = hi
        else:
            new_side = self.side          # zona morta

        event = None
        reason = ""

        if inside and self.side is not None and new_side != self.side:
            if vertical:
                if self.side == "left" and new_side == "right":
                    movement = "right"
                elif self.side == "right" and new_side == "left":
                    movement = "left"
                else:
                    movement = None
            else:
                if self.side == "below" and new_side == "above":
                    movement = "up"
                elif self.side == "above" and new_side == "below":
                    movement = "down"
                else:
                    movement = None

            if movement:
                event = "enter" if movement == enter_dir else "exit"
                reason = (f"cross {'V' if vertical else 'H'} move={movement} "
                          f"pos={coord:.3f} line={line:.2f} margin={m:.2f}")

        if new_side is not None and (inside or self.side is None):
            self.side = new_side

        return event, reason, (prev if prev is not None else (x, y))
