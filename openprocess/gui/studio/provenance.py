"""Where a figure comes from: a *code* link on every card that computes something.

A box on the canvas shows its code on the Code tab.  The pages compute a
few things of their own too (a process map, a footprint, soundness, the
state space, regions), and those must be just as open: each such card gets
a small ``{ } code`` link that opens the file the figure is computed in,
scrolled to the function, so nothing in the app is a black box.
"""

from __future__ import annotations

import inspect

from PySide6.QtWidgets import QMenu, QPushButton

from ...flow.box import Called
from .widgets import button


def _name(obj) -> str:
    return getattr(obj, "__qualname__", getattr(obj, "__name__", str(obj)))


def called_from(obj) -> Called:
    """The function (or class) as a :class:`Called`: its file, line and source."""
    target = inspect.unwrap(obj)
    if isinstance(target, property):
        target = target.fget
    file = inspect.getsourcefile(target) or ""
    try:
        lines, line = inspect.getsourcelines(target)
    except (OSError, TypeError):
        lines, line = [], 0
    return Called(name=_name(target), module=getattr(target, "__module__", "") or "",
                  file=file, line=line, source="".join(lines))


def code_button(*objects, text: str = "{ } code") -> QPushButton:
    """A link that opens the code of ``objects`` (one: straight away; several: a menu)."""
    names = ", ".join(_name(o) for o in objects)
    link = button(text, kind="ghost",
                  tooltip=f"The code that computes this: {names}. Opens the file, scrolled to the function.")
    link.setObjectName("ghost")

    def show(_checked=False) -> None:
        from ..flow.viewers import show_file
        if len(objects) == 1:
            show_file(called_from(objects[0]), link.window())
            return
        menu = QMenu(link)
        for obj in objects:
            menu.addAction(_name(obj), lambda _c=False, o=obj: show_file(called_from(o), link.window()))
        menu.exec(link.mapToGlobal(link.rect().bottomLeft()))

    link.clicked.connect(show)
    return link


def add_code(card, *objects) -> QPushButton:
    """Put a ``{ } code`` link in a card's title row, for what the card computes."""
    link = code_button(*objects)
    card.header.addWidget(link)
    return link


__all__ = ["add_code", "code_button", "called_from"]
