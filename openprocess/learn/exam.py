"""Exams, points and variants.

* **Points**: every answer block has ``points:`` (1 when it says nothing); an
  exercise's points are its blocks' (or ``points:`` in its front matter), and
  :func:`marks` turns a pack into a marks table (``openprocess exercises marks``).
* **Exam mode**: ``exam: yes`` in ``pack.md``'s front matter.  The app then
  shows no hints, no *Show answer* and reveals no hidden result; ``time: 120``
  (minutes) runs a clock from the moment the pack is first opened
  (:class:`ExamState`, kept in ``my exam.json``), and ``deadline: 2026-11-01
  12:00`` closes the answers at that moment.  After the time is up the
  answers stay as they are and can still be read.
* **Variants**: ``seed: student`` with ``generate: net.pnml, cases: 20``
  (see :meth:`openprocess.learn.context.Context.generated_log`).
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .pack import MY_EXAM, Pack


def parse_generate(setting: str) -> tuple[str, int, int]:
    """``generate: net.pnml, cases: 20, length: 50`` → ``("net.pnml", 20, 50)``."""
    parts = [p.strip() for p in setting.split(",") if p.strip()]
    if not parts:
        raise ValueError("generate: needs the net to play out")
    net, cases, length = parts[0], 20, 200
    for part in parts[1:]:
        match = re.match(r"^(cases|traces|length|max length)\s*[:=]?\s*(\d+)$", part, re.I)
        if not match:
            raise ValueError(f"cannot read “{part}” in generate: (use cases: 20, length: 50)")
        if match.group(1).lower() in ("cases", "traces"):
            cases = int(match.group(2))
        else:
            length = int(match.group(2))
    return net, cases, length


# ---------------------------------------------------------------------------
# The clock of an exam
# ---------------------------------------------------------------------------
@dataclass
class ExamState:
    """When the exam was started and when it ends."""

    pack: Pack
    started: datetime | None = None

    @property
    def path(self) -> Path:
        return self.pack.root / MY_EXAM

    @classmethod
    def load(cls, pack: Pack) -> "ExamState":
        state = cls(pack)
        try:
            data = json.loads(state.path.read_text(encoding="utf-8"))
            state.started = datetime.fromisoformat(data["started"])
        except (OSError, ValueError, KeyError, TypeError):
            state.started = None
        return state

    def start(self, now: datetime | None = None) -> None:
        """Note the start (only the first time)."""
        if self.started is not None:
            return
        self.started = (now or datetime.now()).replace(microsecond=0)
        text = json.dumps({"started": self.started.isoformat(), "pack": self.pack.title}, indent=2)
        temporary = self.path.with_name("." + MY_EXAM + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, self.path)

    @property
    def minutes(self) -> int | None:
        text = (self.pack.settings.get("time") or "").strip().lower()
        match = re.match(r"^(\d+)\s*(min|minutes|m|h|hours|hour)?$", text)
        if not match:
            return None
        value = int(match.group(1))
        return value * 60 if (match.group(2) or "").startswith("h") else value

    @property
    def deadline(self) -> datetime | None:
        """The earlier of ``deadline:`` and start + ``time:``."""
        candidates = []
        text = (self.pack.settings.get("deadline") or "").strip()
        if text:
            try:
                candidates.append(datetime.fromisoformat(text.replace("/", "-")))
            except ValueError:
                pass
        if self.started is not None and self.minutes is not None:
            candidates.append(self.started + timedelta(minutes=self.minutes))
        return min(candidates) if candidates else None

    def remaining(self, now: datetime | None = None) -> timedelta | None:
        deadline = self.deadline
        if deadline is None:
            return None
        return deadline - (now or datetime.now())

    def closed(self, now: datetime | None = None) -> bool:
        remaining = self.remaining(now)
        return remaining is not None and remaining.total_seconds() <= 0

    def clock_text(self, now: datetime | None = None) -> str:
        remaining = self.remaining(now)
        if remaining is None:
            return "Exam"
        if remaining.total_seconds() <= 0:
            return "Time is up"
        total = int(remaining.total_seconds())
        hours, rest = divmod(total, 3600)
        minutes, seconds = divmod(rest, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d} left" if hours else f"{minutes}:{seconds:02d} left"


# ---------------------------------------------------------------------------
# Marks
# ---------------------------------------------------------------------------
def marks(pack: Pack) -> list[dict]:
    """One row per exercise: its points, what the answers earn, and per block."""
    rows = []
    for exercise in pack.exercises:
        progress = exercise.load_progress()
        summary = exercise.summary(progress)
        row = {"exercise": exercise.title, "chapter": pack.chapter(exercise),
               "points": summary.points, "earned": round(summary.earned, 2),
               "answered": summary.tried, "of": summary.total, "blocks": {}}
        for task in exercise.sheet.tasks:
            entry = progress.get(task.id, {})
            status = entry.get("status", "")
            share = {"correct": 1.0, "done": 1.0}.get(status, float(entry.get("share", 0) or 0)
                                                     if status == "partial" else 0.0)
            row["blocks"][task.id] = {"status": status, "points": task.points,
                                      "earned": round(task.points * share, 2)}
        rows.append(row)
    return rows


def marks_csv(pack: Pack) -> str:
    """The marks as CSV: exercise, chapter, points, earned, answered, of; then a
    column per answer block."""
    rows = marks(pack)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["student", "exercise", "chapter", "points", "earned", "answered", "of",
                     "block", "block points", "block earned", "status"])
    student = pack.student() or ""
    for row in rows:
        if not row["blocks"]:
            writer.writerow([student, row["exercise"], row["chapter"], row["points"], row["earned"],
                             row["answered"], row["of"], "", "", "", ""])
        for block_id, block in row["blocks"].items():
            writer.writerow([student, row["exercise"], row["chapter"], row["points"], row["earned"],
                             row["answered"], row["of"], block_id, block["points"],
                             block["earned"], block["status"]])
    total = sum(r["points"] for r in rows)
    earned = sum(r["earned"] for r in rows)
    writer.writerow([student, "TOTAL", "", total, round(earned, 2), "", "", "", "", "", ""])
    return out.getvalue()
