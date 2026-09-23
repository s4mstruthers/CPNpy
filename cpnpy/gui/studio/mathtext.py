"""Typeset a small subset of LaTeX maths as Qt rich text (HTML).

Qt's rich-text engine has no maths support, but formulas about Petri nets need
little: italic symbols, sub- and superscripts, an overline, and Unicode for
∀ ∃ ∈ ⇒ •.  This module turns the LaTeX used in
:mod:`cpnpy.mining.definitions` (and in formulas the analysis builds for a
concrete net) into that HTML, so one source serves both GitHub, where MathJax
renders ``docs/definitions.md``, and the app.

Spacing follows TeX's idea rather than the source text: spaces in the source
are ignored, relations (= ∈ ⇒ …) and binary operators (∩ ∧ + …) get space on
both sides, and ``\\;``, ``\\quad`` and ``\\text{ … }`` add space explicitly.

Supported: letters (italic), digits, ``( ) [ ] , . | ! ' * + - < > = /``,
groups ``{…}``, ``_`` and ``^``, and the commands in :data:`SYMBOLS`,
:data:`RELATIONS`, :data:`BINARY` plus ``\\text``, ``\\mathrm``,
``\\mathit``, ``\\mathbb``, ``\\overline``, ``\\xrightarrow`` and ``\\not``.
Anything else raises :class:`ValueError`, so a typo shows up in the tests
instead of as a stray backslash on screen.
"""

from __future__ import annotations

from html import escape

#: The font stack for formulas (serif, like a textbook).
MATH_FONT = ("'STIX Two Math', 'STIX Two Text', 'Cambria Math', 'Latin Modern Math', "
             "'Times New Roman', serif")

#: Ordinary symbols: no extra space around them.
SYMBOLS = {
    "forall": "∀", "exists": "∃", "neg": "¬", "bullet": "•", "emptyset": "∅",
    "langle": "⟨", "rangle": "⟩", "lbrace": "{", "rbrace": "}", "{": "{", "}": "}",
    "ldots": "…", "cdots": "⋯", "infty": "∞", "omega": "ω", "sigma": "σ",
    "tau": "τ", "alpha": "α", "star": "∗", "max": "max",
}
#: Relations: a thick space on both sides.
RELATIONS = {
    "in": "∈", "notin": "∉", "subseteq": "⊆", "neq": "≠", "leq": "≤", "geq": "≥",
    "Rightarrow": "⇒", "iff": "⟺", "to": "→", "rightarrow": "→", "leftarrow": "←",
    "mid": "|", "parallel": "‖", "colon": ":", "#": "#",
}
#: Binary operators: a medium space on both sides.
BINARY = {"cap": "∩", "cup": "∪", "times": "×", "land": "∧", "lor": "∨", "setminus": "∖",
          "cdot": "·"}
#: Explicit spaces.
SPACES = {",": "&#8201;", ";": "&nbsp;", "quad": "&emsp;", "qquad": "&emsp;&emsp;", " ": "&nbsp;",
          "!": ""}
BLACKBOARD = {"N": "ℕ", "Z": "ℤ", "R": "ℝ", "B": "𝔹"}

_ASCII_RELATIONS = {"=": "=", "<": "&lt;", ">": "&gt;"}
_ASCII_BINARY = {"+": "+", "-": "−"}
#: Commands that are negated by \not, and what the negation looks like.
_NEGATED = {"in": "∉", "=": "≠", "subseteq": "⊈", "exists": "∄"}


class _Parser:
    def __init__(self, source: str) -> None:
        self.text = source
        self.index = 0

    # -- low level ---------------------------------------------------------------------
    def peek(self) -> str:
        return self.text[self.index] if self.index < len(self.text) else ""

    def take(self) -> str:
        char = self.peek()
        self.index += 1
        return char

    def skip_spaces(self) -> None:
        while self.peek().isspace():
            self.index += 1

    def command(self) -> str:
        """The name after a backslash (letters, or one other character)."""
        start = self.index
        if self.peek().isalpha():
            while self.peek().isalpha():
                self.index += 1
            return self.text[start:self.index]
        return self.take()

    def group_source(self) -> str:
        """The raw text of a ``{…}`` argument (nested braces allowed)."""
        self.skip_spaces()
        if self.take() != "{":
            raise ValueError(f"expected '{{' at {self.index} in {self.text!r}")
        depth, start = 1, self.index
        while depth:
            char = self.take()
            if not char:
                raise ValueError(f"unbalanced braces in {self.text!r}")
            if char == "\\":
                self.take()
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
        return self.text[start:self.index - 1]

    # -- rendering ---------------------------------------------------------------------
    def argument(self) -> str:
        """One token or group, rendered (for ``_``, ``^`` and commands)."""
        self.skip_spaces()
        if self.peek() == "{":
            return render(self.group_source())
        return self.atom()

    def atom(self) -> str:
        char = self.take()
        if char == "\\":
            return self.backslash()
        if char.isalpha():
            letters = char
            while self.peek().isalpha():
                letters += self.take()
            return f"<i>{letters}</i>"
        if char.isdigit():
            digits = char
            while self.peek().isdigit():
                digits += self.take()
            return digits
        if char == "{":
            self.index -= 1
            return render(self.group_source())
        if char in _ASCII_RELATIONS:
            return f" {_ASCII_RELATIONS[char]} "
        if char in _ASCII_BINARY:
            return f" {_ASCII_BINARY[char]} "
        if char == "'":
            return "′"
        if char == ",":
            return ", "
        if char == "*":
            return "∗"            # the asterisk operator sits at maths height
        if char in "()[]|.!/;:":
            return escape(char)
        raise ValueError(f"unsupported character {char!r} in {self.text!r}")

    def backslash(self) -> str:
        name = self.command()
        if name in SYMBOLS:
            return SYMBOLS[name]
        if name in RELATIONS:
            symbol = RELATIONS[name]
            return f"{symbol} " if name == "colon" else f" {symbol} "
        if name in BINARY:
            return f" {BINARY[name]} "
        if name in SPACES:
            return SPACES[name]
        if name in ("text", "mathrm"):
            return _text(self.group_source())
        if name == "mathit":
            return f"<i>{_text(self.group_source())}</i>"
        if name == "mathbb":
            letter = self.group_source().strip()
            return BLACKBOARD.get(letter, letter)
        if name == "overline":
            return f"<span style='text-decoration: overline'>{self.argument()}</span>"
        if name == "xrightarrow":
            return f" →<sup>{render(self.group_source())}</sup> "
        if name == "not":
            self.skip_spaces()
            if self.peek() == "\\":
                self.take()
                negated = self.command()
                if negated == "xrightarrow":
                    return f" ↛<sup>{render(self.group_source())}</sup> "
                if negated in _NEGATED:
                    return f" {_NEGATED[negated]} "
                raise ValueError(f"cannot negate \\{negated}")
            if self.peek() == "=":
                self.take()
                return " ≠ "
            raise ValueError(f"cannot negate {self.peek()!r}")
        raise ValueError(f"unsupported command \\{name} in {self.text!r}")

    def run(self) -> str:
        parts: list[str] = []
        while True:
            self.skip_spaces()
            if not self.peek():
                break
            char = self.peek()
            if char in "_^":
                self.take()
                tag = "sub" if char == "_" else "sup"
                script = f"<{tag}>{self.argument().strip()}</{tag}>"
                # Attach to the symbol before it; a relation keeps its space after.
                previous = parts.pop() if parts else ""
                spaced = previous.endswith(" ")
                parts.append(previous.rstrip() + script + (" " if spaced else ""))
            elif char == "}":
                raise ValueError(f"unbalanced '}}' in {self.text!r}")
            else:
                parts.append(self.atom())
        return _tidy("".join(parts))


def _text(source: str) -> str:
    """``\\text{…}``: upright words; ``\\{ \\}`` are literal braces, edge spaces kept."""
    plain = source.replace("\\{", "{").replace("\\}", "}").replace("\\_", "_")
    body = escape(plain.strip())
    lead = "&nbsp;" if plain[:1].isspace() else ""
    trail = "&nbsp;" if plain[-1:].isspace() else ""
    return f"{lead}<span style='font-family: sans-serif'>{body}</span>{trail}"


def _tidy(html: str) -> str:
    """Collapse the spaces operators added next to each other and at the ends."""
    while "  " in html:
        html = html.replace("  ", " ")
    return html.replace("( ", "(").replace(" )", ")").strip()


def render(source: str) -> str:
    """HTML for the LaTeX formula ``source`` (without the ``$`` delimiters)."""
    return _Parser(source).run()


def render_text(text: str) -> str:
    """HTML for prose with inline ``$…$`` maths and ``*emphasis*``."""
    out: list[str] = []
    for index, chunk in enumerate(text.split("$")):
        if index % 2:
            out.append(f"<span style='font-family: {MATH_FONT}'>{render(chunk)}</span>")
        else:
            words = escape(chunk).split("*")
            out.append("".join(f"<i>{w}</i>" if n % 2 else w for n, w in enumerate(words)))
    return "".join(out)


def display(source: str, size: int = 15) -> str:
    """A formula on its own line, centred like display maths."""
    return (f"<p align='center' style='font-family: {MATH_FONT}; font-size: {size}px; "
            f"margin: 4px 0'>{render(source)}</p>")


# ---------------------------------------------------------------------------
# Writing formulas about a concrete net
# ---------------------------------------------------------------------------
def name(text: str) -> str:
    """A node name for use inside a formula (``\\text{…}`` with braces escaped)."""
    cleaned = text.replace("\\", "").replace("{", "\\{").replace("}", "\\}")
    return "\\text{" + cleaned + "}"


def name_set(names) -> str:
    items = list(names)
    return "\\emptyset" if not items else \
        "\\lbrace " + ", ".join(name(n) for n in items) + " \\rbrace"


def sequence(names, limit: int = 8) -> str:
    items = list(names)
    if len(items) > limit:
        items = items[:limit - 1] + ["…"]
    return "\\langle " + ", ".join(name(n) for n in items) + " \\rangle"
