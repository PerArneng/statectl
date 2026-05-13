from __future__ import annotations

from pathlib import Path


class FsError(Exception):
    def __init__(self, message: str, path: Path | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.path = path

    def __str__(self) -> str:
        if self.path is not None:
            return f"{self.message}: {self.path}"
        return self.message
