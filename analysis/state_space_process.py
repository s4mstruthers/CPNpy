"""Compute a state space in a separate process.

Why a process and not a thread
------------------------------
State space exploration is pure Python.  In a thread it competes with the
window for Python's global interpreter lock: every paint and every click
handler has to wait for the lock, so the whole app stutters for as long as
the exploration runs.  A separate process has its own interpreter, so the
window stays fully responsive -- and it can be stopped at any moment.

The model travels to the worker as a ``.cpn`` file (the same format the app
saves), and the results come back as plain data (numbers, lists, strings),
which is everything the GUI shows.

The worker is ``python -m cpnpy.analysis.state_space_process`` started with
the same interpreter, rather than :mod:`multiprocessing`, which would
re-import the GUI's main script in the child.

Usage::

    job = StateSpaceJob(net, max_nodes=20_000)
    job.start()
    ...                       # poll job.progress() / job.result() from a timer
    job.cancel()              # ask it to stop; it returns what it has found
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any


def summarise(space, graph_limit: int = 200) -> dict[str, Any]:
    """Everything the GUI displays, as picklable data."""
    net = space.net
    places = list(net.all_places())
    partial = space.partial
    result: dict[str, Any] = {
        "nodes": space.node_count,
        "arcs": space.arc_count,
        "partial": partial,
        "cancelled": space.cancelled,
        "unexplored": space.unexplored_count,
        "sccs": len(space.strongly_connected_components()),
        "dead": space.dead_markings(),
        "home": None if partial else space.home_markings(),
        "dead_transitions": [t.name for t in space.dead_transitions()],
        "live": None if partial else [t.name for t in space.live_transitions()],
        "bounds": [(p.id, p.name, *space.integer_bounds()[p.id]) for p in places],
        "multiset": {k: str(v) for k, v in space.upper_multiset_bounds().items()},
        "report": space.report(),
        "graph": None,
    }
    if space.node_count <= graph_limit:
        dead = set(result["dead"])
        nodes = [(index, space.describe_state(index), index in dead)
                 for index in range(space.node_count)]
        arcs = [(arc.source, arc.target, arc.binding.describe(net))
                for arcs in space.arcs.values() for arc in arcs]
        result["graph"] = (nodes, arcs)
    return result


def _child(model_path: str, max_nodes: int, output_path: str) -> int:
    """The worker: ``python -m cpnpy.analysis.state_space_process MODEL N OUT``.

    Talks to the parent through its standard streams: it prints
    ``progress <nodes> <arcs>`` lines and ``phase <name>`` while working, and
    stops early when the parent writes ``stop``.  The result is pickled to
    ``OUT``, then ``done`` (or ``error <message>``) is printed.
    """
    import pickle
    import sys
    import threading
    import time

    stop = threading.Event()

    def listen() -> None:
        for line in sys.stdin:
            if line.strip() == "stop":
                stop.set()
        stop.set()                      # the parent went away: stop too

    threading.Thread(target=listen, daemon=True).start()

    def say(text: str) -> None:
        print(text, flush=True)

    try:
        from ..io.cpn_reader import read_cpn
        from .state_space import StateSpace
        net = read_cpn(model_path)
        problems = net.compile()
        if problems:
            say("error " + "; ".join(str(p) for p in problems[:3]).replace("\n", " "))
            return 1
        last = [0.0]

        def progress(node_count: int, arc_count: int) -> None:
            now = time.monotonic()
            if now - last[0] > 0.15:
                last[0] = now
                say(f"progress {node_count} {arc_count}")

        space = StateSpace(net).generate(max_nodes=max_nodes, should_stop=stop.is_set,
                                         progress=progress)
        say(f"progress {space.node_count} {space.arc_count}")
        say("phase Analysing")
        with open(output_path, "wb") as handle:
            pickle.dump(summarise(space), handle)
        say("done")
        return 0
    except Exception as error:  # noqa: BLE001 - report anything to the GUI
        say(f"error {type(error).__name__}: {error}".replace("\n", " "))
        return 1


class StateSpaceJob:
    """One state space computation in a child process."""

    def __init__(self, net, max_nodes: int = 20_000) -> None:
        from ..io.cpn_writer import write_cpn
        directory = tempfile.mkdtemp(prefix="cpnpy-space-")
        self.model_path = os.path.join(directory, "model.cpn")
        self.output_path = os.path.join(directory, "result.pickle")
        self.directory = directory
        write_cpn(net, Path(self.model_path))
        self.max_nodes = max_nodes
        self.process: subprocess.Popen | None = None
        self.nodes = self.arcs = 0
        self.phase = "Starting"
        self.outcome: tuple[str, Any] | None = None
        self._message: str | None = None

    def start(self) -> None:
        # A fresh interpreter running this module: nothing of the GUI's state
        # (Qt, open windows) is inherited.
        self.process = subprocess.Popen(
            [sys.executable, "-m", "cpnpy.analysis.state_space_process", self.model_path,
             str(self.max_nodes), self.output_path],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1, cwd=str(Path(__file__).resolve().parents[2]))
        self.phase = "Exploring"
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        """Reader thread: parse the child's messages (blocks on I/O only)."""
        assert self.process is not None and self.process.stdout is not None
        for line in self.process.stdout:
            word, _, rest = line.strip().partition(" ")
            if word == "progress":
                parts = rest.split()
                if len(parts) == 2:
                    self.nodes, self.arcs = int(parts[0]), int(parts[1])
            elif word == "phase":
                self.phase = rest
            elif word in ("done", "error"):
                self._message = word + (" " + rest if rest else "")

    def progress(self) -> tuple[int, int, str]:
        return self.nodes, self.arcs, self.phase

    def poll(self) -> tuple[str, Any] | None:
        """``("done", summary)``, ``("error", message)``, or ``None`` while running."""
        if self.outcome is not None or self.process is None:
            return self.outcome
        if self.process.poll() is None:
            return None
        # The child has exited; make sure its last lines have been read.
        for _ in range(50):
            if self._message is not None:
                break
            import time
            time.sleep(0.01)
        message = self._message or ""
        if message == "done":
            import pickle
            with open(self.output_path, "rb") as handle:
                self.outcome = ("done", pickle.load(handle))
        elif message.startswith("error"):
            self.outcome = ("error", message[6:] or "unknown error")
        else:
            self.outcome = ("error", "stopped")
        self._cleanup()
        return self.outcome

    def cancel(self) -> None:
        """Ask the worker to stop; it then reports what it has explored."""
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.stdin.write("stop\n")
                self.process.stdin.flush()
            except (OSError, ValueError):
                pass

    def kill(self) -> None:
        """Stop at once, without results (closing the page, a stuck worker)."""
        if self.process is not None and self.process.poll() is None:
            self.process.kill()
        self._cleanup()

    def _cleanup(self) -> None:
        import shutil
        shutil.rmtree(self.directory, ignore_errors=True)


if __name__ == "__main__":      # the child process
    raise SystemExit(_child(sys.argv[1], int(sys.argv[2]), sys.argv[3]))
