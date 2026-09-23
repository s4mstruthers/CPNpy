"""Exception hierarchy for the CPN ML subsystem.

Every failure that the user can cause by writing a bad model raises a subclass
of :class:`CPNMLError`.  The GUI catches that one class and shows the message
next to the offending inscription, so it is important that nothing in the ML
layer raises a bare ``ValueError`` for a *user* mistake.  Internal invariant
violations should still raise ``AssertionError`` -- those are our bugs, not the
modeller's.
"""

from __future__ import annotations


class CPNMLError(Exception):
    """Base class for all errors caused by the contents of a model."""

    def __init__(self, message: str, position: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        # Character offset into the source inscription, when we know it.  The
        # editor uses this to underline the exact token.
        self.position = position

    def __str__(self) -> str:  # pragma: no cover - trivial
        if self.position is None:
            return self.message
        return f"{self.message} (at character {self.position})"


class LexError(CPNMLError):
    """The inscription contains a character sequence that is not a token."""


class ParseError(CPNMLError):
    """The tokens are individually valid but do not form a legal expression."""


class TypeError_(CPNMLError):
    """A value does not belong to the colour set it is being used as.

    Named with a trailing underscore so it does not shadow the builtin
    ``TypeError``; exported as ``CPNTypeError`` for readability.
    """


CPNTypeError = TypeError_


class EvalError(CPNMLError):
    """Evaluation failed: unbound identifier, division by zero, no matching
    case branch, wrong number of arguments, and so on."""


class MatchError(EvalError):
    """A pattern could not be matched against a value.

    This is a *recoverable* error during binding search -- the binder catches
    it and simply moves on to the next candidate token -- so it gets its own
    class rather than being reported to the user directly.
    """
