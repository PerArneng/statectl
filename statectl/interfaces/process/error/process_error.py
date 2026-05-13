from __future__ import annotations

from typing import override


class ProcessError(Exception):
    def __init__(self, message: str, argv: tuple[str, ...] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.argv = argv

    @override
    def __str__(self) -> str:
        if self.argv is not None:
            return f"{self.message}: {' '.join(self.argv)}"
        return self.message
