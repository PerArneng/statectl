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
class CopyFileParameters(Parameters):
    src: Path
    dest: Path
    mode: int | None = None
    overwrite: bool = False
    preserve_mtime: bool = False


def _mode_in_range(mode: int) -> bool:
    return 0 <= mode <= 0o7777


class CopyFileStateChanger(RollbackableStateChanger):
    def __init__(
        self,
        params: CopyFileParameters,
        file_system: FileSystem | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()
        self._dest_existed: bool = False
        self._captured_pre_image: bytes | None = None

    @property
    def params(self) -> CopyFileParameters:
        return self._params

    @override
    def name(self) -> str:
        return f"copy-file:{self._params.src}->{self._params.dest}"

    @override
    def assess_state(self) -> StateAssessment:
        src = self._params.src
        dest = self._params.dest
        issues = self._precondition_issues()
        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot copy {src} -> {dest}",
                issues=issues,
            )

        if self._fs.exists(dest):
            return self._assess_when_dest_exists()

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to copy {src} -> {dest}",
        )

    def _precondition_issues(self) -> list[str]:
        src = self._params.src
        dest = self._params.dest
        mode = self._params.mode
        issues: list[str] = []

        if mode is not None and not _mode_in_range(mode):
            issues.append(f"mode out of range: {oct(mode)} (expected 0o000..0o7777)")

        if not self._fs.exists(src):
            issues.append(f"src does not exist: {src}")
        elif not self._fs.is_file(src):
            issues.append(f"src is not a regular file: {src}")

        parent = dest.parent
        if not self._fs.exists(parent):
            issues.append(f"dest parent directory does not exist: {parent}")
        elif not self._fs.is_dir(parent):
            issues.append(f"dest parent is not a directory: {parent}")
        elif not self._fs.is_writable(parent):
            issues.append(f"dest parent directory is not writable: {parent}")

        if self._fs.exists(dest) and not self._fs.is_file(dest):
            issues.append(f"dest exists and is not a regular file: {dest}")

        return issues

    def _assess_when_dest_exists(self) -> StateAssessment:
        src = self._params.src
        dest = self._params.dest
        mode = self._params.mode

        try:
            src_bytes = self._fs.read_binary_file(src)
            dest_bytes = self._fs.read_binary_file(dest)
        except FsError as e:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot compare {src} and {dest}",
                issues=[f"cannot read for comparison: {e}"],
            )

        if src_bytes != dest_bytes:
            if self._params.overwrite:
                return StateAssessment(
                    state=ExistingState.READY,
                    description=f"ready to overwrite {dest}",
                )
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"dest exists with different content: {dest}",
                issues=[f"dest exists with different content: {dest}"],
            )

        if mode is None:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"dest already matches src: {dest}",
            )
        current_mode = self._fs.stat_mode(dest)
        if current_mode is not None and (current_mode & 0o7777) == mode:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"dest already matches src and mode {oct(mode)}: {dest}",
            )
        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to chmod {dest} to {oct(mode)}",
        )

    @override
    def transition(self) -> Result:
        src = self._params.src
        dest = self._params.dest
        mode = self._params.mode

        dest_existed = self._fs.exists(dest)
        pre_image: bytes | None = None
        if dest_existed:
            try:
                pre_image = self._fs.read_binary_file(dest)
            except FsError as e:
                return Result.failure(
                    "READ_FAILED", f"failed to read pre-image of {dest}: {e}"
                )

        try:
            self._fs.copy_file(src, dest, preserve_mtime=self._params.preserve_mtime)
        except FsNotFound:
            return Result.failure(
                "SRC_VANISHED", f"src vanished between assess and copy: {src}"
            )
        except FsError as e:
            code = "READ_FAILED" if not self._fs.exists(src) else "WRITE_FAILED"
            return Result.failure(code, f"failed to copy {src} -> {dest}: {e}")

        if mode is not None:
            try:
                self._fs.chmod(dest, mode)
            except FsError as e:
                return Result.failure("CHMOD_FAILED", f"failed to chmod {dest}: {e}")

        self._dest_existed = dest_existed
        self._captured_pre_image = pre_image

        details: dict[str, str] = {"dest_existed": str(dest_existed)}
        return Result(
            status=ResultStatus.SUCCESS,
            code="OK",
            message=f"copied {src} -> {dest}",
            details=details,
        )

    @override
    def rollback(self) -> StateChanger:
        return CopyFileRollbackStateChanger(
            self._params,
            dest_existed=self._dest_existed,
            pre_image=self._captured_pre_image,
            file_system=self._fs,
        )


class CopyFileRollbackStateChanger(StateChanger):
    def __init__(
        self,
        params: CopyFileParameters,
        dest_existed: bool,
        pre_image: bytes | None,
        file_system: FileSystem | None = None,
    ) -> None:
        self._params = params
        self._dest_existed = dest_existed
        self._pre_image = pre_image
        self._fs: FileSystem = file_system or RealFileSystem()

    @property
    def dest_existed(self) -> bool:
        return self._dest_existed

    @property
    def pre_image(self) -> bytes | None:
        return self._pre_image

    @override
    def name(self) -> str:
        return f"copy-file-rollback:{self._params.dest}"

    @override
    def assess_state(self) -> StateAssessment:
        if not self._dest_existed:
            return self._assess_delete()
        return self._assess_restore()

    def _assess_delete(self) -> StateAssessment:
        dest = self._params.dest
        if not self._fs.exists(dest):
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"nothing to roll back; {dest} does not exist",
            )
        issues: list[str] = []
        if not self._fs.is_file(dest):
            issues.append(f"refusing to remove non-file path: {dest}")
        if not self._fs.is_writable(dest.parent):
            issues.append(f"parent directory is not writable: {dest.parent}")
        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot remove {dest}",
                issues=issues,
            )
        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to remove {dest}",
        )

    def _assess_restore(self) -> StateAssessment:
        dest = self._params.dest
        if self._pre_image is None:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot roll back {dest}",
                issues=[f"dest existed but no pre-image captured for {dest}"],
            )

        precondition = self._restore_precondition()
        if precondition is not None:
            return precondition

        if not self._fs.exists(dest):
            return StateAssessment(
                state=ExistingState.READY,
                description=f"ready to restore pre-image at {dest}",
            )

        try:
            current = self._fs.read_binary_file(dest)
        except FsError as e:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot read {dest}",
                issues=[f"cannot read existing file: {e}"],
            )

        return self._classify_restore(current)

    def _restore_precondition(self) -> StateAssessment | None:
        dest = self._params.dest
        if not self._fs.exists(dest):
            return None
        if not self._fs.is_file(dest):
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot restore {dest}",
                issues=[f"path is not a regular file: {dest}"],
            )
        if not self._fs.is_writable(dest.parent):
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot restore {dest}",
                issues=[f"parent directory is not writable: {dest.parent}"],
            )
        return None

    def _classify_restore(self, current: bytes) -> StateAssessment:
        dest = self._params.dest
        if current == self._pre_image:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"dest already matches pre-image at {dest}",
            )

        try:
            src_bytes = (
                self._fs.read_binary_file(self._params.src)
                if self._fs.exists(self._params.src)
                else None
            )
        except FsError:
            src_bytes = None
        if src_bytes is not None and current == src_bytes:
            return StateAssessment(
                state=ExistingState.READY,
                description=f"ready to restore pre-image at {dest}",
            )

        return StateAssessment(
            state=ExistingState.INVALID,
            description=f"dest drifted at {dest}",
            issues=[
                f"dest content matches neither pre-image nor src at {dest}; refusing to overwrite"
            ],
        )

    @override
    def transition(self) -> Result:
        dest = self._params.dest
        if not self._dest_existed:
            try:
                self._fs.delete_file(dest)
            except FsNotFound:
                return Result.skipped(f"{dest} already gone")
            except FsError as e:
                return Result.failure("UNLINK_FAILED", f"failed to remove {dest}: {e}")
            return Result.success(f"removed {dest}")

        if self._pre_image is None:
            return Result.failure(
                "NO_PRE_IMAGE", f"no pre-image captured for {dest}"
            )

        try:
            self._fs.write_binary_file(dest, self._pre_image)
        except FsError as e:
            return Result.failure("WRITE_FAILED", f"failed to restore {dest}: {e}")
        return Result.success(f"restored pre-image at {dest}")
