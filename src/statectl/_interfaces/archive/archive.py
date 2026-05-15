from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path


class ArchiveFormat(Enum):
    TAR = "tar"
    TAR_GZ = "tar.gz"
    TAR_BZ2 = "tar.bz2"
    TAR_XZ = "tar.xz"
    ZIP = "zip"


class Archive(ABC):
    """Archive extraction abstraction. The action method `extract` raises
    ArchiveError subclasses on failure; the query method `detect_format`
    never raises and returns None when the format cannot be inferred from
    the path's suffix.

    Implementations must translate underlying errors into:
      - ArchiveNotFound            source archive does not exist
      - ArchiveCorrupt             archive is malformed or unreadable
      - ArchiveUnsafeEntry         entry would escape the destination
                                   (path traversal / absolute path)
      - ArchiveUnsupportedFormat   format is not supported by this impl
      - ArchiveIoError             any other IO failure during extraction
    """

    @abstractmethod
    def detect_format(self, path: Path) -> ArchiveFormat | None: ...

    @abstractmethod
    def extract(self, src: Path, dest: Path, format: ArchiveFormat) -> None: ...
