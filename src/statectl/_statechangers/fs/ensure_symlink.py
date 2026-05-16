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
class EnsureSymlinkParameters(Parameters):
    link_path: Path
    target: Path
    overwrite_non_symlink: bool = False
    allow_dangling: bool = True


class EnsureSymlinkStateChanger(RollbackableStateChanger):
    def __init__(
        self,
        params: EnsureSymlinkParameters,
        file_system: FileSystem | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()

    @property
    def params(self) -> EnsureSymlinkParameters:
        return self._params

    @override
    def name(self) -> str:
        return f"ensure-symlink:{self._params.link_path}->{self._params.target}"

    @override
    def assess_state(self) -> StateAssessment:
        link_path = self._params.link_path
        target = self._params.target
        parent = link_path.parent
        issues: list[str] = []

        if not self._fs.exists(parent):
            issues.append(f"parent missing: {parent}")
        elif not self._fs.is_dir(parent):
            issues.append(f"parent is not a directory: {parent}")
        elif not self._fs.is_writable(parent):
            issues.append(f"parent not writable: {parent}")

        link_exists = self._fs.exists(link_path) or self._fs.is_symlink(link_path)
        link_is_symlink = self._fs.is_symlink(link_path)
        if link_exists and not link_is_symlink and not self._params.overwrite_non_symlink:
            issues.append(f"path exists and is not a symlink: {link_path}")

        if not self._params.allow_dangling and not self._fs.exists(target):
            issues.append(f"target does not exist: {target}")

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot ensure symlink {link_path}",
                issues=issues,
            )

        if link_is_symlink:
            try:
                current_target = self._fs.read_symlink(link_path)
            except FsError as e:
                return StateAssessment(
                    state=ExistingState.INVALID,
                    description=f"cannot read existing symlink at {link_path}",
                    issues=[f"cannot read existing symlink: {e}"],
                )
            if current_target == target:
                return StateAssessment(
                    state=ExistingState.ALREADY_APPLIED,
                    description=f"symlink already in place: {link_path} -> {target}",
                )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to ensure symlink {link_path} -> {target}",
        )

    @override
    def transition(self) -> Result:
        link_path = self._params.link_path
        target = self._params.target

        if self._fs.is_symlink(link_path):
            try:
                self._fs.delete_file(link_path)
            except FsNotFound:
                return Result.failure(
                    "LINK_VANISHED",
                    f"symlink vanished mid-replace: {link_path}",
                )
            except FsError as e:
                return Result.failure(
                    "UNLINK_FAILED",
                    f"failed to unlink existing symlink {link_path}: {e}",
                )
        elif self._fs.exists(link_path):
            if not self._params.overwrite_non_symlink:
                return Result.failure(
                    "NON_SYMLINK_PRESENT",
                    f"path exists and is not a symlink: {link_path}",
                )
            try:
                self._fs.delete_file(link_path)
            except FsNotFound:
                pass
            except FsError as e:
                return Result.failure(
                    "UNLINK_FAILED",
                    f"failed to remove existing path {link_path}: {e}",
                )

        try:
            self._fs.create_symlink(link_path, target)
        except FsError as e:
            return Result.failure(
                "SYMLINK_FAILED",
                f"failed to create symlink {link_path} -> {target}: {e}",
            )
        return Result.success(f"linked {link_path} -> {target}")

    @override
    def rollback(self) -> StateChanger:
        return EnsureSymlinkRollbackStateChanger(self._params, file_system=self._fs)


class EnsureSymlinkRollbackStateChanger(StateChanger):
    def __init__(
        self,
        params: EnsureSymlinkParameters,
        file_system: FileSystem | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()

    @override
    def name(self) -> str:
        return f"ensure-symlink-rollback:{self._params.link_path}"

    @override
    def assess_state(self) -> StateAssessment:
        link_path = self._params.link_path
        target = self._params.target

        if not self._fs.exists(link_path) and not self._fs.is_symlink(link_path):
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"nothing to roll back; {link_path} does not exist",
            )

        issues: list[str] = []
        if not self._fs.is_symlink(link_path):
            issues.append(f"path exists and is not a symlink: {link_path}")
        else:
            try:
                current_target = self._fs.read_symlink(link_path)
            except FsError as e:
                issues.append(f"cannot read existing symlink: {e}")
            else:
                if current_target != target:
                    issues.append(
                        f"symlink points elsewhere, not the one we created: "
                        f"{link_path} -> {current_target}"
                    )

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot roll back symlink {link_path}",
                issues=issues,
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to remove symlink {link_path}",
        )

    @override
    def transition(self) -> Result:
        link_path = self._params.link_path
        try:
            self._fs.delete_file(link_path)
        except FsNotFound:
            return Result.skipped(f"{link_path} already gone")
        except FsError as e:
            return Result.failure("UNLINK_FAILED", f"failed to remove symlink {link_path}: {e}")
        return Result.success(f"removed symlink {link_path}")
