from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping, TypeVar


T = TypeVar("T")


class VariableRegistry(ABC):
    """Shared key/value store for outputs flowing between `StateChanger`s.

    `bind` writes once; rebinding the same name raises `DuplicateVariableError`.
    `get` returns the raw value; `require` returns it typed (or raises
    `VariableTypeError`). `snapshot` returns a read-only view safe to log."""

    @abstractmethod
    def bind(self, name: str, value: Any) -> None: ...

    @abstractmethod
    def get(self, name: str) -> Any: ...

    @abstractmethod
    def require(self, name: str, *, as_type: type[T]) -> T: ...

    @abstractmethod
    def has(self, name: str) -> bool: ...

    @abstractmethod
    def snapshot(self) -> Mapping[str, Any]: ...
