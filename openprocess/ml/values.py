"""Runtime values of the CPN ML subset.

Design decisions worth stating up front, because everything else depends on
them:

1. **Values must be hashable.**  A marking is a multiset of values, and we
   implement multisets with dictionaries.  So every value we can put in a place
   has to be usable as a dict key.  That rules out Python ``list`` and ``dict``
   as representations and is why :class:`MLList` and :class:`Record` exist.

2. **Values must be totally ordered.**  State space analysis, canonical
   printing of markings, and deterministic test output all need a stable order
   over values of *different* shapes.  Python will happily compare two ints but
   refuses to compare an int with a string, so we define our own ordering via
   :func:`sort_key`, which prefixes a type rank.

3. **We reuse Python primitives where the semantics coincide.**  CPN ML's
   ``INT``, ``BOOL``, ``STRING`` and ``REAL`` map onto Python ``int``, ``bool``,
   ``str`` and ``float`` exactly.  Only the constructs Python lacks (ML lists
   as values, records, and union constructors) get wrapper classes.

Mapping from CPN ML to this module:

    ==================  ==========================================
    CPN ML              Python representation
    ==================  ==========================================
    unit ``()``         :data:`UNIT` (the single ``Unit`` instance)
    ``true`` / ``false``  ``bool``
    ``3``               ``int``
    ``3.0``             ``float``
    ``"abc"``           ``str``
    ``(a, b)``          ``tuple``           (product colour set)
    ``[a, b]``          :class:`MLList`
    ``{f=a, g=b}``      :class:`Record`
    ``Cons(x)``         :class:`Constructor` (union colour set / enum)
    ==================  ==========================================
"""

from __future__ import annotations

from typing import Any, Iterable, Iterator


# ---------------------------------------------------------------------------
# unit
# ---------------------------------------------------------------------------
class Unit:
    """The single value ``()`` of the ``UNIT`` colour set.

    Implemented as a singleton so that ``UNIT is UNIT`` and equality is cheap.
    In CPN models the unit colour set is used for tokens that carry no data --
    i.e. exactly the tokens of a classical place/transition Petri net.
    """

    _instance: "Unit | None" = None

    def __new__(cls) -> "Unit":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "()"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Unit)

    def __hash__(self) -> int:
        return hash("()")


UNIT = Unit()


# ---------------------------------------------------------------------------
# lists
# ---------------------------------------------------------------------------
class MLList:
    """An immutable CPN ML list value, e.g. ``[1, 2, 3]``.

    We cannot use a Python ``tuple`` because a tuple already represents a
    *product* value, and ``(1, 2)`` and ``[1, 2]`` are different CPN values
    belonging to different colour sets.  Backed by a tuple internally so that
    hashing and equality come for free.
    """

    __slots__ = ("items",)

    def __init__(self, items: Iterable[Any] = ()) -> None:
        self.items: tuple[Any, ...] = tuple(items)

    # -- sequence protocol ---------------------------------------------------
    def __iter__(self) -> Iterator[Any]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> Any:
        return self.items[index]

    # -- value protocol ------------------------------------------------------
    def __eq__(self, other: object) -> bool:
        return isinstance(other, MLList) and self.items == other.items

    def __hash__(self) -> int:
        return hash(("MLList", self.items))

    def __repr__(self) -> str:
        return "[" + ",".join(format_value(x) for x in self.items) + "]"

    # -- ML operations -------------------------------------------------------
    def cons(self, head: Any) -> "MLList":
        """``head :: self`` -- prepend, returning a new list."""
        return MLList((head,) + self.items)

    def append(self, other: "MLList") -> "MLList":
        """``self ^^ other`` / ``self @ other`` -- concatenation."""
        return MLList(self.items + other.items)


# ---------------------------------------------------------------------------
# records
# ---------------------------------------------------------------------------
class Record:
    """An immutable CPN ML record value, e.g. ``{name = "a", age = 3}``.

    Field order is preserved as given by the colour set declaration, because
    CPN Tools prints records in declaration order and we want byte-identical
    round-trips.  Equality and hashing ignore order only in the sense that two
    records with the same field/value pairs in the same declared order are
    equal -- CPN ML has no notion of two records with permuted fields, so this
    is not a limitation.
    """

    __slots__ = ("fields",)

    def __init__(self, fields: Iterable[tuple[str, Any]] | dict[str, Any]) -> None:
        if isinstance(fields, dict):
            fields = tuple(fields.items())
        self.fields: tuple[tuple[str, Any], ...] = tuple(fields)

    def get(self, name: str) -> Any:
        """Field selection, i.e. ML's ``#name record``."""
        for field_name, value in self.fields:
            if field_name == name:
                return value
        raise KeyError(name)

    def names(self) -> tuple[str, ...]:
        return tuple(n for n, _ in self.fields)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Record) and self.fields == other.fields

    def __hash__(self) -> int:
        return hash(("Record", self.fields))

    def __repr__(self) -> str:
        inner = ",".join(f"{n}={format_value(v)}" for n, v in self.fields)
        return "{" + inner + "}"


# ---------------------------------------------------------------------------
# union / enumeration constructors
# ---------------------------------------------------------------------------
class Constructor:
    """A tagged value from a union or enumeration colour set.

    Two shapes exist and both are represented here:

    * ``colset E = with red | green | blue;`` -- an *enumeration*.  Its values
      are constructors with ``argument is None``: ``Constructor("red")``.
    * ``colset U = union Car:CARS + Bike:BIKES;`` -- a *union*.  Its values
      carry a payload: ``Constructor("Car", some_car_value)``.

    Keeping them in one class means pattern matching, printing and ordering
    only have to handle one case.
    """

    __slots__ = ("name", "argument", "_has_arg")

    # Sentinel distinguishing "no argument at all" (enumeration constant) from
    # "argument that happens to be unit".
    _NO_ARG = object()

    def __init__(self, name: str, argument: Any = _NO_ARG) -> None:
        self.name = name
        self.argument = None if argument is Constructor._NO_ARG else argument
        self._has_arg = argument is not Constructor._NO_ARG

    @property
    def has_argument(self) -> bool:
        return self._has_arg

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Constructor)
            and self.name == other.name
            and self._has_arg == other._has_arg
            and self.argument == other.argument
        )

    def __hash__(self) -> int:
        return hash(("Constructor", self.name, self._has_arg, self.argument))

    def __repr__(self) -> str:
        if not self._has_arg:
            return self.name
        return f"{self.name}({format_value(self.argument)})"


# ---------------------------------------------------------------------------
# ordering and printing
# ---------------------------------------------------------------------------
# Rank of each value shape.  Values of different shapes are ordered by rank
# first, which gives us a total order over the whole value universe.  The
# specific numbers are arbitrary but must never change, or saved state spaces
# would reorder between versions.
_TYPE_RANK: dict[type, int] = {
    Unit: 0,
    bool: 1,
    int: 2,
    float: 3,
    str: 4,
    Constructor: 5,
    tuple: 6,
    MLList: 7,
    Record: 8,
}


_SORT_KEYS: dict = {}


def sort_key(value: Any) -> tuple:
    """Memoised :func:`_sort_key` -- the simulator sorts the same token
    values over and over, and building nested key tuples dominated its run
    time.  Values are immutable and hashable, so caching is safe; the cache
    is bounded so a long run cannot grow it without limit."""
    try:
        return _SORT_KEYS[value]
    except KeyError:
        pass
    except TypeError:                      # an unhashable value: compute directly
        return _sort_key(value)
    key = _sort_key(value)
    if len(_SORT_KEYS) > 200_000:
        _SORT_KEYS.clear()
    _SORT_KEYS[value] = key
    return key


def _sort_key(value: Any) -> tuple:
    """Return a tuple that sorts values of *any* shape into a total order.

    Used for canonical marking output and for deterministic iteration during
    state space exploration.  The recursion mirrors the value structure, so
    ``sort_key`` on nested values is itself nested and compares element-wise,
    exactly like ML's structural comparison.
    """
    # ``bool`` must be tested before ``int`` because ``bool`` subclasses ``int``.
    if isinstance(value, Unit):
        return (_TYPE_RANK[Unit],)
    if isinstance(value, bool):
        return (_TYPE_RANK[bool], value)
    if isinstance(value, int):
        return (_TYPE_RANK[int], value)
    if isinstance(value, float):
        return (_TYPE_RANK[float], value)
    if isinstance(value, str):
        return (_TYPE_RANK[str], value)
    if isinstance(value, Constructor):
        arg = sort_key(value.argument) if value.has_argument else ()
        return (_TYPE_RANK[Constructor], value.name, arg)
    if isinstance(value, tuple):
        return (_TYPE_RANK[tuple], tuple(sort_key(v) for v in value))
    if isinstance(value, MLList):
        return (_TYPE_RANK[MLList], tuple(sort_key(v) for v in value.items))
    if isinstance(value, Record):
        return (
            _TYPE_RANK[Record],
            tuple((n, sort_key(v)) for n, v in value.fields),
        )
    # Anything else is a bug in the evaluator, not a user error.
    raise AssertionError(f"value of unsupported shape: {value!r}")


def format_value(value: Any) -> str:
    """Render a value the way CPN Tools would print it.

    Notable conventions we follow deliberately:

    * strings are double-quoted;
    * reals always show a decimal point (``3.0``, not ``3``) so that they are
      visually distinct from integers;
    * negative numbers use ML's ``~`` prefix, not ``-`` (``~3``), because that
      is what CPN Tools writes and what our lexer reads back.
    """
    if isinstance(value, Unit):
        return "()"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return f"~{-value}" if value < 0 else str(value)
    if isinstance(value, float):
        text = repr(value)
        if value < 0:
            text = "~" + repr(-value)
        return text
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, tuple):
        return "(" + ",".join(format_value(v) for v in value) + ")"
    # MLList, Record and Constructor already format themselves in __repr__.
    return repr(value)
