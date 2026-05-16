from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import override

from statectl._interfaces.fs import FileSystem, FsError, FsNotFound
from statectl._modules import RealFileSystem
from statectl._state_changer import (
    ExistingState,
    Parameters,
    Result,
    RollbackableStateChanger,
    StateAssessment,
    StateChanger,
)


@dataclass(frozen=True)
class EnsureDirectoryParameters(Parameters):
    path: Path
    mode: int | None = None
    parents: bool = True


def _first_existing_ancestor(fs: FileSystem, path: Path) -> Path | None:
    for ancestor in path.parents:
        if fs.exists(ancestor):
            return ancestor
    return None


class EnsureDirectoryStateChanger(RollbackableStateChanger):
    def __init__(
        self,
        params: EnsureDirectoryParameters,
        file_system: FileSystem | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()

    @property
    def params(self) -> EnsureDirectoryParameters:
        return self._params

    @override
    def name(self) -> str:
        return f"ensure-directory:{self._params.path}"

    @override
    def assess_state(self) -> StateAssessment:
        path = self._params.path
        mode = self._params.mode
        issues: list[str] = []

        if mode is not None and not (0 <= mode <= 0o7777):
            issues.append(f"mode out of range: {mode:#o}")

        path_exists = self._fs.exists(path)
        path_is_dir = self._fs.is_dir(path)
        if path_exists and not path_is_dir:
            issues.append(f"path exists but is not a directory: {path}")

        if not path_exists:
            parent = path.parent
            if not self._params.parents and not self._fs.exists(parent):
                issues.append(f"parent does not exist: {parent}")
            ancestor = (
                parent
                if self._fs.exists(parent)
                else (_first_existing_ancestor(self._fs, path) if self._params.parents else None)
            )
            if ancestor is not None and not self._fs.is_writable(ancestor):
                issues.append(f"parent not writable: {ancestor}")

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot ensure directory {path}",
                issues=issues,
            )

        if path_exists and path_is_dir:
            if mode is None or self._fs.stat_mode(path) == mode:
                return StateAssessment(
                    state=ExistingState.ALREADY_APPLIED,
                    description=f"directory already in place: {path}",
                )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to ensure directory {path}",
        )

    @override
    def transition(self) -> Result:
        path = self._params.path
        try:
            self._fs.create_folder(path, parents=self._params.parents, exist_ok=True)
        except FsError as e:
            return Result.failure("MKDIR_FAILED", f"failed to create {path}: {e}")
        if self._params.mode is not None:
            try:
                self._fs.chmod(path, self._params.mode)
            except FsNotFound as e:
                return Result.failure("DIR_VANISHED", f"directory vanished before chmod: {e}")
            except FsError as e:
                return Result.failure("CHMOD_FAILED", f"failed to chmod {path}: {e}")
        return Result.success(f"ensured directory {path}")

    @override
    def rollback(self) -> StateChanger:
        return EnsureDirectoryRollbackStateChanger(self._params, file_system=self._fs)


class EnsureDirectoryRollbackStateChanger(StateChanger):
    def __init__(
        self,
        params: EnsureDirectoryParameters,
        file_system: FileSystem | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()

    @override
    def name(self) -> str:
        return f"ensure-directory-rollback:{self._params.path}"

    @override
    def assess_state(self) -> StateAssessment:
        path = self._params.path
        if not self._fs.exists(path):
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"nothing to roll back; {path} does not exist",
            )

        issues: list[str] = []
        if not self._fs.is_dir(path):
            issues.append(f"path is no longer a directory: {path}")
        elif not self._fs.is_empty_dir(path):
            issues.append(f"directory not empty, refusing to delete: {path}")

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot roll back directory {path}",
                issues=issues,
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to remove directory {path}",
        )

    @override
    def transition(self) -> Result:
        path = self._params.path
        try:
            self._fs.delete_folder(path, recursive=False)
        except FsNotFound:
            return Result.skipped(f"{path} already gone")
        except FsError as e:
            return Result.failure("RMDIR_FAILED", f"failed to remove {path}: {e}")
        return Result.success(f"removed directory {path}")
