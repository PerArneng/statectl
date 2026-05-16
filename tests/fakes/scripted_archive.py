from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import override

from statectl._interfaces.archive import (
    Archive,
    ArchiveFormat,
    ArchiveNotFound,
)
from statectl._interfaces.fs import FileSystem


@dataclass(frozen=True)
class RegisteredArchive:
    format: ArchiveFormat
    entries: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class RecordedExtract:
    src: Path
    dest: Path
    format: ArchiveFormat
    strip_components: int = 0


@dataclass
class ScriptedArchive(Archive):
    """In-memory Archive. Register archives with `register_archive(path, format,
    entries=...)` to make `detect_format` return their format and `extract`
    succeed. If a `file_system` is supplied, registered entries are written into
    it on extract so downstream changers can observe extraction. Every extract
    call is recorded on `.calls` for assertions.
    """

    file_system: FileSystem | None = None
    _archives: dict[Path, RegisteredArchive] = field(default_factory=dict)
    calls: list[RecordedExtract] = field(default_factory=list)

    def register_archive(
        self,
        path: Path,
        format: ArchiveFormat,
        entries: dict[str, str] | None = None,
    ) -> None:
        ents = tuple((k, v) for k, v in (entries or {}).items())
        self._archives[path] = RegisteredArchive(format=format, entries=ents)

    @override
    def detect_format(self, path: Path) -> ArchiveFormat | None:
        registered = self._archives.get(path)
        return registered.format if registered else None

    @override
    def extract(
        self,
        src: Path,
        dest: Path,
        format: ArchiveFormat,
        strip_components: int = 0,
    ) -> None:
        self.calls.append(
            RecordedExtract(
                src=src, dest=dest, format=format, strip_components=strip_components
            )
        )
        registered = self._archives.get(src)
        if registered is None:
            raise ArchiveNotFound("archive not found", path=src)
        if self.file_system is None:
            return
        self.file_system.create_folder(dest, parents=True, exist_ok=True)
        for name, content in registered.entries:
            stripped = _strip_path(name, strip_components)
            if stripped is None:
                continue
            target = dest / stripped
            if target.parent != dest:
                self.file_system.create_folder(target.parent, parents=True, exist_ok=True)
            self.file_system.write_text_file(target, content)


def _strip_path(name: str, strip_components: int) -> str | None:
    if strip_components <= 0:
        return name
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
    if len(parts) <= strip_components:
        return None
    return "/".join(parts[strip_components:])
