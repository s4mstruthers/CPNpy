"""The colour set system: CPN's type system.

A *colour set* in CPN terminology is a type.  Every place is annotated with
one, and a token in that place must carry a value belonging to it.  CPN Tools
offers a fixed catalogue of colour set forms, and this module implements them
one class each.

The catalogue, with the CPN Tools declaration syntax we parse:

    ==================================  ===========================
    Declaration                          Class
    ==================================  ===========================
    ``colset U = unit;``                 :class:`UnitColourSet`
    ``colset B = bool;``                 :class:`BoolColourSet`
    ``colset I = int;``                  :class:`IntColourSet`
    ``colset I = int with 1..10;``        :class:`IntColourSet` (ranged)
    ``colset R = real;``                 :class:`RealColourSet`
    ``colset S = string;``               :class:`StringColourSet`
    ``colset E = with a | b | c;``        :class:`EnumColourSet`
    ``colset X = index i with 1..5;``     :class:`IndexColourSet`
    ``colset P = product A * B;``         :class:`ProductColourSet`
    ``colset Rc = record f:A * g:B;``     :class:`RecordColourSet`
    ``colset L = list A;``                :class:`ListColourSet`
    ``colset Un = union C1:A + C2:B;``    :class:`UnionColourSet`
    ``colset Sub = subset A by pred;``    :class:`SubsetColourSet`
    ``colset Al = A;``                    :class:`AliasColourSet`
    ==================================  ===========================

Any of these may carry the ``timed`` keyword, which does not change the set of
values -- it changes how the *place* stores them (see
:class:`~cpnpy.ml.multiset.TimedMultiset`).

Two operations matter for the rest of the system:

``contains(value)``
    Type checking.  Called when a place's initial marking is evaluated and
    whenever a binding assigns a value to a typed variable.

``members()``
    Enumeration.  The binder falls back to enumerating a variable's colour set
    when the variable cannot be determined from the input tokens (for example
    a variable that appears only on an output arc).  Infinite colour sets raise
    :class:`InfiniteColourSetError`, which the binder turns into a clear
    "cannot enumerate INT, constrain this variable" message rather than hanging.
"""

from __future__ import annotations

import itertools
from typing import Any, Callable, Iterator, Sequence

from .errors import CPNMLError
from .values import UNIT, Constructor, MLList, Record, Unit, format_value


class InfiniteColourSetError(CPNMLError):
    """Raised by :meth:`ColourSet.members` on a colour set that cannot be listed."""


class ColourSet:
    """Abstract base class for all colour sets."""

    #: Whether values of this colour set carry time stamps in a place.
    timed: bool

    def __init__(self, name: str, timed: bool = False) -> None:
        self.name = name
        self.timed = timed

    # -- to be provided by subclasses ---------------------------------------
    def contains(self, value: Any) -> bool:
        """Is ``value`` a legal member of this colour set?"""
        raise NotImplementedError

    def members(self) -> Iterator[Any]:
        """Yield every member.  Raises for infinite colour sets."""
        raise InfiniteColourSetError(
            f"colour set '{self.name}' has infinitely many members and cannot be enumerated"
        )

    def is_finite(self) -> bool:
        return False

    # -- shared helpers ------------------------------------------------------
    def check(self, value: Any) -> Any:
        """Return ``value`` if it belongs here, else raise a typing error."""
        if not self.contains(value):
            raise CPNMLError(
                f"value {format_value(value)} is not a member of colour set '{self.name}'"
            )
        return value

    def size(self) -> int:
        """Number of members; only meaningful when :meth:`is_finite`."""
        return sum(1 for _ in self.members())

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name}{' timed' if self.timed else ''}>"


# ---------------------------------------------------------------------------
# Simple (atomic) colour sets
# ---------------------------------------------------------------------------
class UnitColourSet(ColourSet):
    """``colset U = unit;`` -- exactly one value, ``()``.

    ``unit with e`` renames that single value to the identifier ``e``; we keep
    the alias for printing but the value is still :data:`~cpnpy.ml.values.UNIT`.
    """

    def __init__(self, name: str, timed: bool = False, alias: str | None = None) -> None:
        super().__init__(name, timed)
        self.alias = alias

    def contains(self, value: Any) -> bool:
        return isinstance(value, Unit)

    def members(self) -> Iterator[Any]:
        yield UNIT

    def is_finite(self) -> bool:
        return True


class BoolColourSet(ColourSet):
    """``colset B = bool;`` -- ``{false, true}``."""

    def __init__(self, name: str, timed: bool = False,
                 false_alias: str | None = None, true_alias: str | None = None) -> None:
        super().__init__(name, timed)
        self.false_alias = false_alias
        self.true_alias = true_alias

    def contains(self, value: Any) -> bool:
        return isinstance(value, bool)

    def members(self) -> Iterator[Any]:
        yield False
        yield True

    def is_finite(self) -> bool:
        return True


class IntColourSet(ColourSet):
    """``colset I = int;`` or ``colset I = int with 1..10;``.

    Without a range this is infinite (and so not enumerable).  With a range it
    behaves like a finite interval, which is the usual way modellers make a
    variable enumerable.
    """

    def __init__(self, name: str, timed: bool = False,
                 low: int | None = None, high: int | None = None) -> None:
        super().__init__(name, timed)
        self.low = low
        self.high = high

    def contains(self, value: Any) -> bool:
        # ``bool`` is a subclass of ``int`` in Python but is a different colour
        # set in CPN, so exclude it explicitly.
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        if self.low is not None and value < self.low:
            return False
        if self.high is not None and value > self.high:
            return False
        return True

    def is_finite(self) -> bool:
        return self.low is not None and self.high is not None

    def members(self) -> Iterator[Any]:
        if not self.is_finite():
            return super().members()
        return iter(range(self.low, self.high + 1))  # type: ignore[arg-type]


class IntInfColourSet(IntColourSet):
    """``colset II = intinf;`` -- arbitrary precision integers.

    Python integers are already arbitrary precision, so this differs from
    :class:`IntColourSet` only in name.  It exists so that round-tripping a
    ``.cpn`` file preserves the declaration the modeller wrote.
    """


class RealColourSet(ColourSet):
    """``colset R = real;`` -- floating point numbers, never enumerable."""

    def __init__(self, name: str, timed: bool = False,
                 low: float | None = None, high: float | None = None) -> None:
        super().__init__(name, timed)
        self.low = low
        self.high = high

    def contains(self, value: Any) -> bool:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        value = float(value)
        if self.low is not None and value < self.low:
            return False
        if self.high is not None and value > self.high:
            return False
        return True


class StringColourSet(ColourSet):
    """``colset S = string;``, optionally constrained.

    CPN Tools allows ``string with "a".."z"`` (restrict the character set) and
    ``and 1..8`` (restrict the length).  Both are supported here.
    """

    def __init__(self, name: str, timed: bool = False,
                 char_low: str | None = None, char_high: str | None = None,
                 length_low: int | None = None, length_high: int | None = None) -> None:
        super().__init__(name, timed)
        self.char_low = char_low
        self.char_high = char_high
        self.length_low = length_low
        self.length_high = length_high

    def contains(self, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        if self.length_low is not None and len(value) < self.length_low:
            return False
        if self.length_high is not None and len(value) > self.length_high:
            return False
        if self.char_low is not None or self.char_high is not None:
            low = self.char_low or "\x00"
            high = self.char_high or "\U0010ffff"
            if any(not (low <= ch <= high) for ch in value):
                return False
        return True

    def is_finite(self) -> bool:
        # Finite only when both the alphabet and the maximum length are bounded.
        return (
            self.char_low is not None
            and self.char_high is not None
            and self.length_high is not None
        )

    def members(self) -> Iterator[Any]:
        if not self.is_finite():
            return super().members()
        alphabet = [chr(c) for c in range(ord(self.char_low), ord(self.char_high) + 1)]  # type: ignore[arg-type]
        low = self.length_low or 0
        for length in range(low, self.length_high + 1):  # type: ignore[arg-type]
            for combination in itertools.product(alphabet, repeat=length):
                yield "".join(combination)


class EnumColourSet(ColourSet):
    """``colset E = with red | green | blue;``.

    Members are :class:`~cpnpy.ml.values.Constructor` values without arguments.
    The identifiers are also injected into the global evaluation environment as
    constants, so an inscription can just write ``red``.
    """

    def __init__(self, name: str, constants: Sequence[str], timed: bool = False) -> None:
        super().__init__(name, timed)
        self.constants = tuple(constants)

    def contains(self, value: Any) -> bool:
        return (
            isinstance(value, Constructor)
            and not value.has_argument
            and value.name in self.constants
        )

    def members(self) -> Iterator[Any]:
        for constant in self.constants:
            yield Constructor(constant)

    def is_finite(self) -> bool:
        return True


class IndexColourSet(ColourSet):
    """``colset X = index proc with 1..5;``.

    Values are constructors carrying an integer, printed ``proc(1)``.  This is
    CPN Tools' idiomatic way of naming a finite family of otherwise identical
    entities (processes, resources, sites).
    """

    def __init__(self, name: str, tag: str, low: int, high: int, timed: bool = False) -> None:
        super().__init__(name, timed)
        self.tag = tag
        self.low = low
        self.high = high

    def contains(self, value: Any) -> bool:
        return (
            isinstance(value, Constructor)
            and value.name == self.tag
            and value.has_argument
            and isinstance(value.argument, int)
            and not isinstance(value.argument, bool)
            and self.low <= value.argument <= self.high
        )

    def members(self) -> Iterator[Any]:
        for index in range(self.low, self.high + 1):
            yield Constructor(self.tag, index)

    def is_finite(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Compound colour sets
# ---------------------------------------------------------------------------
class ProductColourSet(ColourSet):
    """``colset P = product A * B * C;`` -- Cartesian product, values are tuples."""

    def __init__(self, name: str, components: Sequence[ColourSet], timed: bool = False) -> None:
        super().__init__(name, timed)
        self.components = tuple(components)

    def contains(self, value: Any) -> bool:
        return (
            isinstance(value, tuple)
            and len(value) == len(self.components)
            and all(cs.contains(v) for cs, v in zip(self.components, value))
        )

    def is_finite(self) -> bool:
        return all(cs.is_finite() for cs in self.components)

    def members(self) -> Iterator[Any]:
        if not self.is_finite():
            return super().members()
        # ``itertools.product`` materialises each component, which is fine
        # because we have already established that each one is finite.
        return itertools.product(*(list(cs.members()) for cs in self.components))


class RecordColourSet(ColourSet):
    """``colset R = record name:STRING * age:INT;`` -- labelled product."""

    def __init__(self, name: str, fields: Sequence[tuple[str, ColourSet]], timed: bool = False) -> None:
        super().__init__(name, timed)
        self.fields = tuple(fields)

    def contains(self, value: Any) -> bool:
        if not isinstance(value, Record):
            return False
        if value.names() != tuple(n for n, _ in self.fields):
            return False
        return all(cs.contains(v) for (_, cs), (_, v) in zip(self.fields, value.fields))

    def is_finite(self) -> bool:
        return all(cs.is_finite() for _, cs in self.fields)

    def members(self) -> Iterator[Any]:
        if not self.is_finite():
            return super().members()
        names = [n for n, _ in self.fields]
        for combination in itertools.product(*(list(cs.members()) for _, cs in self.fields)):
            yield Record(tuple(zip(names, combination)))


class ListColourSet(ColourSet):
    """``colset L = list A;`` or ``list A with 0..3;`` (bounded length).

    Unbounded lists are infinite even over a finite element colour set, so
    enumeration requires the ``with`` bound.
    """

    def __init__(self, name: str, element: ColourSet, timed: bool = False,
                 length_low: int | None = None, length_high: int | None = None) -> None:
        super().__init__(name, timed)
        self.element = element
        self.length_low = length_low
        self.length_high = length_high

    def contains(self, value: Any) -> bool:
        if not isinstance(value, MLList):
            return False
        if self.length_low is not None and len(value) < self.length_low:
            return False
        if self.length_high is not None and len(value) > self.length_high:
            return False
        return all(self.element.contains(v) for v in value)

    def is_finite(self) -> bool:
        return self.element.is_finite() and self.length_high is not None

    def members(self) -> Iterator[Any]:
        if not self.is_finite():
            return super().members()
        element_values = list(self.element.members())
        low = self.length_low or 0
        for length in range(low, self.length_high + 1):  # type: ignore[arg-type]
            for combination in itertools.product(element_values, repeat=length):
                yield MLList(combination)


class UnionColourSet(ColourSet):
    """``colset U = union Car:CARS + Bike:BIKES + Walk;`` -- tagged sum.

    A constructor may be *nullary* (``Walk`` above), in which case its member is
    a bare :class:`~cpnpy.ml.values.Constructor` with no argument, exactly like
    an enumeration constant.
    """

    def __init__(self, name: str, variants: Sequence[tuple[str, ColourSet | None]],
                 timed: bool = False) -> None:
        super().__init__(name, timed)
        self.variants = tuple(variants)

    def _variant(self, tag: str) -> tuple[str, ColourSet | None] | None:
        for variant in self.variants:
            if variant[0] == tag:
                return variant
        return None

    def contains(self, value: Any) -> bool:
        if not isinstance(value, Constructor):
            return False
        variant = self._variant(value.name)
        if variant is None:
            return False
        _, payload_cs = variant
        if payload_cs is None:
            return not value.has_argument
        return value.has_argument and payload_cs.contains(value.argument)

    def is_finite(self) -> bool:
        return all(cs is None or cs.is_finite() for _, cs in self.variants)

    def members(self) -> Iterator[Any]:
        if not self.is_finite():
            return super().members()
        for tag, payload_cs in self.variants:
            if payload_cs is None:
                yield Constructor(tag)
            else:
                for payload in payload_cs.members():
                    yield Constructor(tag, payload)


class SubsetColourSet(ColourSet):
    """``colset S = subset A by pred;`` -- members of ``A`` satisfying a predicate.

    The predicate is supplied as a Python callable by the declaration compiler,
    which wraps the user's CPN ML function.  Enumeration filters the base set,
    so a subset of an infinite colour set stays non-enumerable.
    """

    def __init__(self, name: str, base: ColourSet, predicate: Callable[[Any], bool],
                 timed: bool = False, predicate_source: str = "",
                 members: Sequence[Any] | None = None) -> None:
        super().__init__(name, timed)
        self.base = base
        self.predicate = predicate
        # Kept so that the writer can reproduce the original declaration text.
        self.predicate_source = predicate_source
        #: ``subset A with [v1, v2]``: the listed values, in order.  Finite
        #: even when ``A`` is not.
        self.listed = list(members) if members is not None else None

    def contains(self, value: Any) -> bool:
        return self.base.contains(value) and bool(self.predicate(value))

    def is_finite(self) -> bool:
        return self.listed is not None or self.base.is_finite()

    def members(self) -> Iterator[Any]:
        if self.listed is not None:
            yield from self.listed
            return
        for value in self.base.members():
            if self.predicate(value):
                yield value


class AliasColourSet(ColourSet):
    """``colset MyInt = INT;`` -- a new name for an existing colour set.

    Delegates every operation to the target.  We keep the indirection rather
    than collapsing it so that the declaration survives a save/load round trip
    and so that error messages can name the alias the modeller actually used.
    """

    def __init__(self, name: str, target: ColourSet, timed: bool | None = None) -> None:
        super().__init__(name, target.timed if timed is None else timed)
        self.target = target

    def contains(self, value: Any) -> bool:
        return self.target.contains(value)

    def is_finite(self) -> bool:
        return self.target.is_finite()

    def members(self) -> Iterator[Any]:
        return self.target.members()


# ---------------------------------------------------------------------------
# The standard colour sets that CPN Tools predeclares
# ---------------------------------------------------------------------------
def standard_colour_sets() -> dict[str, ColourSet]:
    """The colour sets available in every model without being declared.

    CPN Tools makes ``UNIT``, ``BOOL``, ``INT``, ``INTINF``, ``REAL`` and
    ``STRING`` available implicitly.  We create a fresh dictionary per call so
    that two models can never share (and accidentally mutate) the same objects.
    """
    return {
        "UNIT": UnitColourSet("UNIT"),
        "BOOL": BoolColourSet("BOOL"),
        "INT": IntColourSet("INT"),
        "INTINF": IntInfColourSet("INTINF"),
        "REAL": RealColourSet("REAL"),
        "STRING": StringColourSet("STRING"),
    }
