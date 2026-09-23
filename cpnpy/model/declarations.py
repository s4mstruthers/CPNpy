"""Parsing and compiling a model's declaration block.

A CPN model's declarations live in what CPN Tools calls the *global box*
(``<globbox>`` in the file format).  They come in four kinds:

``colset`` -- a colour set (a type)
    ``colset PACKET = product INT * STRING timed;``
``var`` -- a typed variable usable in inscriptions
    ``var p : PACKET;  var n, m : INT;``
``val`` / ``fun`` -- ordinary ML value and function declarations
    ``val limit = 10;   fun next n = n + 1;``
``globref`` -- a mutable global reference
    ``globref counter = 0;``

This module turns that text into:

* a **colour set registry**: name -> :class:`~cpnpy.ml.colorsets.ColourSet`;
* a **variable table**: name -> the colour set it ranges over (the binder needs
  this to know what to enumerate);
* **global environment entries**: enumeration constants, union constructors,
  and any ``val``/``fun`` bindings, all installed into the evaluator.

Order matters -- a colour set may refer to earlier ones -- so declarations are
compiled in the order they appear, and a forward reference is an error with a
message naming the missing colour set.

Why a separate parser
---------------------
Declaration syntax is *not* ML expression syntax: ``product A * B`` and
``union C1:A + C2`` are CPN Tools' own notation.  We reuse the ML
:func:`~cpnpy.ml.lexer.tokenise` for the token stream, then apply a small
purpose-built grammar here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from ..ml.colorsets import (
    AliasColourSet, BoolColourSet, ColourSet, EnumColourSet, IndexColourSet,
    IntColourSet, IntInfColourSet, ListColourSet, ProductColourSet,
    RealColourSet, RecordColourSet, StringColourSet, SubsetColourSet,
    UnionColourSet, UnitColourSet, standard_colour_sets,
)
from ..ml.errors import CPNMLError, ParseError
from ..ml.evaluator import ConstructorFunction, Evaluator
from ..ml.lexer import Token, tokenise
from ..ml.parser import Parser, parse_declarations
from ..ml.values import Constructor


@dataclass
class VariableDeclaration:
    """``var name : COLOURSET;`` -- one variable usable in inscriptions."""

    name: str
    colour_set_name: str


@dataclass
class DeclarationBlock:
    """The parsed contents of a model's global box.

    Kept as ordered lists of *source text* alongside the compiled results, so
    that saving a model reproduces exactly what the modeller wrote rather than
    a pretty-printed approximation.
    """

    #: ``(name, source_text)`` for every ``colset`` declaration, in order.
    colour_set_sources: list[tuple[str, str]] = field(default_factory=list)
    #: ``(name, colour_set_name, source_text)`` for every ``var`` declaration.
    variable_sources: list[tuple[str, str, str]] = field(default_factory=list)
    #: Raw ``val`` / ``fun`` declaration text, in order.
    ml_sources: list[str] = field(default_factory=list)
    #: ``(name, initial_expression_text)`` for every ``globref``.
    globref_sources: list[tuple[str, str]] = field(default_factory=list)

    # Filled in by :meth:`compile`.
    colour_sets: dict[str, ColourSet] = field(default_factory=dict)
    variables: dict[str, str] = field(default_factory=dict)

    # -- compilation ---------------------------------------------------------
    def compile(self, evaluator: Evaluator) -> None:
        """Build the colour sets and install everything into ``evaluator``.

        Called once when a model is loaded and again whenever the modeller
        edits a declaration.  It is idempotent: the registry is rebuilt from
        the standard colour sets each time, so removing a declaration really
        removes it.
        """
        from ..ml.parser import parse_expression
        self.colour_sets = standard_colour_sets()
        self.variables = {}

        for colour_set in self.colour_sets.values():         # INT.all () ...
            _install_colour_set_functions(colour_set, evaluator)

        # Colour sets and ML declarations may depend on each other in either
        # direction: `val n = 5; colset N = int with 1..n;`, a subset by a
        # predicate function, or `val phs = PH.all ();`.  The three lists do
        # not record how the modeller interleaved them, so compile in passes:
        # each pass compiles whatever it can, and a declaration that fails
        # waits for the next pass.  Only when a whole pass makes no progress
        # is the first remaining problem reported.
        pending_sets = list(self.colour_sets_in_order())
        pending_ml = list(self.ml_sources)
        pending_refs = list(self.globref_sources)
        while pending_sets or pending_ml or pending_refs:
            problems: list[CPNMLError] = []
            progress = False

            waiting_sets = []
            for name, source in pending_sets:
                try:
                    colour_set = parse_colour_set_declaration(source, self.colour_sets, evaluator)
                except CPNMLError as problem:
                    waiting_sets.append((name, source))
                    # Say which declaration failed: positions are relative to it.
                    problems.append(type(problem)(f"colset {name}: {problem.message}",
                                                  problem.position))
                    continue
                self.colour_sets[colour_set.name] = colour_set
                _install_constructors(colour_set, evaluator)
                _install_colour_set_functions(colour_set, evaluator)
                progress = True
            pending_sets = waiting_sets

            waiting_ml = []
            for source in pending_ml:
                try:
                    evaluator.run_declarations(parse_declarations(source))
                except CPNMLError as problem:
                    waiting_ml.append(source)
                    problems.append(problem)
                    continue
                progress = True
            pending_ml = waiting_ml

            waiting_refs = []
            for name, initial in pending_refs:
                try:
                    evaluator.globals.define(name, evaluator.evaluate(parse_expression(initial)))
                except CPNMLError as problem:
                    waiting_refs.append((name, initial))
                    problems.append(type(problem)(f"globref {name}: {problem.message}",
                                                  problem.position))
                    continue
                progress = True
            pending_refs = waiting_refs

            if not progress:
                raise problems[0]

        for name, colour_set_name, _source in self.variable_sources:
            if colour_set_name not in self.colour_sets:
                raise CPNMLError(
                    f"variable '{name}' is declared with unknown colour set "
                    f"'{colour_set_name}'"
                )
            self.variables[name] = colour_set_name

    def colour_sets_in_order(self) -> list[tuple[str, str]]:
        return list(self.colour_set_sources)

    def variable_colour_set(self, name: str) -> ColourSet | None:
        """The colour set a variable ranges over, or ``None`` if undeclared."""
        colour_set_name = self.variables.get(name)
        if colour_set_name is None:
            return None
        return self.colour_sets.get(colour_set_name)


def _install_constructors(colour_set: ColourSet, evaluator: Evaluator) -> None:
    """Make a colour set's constants and constructors usable in inscriptions.

    * enumeration constants (``red``) become bound values;
    * index tags (``proc``) and union tags with a payload become functions;
    * nullary union tags become bound values, like enumeration constants.

    Without this step an inscription mentioning ``red`` would fail with
    "unbound identifier".
    """
    if isinstance(colour_set, EnumColourSet):
        for constant in colour_set.constants:
            evaluator.globals.define(constant, Constructor(constant))
    elif isinstance(colour_set, IndexColourSet):
        evaluator.globals.define(colour_set.tag, ConstructorFunction(colour_set.tag))
    elif isinstance(colour_set, UnionColourSet):
        for tag, payload in colour_set.variants:
            if payload is None:
                evaluator.globals.define(tag, Constructor(tag))
            else:
                evaluator.globals.define(tag, ConstructorFunction(tag))
    elif isinstance(colour_set, UnitColourSet) and colour_set.alias:
        from ..ml.values import UNIT
        evaluator.globals.define(colour_set.alias, UNIT)
    elif isinstance(colour_set, BoolColourSet):
        if colour_set.false_alias:
            evaluator.globals.define(colour_set.false_alias, False)
        if colour_set.true_alias:
            evaluator.globals.define(colour_set.true_alias, True)


def _install_colour_set_functions(colour_set: ColourSet, evaluator: Evaluator) -> None:
    """CPN Tools' colour set functions: ``PH.all()``, ``PH.ran()`` and friends.

    Every colour set ``CS`` comes with

    ``CS.all ()``    the multiset with one of each colour (finite sets only)
    ``CS.size ()``   the number of colours
    ``CS.ran ()``    a colour drawn at random
    ``CS.ord c``     the position of ``c``, counting from 0
    ``CS.col i``     the colour at position ``i``
    ``CS.legal c``   whether ``c`` is a member
    ``CS.mkstr c``   ``c`` as a string

    The colours are listed on first use only, so declaring a large colour set
    costs nothing until one of these is called.
    """
    from ..ml.builtins import Builtin
    from ..ml.errors import EvalError
    from ..ml.multiset import Multiset
    from ..ml.values import format_value

    name = colour_set.name
    cache: list[list[Any]] = []

    def members() -> list[Any]:
        if not cache:
            if not colour_set.is_finite():
                raise EvalError(f"{name} is infinite, so it has no {name}.all/ran/ord/col")
            cache.append(list(colour_set.members()))
        return cache[0]

    def ordinal(colour: Any) -> int:
        try:
            return members().index(colour)
        except ValueError:
            raise EvalError(f"{format_value(colour)} is not a colour of {name}") from None

    def column(index: Any) -> Any:
        colours = members()
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(colours):
            raise EvalError(f"{name}.col expects 0..{len(colours) - 1}, got {format_value(index)}")
        return colours[index]

    def random_colour(_unit: Any) -> Any:
        colours = members()
        if not colours:
            raise EvalError(f"{name} is empty, so {name}.ran has nothing to choose")
        return evaluator.rng.choice(colours)

    functions = {
        "all": lambda _unit: Multiset.from_values(members()),
        "size": lambda _unit: len(members()),
        "ran": random_colour,
        "ord": ordinal,
        "col": column,
        "legal": lambda colour: bool(colour_set.contains(colour)),
        "mkstr": lambda colour: format_value(colour),
    }
    for function_name, function in functions.items():
        qualified = f"{name}.{function_name}"
        evaluator.globals.define(qualified, Builtin(qualified, function))


# ===========================================================================
# The colour set declaration parser
# ===========================================================================
class _ColourSetParser(Parser):
    """Extends the ML parser cursor with the ``colset`` grammar."""

    def __init__(self, tokens: Sequence[Token], registry: dict[str, ColourSet], source: str,
                 evaluator: Evaluator | None = None) -> None:
        super().__init__(tokens, source)
        self.registry = registry
        #: Evaluates named range bounds and subset predicates; without it only
        #: literals are accepted and subsets keep every value.
        self.evaluator = evaluator

    # -- helpers -------------------------------------------------------------
    def _resolve(self, name: str) -> ColourSet:
        if name not in self.registry:
            raise ParseError(
                f"unknown colour set '{name}' -- declare it before it is used",
                self.peek().position,
            )
        return self.registry[name]

    def _constant_int(self) -> int:
        """Read an integer bound: a literal, or an expression such as ``n``
        or ``n * 2`` over values declared with ``val`` (as CPN Tools allows).
        """
        token = self.peek()
        if token.kind == "INT" and (self.peek(1).kind == "EOF" or self._bound_ends(1)):
            self.next_token()
            return int(token.value)  # type: ignore[arg-type]
        value = self._evaluate_until_bound_end("a colour set range")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ParseError(f"a colour set range must be an integer, got {value!r}",
                             token.position)
        return value

    def _bound_ends(self, offset: int = 0) -> bool:
        """Does the token at ``offset`` end a range bound?"""
        token = self.peek(offset)
        if token.kind == "EOF":
            return True
        if token.kind == "OP" and token.value in ("..", ";"):
            return True
        return token.kind in ("ID", "KEYWORD") and token.value in ("timed", "and")

    def _evaluate_until_bound_end(self, what: str) -> Any:
        """Evaluate the tokens up to the end of a bound (``..``, ``;``, ...)."""
        from ..ml.parser import parse_expression
        start = self.peek().position
        while not self._bound_ends():
            self.next_token()
        end = self.peek().position if not self.at_end() else len(self.source)
        text = self.source[start:end].strip()
        if not text:
            raise ParseError(f"expected {what}", start)
        if self.evaluator is None:
            raise ParseError(f"{what} must be an integer literal here (found {text!r})", start)
        return self.evaluator.evaluate(parse_expression(text))

    def _string_literal(self) -> str:
        token = self.next_token()
        if token.kind not in ("STRING", "CHAR"):
            raise ParseError("expected a string literal", token.position)
        return str(token.value)

    # -- the grammar ---------------------------------------------------------
    def parse(self) -> ColourSet:
        """``colset NAME = <definition> [timed];``"""
        if self.peek().kind == "ID" and self.peek().value == "colset":
            self.next_token()
        name = self.expect_identifier()
        self.expect_operator("=")
        colour_set = self._parse_definition(name)
        # The optional `timed` keyword follows the definition.
        if self.peek().kind == "ID" and self.peek().value == "timed":
            self.next_token()
            colour_set.timed = True
        if self.at_operator(";"):
            self.next_token()
        return colour_set

    def _parse_definition(self, name: str) -> ColourSet:
        token = self.peek()

        # `with a | b | c` -- an enumeration.
        if self._at_word("with"):
            self.next_token()
            constants = [self.expect_identifier()]
            while self.at_operator("|"):
                self.next_token()
                constants.append(self.expect_identifier())
            return EnumColourSet(name, constants)

        if token.kind != "ID":
            raise ParseError(
                f"expected a colour set definition, found {token.value!r}", token.position
            )

        word = str(token.value)

        if word == "unit":
            self.next_token()
            alias = None
            if self._at_word("with"):
                self.next_token()
                alias = self.expect_identifier()
            return UnitColourSet(name, alias=alias)

        if word == "bool":
            self.next_token()
            false_alias = true_alias = None
            if self._at_word("with"):
                self.next_token()
                self.expect_operator("(")
                false_alias = self.expect_identifier()
                self.expect_operator(",")
                true_alias = self.expect_identifier()
                self.expect_operator(")")
            return BoolColourSet(name, false_alias=false_alias, true_alias=true_alias)

        if word in ("int", "intinf"):
            self.next_token()
            low = high = None
            if self._at_word("with"):
                self.next_token()
                low = self._constant_int()
                self.expect_operator("..")
                high = self._constant_int()
            cls = IntColourSet if word == "int" else IntInfColourSet
            return cls(name, low=low, high=high)

        if word == "time":
            # CPN Tools' built-in model-time type.  Model time is a number
            # (integer or real, depending on the simulator setting), so it
            # behaves like an unbounded real colour set.
            self.next_token()
            return RealColourSet(name)

        if word == "real":
            self.next_token()
            low = high = None
            if self._at_word("with"):
                self.next_token()
                low = float(self.next_token().value)  # type: ignore[arg-type]
                self.expect_operator("..")
                high = float(self.next_token().value)  # type: ignore[arg-type]
            return RealColourSet(name, low=low, high=high)

        if word == "string":
            self.next_token()
            char_low = char_high = None
            length_low = length_high = None
            if self._at_word("with"):
                self.next_token()
                char_low = self._string_literal()
                self.expect_operator("..")
                char_high = self._string_literal()
                if self._at_word("and"):
                    self.next_token()
                    length_low = self._constant_int()
                    self.expect_operator("..")
                    length_high = self._constant_int()
            return StringColourSet(
                name, char_low=char_low, char_high=char_high,
                length_low=length_low, length_high=length_high,
            )

        if word == "index":
            self.next_token()
            tag = self.expect_identifier()
            self._expect_word("with")
            low = self._constant_int()
            self.expect_operator("..")
            high = self._constant_int()
            return IndexColourSet(name, tag, low, high)

        if word == "product":
            self.next_token()
            components = [self._resolve(self.expect_identifier())]
            while self.at_operator("*"):
                self.next_token()
                components.append(self._resolve(self.expect_identifier()))
            return ProductColourSet(name, components)

        if word == "record":
            self.next_token()
            fields = [self._parse_record_field()]
            while self.at_operator("*"):
                self.next_token()
                fields.append(self._parse_record_field())
            return RecordColourSet(name, fields)

        if word == "list":
            self.next_token()
            element = self._resolve(self.expect_identifier())
            length_low = length_high = None
            if self._at_word("with"):
                self.next_token()
                length_low = self._constant_int()
                self.expect_operator("..")
                length_high = self._constant_int()
            return ListColourSet(name, element, length_low=length_low, length_high=length_high)

        if word == "union":
            self.next_token()
            variants = [self._parse_union_variant()]
            while self.at_operator("+"):
                self.next_token()
                variants.append(self._parse_union_variant())
            return UnionColourSet(name, variants)

        if word == "subset":
            self.next_token()
            base = self._resolve(self.expect_identifier())
            return self._parse_subset(name, base)

        # Anything else is an alias for an existing colour set.
        self.next_token()
        return AliasColourSet(name, self._resolve_named(word, token.position))

    # -- pieces --------------------------------------------------------------
    def _resolve_named(self, name: str, position: int) -> ColourSet:
        if name not in self.registry:
            raise ParseError(f"unknown colour set '{name}'", position)
        return self.registry[name]

    def _parse_record_field(self) -> tuple[str, ColourSet]:
        field_name = self.expect_identifier()
        self.expect_operator(":")
        return field_name, self._resolve(self.expect_identifier())

    def _parse_union_variant(self) -> tuple[str, ColourSet | None]:
        tag = self.expect_identifier()
        if self.at_operator(":"):
            self.next_token()
            return tag, self._resolve(self.expect_identifier())
        return tag, None

    def _parse_subset(self, name: str, base: ColourSet) -> ColourSet:
        """``subset A by pred`` or ``subset A with [v1, v2]``.

        ``by`` takes a predicate function, ``with`` an explicit member list.
        The predicate is stored as source text and compiled lazily by the
        model, because it may refer to functions declared further down.
        """
        if self._at_word("by"):
            self.next_token()
            start = self.peek().position
            # The predicate runs to the end of the declaration.
            while not self.at_end() and not self.at_operator(";") and not self._at_word("timed"):
                self.next_token()
            end = self.peek().position if not self.at_end() else len(self.source)
            source = self.source[start:end].strip()
            if self.evaluator is None:
                # Parsed only for its shape (no evaluator): keep every value.
                return SubsetColourSet(name, base, lambda _v: True, predicate_source=source)
            from ..ml.parser import parse_expression
            evaluator = self.evaluator
            # Evaluated now, so an undeclared predicate makes this colour set
            # wait until the ML declarations have defined it.
            function = evaluator.evaluate(parse_expression(source))

            def predicate(value: Any) -> bool:
                try:
                    return evaluator.apply(function, value) is True
                except CPNMLError:
                    return False

            return SubsetColourSet(name, base, predicate, predicate_source=source)

        if self._at_word("with"):
            self.next_token()
            self.expect_operator("[")
            start = self.peek().position
            depth = 1
            while depth:
                if self.at_operator("["):
                    depth += 1
                elif self.at_operator("]"):
                    depth -= 1
                    if depth == 0:
                        break
                self.next_token()
            end = self.peek().position
            source = self.source[start:end]
            self.expect_operator("]")
            if self.evaluator is None:
                return SubsetColourSet(name, base, lambda _v: True,
                                       predicate_source=f"MEMBERS[{source}]")
            from ..ml.parser import parse_expression
            listed = list(self.evaluator.evaluate(parse_expression(f"[{source}]")))
            for value in listed:
                if not base.contains(value):
                    raise ParseError(f"{value!r} in subset '{name}' is not a member of "
                                     f"'{base.name}'", start)
            return SubsetColourSet(name, base, lambda value: value in listed,
                                   predicate_source=f"MEMBERS[{source}]",
                                   members=listed)

        raise ParseError("'subset' must be followed by 'by' or 'with'", self.peek().position)

    # -- word helpers (CPN keywords are plain identifiers to the ML lexer) ---
    def _at_word(self, word: str) -> bool:
        token = self.peek()
        return token.kind == "ID" and token.value == word

    def _expect_word(self, word: str) -> None:
        if not self._at_word(word):
            raise ParseError(f"expected '{word}'", self.peek().position)
        self.next_token()


def parse_colour_set_declaration(source: str, registry: dict[str, ColourSet],
                                 evaluator: Evaluator | None = None) -> ColourSet:
    """Parse one ``colset ... = ...;`` declaration against ``registry``.

    With an ``evaluator``, range bounds may name declared values and subset
    predicates are compiled; without one, only literal bounds are accepted.
    """
    return _ColourSetParser(tokenise(source), registry, source, evaluator).parse()


def parse_variable_declaration(source: str) -> list[VariableDeclaration]:
    """Parse ``var a, b : COLOURSET;`` into one entry per name."""
    parser = Parser(tokenise(source), source)
    if parser.peek().kind == "ID" and parser.peek().value == "var":
        parser.next_token()
    names = [parser.expect_identifier()]
    while parser.at_operator(","):
        parser.next_token()
        names.append(parser.expect_identifier())
    parser.expect_operator(":")
    colour_set_name = parser.expect_identifier()
    return [VariableDeclaration(name, colour_set_name) for name in names]


def classify_declaration(source: str) -> str:
    """Return ``'colset'``, ``'var'``, ``'globref'`` or ``'ml'`` for a snippet.

    Used by the ``.cpn`` reader, which sometimes receives a declaration block
    as one lump of text rather than as individually tagged elements.
    """
    stripped = source.lstrip()
    for keyword in ("colset", "var", "globref"):
        if stripped.startswith(keyword) and (
            len(stripped) == len(keyword) or not stripped[len(keyword)].isalnum()
        ):
            return keyword
    return "ml"
