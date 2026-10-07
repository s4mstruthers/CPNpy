"""Hiding analysis results while you do an exercise.

Inside an exercise (see :mod:`.exercise_mode`) the answers the app would
normally show straight away -- soundness, properties, invariants, the
footprint, discovered models, conformance figures, regions -- are hidden.
Each result card shows *Hidden in this exercise · Reveal* instead; clicking
reveals that one, and *Reveal Every Hidden Result* (the ⋯ menu) reveals the lot.

One :class:`Concealment` belongs to the open exercise.  Pages that show
results mix in :class:`ConcealsResults` and register their cards with
:meth:`ConcealsResults.conceal_card`; the exercise view hands its
concealment to the pages of the exercise's materials.  Pages outside
exercise mode have none, and show everything.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

#: What each key hides, for the reveal buttons.
RESULTS = {
    "soundness": "soundness",
    "theorem": "the short-circuited net",
    "structure": "the structural properties",
    "invariants": "the invariants",
    "properties": "the behavioural properties",
    "footprint": "the footprint",
    "discovery": "the discovered model",
    "conformance": "the conformance figures",
    "regions": "the regions",
}


class Concealment(QObject):
    """Which results are still hidden in the open exercise."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.revealed: set[str] = set()
        self.everything = False

    def hidden(self, key: str) -> bool:
        return not self.everything and key not in self.revealed

    def reveal(self, key: str) -> None:
        if self.hidden(key):
            self.revealed.add(key)
            self.changed.emit()

    def reveal_all(self) -> None:
        if not self.everything:
            self.everything = True
            self.changed.emit()

    @property
    def anything_hidden(self) -> bool:
        return not self.everything


class ConcealsResults:
    """Mixin for pages with result cards that an exercise hides."""

    def conceal_card(self, card, key: str) -> None:
        """Register ``card`` as showing the result ``key``."""
        cards = self.__dict__.setdefault("_concealed_cards", [])
        cards.append((card, key))
        card.set_concealment(getattr(self, "concealment", None), key)

    def set_concealment(self, concealment: Concealment | None) -> None:
        """Hide (or, with ``None``, show) every registered card."""
        self.concealment = concealment
        alive = []
        for card, key in self.__dict__.get("_concealed_cards", []):
            try:
                card.set_concealment(concealment, key)
            except RuntimeError:            # the card was deleted (a tab rebuilt)
                continue
            alive.append((card, key))
        self._concealed_cards = alive

    def results_hidden(self, key: str) -> bool:
        concealment = getattr(self, "concealment", None)
        return concealment is not None and concealment.hidden(key)
