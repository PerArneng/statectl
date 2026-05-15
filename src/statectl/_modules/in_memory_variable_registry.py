from __future__ import annotations

import threading
from types import MappingProxyType
from typing import Any, Mapping, TypeVar, override

from statectl._interfaces.registry import (
    DuplicateVariableError,
    VariableNotFoundError,
    VariableRegistry,
    VariableTypeError,
)


T = TypeVar("T")


class InMemoryVariableRegistry(VariableRegistry):
    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._values: dict[str, Any] = {}

    @override
    def bind(self, name: str, value: Any) -> None:
        with self._lock:
            if name in self._values:
                raise DuplicateVariableError(name)
            self._values[name] = value

    @override
    def get(self, name: str) -> Any:
        with self._lock:
            if name not in self._values:
                raise VariableNotFoundError(name)
            return self._values[name]

    @override
    def require(self, name: str, *, as_type: type[T]) -> T:
        with self._lock:
            if name not in self._values:
                raise VariableNotFoundError(name)
            value: Any = self._values[name]
        if not isinstance(value, as_type):
            raise VariableTypeError(name, expected=as_type, actual=type(value))
        return value

    @override
    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._values

    @override
    def snapshot(self) -> Mapping[str, Any]:
        with self._lock:
            return MappingProxyType(dict(self._values))
