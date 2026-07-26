"""Domain exception hierarchy.

Invalid operations raise these instead of ad hoc ValueError/AssertionError,
so Application (and eventually interop readers) can catch a consistent,
narrow type rather than guessing what a bare ValueError meant.
"""

from __future__ import annotations


class CoconutError(Exception):
    """Base class for all domain errors raised by core/."""


class ValidationError(CoconutError):
    """A requested mutation failed a domain invariant (bad predecessor
    syntax, unknown id, duplicate id, etc.)."""


class SchedulingError(CoconutError):
    """The scheduler could not produce a valid schedule (e.g. a cyclic
    dependency graph)."""


class NothingToUndoError(CoconutError):
    """undo() was called with an empty undo stack."""


class NothingToRedoError(CoconutError):
    """redo() was called with an empty redo stack."""
