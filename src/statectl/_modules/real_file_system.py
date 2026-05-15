from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, override

from statectl._interfaces.fs import (
    FileEntry,
    FileSystem,
    FsAlreadyExists,
    FsDecodeError,
    FsIoError,
    FsNotADirectory,
    FsNotAFile,
    FsNotFound,
    FsPermissionDenied,
)


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
    @override
    def exists(self, path: Path) -> bool:
        return path.exists()

    @override
    def is_file(self, path: Path) -> bool:
        return path.is_file()

    @override
    def is_dir(self, path: Path) -> bool:
        return path.is_dir()

    @override
    def is_symlink(self, path: Path) -> bool:
        return path.is_symlink()

    @override
    def is_writable(self, path: Path) -> bool:
        return os.access(path, os.W_OK)

    @override
    def is_empty_dir(self, path: Path) -> bool:
        try:
            with os.scandir(path) as it:
                return next(it, None) is None
        except OSError:
            return False

    @override
    def stat_mode(self, path: Path, follow_symlinks: bool = True) -> int | None:
        try:
            if follow_symlinks:
                st = os.stat(path)
            else:
                st = os.lstat(path)
            return st.st_mode & 0o7777
        except OSError:
            return None

    @override
    def supports_lchmod(self) -> bool:
        return os.chmod in os.supports_follow_symlinks

    @override
    def read_text_file(self, path: Path, encoding: str = "utf-8") -> str:
        with _translate(path):
            return path.read_text(encoding=encoding)

    @override
    def write_text_file(self, path: Path, text: str, encoding: str = "utf-8") -> None:
        with _translate(path):
            path.write_text(text, encoding=encoding)

    @override
    def delete_file(self, path: Path) -> None:
        with _translate(path):
            path.unlink()

    @override
    def list_files(self, path: Path) -> list[FileEntry]:
        with _translate(path):
            return [
                FileEntry(path=p, name=p.name, is_dir=p.is_dir(), is_file=p.is_file())
                for p in path.iterdir()
            ]

    @override
    def create_folder(self, path: Path, parents: bool = False, exist_ok: bool = False) -> None:
        with _translate(path):
            path.mkdir(parents=parents, exist_ok=exist_ok)

    @override
    def delete_folder(self, path: Path, recursive: bool = False) -> None:
        with _translate(path):
            if recursive:
                shutil.rmtree(path)
            else:
                path.rmdir()

    @override
    def chmod(self, path: Path, mode: int, follow_symlinks: bool = True) -> None:
        with _translate(path):
            if follow_symlinks:
                os.chmod(path, mode)
            else:
                if os.chmod not in os.supports_follow_symlinks:
                    raise FsIoError("lchmod not supported on this platform", path=path)
                os.chmod(path, mode, follow_symlinks=False)

    @override
    def create_temp_folder(self, prefix: str | None = None) -> Path:
        with _translate(Path(tempfile.gettempdir())):
            return Path(tempfile.mkdtemp(prefix=prefix))
