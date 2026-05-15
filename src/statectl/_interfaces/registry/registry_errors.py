from __future__ import annotations

from typing import override


class RegistryError(Exception):
    def __init__(self, message: str, name: str | None = None) -> None:
        super().__init__(message)
        self.message: str = message
        self.name: str | None = name

    @override
    def __str__(self) -> str:
        if self.name is not None:
            return f"{self.message}: {self.name!r}"
        return self.message


class VariableNotFoundError(RegistryError):
    def __init__(self, name: str) -> None:
        super().__init__("variable not found in registry", name=name)


class DuplicateVariableError(RegistryError):
    def __init__(self, name: str) -> None:
        super().__init__("variable already bound in registry", name=name)


class VariableTypeError(RegistryError):
    def __init__(self, name: str, expected: type, actual: type) -> None:
        super().__init__(
            f"variable type mismatch: expected {expected.__name__}, "
            f"got {actual.__name__}",
            name=name,
        )
        self.expected: type = expected
        self.actual: type = actual
