"""Turning a past exam into a pack: the guided import.

Paste the exam's text (or give the file); :func:`split_questions` finds the
questions and their parts by their numbering, :func:`guess_type` picks an
answer block for each part from how it is worded, and :func:`write_pack`
writes the skeleton: one exercise folder per question with a
``question.md`` whose blocks are ready for the author to finish.  Each
block carries a ``TODO`` where the author must act: drop in the net or the
log as a file, replace a guessed ``compute:`` with the right one, or write a
``solution:`` for an open question.  ``openprocess exercises check`` then lists
what is still missing.

The import never computes answers itself: it cannot know the net or the log
the exam showed as a picture.  Its job is the structure, so that the author
types nothing twice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

#: The start of a question: "1.", "Question 2", "Q3", "2)" at the start of a line.
_QUESTION = re.compile(r"^\s*(?:question|q|exercise|opgave)?\s*(\d{1,2})\s*[.):]\s*(.*)$", re.I)
#: The start of a part: "a.", "(a)", "a)", "1a".
_PART = re.compile(r"^\s*\(?(?:\d{1,2})?([a-z])[.)]\s+(.*)$", re.I)
#: "(2 points)", "[3 pt]", "(1.5 punten)"
_POINTS = re.compile(r"[\(\[]\s*(\d+(?:[.,]\d+)?)\s*(?:points?|pts?|punten|p)\s*[\)\]]", re.I)


@dataclass
class Part:
    letter: str
    text: str
    points: float | None = None

    @property
    def kind(self) -> str:
        return guess_type(self.text)


@dataclass
class Question:
    number: int
    title: str
    intro: str = ""
    parts: list[Part] = field(default_factory=list)
    points: float | None = None


def _points(text: str) -> tuple[float | None, str]:
    match = _POINTS.search(text)
    if not match:
        return None, text
    return float(match.group(1).replace(",", ".")), (text[:match.start()] + text[match.end():]).strip()


def split_questions(text: str) -> list[Question]:
    """The questions of an exam, each with its lettered parts."""
    questions: list[Question] = []
    current: Question | None = None
    part: Part | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        question = _QUESTION.match(line)
        if question and (current is None or int(question.group(1)) == current.number + 1):
            points, title = _points(question.group(2).strip())
            current = Question(int(question.group(1)), title or f"Question {question.group(1)}",
                               points=points)
            questions.append(current)
            part = None
            continue
        if current is None:
            continue
        found = _PART.match(line)
        expected = chr(ord(current.parts[-1].letter) + 1) if current.parts else "a"
        if found and found.group(1).lower() == expected:
            points, body = _points(found.group(2).strip())
            part = Part(expected, body, points)
            current.parts.append(part)
            continue
        if part is not None:
            part.text = (part.text + "\n" + line).strip()
        else:
            current.intro = (current.intro + "\n" + line).strip()
    return questions


#: Wording → block type, first match wins.
_CUES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(draw|model|construct|design|complete|repair|change)\b.*\b(net|petri)", re.I | re.S), "net"),
    (re.compile(r"\b(draw|give|construct)\b.*\b(reachability|marking) graph|transition system\b", re.I | re.S), "ts"),
    (re.compile(r"\bfootprint\b|\brelation(s)? between\b|\b(causal|parallel|choice) relation", re.I), "footprint"),
    (re.compile(r"\b(incidence|matrix|matrices)\b", re.I), "matrix"),
    (re.compile(r"\balignment\b.*\b(optimal|sub-?optimal|not an alignment)", re.I | re.S), "choice"),
    (re.compile(r"\b(give|write|construct)\b.*\balignment\b", re.I | re.S), "alignment"),
    (re.compile(r"\bprocess tree\b", re.I), "tree"),
    (re.compile(r"\b(cut)\b.*\binductive\b|\binductive\b.*\bcut\b", re.I | re.S), "cut"),
    (re.compile(r"\b(sublog|split the log|projected log)\b", re.I), "log"),
    (re.compile(r"\b(produced|consumed|missing|remaining)\b", re.I), "replay"),
    (re.compile(r"\b(rank|order)\b.*\b(models?|nets?)\b", re.I | re.S), "ranking"),
    (re.compile(r"\b(firing sequence|trace)\b.*\b(deadlock|dead marking|not in the log|never)", re.I | re.S), "trace"),
    (re.compile(r"\b(reachable|terminal|dead) markings\b", re.I), "markings"),
    (re.compile(r"\bmarking\b.*\b(after|reached|firing)", re.I | re.S), "marking"),
    (re.compile(r"\(P\s*,\s*T\s*,\s*F|\bformalise\b|\bformalize\b|\bpreset\b|\bpostset\b", re.I), "tuple"),
    (re.compile(r"\bwhich of the following\b|\bchoose\b|\bselect\b|\bmultiple[- ]choice\b", re.I), "choice"),
    (re.compile(r"\bhow many\b|\bcompute\b|\bcalculate\b|\bfitness\b|\bnumber of\b|\bprobability\b", re.I), "number"),
    (re.compile(r"\b(is|are|does|do|can|could|has|have|will)\b\s+(the|this|it|there|every|each|any)\b.*\?", re.I | re.S), "yesno"),
    (re.compile(r"\b(true or false|yes or no)\b", re.I), "yesno"),
    (re.compile(r"\b(give|list|which|what are|determine)\b.*\b(set|activities|transitions|places|states|regions|pairs)\b", re.I | re.S), "set"),
    (re.compile(r"\b(explain|why|argue|motivate|describe|discuss)\b", re.I), "open"),
]


def guess_type(text: str) -> str:
    """The answer block a question's wording suggests (``open`` when unsure)."""
    for pattern, kind in _CUES:
        if pattern.search(text):
            return kind
    return "open"


_COMPUTE_HINT = {
    "yesno": "compute: sound            # TODO: the property asked (sound, live, bounded, dead(t)…)",
    "number": "compute: fitness          # TODO: the figure asked (fitness, deadlocks, bound, cases…)",
    "set": "compute: alpha.T_I        # TODO: the set asked (dead transitions, enabled([p1]), net.T…)",
    "footprint": "pairs: (a, b), (b, c)     # TODO: only the pairs the exam asks (or remove for all)",
    "matrix": "compute: incidence        # TODO: incidence, language.M or language.M'",
    "ts": "compute: reachability graph",
    "markings": "compute: reachable        # TODO: reachable or terminal",
    "marking": "compute: fire(a, [p1])    # TODO: the sequence and the start marking",
    "tuple": "",
    "tree": "compute: im.tree",
    "cut": "compute: im.cut           # TODO: im.cut(2) for a deeper step",
    "log": "compute: im.split(1)      # TODO: which part of which cut",
    "replay": "",
    "alignment": "trace: a, b, c            # TODO: the trace to align",
    "ranking": "over: m1.pnml, m2.pnml    # TODO: the nets to rank, as files\nby: fitness",
    "trace": "ends: deadlock            # TODO: any, final, deadlock, stuck or improper",
    "net": "answer: answer.pnml       # TODO: draw the model answer and save it as answer.pnml\nsound: yes",
    "choice": "- [ ] TODO: the first option\n- [ ] TODO: the second option",
    "open": "solution: TODO: write the model answer here",
}


def block_for(part: Part) -> str:
    """The answer block (as text) for a part of a question."""
    kind = part.kind
    lines = [f"type: {kind}"]
    hint = _COMPUTE_HINT.get(kind, "")
    if hint:
        lines.extend(hint.split("\n"))
    if part.points is not None:
        lines.append(f"points: {part.points:g}")
    if kind != "open" and "solution" not in hint:
        lines.append("solution: TODO: the grading scheme's answer, in words")
    return "```answer\n" + "\n".join(lines) + "\n```"


def question_markdown(question: Question) -> str:
    """``question.md`` for one question of the exam."""
    points = question.points if question.points is not None else \
        (sum(p.points for p in question.parts if p.points) or None)
    title = f"# {question.number} · {question.title}" + (f" ({points:g} points)" if points else "")
    out = []
    # The question's points, when its parts do not add up to them (none given,
    # or a different total): front matter keeps the exam's total right.
    if points and sum(p.points or 0 for p in question.parts) != points:
        out += ["---", f"points: {points:g}", "---"]
    out += [title, ""]
    if question.intro:
        out += [question.intro, "", "> **TODO:** the exam showed a net or a log here: recreate it as "
                "`net.pnml` / `log.txt` in this folder so the app can compute the answers.", ""]
    for part in question.parts:
        out += [f"**{part.letter}.** {part.text}", "", block_for(part), ""]
    if not question.parts:
        out += [block_for(Part("a", question.intro or question.title)), ""]
    return "\n".join(out).rstrip() + "\n"


def write_pack(text: str, target: str | Path, title: str = "Exam") -> list[Path]:
    """Write the skeleton pack for an exam's text; the files written."""
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    questions = split_questions(text)
    if not questions:
        raise ValueError("no questions found: number them 1., 2., … with parts a., b., …")
    written = []
    pack_file = target / "pack.md"
    if not pack_file.exists():
        total = sum(q.points or sum(p.points for p in q.parts if p.points) or 0 for q in questions)
        pack_file.write_text("---\nexam: yes\ntime: 180\n---\n" + f"# {title}\n\n"
                             f"{len(questions)} questions" + (f", {total:g} points" if total else "")
                             + ".  Made with *Make a pack from an exam*: every `TODO` in the "
                             "questions is for the author to finish, then run "
                             "`openprocess exercises check` on this folder.\n", encoding="utf-8")
        written.append(pack_file)
    for question in questions:
        name = re.sub(r"[^\w\s\-·]+", "", question.title).strip() or f"Question {question.number}"
        folder = target / f"{question.number} {name[:60]}"
        folder.mkdir(exist_ok=True)
        path = folder / "question.md"
        path.write_text(question_markdown(question), encoding="utf-8")
        written.append(path)
    return written


def todo_list(target: str | Path) -> list[str]:
    """Every ``TODO`` left in a pack, with its file and line."""
    found = []
    for path in sorted(Path(target).rglob("question.md")):
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if "TODO" in line:
                found.append(f"{path.parent.name}/question.md:{number}: {line.strip()}")
    return found
