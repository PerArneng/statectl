from __future__ import annotations


class DeferredHandle:
    """Opaque handle returned by `StateCtl.add_deferred`. Pass it via
    `depends_on=[...]` to subsequent `add` / `add_deferred` calls."""

    def __init__(self, placeholder_name: str) -> None:
        self._placeholder_name: str = placeholder_name

    @property
    def placeholder_name(self) -> str:
        return self._placeholder_name
