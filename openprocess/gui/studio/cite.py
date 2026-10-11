"""*Cite*: BibTeX for the app and for the works an algorithm follows, to copy."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QDialog, QPlainTextEdit

from ... import citation
from .. import theme
from .widgets import button, hbox, label, vbox


def cite_dialog(title: str, intro: str, entries: list[citation.Entry], parent=None,
                text_line: str = "") -> QDialog:
    """A window with the BibTeX of ``entries`` (and a one-line citation when
    given), each with a Copy button."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(720, 560)
    bibtex = "\n\n".join(entry.bibtex() for entry in entries)
    code = QPlainTextEdit(bibtex)
    code.setReadOnly(True)
    code.setFont(theme.mono_font(11))
    widgets = [label(intro, "muted", wrap=True)]
    if text_line:
        line = QPlainTextEdit(text_line)
        line.setReadOnly(True)
        line.setMaximumHeight(64)
        widgets += [label("IN A SENTENCE", "sectionLabel"), line]
    widgets += [label("BIBTEX", "sectionLabel"), code]
    buttons = [button("Copy BibTeX", lambda: QApplication.clipboard().setText(bibtex), kind="primary")]
    if text_line:
        buttons.append(button("Copy the sentence", lambda: QApplication.clipboard().setText(text_line)))
    widgets.append(hbox(*buttons, None, button("Close", dialog.close)))
    dialog.setLayout(vbox(*widgets, margins=(16, 16, 16, 16)))
    dialog.bibtex = bibtex
    dialog.show()
    return dialog


def cite_app(parent=None) -> QDialog:
    """Help ▸ Cite OpenProcess…"""
    return cite_dialog(
        "Cite OpenProcess",
        "If OpenProcess helped with a course, a thesis or a paper, cite it like this. Each algorithm's Code "
        "tab has a Cite button for the paper it follows.",
        [citation.app_entry()], parent, citation.app_text())


def cite_module(module: str, name: str, parent=None) -> QDialog:
    """The Code tab's Cite: the works the function's module follows."""
    entries = citation.entries_for_module(module)
    intro = (f"The works that {name} follows, as BibTeX." if entries else
             f"{name} has no reference on record: see Help ▸ References for the list, and cite OpenProcess "
             "itself for the implementation.")
    return cite_dialog(f"Cite: {name}", intro, entries or [citation.app_entry()], parent)


__all__ = ["cite_dialog", "cite_app", "cite_module"]
