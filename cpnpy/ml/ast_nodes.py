"""Abstract syntax tree for the CPN ML subset.

Nodes are plain frozen dataclasses -- no behaviour, no evaluation logic.  The
evaluator walks them in :mod:`cpnpy.ml.evaluator` and the binder walks the
pattern nodes in :mod:`cpnpy.sim.binding`.  Keeping the tree behaviour-free
means we can serialise, pretty-print, or analyse it (for example to collect a
transition's free variables) without dragging the interpreter along.

The tree is split into three families:

``Expr``
    Things that evaluate to a value: literals, variables, applications,
    ``if``/``let``/``case``, and the CPN multiset forms.

``Pattern``
    Things that *destructure* a value and produce variable bindings.  Used by
    ``fn``, ``case``, ``val``, and -- most importantly -- by the binder, which
    matches input arc inscriptions against the tokens actually in a place.

``Decl``
    ``val`` and ``fun`` bindings, appearing inside ``let`` and at the top level
    of a model's declaration blocks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ===========================================================================
# Expressions
# ===========================================================================
class Expr:
    """Base class for expression nodes.

    ``position`` is the source offset of the construct, carried so that runtime
    errors can be reported against the exact spot in the inscription.
    """

    position: int = 0


@dataclass(frozen=True)
class Literal(Expr):
    """An integer, real, string, character, boolean or ``()`` literal."""

    value: Any
    position: int = 0


@dataclass(frozen=True)
class Var(Expr):
    """An identifier: a bound variable, a function, or a nullary constructor.

    Which of the three it is cannot be decided syntactically -- ``red`` looks
    identical whether it is a variable or an enumeration constant -- so the
    decision is deferred to the evaluator, which consults the environment.
    """

    name: str
    position: int = 0


@dataclass(frozen=True)
class TupleExpr(Expr):
    """``(a, b, c)`` -- a value of a product colour set."""

    items: tuple[Expr, ...]
    position: int = 0


@dataclass(frozen=True)
class ListExpr(Expr):
    """``[a, b, c]`` -- a value of a list colour set."""

    items: tuple[Expr, ...]
    position: int = 0


@dataclass(frozen=True)
class RecordExpr(Expr):
    """``{name = a, age = b}`` -- a value of a record colour set."""

    fields: tuple[tuple[str, Expr], ...]
    position: int = 0


@dataclass(frozen=True)
class Selector(Expr):
    """``#field`` or ``#2`` used as a function.

    In ML ``#name`` is an ordinary first-class function that projects a field
    out of a record, and ``#2`` does the same for a tuple component (1-based).
    Representing it as an atom rather than as special syntax means ``#name r``
    is simply an :class:`App`, and ``List.map #name people`` works for free.
    """

    field_name: str
    position: int = 0


@dataclass(frozen=True)
class App(Expr):
    """Function application ``f x``.

    Curried: ``f x y`` is ``App(App(f, x), y)``.  Constructor application
    (``Car(v)``) uses the same node; the evaluator distinguishes them by what
    ``f`` evaluates to.
    """

    function: Expr
    argument: Expr
    position: int = 0


@dataclass(frozen=True)
class BinOp(Expr):
    """An infix operator application, e.g. ``a + b`` or ``m1 ++ m2``."""

    operator: str
    left: Expr
    right: Expr
    position: int = 0


@dataclass(frozen=True)
class UnOp(Expr):
    """A prefix operator: ``~x`` (negation) or ``not b``."""

    operator: str
    operand: Expr
    position: int = 0


@dataclass(frozen=True)
class IfExpr(Expr):
    """``if c then a else b``.  The ``else`` branch is mandatory in ML."""

    condition: Expr
    then_branch: Expr
    else_branch: Expr
    position: int = 0


@dataclass(frozen=True)
class LetExpr(Expr):
    """``let val x = e1 ... in e2 end`` -- local declarations then a body."""

    declarations: tuple["Decl", ...]
    body: Expr
    position: int = 0


@dataclass(frozen=True)
class CaseExpr(Expr):
    """``case e of p1 => e1 | p2 => e2``.

    Rules are tried top to bottom; the first pattern that matches wins, exactly
    as in ML.  If none matches, evaluation raises ``MatchError``.
    """

    scrutinee: Expr
    rules: tuple[tuple["Pattern", Expr], ...]
    position: int = 0


@dataclass(frozen=True)
class FnExpr(Expr):
    """``fn p1 => e1 | p2 => e2`` -- an anonymous function."""

    rules: tuple[tuple["Pattern", Expr], ...]
    position: int = 0


# -- CPN-specific multiset syntax -------------------------------------------
@dataclass(frozen=True)
class Coefficient(Expr):
    """``n`v`` -- the multiset containing ``n`` copies of ``v``.

    This is the one piece of syntax that is CPN's rather than ML's.  Note the
    coefficient may itself be an arbitrary expression, as in ``(k+1)`x``.
    """

    count: Expr
    value: Expr
    position: int = 0


@dataclass(frozen=True)
class EmptyMultiset(Expr):
    """The literal ``empty`` -- the multiset with no tokens."""

    position: int = 0


@dataclass(frozen=True)
class Delay(Expr):
    """``e @+ d`` -- an arc expression with a time delay.

    Only legal at the top level of an arc inscription on an output arc into a
    timed place.  ``e`` yields the tokens, ``d`` yields the delay to add to the
    current model clock to get their time stamp.
    """

    base: Expr
    delay: Expr
    position: int = 0


# ===========================================================================
# Patterns
# ===========================================================================
class Pattern:
    """Base class for pattern nodes."""

    position: int = 0


@dataclass(frozen=True)
class PWildcard(Pattern):
    """``_`` -- matches anything, binds nothing."""

    position: int = 0


@dataclass(frozen=True)
class PVar(Pattern):
    """``x`` -- matches anything and binds it to ``x``."""

    name: str
    position: int = 0


@dataclass(frozen=True)
class PLiteral(Pattern):
    """A constant pattern: matches only that exact value."""

    value: Any
    position: int = 0


@dataclass(frozen=True)
class PTuple(Pattern):
    """``(p1, p2)`` -- matches a tuple of the same arity, component-wise."""

    items: tuple[Pattern, ...]
    position: int = 0


@dataclass(frozen=True)
class PList(Pattern):
    """``[p1, p2]`` -- matches a list of exactly that length."""

    items: tuple[Pattern, ...]
    position: int = 0


@dataclass(frozen=True)
class PRecord(Pattern):
    """``{name = p, ...}`` -- matches a record.

    ``open_ended`` records the ``...`` ellipsis, which lets a pattern mention
    only some of the fields.
    """

    fields: tuple[tuple[str, Pattern], ...]
    open_ended: bool = False
    position: int = 0


@dataclass(frozen=True)
class PCons(Pattern):
    """``h :: t`` -- matches a non-empty list, splitting head from tail."""

    head: Pattern
    tail: Pattern
    position: int = 0


@dataclass(frozen=True)
class PConstructor(Pattern):
    """``Car p`` or a bare ``red`` -- matches a union/enumeration value.

    ``argument`` is ``None`` for nullary constructors.
    """

    name: str
    argument: Pattern | None = None
    position: int = 0


@dataclass(frozen=True)
class PAs(Pattern):
    """``x as p`` -- match ``p`` but also bind the whole value to ``x``."""

    name: str
    pattern: Pattern
    position: int = 0


# ===========================================================================
# Declarations
# ===========================================================================
class Decl:
    """Base class for declaration nodes."""

    position: int = 0


@dataclass(frozen=True)
class ValDecl(Decl):
    """``val p = e`` -- evaluate ``e`` and bind whatever ``p`` destructures."""

    pattern: Pattern
    expression: Expr
    position: int = 0


@dataclass(frozen=True)
class FunDecl(Decl):
    """``fun f p1 = e1 | f p2 = e2`` -- a (possibly recursive) function.

    ``clauses`` holds one entry per bar-separated alternative; each entry is a
    tuple of argument patterns (more than one for a curried function) and the
    body.  Recursion works because the evaluator binds ``f`` in the closure's
    own environment before the body is ever run.
    """

    name: str
    clauses: tuple[tuple[tuple[Pattern, ...], Expr], ...] = field(default=())
    position: int = 0
