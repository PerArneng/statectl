from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, override

from statectl._interfaces.fs import FileSystem, FsError, FsNotFound
from statectl._modules import RealFileSystem
from statectl._state_changer import (
    ExistingState,
    Parameters,
    Result,
    StateAssessment,
    StateChanger,
)


PathKind = Literal["file", "symlink", "dir", "any"]


@dataclass(frozen=True)
class DeletePathParameters(Parameters):
    path: Path
    kind: PathKind
    recursive: bool = False
    missing_ok: bool = True


def _detect_kind(fs: FileSystem, path: Path) -> PathKind | None:
    if not fs.exists(path):
        return None
    if fs.is_symlink(path):
        return "symlink"
    if fs.is_dir(path):
        return "dir"
    if fs.is_file(path):
        return "file"
    return None


class DeletePathStateChanger(StateChanger):
    def __init__(
        self,
        params: DeletePathParameters,
        file_system: FileSystem | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()

    @property
    def params(self) -> DeletePathParameters:
        return self._params

    @override
    def name(self) -> str:
        return f"delete-path:{self._params.path}"

    @override
    def assess_state(self) -> StateAssessment:
        path = self._params.path
        expected = self._params.kind
        actual = _detect_kind(self._fs, path)

        if actual is None:
            if self._params.missing_ok:
                return StateAssessment(
                    state=ExistingState.ALREADY_APPLIED,
                    description=f"path already absent: {path}",
                )
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"path does not exist: {path}",
                issues=[f"path does not exist: {path}"],
            )

        issues: list[str] = []

        if expected != "any" and actual != expected:
            issues.append(f"path is {actual}, expected {expected}: {path}")

        if actual == "dir" and not self._params.recursive and not self._fs.is_empty_dir(path):
            issues.append(f"directory not empty, recursive=False: {path}")

        if not self._fs.is_writable(path.parent):
            issues.append(f"parent not writable: {path.parent}")

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot delete {path}",
                issues=issues,
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to delete {path}",
        )

    @override
    def transition(self) -> Result:
        path = self._params.path
        actual = _detect_kind(self._fs, path)

        if actual is None:
            return Result.skipped(f"{path} already gone")

        expected = self._params.kind
        if expected != "any" and actual != expected:
            return Result.failure(
                "KIND_CHANGED",
                f"kind changed between assess and transition: actual={actual}, expected={expected}",
            )

        if actual in ("file", "symlink"):
            try:
                self._fs.delete_file(path)
            except FsNotFound:
                return Result.skipped(f"{path} already gone")
            except FsError as e:
                return Result.failure("UNLINK_FAILED", f"failed to unlink {path}: {e}")
            return Result.success(f"deleted {actual} {path}")

        try:
            self._fs.delete_folder(path, recursive=self._params.recursive)
        except FsNotFound:
            return Result.skipped(f"{path} already gone")
        except FsError as e:
            return Result.failure("RMDIR_FAILED", f"failed to remove directory {path}: {e}")
        return Result.success(f"deleted directory {path}")
