from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

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
    def __init__(self, params: NewTextFileParameters) -> None:
        self._params = params

    def name(self) -> str:
        return f"new-text-file:{self._params.path}"

    def assess_state(self) -> StateAssessment:
        path = self._params.path
        parent = path.parent
        issues: list[str] = []

        if not parent.exists():
            issues.append(f"parent directory does not exist: {parent}")
        elif not parent.is_dir():
            issues.append(f"parent path is not a directory: {parent}")
        elif not os.access(parent, os.W_OK):
            issues.append(f"parent directory is not writable: {parent}")

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot create {path}",
                issues=issues,
            )

        if path.exists():
            if not path.is_file():
                return StateAssessment(
                    state=ExistingState.INVALID,
                    description=f"path exists but is not a regular file: {path}",
                    issues=[f"target path exists but is not a regular file: {path}"],
                )
            try:
                existing = path.read_text(encoding=self._params.encoding)
            except (OSError, UnicodeDecodeError) as e:
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

    def transition(self) -> Result:
        try:
            self._params.path.write_text(self._params.text, encoding=self._params.encoding)
        except OSError as e:
            return Result.failure("WRITE_FAILED", f"failed to write {self._params.path}: {e}")
        return Result.success(f"wrote {self._params.path}")

    def rollback(self) -> StateChanger:
        return NewTextFileRollbackStateChanger(self._params)


class NewTextFileRollbackStateChanger(StateChanger):
    def __init__(self, params: NewTextFileParameters) -> None:
        self._params = params

    def name(self) -> str:
        return f"new-text-file-rollback:{self._params.path}"

    def assess_state(self) -> StateAssessment:
        path = self._params.path
        if not path.exists():
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"nothing to roll back; {path} does not exist",
            )

        issues: list[str] = []
        if not path.is_file():
            issues.append(f"refusing to remove non-file path: {path}")
        if not os.access(path.parent, os.W_OK):
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

    def transition(self) -> Result:
        try:
            self._params.path.unlink()
        except FileNotFoundError:
            return Result.skipped(f"{self._params.path} already gone")
        except OSError as e:
            return Result.failure("UNLINK_FAILED", f"failed to remove {self._params.path}: {e}")
        return Result.success(f"removed {self._params.path}")
