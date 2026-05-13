from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from statectl.interfaces.fs.file_entry import FileEntry


class FileSystem(ABC):
    """Filesystem abstraction. All mutating / reading methods raise FsError
    subclasses on failure; query methods (exists / is_file / is_dir /
    is_writable) return bool and never raise.

    Implementations must translate underlying errors into:
      - FsNotFound          path is missing when required
      - FsNotAFile          path exists but is not a regular file
      - FsNotADirectory     path exists but is not a directory
      - FsPermissionDenied  permission refused by OS
      - FsAlreadyExists     target already exists (create_folder w/o exist_ok)
      - FsDecodeError       text could not be decoded with given encoding
      - FsIoError           any other IO failure
    """

    @abstractmethod
    def exists(self, path: Path) -> bool: ...

    @abstractmethod
    def is_file(self, path: Path) -> bool: ...

    @abstractmethod
    def is_dir(self, path: Path) -> bool: ...

    @abstractmethod
    def is_writable(self, path: Path) -> bool: ...

    @abstractmethod
    def read_text_file(self, path: Path, encoding: str = "utf-8") -> str: ...

    @abstractmethod
    def write_text_file(self, path: Path, text: str, encoding: str = "utf-8") -> None: ...

    @abstractmethod
    def delete_file(self, path: Path) -> None: ...

    @abstractmethod
    def list_files(self, path: Path) -> list[FileEntry]: ...

    @abstractmethod
    def create_folder(self, path: Path, parents: bool = False, exist_ok: bool = False) -> None: ...

    @abstractmethod
    def delete_folder(self, path: Path, recursive: bool = False) -> None: ...

    @abstractmethod
    def create_temp_folder(self, prefix: str | None = None) -> Path: ...
