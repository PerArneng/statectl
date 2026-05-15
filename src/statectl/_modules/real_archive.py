from __future__ import annotations

import tarfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, override

from statectl._interfaces.archive import (
    Archive,
    ArchiveCorrupt,
    ArchiveFormat,
    ArchiveIoError,
    ArchiveNotFound,
    ArchiveUnsafeEntry,
    ArchiveUnsupportedFormat,
)


_TarOpener = Callable[[Path], tarfile.TarFile]


def _open_tar(path: Path) -> tarfile.TarFile:
    return tarfile.open(path, mode="r:")


def _open_tar_gz(path: Path) -> tarfile.TarFile:
    return tarfile.open(path, mode="r:gz")


def _open_tar_bz2(path: Path) -> tarfile.TarFile:
    return tarfile.open(path, mode="r:bz2")


def _open_tar_xz(path: Path) -> tarfile.TarFile:
    return tarfile.open(path, mode="r:xz")


_TAR_OPENERS: dict[ArchiveFormat, _TarOpener] = {
    ArchiveFormat.TAR: _open_tar,
    ArchiveFormat.TAR_GZ: _open_tar_gz,
    ArchiveFormat.TAR_BZ2: _open_tar_bz2,
    ArchiveFormat.TAR_XZ: _open_tar_xz,
}


_SUFFIX_FORMATS: tuple[tuple[tuple[str, ...], ArchiveFormat], ...] = (
    ((".tar", ".gz"), ArchiveFormat.TAR_GZ),
    ((".tgz",), ArchiveFormat.TAR_GZ),
    ((".tar", ".bz2"), ArchiveFormat.TAR_BZ2),
    ((".tbz2",), ArchiveFormat.TAR_BZ2),
    ((".tar", ".xz"), ArchiveFormat.TAR_XZ),
    ((".txz",), ArchiveFormat.TAR_XZ),
    ((".tar",), ArchiveFormat.TAR),
    ((".zip",), ArchiveFormat.ZIP),
)


@contextmanager
def _translate(path: Path) -> Iterator[None]:
    try:
        yield
    except FileNotFoundError as e:
        raise ArchiveNotFound("archive not found", path=path) from e
    except (tarfile.ReadError, zipfile.BadZipFile, EOFError) as e:
        raise ArchiveCorrupt(f"archive is corrupt: {e}", path=path) from e
    except tarfile.TarError as e:
        raise ArchiveCorrupt(f"tar error: {e}", path=path) from e
    except OSError as e:
        raise ArchiveIoError(f"io error: {e}", path=path) from e


def _is_safe_member(member_name: str, resolved_dest: Path) -> bool:
    member_path = Path(member_name)
    if member_path.is_absolute():
        return False
    target = (resolved_dest / member_path).resolve()
    if target == resolved_dest:
        return True
    return resolved_dest in target.parents


class RealArchive(Archive):
    @override
    def detect_format(self, path: Path) -> ArchiveFormat | None:
        suffixes = tuple(s.lower() for s in path.suffixes)
        for suffix_tuple, fmt in _SUFFIX_FORMATS:
            if suffixes[-len(suffix_tuple):] == suffix_tuple:
                return fmt
        return None

    @override
    def extract(self, src: Path, dest: Path, format: ArchiveFormat) -> None:
        if not src.exists():
            raise ArchiveNotFound("archive not found", path=src)
        if format is ArchiveFormat.ZIP:
            self._extract_zip(src, dest)
            return
        opener = _TAR_OPENERS.get(format)
        if opener is None:
            raise ArchiveUnsupportedFormat(
                f"unsupported archive format: {format.value}", path=src
            )
        self._extract_tar(src, dest, opener)

    def _extract_tar(
        self,
        src: Path,
        dest: Path,
        opener: "_TarOpener",
    ) -> None:
        with _translate(src):
            dest.mkdir(parents=True, exist_ok=True)
            resolved_dest = dest.resolve()
            with opener(src) as tf:
                for member in tf.getmembers():
                    if not _is_safe_member(member.name, resolved_dest):
                        raise ArchiveUnsafeEntry(
                            f"unsafe archive entry: {member.name}", path=src
                        )
                tf.extractall(dest, filter="data")

    def _extract_zip(self, src: Path, dest: Path) -> None:
        with _translate(src):
            dest.mkdir(parents=True, exist_ok=True)
            resolved_dest = dest.resolve()
            with zipfile.ZipFile(src) as zf:
                for name in zf.namelist():
                    if not _is_safe_member(name, resolved_dest):
                        raise ArchiveUnsafeEntry(
                            f"unsafe archive entry: {name}", path=src
                        )
                zf.extractall(dest)
