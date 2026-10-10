"""Entry point of the standalone OpenProcess Studio app (see ``packaging/openprocess.spec``).

PyInstaller freezes this script into the app's program.  The same program is
started in three ways:

``OpenProcess [files…]``
    The normal case: open OpenProcess Studio, optionally with files.
``OpenProcess --openprocess-state-space-worker MODEL MAX_NODES OUT``
    Started by the app itself to compute a state space in a separate process
    (see :mod:`openprocess.analysis.state_space_process`).  A frozen app has no
    separate Python to run, so it runs itself with this flag.  No window opens.
``OpenProcess --openprocess-self-test [MODEL.cpn]``
    Used by the build script: build the main window without showing it,
    check the update check has certificates to trust and, given a model,
    compute its state space the way the app does (in a worker process); print
    ``ok`` and exit.  Proves the bundle contains everything the GUI imports,
    can reach GitHub securely and can start its own workers, also on machines
    without a screen (with QT_QPA_PLATFORM=offscreen).
"""

from __future__ import annotations

import sys

SELF_TEST_FLAG = "--openprocess-self-test"


def self_test(model_path: str | None = None) -> int:
    """Create the Studio window off-screen, optionally run a state space job."""
    from PySide6.QtWidgets import QApplication

    from openprocess.gui.studio.app import StudioWindow

    application = QApplication.instance() or QApplication(sys.argv[:1])
    window = StudioWindow(persist=False)    # persist=False: leave the user's settings alone
    application.processEvents()
    window.close()

    # The update check needs certificates to reach GitHub; a bundle without
    # them fails with CERTIFICATE_VERIFY_FAILED on users' machines (0.3.0).
    from openprocess.gui.studio.updates import ssl_context
    certificates = ssl_context().cert_store_stats()["x509_ca"]
    if certificates == 0:
        print("update check: no trusted certificates in the app", flush=True)
        return 1
    print(f"update check: {certificates} trusted certificates", flush=True)

    # Workflows: the standard boxes are imported by name, so a bundle can miss
    # them (0.7.0 did); the Code tab needs the sources.  Build and run the
    # ready-made workflow, and read a box's code, as the app would.
    from openprocess.flow import Runner, standard_library
    from openprocess.flow.box import algorithm_calls
    from openprocess.gui.flow.templates import TEMPLATES
    library = standard_library()
    if len(library) < 40:
        print(f"workflows: only {len(library)} boxes in the app", flush=True)
        return 1
    workflow = TEMPLATES[0][1](library, None)
    run = Runner(library).run(workflow)
    failed = [n.id for n in workflow.nodes.values() if run.status(n) != "done"]
    if failed:
        print(f"workflows: boxes did not run: {failed}", flush=True)
        return 1
    alpha = library.get("openprocess.flow.boxes.discover.alpha_miner")
    if "def alpha_miner" not in alpha.source or not algorithm_calls(alpha):
        print("workflows: the Code tab has no source in the app", flush=True)
        return 1
    print(f"workflows: {len(library)} boxes, the ready-made workflow runs, the code is there",
          flush=True)

    if model_path:
        import time

        from openprocess.analysis.state_space_process import StateSpaceJob
        from openprocess.io.cpn_reader import read_cpn

        job = StateSpaceJob(read_cpn(model_path), max_nodes=1000)
        job.start()
        deadline = time.monotonic() + 120
        while (outcome := job.poll()) is None:
            if time.monotonic() > deadline:
                job.kill()
                print("state space: timed out", flush=True)
                return 1
            time.sleep(0.05)
        if outcome[0] != "done":
            print(f"state space: {outcome[1]}", flush=True)
            return 1
        print(f"state space: {outcome[1]['nodes']} nodes", flush=True)

    print("ok", flush=True)
    return 0


def main() -> int:
    # Decide what this run is before importing Qt: a state space worker must
    # stay light and must never open a window.
    from openprocess.analysis.state_space_process import WORKER_FLAG, run_worker

    if len(sys.argv) > 1 and sys.argv[1] == WORKER_FLAG:
        return run_worker(sys.argv[2:5])
    if len(sys.argv) > 1 and sys.argv[1] == SELF_TEST_FLAG:
        return self_test(sys.argv[2] if len(sys.argv) > 2 else None)

    from openprocess.gui.studio.app import main as studio_main
    return studio_main(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
