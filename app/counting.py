"""Conteggio per attraversamento linea, a macchina a stati per ogni persona.

A differenza del vecchio approccio (mediana primo/ultimo punto), qui seguiamo
in tempo reale da che lato della linea sta la persona:

  zona ALTA   = y <= LINE_Y - LINE_MARGIN
  zona BASSA  = y >= LINE_Y + LINE_MARGIN
  zona morta  = in mezzo (nessun cambio di stato → niente conteggio)

Conta SOLO quando il punto passa da una zona all'altra mentre è dentro la ROI.
Chi staziona nella zona morta, o va avanti/indietro senza superare entrambe le
soglie, non viene mai contato. Un andata+ritorno completi contano 1 enter e
1 exit (corretto per una porta reale).
"""

from app.config import Config


def point_in_roi(x, y):
    return (Config.MOTION_X1 <= x <= Config.MOTION_X2 and
            Config.MOTION_Y1 <= y <= Config.MOTION_Y2)


class LineCounter:
    """Stato di attraversamento per UNA persona (un id di tracking)."""

    def __init__(self):
        self.side = None          # 'above' | 'below' | None
        self.last_point = None    # ultimo (x, y) visto

    def update(self, x, y):
        """Aggiorna con il nuovo punto. Ritorna (event, reason, start_point)
        dove event ∈ {'enter','exit',None}."""
        prev = self.last_point
        self.last_point = (x, y)

        inside = point_in_roi(x, y)
        line = Config.LINE_Y
        m = Config.LINE_MARGIN

        if y <= line - m:
            new_side = "above"
        elif y >= line + m:
            new_side = "below"
        else:
            new_side = self.side          # zona morta: nessun cambio

        event = None
        reason = ""

        if inside and self.side is not None and new_side != self.side:
            if self.side == "above" and new_side == "below":
                movement = "down"
            elif self.side == "below" and new_side == "above":
                movement = "up"
            else:
                movement = None

            if movement:
                event = ("enter" if movement == Config.ENTER_DIRECTION
                         else "exit")
                reason = (f"cross movement={movement} y={y:.3f} "
                          f"line={line:.2f} margin={m:.2f}")

        # aggiorna lo stato lato linea solo quando siamo dentro la ROI
        # (oppure al primissimo punto, per inizializzare)
        if new_side is not None and (inside or self.side is None):
            self.side = new_side

        return event, reason, (prev if prev is not None else (x, y))
