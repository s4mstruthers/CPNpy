"""Exercise packs: worksheets with answer boxes that check themselves.

* :mod:`.sheet` -- reading ``question.md``: Markdown with ``answer`` blocks;
* :mod:`.pack` -- exercise folders, packs of them, and the student's progress;
* :mod:`.answers` -- reading typed answers (sets, pairs, traces, numbers);
* :mod:`.checks` -- checking an answer, with computed right answers.

No Qt here: the same code checks answers in the app and in
``cpnpy exercises check`` (see ``docs/exercise-packs.md``).
"""

from .pack import Exercise, ExerciseFiles, Pack, exercise_files, load_pack, pack_root
from .sheet import Sheet, SheetError, Task, parse_sheet

__all__ = ["Exercise", "ExerciseFiles", "Pack", "Sheet", "SheetError", "Task",
           "exercise_files", "load_pack", "pack_root", "parse_sheet"]
