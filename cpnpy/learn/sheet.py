"""An exercise as a worksheet: its question text with answer boxes in it.

An exercise is a folder with a ``question.md``.  The question is ordinary
Markdown (with ``$…$`` maths); wherever the student should answer, the
author puts an *answer block*, a fenced code block marked ``answer``::

    a. Give the start activities $T_I$.

    ```answer
    type: set
    compute: alpha.T_I
    hint: Which activities does a trace begin with?
    ```

The text between two answer blocks is the question for the second one, so
the sheet reads top to bottom like the paper version.  Inside a block:

* ``key: value`` lines (keys are listed in :data:`KEYS`);
* lines that start with spaces continue the value above them (for a
  ``solution`` of several lines);
* ``- [x] option`` / ``- [ ] option`` lines are the options of a choice
  (``[x]`` marks the right ones); ``- text`` lines are further accepted
  answers of a ``text`` question.

A sheet may start with *front matter* between two ``---`` lines: settings of
the whole exercise (``points``, ``seed``, ``generate``, ``boxes``), read by
:mod:`.pack`.

The full reference, with every type and what each checks, is
``cpnpy/learn/exercise-packs.md`` (*Help ▸ Writing Exercise Packs*).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

#: The kinds of answer box, and what each one is.
TYPES = {
    "net": "draw or change a Petri net in the editor beside the question",
    "footprint": "fill in a footprint matrix (→ ← ‖ #)",
    "yesno": "answer yes or no",
    "choice": "pick one option (or several, if more than one is right)",
    "set": "write a set, e.g. {a, b} — or a set of sets or of pairs",
    "trace": "write a firing sequence, e.g. ⟨register, send letter⟩",
    "number": "write a number",
    "text": "write a short answer",
    "open": "write freely; compare with the model answer yourself",
    "marking": "write a marking, e.g. [p1, p4^2]",
    "markings": "write a set of markings, e.g. [p1], [p2, p3]",
    "tuple": "write a net as (P, T, F, m0): four boxes",
    "ts": "write a transition system: s0 -a-> s1 lines",
    "matrix": "fill in a matrix with row and column headers",
    "cut": "write a cut of the Inductive Miner, e.g. → {a} {b, c} {d}",
    "log": "write a log in the course's notation, e.g. [<a, b>^2, <a, c>]",
    "tree": "write a process tree, e.g. →(a, ×(b, c), d)",
    "replay": "fill in produced, consumed, missing and remaining tokens per trace",
    "alignment": "write an alignment as two rows of moves (≫ for no move)",
    "ranking": "put the named models in order",
    "predict": "predict a box's result before running it",
    "workflow": "build a workflow in the Workflow tab",
}

#: Types whose editor is a text field with a notation (one line or several).
TEXT_TYPES = {"marking", "markings", "ts", "cut", "log", "tree", "alignment"}

#: Every key an answer block may use.
KEYS = {"type", "id", "answer", "compute", "hint", "solution", "start", "net", "log", "of",
        "sound", "fits", "ends", "tolerance", "title", "labels", "pattern",
        # the new blocks
        "points", "pairs", "exact", "unseen", "trace", "alignment", "over", "by", "order",
        "box", "value", "as", "settings", "needs", "result", "rows", "columns", "chart", "ts",
        "material"}

#: Keys the front matter of a sheet may use.
FRONT_KEYS = {"points", "seed", "generate", "boxes", "title", "time"}

_FENCE = re.compile(r"^(```+|~~~+)\s*answer\s*$", re.I)
_OPTION = re.compile(r"^-\s*\[( |x|X)\]\s*(.+)$")
_ITEM = re.compile(r"^-\s+(.+)$")
_KEY = re.compile(r"^([A-Za-z_]+)\s*:\s?(.*)$")
#: "start: net.pnml   # a comment" -- at least two spaces before the #, because
#: "a # b" is the α-algorithm's choice relation, often written in an answer.
_COMMENT = re.compile(r"\s{2,}#\s.*$")


class SheetError(ValueError):
    """A mistake in an answer block, with the line it is on."""


@dataclass
class Option:
    text: str
    correct: bool


@dataclass
class Task:
    """One answer box."""

    type: str
    id: str
    #: The question text just above the box (Markdown).
    prompt: str = ""
    #: Everything the block says, by key (values as written).
    settings: dict[str, str] = field(default_factory=dict)
    options: list[Option] = field(default_factory=list)
    #: ``- text`` lines: more accepted answers (``text``).
    alternatives: list[str] = field(default_factory=list)
    #: The line in question.md where the block starts (for error messages).
    line: int = 0

    def get(self, key: str, default: str | None = None) -> str | None:
        return self.settings.get(key, default)

    @property
    def hint(self) -> str | None:
        return self.settings.get("hint")

    @property
    def solution(self) -> str | None:
        return self.settings.get("solution")

    @property
    def points(self) -> float:
        """What a right answer earns (``points:``; 1 when the block says nothing)."""
        try:
            return float(self.settings.get("points", "") or 1)
        except ValueError:
            return 1.0

    @property
    def checkable(self) -> bool:
        """Can the app say whether the answer is right?"""
        if self.type == "open":
            return False
        if self.type == "choice":
            return any(o.correct for o in self.options) or "compute" in self.settings
        if self.type in ("set", "number", "yesno", "marking", "markings", "ts", "matrix", "cut",
                         "log", "tree", "replay"):
            return "answer" in self.settings or "compute" in self.settings
        if self.type == "text":
            return "answer" in self.settings or bool(self.alternatives) or \
                "pattern" in self.settings or "compute" in self.settings
        if self.type == "net":
            return any(k in self.settings for k in ("answer", "sound", "fits", "compute"))
        if self.type == "ranking":
            return "over" in self.settings
        if self.type == "predict":
            return "box" in self.settings
        if self.type == "workflow":
            return "needs" in self.settings or "result" in self.settings
        return True                     # footprint, trace, tuple, alignment


@dataclass
class Sheet:
    """The question as blocks: Markdown strings and :class:`Task` objects, in order."""

    title: str
    blocks: list = field(default_factory=list)
    #: The front matter: settings of the whole exercise.
    settings: dict[str, str] = field(default_factory=dict)

    @property
    def tasks(self) -> list[Task]:
        return [block for block in self.blocks if isinstance(block, Task)]

    @property
    def points(self) -> float:
        return sum(t.points for t in self.tasks)


def _parse_block(lines: list[str], start_line: int, index: int, prompt: str) -> Task:
    settings: dict[str, str] = {}
    options: list[Option] = []
    alternatives: list[str] = []
    current: str | None = None
    for offset, raw in enumerate(lines):
        number = start_line + offset + 1
        if not raw.strip():
            if current is not None:
                settings[current] += "\n"
            continue
        if raw[0] in " \t" and current is not None:
            settings[current] += ("\n" if settings[current] else "") + raw.strip()
            continue
        line = raw.strip()
        option = _OPTION.match(line)
        if option:
            options.append(Option(option.group(2).strip(), option.group(1) != " "))
            current = None
            continue
        item = _ITEM.match(line)
        if item:
            alternatives.append(item.group(1).strip())
            current = None
            continue
        key = _KEY.match(line)
        if not key:
            raise SheetError(f"line {number}: expected “key: value”, found “{line}”")
        name = key.group(1).lower()
        if name not in KEYS:
            raise SheetError(f"line {number}: unknown key “{name}” (known: "
                             + ", ".join(sorted(KEYS)) + ")")
        # "start: net.pnml   # a comment": the comment goes.
        settings[name] = _COMMENT.sub("", key.group(2)).strip()
        current = name
    settings = {k: v.strip() for k, v in settings.items()}
    kind = settings.get("type", "").lower()
    if not kind:
        kind = "choice" if options else "text" if alternatives else ""
    if kind not in TYPES:
        raise SheetError(f"line {start_line}: answer block needs a type, one of "
                         + ", ".join(TYPES) + (f" (found “{kind}”)" if kind else ""))
    if kind == "choice" and not options:
        raise SheetError(f"line {start_line}: a choice needs options, written as "
                         "“- [x] right” and “- [ ] wrong”")
    task_id = settings.get("id") or f"q{index}"
    return Task(kind, task_id, prompt.strip(), settings, options, alternatives, start_line)


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """``---`` lines at the top with ``key: value`` settings, and the rest."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    settings: dict[str, str] = {}
    for number, line in enumerate(lines[1:], 2):
        if line.strip() == "---":
            return settings, "\n".join(lines[number:])
        if not line.strip():
            continue
        key = _KEY.match(line.strip())
        if not key:
            raise SheetError(f"line {number}: expected “key: value” in the front matter")
        settings[key.group(1).lower()] = key.group(2).strip()
    raise SheetError("the front matter is not closed (add a line ---)")


def parse_sheet(text: str, title: str = "") -> Sheet:
    """Split question.md into Markdown and answer blocks."""
    settings, text = parse_front_matter(text)
    lines = text.splitlines()
    blocks: list = []
    markdown: list[str] = []
    index = 0
    position = 0
    heading = title
    while position < len(lines):
        line = lines[position]
        fence = _FENCE.match(line.strip())
        if fence:
            end = position + 1
            while end < len(lines) and not lines[end].strip().startswith(fence.group(1)):
                end += 1
            if end >= len(lines):
                raise SheetError(f"line {position + 1}: the answer block is not closed "
                                 f"(add a line {fence.group(1)})")
            index += 1
            # The prompt is the text since the previous block (or heading).
            prompt = "\n".join(markdown)
            if prompt.strip():
                blocks.append(prompt)
            task = _parse_block(lines[position + 1:end], position + 1, index,
                                _last_paragraphs(prompt))
            blocks.append(task)
            markdown = []
            position = end + 1
            continue
        if not heading and line.startswith("# "):
            heading = line[2:].strip()
            position += 1
            continue
        markdown.append(line)
        position += 1
    if "\n".join(markdown).strip():
        blocks.append("\n".join(markdown))
    ids = [t.id for t in blocks if isinstance(t, Task)]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise SheetError("two answer blocks have the same id: " + ", ".join(duplicates))
    sheet = Sheet(heading or settings.get("title") or "Exercise", blocks, settings)
    return sheet


def _last_paragraphs(markdown: str) -> str:
    """The part of the text that asks the question (for listings and the CLI)."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", markdown) if p.strip()]
    return paragraphs[-1] if paragraphs else ""


def read_sheet(path: str | Path) -> Sheet:
    path = Path(path)
    return parse_sheet(path.read_text(encoding="utf-8", errors="replace"))
