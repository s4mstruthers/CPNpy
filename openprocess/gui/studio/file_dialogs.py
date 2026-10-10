"""Small dialogs about files and folders.

* :class:`ImportDialog` -- a file from outside the open folder is being
  opened: copy it in, move it in, or open it where it is?
* :func:`ask_about_clash` -- a file with that name is already there: keep
  both, or replace it?
* :class:`SettingsDialog` -- the app's settings (File ▸ Settings…, or the
  application menu on macOS).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QMessageBox, QRadioButton, QVBoxLayout, QWidget,
)

from .widgets import label, shortcut_text

#: What to do with a file opened from outside the folder.
IMPORT_CHOICES = {
    "copy": "Copy into {folder}",
    "move": "Move into {folder}",
    "open": "Open from where it is",
}
IMPORT_DETAILS = {
    "copy": "The original stays where it is.",
    "move": "The file is no longer where it was.",
    "open": "The folder will not have it next time.",
}


class ImportDialog(QDialog):
    """Add files from elsewhere to the open folder?"""

    def __init__(self, names: list[str], folder: str, parent=None,
                 allow_open: bool = True, default: str = "copy") -> None:
        super().__init__(parent)
        self.setWindowTitle("Add to folder")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        what = f"“{names[0]}”" if len(names) == 1 else f"{len(names)} files"
        heading = QLabel(f"<b>Add {what} to {folder}?</b>")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        if len(names) > 1:
            listing = ", ".join(names[:5]) + (f" and {len(names) - 5} more" if len(names) > 5
                                             else "")
            layout.addWidget(label(listing, "muted", wrap=True))
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QRadioButton] = {}
        for key, text in IMPORT_CHOICES.items():
            if key == "open" and not allow_open:
                continue
            radio = QRadioButton(text.format(folder=folder))
            radio.setToolTip(IMPORT_DETAILS[key])
            self.group.addButton(radio)
            self.buttons[key] = radio
            layout.addWidget(radio)
        self.buttons.get(default, self.buttons["copy"]).setChecked(True)
        self.always = QCheckBox(f"Always do this in {folder}")
        layout.addWidget(self.always)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Add")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def choice(self) -> str:
        return next(key for key, radio in self.buttons.items() if radio.isChecked())


def ask_about_clash(parent: QWidget, target: Path) -> str | None:
    """``"keep"`` (keep both), ``"replace"``, or None (skip this file)."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle("A file with that name exists")
    box.setText(f"“{target.name}” is already in {target.parent.name}.")
    box.setInformativeText("Keep both (the new one gets a number), or replace the one "
                           "that is there? A replaced file goes to the Bin.")
    keep = box.addButton("Keep Both", QMessageBox.AcceptRole)
    replace = box.addButton("Replace", QMessageBox.DestructiveRole)
    box.addButton("Skip", QMessageBox.RejectRole)
    box.setDefaultButton(keep)
    box.exec()
    clicked = box.clickedButton()
    return "keep" if clicked is keep else "replace" if clicked is replace else None


class SettingsDialog(QDialog):
    """The few settings the app has."""

    IMPORT_LABELS = {"ask": "Ask each time", "copy": "Copy it into the folder",
                     "move": "Move it into the folder", "open": "Open it from where it is"}

    def __init__(self, values: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        form = QFormLayout()
        form.setVerticalSpacing(10)

        self.autosave = QCheckBox("Save edits automatically")
        self.autosave.setChecked(values["autosave"])
        form.addRow("Nets in a folder", self.autosave)
        form.addRow("", label("A second after you stop editing, and when you switch to "
                              "another file or quit. Only for files in the open folder; "
                              ".cpn files from CPN Tools are saved when you press "
                              f"{shortcut_text('Ctrl+S')}.",
                              "muted", wrap=True))

        self.import_box = QComboBox()
        for key, text in self.IMPORT_LABELS.items():
            self.import_box.addItem(text, key)
        self.import_box.setCurrentIndex(max(0, self.import_box.findData(values["import"])))
        form.addRow("Opening a file from\noutside the folder", self.import_box)
        form.addRow("", label("A choice made for one folder (“Always do this”) takes "
                              "precedence.", "muted", wrap=True))

        self.restore = QCheckBox("Reopen the folder and files at launch")
        self.restore.setChecked(values["restore"])
        form.addRow("Launch", self.restore)

        self.updates = QCheckBox("Check for a new version when OpenProcess opens")
        self.updates.setChecked(values["check_updates"])
        form.addRow("Updates", self.updates)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict:
        return {"autosave": self.autosave.isChecked(),
                "import": self.import_box.currentData(),
                "restore": self.restore.isChecked(),
                "check_updates": self.updates.isChecked()}
