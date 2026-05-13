from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import override

from statectl.interfaces.fs.file_system import FileSystem
from statectl.interfaces.fs.error.fs_error import FsError
from statectl.interfaces.fs.error.fs_not_found import FsNotFound
from statectl.modules.fs.real_file_system import RealFileSystem
from statectl.state_changer import (
    ExistingState,
    Parameters,
    Result,
    RollbackableStateChanger,
    StateAssessment,
    StateChanger,
)


@dataclass(frozen=True)
class NewTextFileParameters(Parameters):
    path: Path
    text: str
    encoding: str = "utf-8"


class NewTextFileStateChanger(RollbackableStateChanger):
    def __init__(
        self,
        params: NewTextFileParameters,
        file_system: FileSystem | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()

    @override
    def name(self) -> str:
        return f"new-text-file:{self._params.path}"

    @override
    def assess_state(self) -> StateAssessment:
        path = self._params.path
        parent = path.parent
        issues: list[str] = []

        if not self._fs.exists(parent):
            issues.append(f"parent directory does not exist: {parent}")
        elif not self._fs.is_dir(parent):
            issues.append(f"parent path is not a directory: {parent}")
        elif not self._fs.is_writable(parent):
            issues.append(f"parent directory is not writable: {parent}")

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot create {path}",
                issues=issues,
            )

        if self._fs.exists(path):
            if not self._fs.is_file(path):
                return StateAssessment(
                    state=ExistingState.INVALID,
                    description=f"path exists but is not a regular file: {path}",
                    issues=[f"target path exists but is not a regular file: {path}"],
                )
            try:
                existing = self._fs.read_text_file(path, encoding=self._params.encoding)
            except FsError as e:
                return StateAssessment(
                    state=ExistingState.INVALID,
                    description=f"cannot read existing file at {path}",
                    issues=[f"cannot read existing file to compare: {e}"],
                )
            if existing == self._params.text:
                return StateAssessment(
                    state=ExistingState.ALREADY_APPLIED,
                    description=f"file already has desired content: {path}",
                )
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"file exists with different content: {path}",
                issues=["file exists with different content"],
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to create {path}",
        )

    @override
    def transition(self) -> Result:
        try:
            self._fs.write_text_file(
                self._params.path, self._params.text, encoding=self._params.encoding
            )
        except FsError as e:
            return Result.failure("WRITE_FAILED", f"failed to write {self._params.path}: {e}")
        return Result.success(f"wrote {self._params.path}")

    @override
    def rollback(self) -> StateChanger:
        return NewTextFileRollbackStateChanger(self._params, file_system=self._fs)


class NewTextFileRollbackStateChanger(StateChanger):
    def __init__(
        self,
        params: NewTextFileParameters,
        file_system: FileSystem | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()

    @override
    def name(self) -> str:
        return f"new-text-file-rollback:{self._params.path}"

    @override
    def assess_state(self) -> StateAssessment:
        path = self._params.path
        if not self._fs.exists(path):
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"nothing to roll back; {path} does not exist",
            )

        issues: list[str] = []
        if not self._fs.is_file(path):
            issues.append(f"refusing to remove non-file path: {path}")
        if not self._fs.is_writable(path.parent):
            issues.append(f"parent directory is not writable: {path.parent}")

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot remove {path}",
                issues=issues,
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to remove {path}",
        )

    @override
    def transition(self) -> Result:
        try:
            self._fs.delete_file(self._params.path)
        except FsNotFound:
            return Result.skipped(f"{self._params.path} already gone")
        except FsError as e:
            return Result.failure("UNLINK_FAILED", f"failed to remove {self._params.path}: {e}")
        return Result.success(f"removed {self._params.path}")
