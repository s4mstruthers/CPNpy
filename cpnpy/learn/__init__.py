"""CPNpy Learn: exercise packs, their answer boxes, and checking them.

* :mod:`.sheet` -- reading ``question.md``: Markdown with ``answer`` blocks
  and front matter;
* :mod:`.pack` -- exercise folders, packs of them, the student's progress,
  points and exam settings;
* :mod:`.answers` and :mod:`.notation` -- reading typed answers: sets, pairs,
  traces, numbers, markings, matrices, cuts, trees, alignments…;
* :mod:`.computed` -- the right answers worked out from the exercise's files
  (``compute: alpha.T_I``), one documented function each;
* :mod:`.checks` -- checking an answer, with partial credit;
* :mod:`.exam` -- exam mode, the clock, marks and variants;
* :mod:`.importer` -- a past exam's text into a skeleton pack.

No Qt here: the same code checks answers in the app (``cpnpy.gui.learn``)
and in ``cpnpy exercises check`` (see ``cpnpy/learn/exercise-packs.md``).
"""

from .pack import Exercise, ExerciseFiles, Pack, exercise_files, load_pack, pack_root
from .sheet import Sheet, SheetError, Task, parse_sheet

__all__ = ["Exercise", "ExerciseFiles", "Pack", "Sheet", "SheetError", "Task",
           "exercise_files", "load_pack", "pack_root", "parse_sheet"]
