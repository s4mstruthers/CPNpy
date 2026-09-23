"""Run slow computations off the GUI thread.

Alignments, state spaces and large imports can take seconds.  Running them
on the GUI thread would freeze the window (the spinning beach ball), so they
run on Qt's thread pool and report back through signals, which Qt delivers
on the GUI thread -- the only thread allowed to touch widgets.

Usage::

    run_in_background(lambda: align_log(net, log), on_done, on_error)
"""

from __future__ import annotations

import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, function) -> None:
        super().__init__()
        self.function = function
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self.function()
        except Exception as error:  # noqa: BLE001 - report anything to the UI
            detail = "".join(traceback.format_exception_only(type(error), error)).strip()
            self.signals.failed.emit(detail)
        else:
            self.signals.done.emit(result)


# Keep references: a QRunnable's signal object must outlive the thread.
_running: set[_Task] = set()


def run_in_background(function, on_done, on_error=None) -> None:
    task = _Task(function)
    _running.add(task)

    def finished(result) -> None:
        _running.discard(task)
        on_done(result)

    def failed(message: str) -> None:
        _running.discard(task)
        if on_error is not None:
            on_error(message)

    task.signals.done.connect(finished)
    task.signals.failed.connect(failed)
    QThreadPool.globalInstance().start(task)
