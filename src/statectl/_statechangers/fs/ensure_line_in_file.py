from __future__ import annotations

import re
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
class AfterRegex:
    pattern: str


@dataclass(frozen=True)
class BeforeRegex:
    pattern: str


@dataclass(frozen=True)
class AtEnd:
    pass


@dataclass(frozen=True)
class AtStart:
    pass


Placement = AfterRegex | BeforeRegex | AtEnd | AtStart


@dataclass(frozen=True)
class EnsureLineInFileParameters(Parameters):
    path: Path
    line: str
    placement: Placement
    strict_anchor: bool = True
    encoding: str = "utf-8"


def _expected_line_present_at_placement(
    lines: list[str],
    placement: Placement,
    anchor_index: int | None,
    line: str,
) -> bool:
    if isinstance(placement, AtStart):
        return len(lines) > 0 and lines[0] == line
    if isinstance(placement, AtEnd):
        return len(lines) > 0 and lines[-1] == line
    if isinstance(placement, AfterRegex):
        assert anchor_index is not None
        return anchor_index + 1 < len(lines) and lines[anchor_index + 1] == line
    assert anchor_index is not None
    return anchor_index > 0 and lines[anchor_index - 1] == line


def _insertion_index(
    lines: list[str],
    placement: Placement,
    anchor_index: int | None,
) -> int:
    if isinstance(placement, AtStart):
        return 0
    if isinstance(placement, AtEnd):
        return len(lines)
    assert anchor_index is not None
    if isinstance(placement, AfterRegex):
        return anchor_index + 1
    return anchor_index


def _find_anchor_indices(lines: list[str], pattern: re.Pattern[str]) -> list[int]:
    return [i for i, ln in enumerate(lines) if pattern.search(ln)]


def _join_lines(lines: list[str]) -> str:
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def _resolve_anchor(
    placement: Placement,
    lines: list[str],
) -> tuple[int | None, str | None]:
    """Return (anchor_index, issue). issue is non-None if the placement is
    anchored and matching produced zero or multiple results, or the regex is
    invalid. For non-anchored placements returns (None, None)."""
    if not isinstance(placement, (AfterRegex, BeforeRegex)):
        return None, None
    try:
        compiled = re.compile(placement.pattern)
    except re.error as e:
        return None, f"invalid anchor regex {placement.pattern!r}: {e}"
    matches = _find_anchor_indices(lines, compiled)
    if len(matches) == 0:
        return None, f"anchor not found: {placement.pattern}"
    if len(matches) > 1:
        positions = ", ".join(str(i + 1) for i in matches)
        return None, (
            f"anchor is ambiguous, matches {len(matches)} lines at: {positions}"
        )
    return matches[0], None


class EnsureLineInFileStateChanger(RollbackableStateChanger):
    def __init__(
        self,
        params: EnsureLineInFileParameters,
        file_system: FileSystem | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()

    @property
    def params(self) -> EnsureLineInFileParameters:
        return self._params

    @override
    def name(self) -> str:
        return f"ensure-line-in-file:{self._params.path}"

    @override
    def assess_state(self) -> StateAssessment:
        path = self._params.path
        line = self._params.line
        placement = self._params.placement

        issues = self._precondition_issues()
        if "\n" in line or "\r" in line:
            issues.append("line must not contain newline characters")
        if issues:
            return self._invalid(issues)

        try:
            text = self._fs.read_text_file(path, encoding=self._params.encoding)
        except FsError as e:
            return self._invalid([f"cannot read existing file to compare: {e}"])

        lines = text.splitlines()
        anchor_index, anchor_issue = _resolve_anchor(placement, lines)
        if anchor_issue is not None:
            return self._invalid([anchor_issue])

        if _expected_line_present_at_placement(lines, placement, anchor_index, line):
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"line already at expected position in {path}",
            )

        elsewhere = [i + 1 for i, ln in enumerate(lines) if ln == line]
        if elsewhere:
            if not self._params.strict_anchor:
                return StateAssessment(
                    state=ExistingState.ALREADY_APPLIED,
                    description=f"line already present in {path}",
                )
            positions = ", ".join(str(p) for p in elsewhere)
            return self._invalid(
                [f"line already exists at wrong location: line {positions}"]
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to ensure line in {path}",
        )

    def _precondition_issues(self) -> list[str]:
        path = self._params.path
        issues: list[str] = []
        if not self._fs.exists(path):
            issues.append(f"path does not exist: {path}")
            return issues
        if not self._fs.is_file(path):
            issues.append(f"path is not a regular file: {path}")
            return issues
        if not self._fs.is_writable(path):
            issues.append(f"path is not writable: {path}")
        return issues

    def _invalid(self, issues: list[str]) -> StateAssessment:
        return StateAssessment(
            state=ExistingState.INVALID,
            description=f"cannot ensure line in {self._params.path}",
            issues=issues,
        )

    @override
    def transition(self) -> Result:
        path = self._params.path
        try:
            text = self._fs.read_text_file(path, encoding=self._params.encoding)
        except FsError as e:
            return Result.failure("READ_FAILED", f"failed to read {path}: {e}")

        lines = text.splitlines()
        placement = self._params.placement
        anchor_index, anchor_issue = _resolve_anchor(placement, lines)
        if anchor_issue is not None:
            return Result.failure(
                "ANCHOR_VANISHED",
                f"anchor no longer matches uniquely: {anchor_issue}",
            )

        insert_idx = _insertion_index(lines, placement, anchor_index)
        new_lines = lines[:insert_idx] + [self._params.line] + lines[insert_idx:]

        try:
            self._fs.write_text_file(
                path, _join_lines(new_lines), encoding=self._params.encoding
            )
        except FsError as e:
            return Result.failure("WRITE_FAILED", f"failed to write {path}: {e}")
        return Result.success(f"inserted line in {path}")

    @override
    def rollback(self) -> StateChanger:
        return EnsureLineInFileRollbackStateChanger(self._params, file_system=self._fs)


def _placement_line_index(
    lines: list[str],
    placement: Placement,
    line: str,
) -> int | None:
    """Return the index in `lines` of the line at the placement-implied
    position, or None if it isn't there."""
    if isinstance(placement, AtStart):
        return 0 if lines and lines[0] == line else None
    if isinstance(placement, AtEnd):
        return len(lines) - 1 if lines and lines[-1] == line else None
    try:
        compiled = re.compile(placement.pattern)
    except re.error:
        return None
    matches = _find_anchor_indices(lines, compiled)
    if len(matches) != 1:
        return None
    anchor = matches[0]
    if isinstance(placement, AfterRegex):
        if anchor + 1 < len(lines) and lines[anchor + 1] == line:
            return anchor + 1
        return None
    if anchor > 0 and lines[anchor - 1] == line:
        return anchor - 1
    return None


class EnsureLineInFileRollbackStateChanger(StateChanger):
    def __init__(
        self,
        params: EnsureLineInFileParameters,
        file_system: FileSystem | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()

    @override
    def name(self) -> str:
        return f"ensure-line-in-file-rollback:{self._params.path}"

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
            issues.append(f"path is not a regular file: {path}")
        elif not self._fs.is_writable(path):
            issues.append(f"path is not writable: {path}")
        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot roll back line in {path}",
                issues=issues,
            )

        try:
            text = self._fs.read_text_file(path, encoding=self._params.encoding)
        except FsError as e:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot read {path}",
                issues=[f"cannot read existing file: {e}"],
            )

        lines = text.splitlines()
        if _placement_line_index(lines, self._params.placement, self._params.line) is None:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"line not present at placement in {path}",
            )
        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to remove line from {path}",
        )

    @override
    def transition(self) -> Result:
        path = self._params.path
        try:
            text = self._fs.read_text_file(path, encoding=self._params.encoding)
        except FsNotFound:
            return Result.skipped(f"{path} already gone")
        except FsError as e:
            return Result.failure("READ_FAILED", f"failed to read {path}: {e}")

        lines = text.splitlines()
        target = _placement_line_index(lines, self._params.placement, self._params.line)
        if target is None:
            return Result.skipped(f"line not present at placement in {path}")

        new_lines = lines[:target] + lines[target + 1 :]
        try:
            self._fs.write_text_file(
                path, _join_lines(new_lines), encoding=self._params.encoding
            )
        except FsError as e:
            return Result.failure("WRITE_FAILED", f"failed to write {path}: {e}")
        return Result.success(f"removed line from {path}")
