"""Typed contracts for pytest helpers whose annotations are incomplete."""

from typing import Protocol


class _SyspathPrepender(Protocol):
    """The part of ``pytest.MonkeyPatch`` used to prepend import paths."""

    def syspath_prepend(self, path: str) -> None:
        """Prepend a path and invalidate import caches."""


def syspath_prepend(*, monkeypatch: _SyspathPrepender, path: str) -> None:
    """Prepend a path through the locally typed pytest contract."""
    monkeypatch.syspath_prepend(path)
