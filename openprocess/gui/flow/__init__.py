"""The Workflows page: the workflow canvas, the box list and the side panel.

Everything here draws :mod:`openprocess.flow`; nothing in :mod:`openprocess.flow`
knows about Qt.  ``canvas.py`` is the canvas (boxes, wires, dragging a
wire from a box to a box), ``viewers.py`` shows a box's result, how it got
there, its code and its settings, ``page.py`` puts them together with the
runner, and ``templates.py`` holds the ready-made workflows.
"""
