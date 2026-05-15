from __future__ import annotations

from pathlib import Path

from statectl._interfaces.fs import (
    FileEntry,
    FileSystem,
    FsError,
)


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

    def is_symlink(self, path: Path) -> bool:
        return self._inner.is_symlink(path)

    def is_writable(self, path: Path) -> bool:
        return self._inner.is_writable(path)

    def is_empty_dir(self, path: Path) -> bool:
        return self._inner.is_empty_dir(path)

    def stat_mode(self, path: Path, follow_symlinks: bool = True) -> int | None:
        return self._inner.stat_mode(path, follow_symlinks=follow_symlinks)

    def supports_lchmod(self) -> bool:
        return self._inner.supports_lchmod()

    def read_text_file(self, path: Path, encoding: str = "utf-8") -> str:
        self._maybe_fail("read_text_file", path)
        return self._inner.read_text_file(path, encoding=encoding)

    def write_text_file(self, path: Path, text: str, encoding: str = "utf-8") -> None:
        self._maybe_fail("write_text_file", path)
        self._inner.write_text_file(path, text, encoding=encoding)

    def read_binary_file(self, path: Path) -> bytes:
        self._maybe_fail("read_binary_file", path)
        return self._inner.read_binary_file(path)

    def write_binary_file(self, path: Path, data: bytes) -> None:
        self._maybe_fail("write_binary_file", path)
        self._inner.write_binary_file(path, data)

    def copy_file(self, src: Path, dest: Path, preserve_mtime: bool = False) -> None:
        self._maybe_fail("copy_file", src)
        self._inner.copy_file(src, dest, preserve_mtime=preserve_mtime)

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

    def chmod(self, path: Path, mode: int, follow_symlinks: bool = True) -> None:
        self._maybe_fail("chmod", path)
        self._inner.chmod(path, mode, follow_symlinks=follow_symlinks)

    def read_symlink(self, path: Path) -> Path:
        self._maybe_fail("read_symlink", path)
        return self._inner.read_symlink(path)

    def create_symlink(self, link_path: Path, target: Path) -> None:
        self._maybe_fail("create_symlink", link_path)
        self._inner.create_symlink(link_path, target)

    def create_temp_folder(self, prefix: str | None = None) -> Path:
        self._maybe_fail("create_temp_folder", None)
        return self._inner.create_temp_folder(prefix=prefix)
