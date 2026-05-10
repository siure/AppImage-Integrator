from __future__ import annotations

from collections.abc import Callable

CancelCallback = Callable[[], bool]


class OperationCancelled(Exception):
    """Raised when a user-visible long-running operation is cancelled."""


def raise_if_cancelled(should_cancel: CancelCallback | None) -> None:
    if should_cancel is not None and should_cancel():
        raise OperationCancelled()
