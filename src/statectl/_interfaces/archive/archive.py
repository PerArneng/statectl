from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path


def strip_path_components(name: str, strip_components: int) -> str | None:
    """Return `name` with `strip_components` leading path components removed,
    or None if `name` has too few components to strip. Used by both the real
    Archive impl and the in-memory test fake so they share semantics."""
    if strip_components <= 0:
        return name
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
    if len(parts) <= strip_components:
        return None
    return "/".join(parts[strip_components:])


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
    def extract(
        self,
        src: Path,
        dest: Path,
        format: ArchiveFormat,
        strip_components: int = 0,
    ) -> None: ...
