from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from statectl.interfaces.fs import (
    FileEntry,
    FileSystem,
    FsAlreadyExists,
    FsDecodeError,
    FsIoError,
    FsNotADirectory,
    FsNotAFile,
    FsNotFound,
)


@dataclass
class _Node:
    is_dir: bool
    content: str = ""
    writable: bool = True
    readable_text: bool = True


@dataclass
class InMemoryFileSystem(FileSystem):
    """Pure in-memory FileSystem for tests. Holds a flat path -> node map.

    Helpers (add_dir / add_file) configure pre-existing state. Switch the
    `writable` or `readable_text` flag on a node to simulate permission and
    decode failures without needing a wrapping fake.
    """

    _nodes: dict[Path, _Node] = field(default_factory=dict)
    _temp_counter: int = 0
    temp_root: Path = Path("/tmp")

    def add_dir(self, path: Path, writable: bool = True) -> None:
        self._nodes[path] = _Node(is_dir=True, writable=writable)

    def add_file(
        self,
        path: Path,
        content: str = "",
        writable: bool | None = None,
        readable_text: bool = True,
    ) -> None:
        parent_writable = True
        if path.parent in self._nodes:
            parent_writable = self._nodes[path.parent].writable
        self._nodes[path] = _Node(
            is_dir=False,
            content=content,
            writable=parent_writable if writable is None else writable,
            readable_text=readable_text,
        )

    def set_writable(self, path: Path, writable: bool) -> None:
        self._nodes[path].writable = writable

    def set_readable_text(self, path: Path, readable_text: bool) -> None:
        self._nodes[path].readable_text = readable_text

    def exists(self, path: Path) -> bool:
        return path in self._nodes

    def is_file(self, path: Path) -> bool:
        node = self._nodes.get(path)
        return node is not None and not node.is_dir

    def is_dir(self, path: Path) -> bool:
        node = self._nodes.get(path)
        return node is not None and node.is_dir

    def is_writable(self, path: Path) -> bool:
        node = self._nodes.get(path)
        return node is not None and node.writable

    def read_text_file(self, path: Path, encoding: str = "utf-8") -> str:
        node = self._nodes.get(path)
        if node is None:
            raise FsNotFound("path not found", path=path)
        if node.is_dir:
            raise FsNotAFile("path is a directory, not a file", path=path)
        if not node.readable_text:
            raise FsDecodeError(f"could not decode bytes with {encoding}", path=path)
        return node.content

    def write_text_file(self, path: Path, text: str, encoding: str = "utf-8") -> None:
        parent = self._nodes.get(path.parent)
        if parent is None:
            raise FsNotFound("parent directory does not exist", path=path.parent)
        if not parent.is_dir:
            raise FsNotADirectory("parent is not a directory", path=path.parent)
        if not parent.writable:
            raise FsIoError("parent directory is not writable", path=path.parent)
        existing = self._nodes.get(path)
        if existing is not None and existing.is_dir:
            raise FsNotAFile("path is a directory, not a file", path=path)
        if existing is not None and not existing.writable:
            raise FsIoError("file is not writable", path=path)
        self._nodes[path] = _Node(
            is_dir=False,
            content=text,
            writable=parent.writable,
        )

    def delete_file(self, path: Path) -> None:
        node = self._nodes.get(path)
        if node is None:
            raise FsNotFound("path not found", path=path)
        if node.is_dir:
            raise FsNotAFile("path is a directory, not a file", path=path)
        parent = self._nodes.get(path.parent)
        if parent is not None and not parent.writable:
            raise FsIoError("parent directory is not writable", path=path.parent)
        del self._nodes[path]

    def list_files(self, path: Path) -> list[FileEntry]:
        node = self._nodes.get(path)
        if node is None:
            raise FsNotFound("path not found", path=path)
        if not node.is_dir:
            raise FsNotADirectory("not a directory", path=path)
        entries: list[FileEntry] = []
        for p, n in self._nodes.items():
            if p.parent == path and p != path:
                entries.append(FileEntry(path=p, name=p.name, is_dir=n.is_dir, is_file=not n.is_dir))
        return entries

    def create_folder(self, path: Path, parents: bool = False, exist_ok: bool = False) -> None:
        if path in self._nodes:
            if exist_ok and self._nodes[path].is_dir:
                return
            raise FsAlreadyExists("path already exists", path=path)
        if path.parent not in self._nodes:
            if not parents:
                raise FsNotFound("parent directory does not exist", path=path.parent)
            self.create_folder(path.parent, parents=True, exist_ok=True)
        if not self._nodes[path.parent].is_dir:
            raise FsNotADirectory("parent is not a directory", path=path.parent)
        self._nodes[path] = _Node(is_dir=True, writable=True)

    def delete_folder(self, path: Path, recursive: bool = False) -> None:
        node = self._nodes.get(path)
        if node is None:
            raise FsNotFound("path not found", path=path)
        if not node.is_dir:
            raise FsNotADirectory("not a directory", path=path)
        children = [p for p in self._nodes if p.parent == path and p != path]
        if children and not recursive:
            raise FsIoError("directory not empty", path=path)
        if recursive:
            for p in list(self._nodes):
                if p == path or _is_ancestor(path, p):
                    del self._nodes[p]
        else:
            del self._nodes[path]

    def create_temp_folder(self, prefix: str | None = None) -> Path:
        if self.temp_root not in self._nodes:
            self.add_dir(self.temp_root)
        self._temp_counter += 1
        name = f"{prefix or 'tmp'}{self._temp_counter}"
        path = self.temp_root / name
        self._nodes[path] = _Node(is_dir=True, writable=True)
        return path


def _is_ancestor(ancestor: Path, descendant: Path) -> bool:
    return ancestor in descendant.parents
