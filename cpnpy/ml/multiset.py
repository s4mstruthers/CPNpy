"""Multiset (bag) algebra -- the arithmetic that CPN markings are made of.

Why multisets are the central data structure
--------------------------------------------
In a Coloured Petri Net a place does not hold "3 tokens"; it holds a *multiset
of coloured tokens*, for example ``2`"a" ++ 1`"b"``.  Arc expressions evaluate
to multisets, and the firing rule is stated entirely in multiset terms:

    a transition ``t`` is enabled in marking ``M`` under binding ``b`` iff
    for every input place ``p``:   E(p,t)<b>  <=  M(p)

    firing produces               M'(p) = (M(p) -- E(p,t)<b>) ++ E(t,p)<b>

So if the multiset operations ``<=``, ``--`` and ``++`` are right, the
simulator is a very short piece of code.  That is the whole reason this module
is separate and heavily tested.

Two classes live here:

* :class:`Multiset` -- untimed.  A map from value to a strictly positive count.
* :class:`TimedMultiset` -- timed.  A map from ``(value, timestamp)`` to a
  count.  Used only for places whose colour set is declared ``timed``.

Both are treated as **immutable**: every operator returns a new object.  This
matters for state space analysis, where markings are used as dictionary keys
and must never mutate after being stored.
"""

from __future__ import annotations

from typing import Any, Iterable, Iterator

from .errors import EvalError
from .values import format_value, sort_key


class Multiset:
    """An immutable multiset of CPN values.

    Internally a ``dict`` from value to count.  We maintain one invariant that
    the rest of the code relies on:

        **no key ever maps to a count of zero.**

    Keeping zero entries out means equality is just dict equality, the support
    is just ``keys()``, and hashing is straightforward.
    """

    __slots__ = ("_counts", "_hash")

    def __init__(self, counts: dict[Any, int] | Iterable[tuple[Any, int]] | None = None) -> None:
        cleaned: dict[Any, int] = {}
        if counts is not None:
            items = counts.items() if isinstance(counts, dict) else counts
            for value, count in items:
                if count < 0:
                    raise EvalError(
                        f"multiset coefficient must not be negative, got {count} "
                        f"for {format_value(value)}"
                    )
                if count:
                    cleaned[value] = cleaned.get(value, 0) + count
        self._counts = cleaned
        self._hash: int | None = None

    # -- constructors --------------------------------------------------------
    @classmethod
    def _clean(cls, counts: dict[Any, int]) -> "Multiset":
        """Wrap a dict already known to hold only positive counts.

        Skips the validation loop of ``__init__``: the algebra below builds
        clean dicts itself, and multiset arithmetic is the simulator's (and
        the state space tool's) hottest code.
        """
        result = cls.__new__(cls)
        result._counts = counts
        result._hash = None
        return result

    @staticmethod
    def empty() -> "Multiset":
        """The empty multiset, written ``empty`` in CPN ML."""
        return Multiset()

    @staticmethod
    def singleton(value: Any, count: int = 1) -> "Multiset":
        """``count`value`` -- ``count`` copies of one value."""
        return Multiset({value: count})

    @staticmethod
    def from_values(values: Iterable[Any]) -> "Multiset":
        """Build from a plain iterable, summing duplicates."""
        counts: dict[Any, int] = {}
        for value in values:
            counts[value] = counts.get(value, 0) + 1
        return Multiset(counts)

    # -- inspection ----------------------------------------------------------
    def count(self, value: Any) -> int:
        """Coefficient of ``value``; zero if absent."""
        return self._counts.get(value, 0)

    def support(self) -> list[Any]:
        """Distinct values present, in canonical (sorted) order."""
        return sorted(self._counts, key=sort_key)

    def size(self) -> int:
        """Total number of tokens, counting multiplicity."""
        return sum(self._counts.values())

    def is_empty(self) -> bool:
        return not self._counts

    def __bool__(self) -> bool:
        return bool(self._counts)

    def __len__(self) -> int:
        return self.size()

    def __contains__(self, value: Any) -> bool:
        return value in self._counts

    def items(self) -> Iterator[tuple[Any, int]]:
        """Iterate ``(value, count)`` pairs in canonical order."""
        for value in self.support():
            yield value, self._counts[value]

    def expand(self) -> Iterator[Any]:
        """Iterate individual tokens, repeating values by multiplicity.

        Used by the binder, which needs to pick concrete tokens out of a place.
        """
        for value, count in self.items():
            for _ in range(count):
                yield value

    # -- algebra -------------------------------------------------------------
    def __add__(self, other: "Multiset") -> "Multiset":
        """``++`` -- multiset union (pointwise sum of coefficients)."""
        if not isinstance(other, Multiset):
            return NotImplemented
        result = dict(self._counts)
        for value, count in other._counts.items():
            result[value] = result.get(value, 0) + count
        return Multiset._clean(result)

    def __sub__(self, other: "Multiset") -> "Multiset":
        """``--`` -- multiset difference, truncated at zero.

        CPN Tools defines ``(m1 -- m2)(c) = max(0, m1(c) - m2(c))``.  The
        simulator never relies on the truncation, because it checks
        ``other <= self`` first, but user inscriptions may.
        """
        if not isinstance(other, Multiset):
            return NotImplemented
        result = dict(self._counts)
        for value, count in other._counts.items():
            remaining = result.get(value, 0) - count
            if remaining > 0:
                result[value] = remaining
            else:
                result.pop(value, None)
        return Multiset._clean(result)

    def __mul__(self, factor: int) -> "Multiset":
        """Scalar multiplication: every coefficient times ``factor``."""
        if not isinstance(factor, int):
            return NotImplemented
        if factor < 0:
            raise EvalError("cannot multiply a multiset by a negative number")
        if factor == 0:
            return Multiset()
        return Multiset._clean({v: c * factor for v, c in self._counts.items()})

    __rmul__ = __mul__

    def __le__(self, other: "Multiset") -> bool:
        """Multiset inclusion -- **this is the enabling test**.

        ``self <= other`` iff every value occurs at least as often in ``other``
        as it does in ``self``.  Note this is a *partial* order: two multisets
        can be incomparable, so ``not (a <= b)`` does not imply ``b <= a``.
        """
        if not isinstance(other, Multiset):
            return NotImplemented
        return all(count <= other._counts.get(value, 0) for value, count in self._counts.items())

    def __ge__(self, other: "Multiset") -> bool:
        if not isinstance(other, Multiset):
            return NotImplemented
        return other <= self

    def __lt__(self, other: "Multiset") -> bool:
        return self <= other and self != other

    def __gt__(self, other: "Multiset") -> bool:
        return other < self

    # -- identity ------------------------------------------------------------
    def __eq__(self, other: object) -> bool:
        return isinstance(other, Multiset) and self._counts == other._counts

    def __hash__(self) -> int:
        # Cached because markings are hashed once per state space node visit.
        if self._hash is None:
            self._hash = hash(frozenset(self._counts.items()))
        return self._hash

    # -- printing ------------------------------------------------------------
    def __repr__(self) -> str:
        """CPN Tools syntax: ``2`"a"++1`"b"``; the empty multiset is ``empty``."""
        if not self._counts:
            return "empty"
        return "++".join(f"{count}`{format_value(value)}" for value, count in self.items())

    __str__ = __repr__


class TimedMultiset:
    """A multiset of *timestamped* tokens, for places with a timed colour set.

    In a timed CPN each token carries a time stamp saying when it becomes
    available.  A transition may only consume tokens whose stamp is less than
    or equal to the current model time.  We therefore key the underlying dict
    on ``(value, timestamp)`` pairs and expose two extra operations that the
    untimed class does not need:

    * :meth:`available_at` -- project down to the untimed multiset of tokens
      that are ready at a given clock value;
    * :meth:`earliest_time` -- the smallest timestamp present, which the
      simulator uses to decide how far to advance the clock when no transition
      is enabled now.
    """

    __slots__ = ("_counts", "_hash")

    def __init__(self, counts: dict[tuple[Any, int], int] | Iterable[tuple[tuple[Any, int], int]] | None = None) -> None:
        cleaned: dict[tuple[Any, int], int] = {}
        if counts is not None:
            items = counts.items() if isinstance(counts, dict) else counts
            for key, count in items:
                if count < 0:
                    raise EvalError("timed multiset coefficient must not be negative")
                if count:
                    cleaned[key] = cleaned.get(key, 0) + count
        self._counts = cleaned
        self._hash: int | None = None

    @staticmethod
    def empty() -> "TimedMultiset":
        return TimedMultiset()

    @staticmethod
    def from_multiset(multiset: Multiset, timestamp: int) -> "TimedMultiset":
        """Stamp every token of an untimed multiset with the same time.

        This is how an output arc result becomes tokens in a timed place: the
        arc yields a plain multiset, and the arc's ``@+`` delay expression
        (plus the current clock) supplies the stamp.
        """
        return TimedMultiset({(value, timestamp): count for value, count in multiset.items()})

    # -- inspection ----------------------------------------------------------
    def size(self) -> int:
        return sum(self._counts.values())

    def is_empty(self) -> bool:
        return not self._counts

    def __bool__(self) -> bool:
        return bool(self._counts)

    def items(self) -> Iterator[tuple[Any, int, int]]:
        """Iterate ``(value, timestamp, count)`` in canonical order."""
        for value, timestamp in sorted(self._counts, key=lambda k: (sort_key(k[0]), k[1])):
            yield value, timestamp, self._counts[(value, timestamp)]

    def available_at(self, clock: int) -> Multiset:
        """Untimed multiset of the tokens whose stamp has been reached."""
        ready: dict[Any, int] = {}
        for (value, timestamp), count in self._counts.items():
            if timestamp <= clock:
                ready[value] = ready.get(value, 0) + count
        return Multiset(ready)

    def earliest_time(self) -> int | None:
        """Smallest timestamp in the place, or ``None`` if the place is empty."""
        if not self._counts:
            return None
        return min(timestamp for _, timestamp in self._counts)

    def next_time_after(self, clock: int) -> int | None:
        """Smallest timestamp strictly greater than ``clock``.

        The simulator asks every place this question to compute the next
        interesting model time when nothing is enabled at the current one.
        """
        future = [t for _, t in self._counts if t > clock]
        return min(future) if future else None

    # -- algebra -------------------------------------------------------------
    def add(self, other: "TimedMultiset") -> "TimedMultiset":
        result = dict(self._counts)
        for key, count in other._counts.items():
            result[key] = result.get(key, 0) + count
        return TimedMultiset(result)

    def remove_available(self, wanted: Multiset, clock: int) -> "TimedMultiset":
        """Consume ``wanted`` tokens, taking the *oldest* available ones first.

        CPN Tools removes tokens with the smallest timestamp first.  This is
        not merely a convention: it keeps timed simulation deterministic with
        respect to which stamps remain in the place, which matters when a
        later transition's enabling depends on those stamps.  Raises
        :class:`EvalError` if not enough tokens are available at ``clock`` --
        the caller is expected to have checked enabling first.
        """
        result = dict(self._counts)
        for value, needed in wanted.items():
            # Candidate stamps for this value that have already been reached,
            # oldest first.
            stamps = sorted(t for (v, t) in result if v == value and t <= clock)
            for timestamp in stamps:
                if needed == 0:
                    break
                key = (value, timestamp)
                take = min(needed, result[key])
                result[key] -= take
                if result[key] == 0:
                    del result[key]
                needed -= take
            if needed:
                raise EvalError(
                    f"cannot remove {wanted.count(value)}`{format_value(value)} at time "
                    f"{clock}: only {wanted.count(value) - needed} available"
                )
        return TimedMultiset(result)

    # -- identity ------------------------------------------------------------
    def __eq__(self, other: object) -> bool:
        return isinstance(other, TimedMultiset) and self._counts == other._counts

    def __hash__(self) -> int:
        if self._hash is None:
            self._hash = hash(frozenset(self._counts.items()))
        return self._hash

    def __repr__(self) -> str:
        """CPN Tools syntax: ``2`"a"@[0,5]``.

        We print one term per (value, timestamp) pair, which is unambiguous and
        matches what CPN Tools shows in the marking tooltip for simple cases.
        """
        if not self._counts:
            return "empty"
        return "++".join(
            f"{count}`{format_value(value)}@[{timestamp}]" for value, timestamp, count in self.items()
        )

    __str__ = __repr__
