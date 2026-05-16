from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class Hashing(ABC):
    """Content-hashing capability. `sha256_file` returns the lowercase
    hex digest of the file at `path`. Raises `HashingError` subclasses on
    failure — typed errors mirror the FileSystem convention so changers
    can map them onto distinct failure codes.

    Implementations must translate underlying errors into:
      - HashingNotFound        path is missing
      - HashingIoError         any other IO failure while reading
    """

    @abstractmethod
    def sha256_file(self, path: Path) -> str: ...
