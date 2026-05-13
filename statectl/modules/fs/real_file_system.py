from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from statectl.interfaces.fs.file_entry import FileEntry
from statectl.interfaces.fs.file_system import FileSystem
from statectl.interfaces.fs.error.fs_already_exists import FsAlreadyExists
from statectl.interfaces.fs.error.fs_decode_error import FsDecodeError
from statectl.interfaces.fs.error.fs_io_error import FsIoError
from statectl.interfaces.fs.error.fs_not_a_directory import FsNotADirectory
from statectl.interfaces.fs.error.fs_not_a_file import FsNotAFile
from statectl.interfaces.fs.error.fs_not_found import FsNotFound
from statectl.interfaces.fs.error.fs_permission_denied import FsPermissionDenied


@contextmanager
def _translate(path: Path) -> Iterator[None]:
    try:
        yield
    except FileNotFoundError as e:
        raise FsNotFound("path not found", path=path) from e
    except FileExistsError as e:
        raise FsAlreadyExists("path already exists", path=path) from e
    except NotADirectoryError as e:
        raise FsNotADirectory("not a directory", path=path) from e
    except IsADirectoryError as e:
        raise FsNotAFile("path is a directory, not a file", path=path) from e
    except PermissionError as e:
        raise FsPermissionDenied("permission denied", path=path) from e
    except UnicodeDecodeError as e:
        raise FsDecodeError(f"could not decode bytes: {e}", path=path) from e
    except OSError as e:
        raise FsIoError(f"io error: {e}", path=path) from e


class RealFileSystem(FileSystem):
    def exists(self, path: Path) -> bool:
        return path.exists()

    def is_file(self, path: Path) -> bool:
        return path.is_file()

    def is_dir(self, path: Path) -> bool:
        return path.is_dir()

    def is_writable(self, path: Path) -> bool:
        return os.access(path, os.W_OK)

    def read_text_file(self, path: Path, encoding: str = "utf-8") -> str:
        with _translate(path):
            return path.read_text(encoding=encoding)

    def write_text_file(self, path: Path, text: str, encoding: str = "utf-8") -> None:
        with _translate(path):
            path.write_text(text, encoding=encoding)

    def delete_file(self, path: Path) -> None:
        with _translate(path):
            path.unlink()

    def list_files(self, path: Path) -> list[FileEntry]:
        with _translate(path):
            return [
                FileEntry(path=p, name=p.name, is_dir=p.is_dir(), is_file=p.is_file())
                for p in path.iterdir()
            ]

    def create_folder(self, path: Path, parents: bool = False, exist_ok: bool = False) -> None:
        with _translate(path):
            path.mkdir(parents=parents, exist_ok=exist_ok)

    def delete_folder(self, path: Path, recursive: bool = False) -> None:
        with _translate(path):
            if recursive:
                shutil.rmtree(path)
            else:
                path.rmdir()

    def create_temp_folder(self, prefix: str | None = None) -> Path:
        with _translate(Path(tempfile.gettempdir())):
            return Path(tempfile.mkdtemp(prefix=prefix))
