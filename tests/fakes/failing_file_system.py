from __future__ import annotations

from pathlib import Path

from statectl.interfaces.fs.error.fs_error import FsError
from statectl.interfaces.fs.file_entry import FileEntry
from statectl.interfaces.fs.file_system import FileSystem


class FailingFileSystem(FileSystem):
    """Wraps another FileSystem and injects FsError on specific method calls.

    Use `fail(method, error, path=None)` to register a failure: the next call
    matching `method` (and optionally `path`) raises `error` instead of
    delegating. Failures are one-shot and consumed on use. Useful for
    simulating IO errors at points the in-memory fake would otherwise succeed.
    """

    def __init__(self, inner: FileSystem) -> None:
        self._inner = inner
        self._failures: list[tuple[str, Path | None, FsError]] = []

    def fail(self, method: str, error: FsError, path: Path | None = None) -> None:
        self._failures.append((method, path, error))

    def _maybe_fail(self, method: str, path: Path | None) -> None:
        for i, (m, p, err) in enumerate(self._failures):
            if m == method and (p is None or p == path):
                del self._failures[i]
                raise err

    def exists(self, path: Path) -> bool:
        return self._inner.exists(path)

    def is_file(self, path: Path) -> bool:
        return self._inner.is_file(path)

    def is_dir(self, path: Path) -> bool:
        return self._inner.is_dir(path)

    def is_writable(self, path: Path) -> bool:
        return self._inner.is_writable(path)

    def read_text_file(self, path: Path, encoding: str = "utf-8") -> str:
        self._maybe_fail("read_text_file", path)
        return self._inner.read_text_file(path, encoding=encoding)

    def write_text_file(self, path: Path, text: str, encoding: str = "utf-8") -> None:
        self._maybe_fail("write_text_file", path)
        self._inner.write_text_file(path, text, encoding=encoding)

    def delete_file(self, path: Path) -> None:
        self._maybe_fail("delete_file", path)
        self._inner.delete_file(path)

    def list_files(self, path: Path) -> list[FileEntry]:
        self._maybe_fail("list_files", path)
        return self._inner.list_files(path)

    def create_folder(self, path: Path, parents: bool = False, exist_ok: bool = False) -> None:
        self._maybe_fail("create_folder", path)
        self._inner.create_folder(path, parents=parents, exist_ok=exist_ok)

    def delete_folder(self, path: Path, recursive: bool = False) -> None:
        self._maybe_fail("delete_folder", path)
        self._inner.delete_folder(path, recursive=recursive)

    def create_temp_folder(self, prefix: str | None = None) -> Path:
        self._maybe_fail("create_temp_folder", None)
        return self._inner.create_temp_folder(prefix=prefix)
