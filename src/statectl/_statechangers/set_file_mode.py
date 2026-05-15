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
    ResultStatus,
    RollbackableStateChanger,
    StateAssessment,
    StateChanger,
)


@dataclass(frozen=True)
class SetFileModeParameters(Parameters):
    path: Path
    mode: int
    follow_symlinks: bool = True


def _mode_in_range(mode: int) -> bool:
    return 0 <= mode <= 0o7777


class SetFileModeStateChanger(RollbackableStateChanger):
    def __init__(
        self,
        params: SetFileModeParameters,
        file_system: FileSystem | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()

    @property
    def params(self) -> SetFileModeParameters:
        return self._params

    @override
    def name(self) -> str:
        return f"set-file-mode:{self._params.path}"

    @override
    def assess_state(self) -> StateAssessment:
        path = self._params.path
        mode = self._params.mode
        follow = self._params.follow_symlinks
        issues: list[str] = []

        if not _mode_in_range(mode):
            issues.append(f"mode out of range: {oct(mode)} (expected 0o000..0o7777)")

        if not self._fs.exists(path):
            issues.append(f"path does not exist: {path}")

        if not follow and not self._fs.supports_lchmod():
            issues.append("lchmod unsupported on this platform")

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot chmod {path}",
                issues=issues,
            )

        current = self._fs.stat_mode(path, follow_symlinks=follow)
        if current is not None and (current & 0o7777) == mode:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"mode already {oct(mode)}: {path}",
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to chmod {path} to {oct(mode)}",
        )

    @override
    def transition(self) -> Result:
        path = self._params.path
        mode = self._params.mode
        follow = self._params.follow_symlinks

        pre_mode = self._fs.stat_mode(path, follow_symlinks=follow)
        if pre_mode is None:
            return Result.failure(
                "PATH_VANISHED", f"path vanished between assess and chmod: {path}"
            )

        try:
            self._fs.chmod(path, mode, follow_symlinks=follow)
        except FsNotFound:
            return Result.failure(
                "PATH_VANISHED", f"path vanished between assess and chmod: {path}"
            )
        except FsError as e:
            return Result.failure("CHMOD_FAILED", f"failed to chmod {path}: {e}")

        return Result(
            status=ResultStatus.SUCCESS,
            code="OK",
            message=f"chmod {path} {oct(pre_mode)} -> {oct(mode)}",
            details={"pre_mode": oct(pre_mode)},
        )

    @override
    def rollback(self) -> StateChanger:
        pre_mode = self._fs.stat_mode(
            self._params.path, follow_symlinks=self._params.follow_symlinks
        )
        return SetFileModeRollbackStateChanger(
            self._params, pre_mode=pre_mode, file_system=self._fs
        )


class SetFileModeRollbackStateChanger(StateChanger):
    def __init__(
        self,
        params: SetFileModeParameters,
        pre_mode: int | None,
        file_system: FileSystem | None = None,
    ) -> None:
        self._params = params
        self._pre_mode: int | None = pre_mode if pre_mode is None else pre_mode & 0o7777
        self._fs: FileSystem = file_system or RealFileSystem()

    @property
    def pre_mode(self) -> int | None:
        return self._pre_mode

    @override
    def name(self) -> str:
        return f"set-file-mode-rollback:{self._params.path}"

    @override
    def assess_state(self) -> StateAssessment:
        path = self._params.path
        follow = self._params.follow_symlinks
        issues: list[str] = []

        if self._pre_mode is None:
            issues.append("no pre-mode captured")

        if not self._fs.exists(path):
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"nothing to roll back; {path} does not exist",
            )

        if not follow and not self._fs.supports_lchmod():
            issues.append("lchmod unsupported on this platform")

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot rollback chmod {path}",
                issues=issues,
            )

        pre_mode = self._pre_mode
        assert pre_mode is not None
        current = self._fs.stat_mode(path, follow_symlinks=follow)
        if current is not None and (current & 0o7777) == pre_mode:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"mode already restored to {oct(pre_mode)}: {path}",
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to restore mode {oct(pre_mode)} on {path}",
        )

    @override
    def transition(self) -> Result:
        path = self._params.path
        follow = self._params.follow_symlinks
        pre_mode = self._pre_mode
        if pre_mode is None:
            return Result.failure("NO_PRE_MODE", "no pre-mode captured for rollback")

        try:
            self._fs.chmod(path, pre_mode, follow_symlinks=follow)
        except FsNotFound:
            return Result.skipped(f"{path} already gone")
        except FsError as e:
            return Result.failure("CHMOD_FAILED", f"failed to chmod {path}: {e}")

        return Result.success(f"restored mode {oct(pre_mode)} on {path}")
