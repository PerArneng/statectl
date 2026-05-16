from __future__ import annotations

import hashlib
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
    ResultStatus,
    RollbackableStateChanger,
    StateAssessment,
    StateChanger,
)


@dataclass(frozen=True)
class LiteralMatch:
    needle: str
    expected_count: int
    replacement: str


@dataclass(frozen=True)
class RegexMatch:
    pattern: str
    expected_count: int
    replacement: str


Match = LiteralMatch | RegexMatch


@dataclass(frozen=True)
class ReplaceInFileParameters(Parameters):
    path: Path
    match: Match
    encoding: str = "utf-8"


def _compile_regex(pattern: str) -> tuple[re.Pattern[str] | None, str | None]:
    try:
        return re.compile(pattern), None
    except re.error as e:
        return None, f"bad regex: {e}"


def _count_matches(text: str, match: Match) -> tuple[int | None, str | None]:
    """Return (count, issue). issue is non-None for invalid regex."""
    if isinstance(match, LiteralMatch):
        if match.needle == "":
            return 0, None
        return text.count(match.needle), None
    compiled, issue = _compile_regex(match.pattern)
    if compiled is None:
        return None, issue
    return len(compiled.findall(text)), None


def _apply(text: str, match: Match) -> tuple[str | None, str | None]:
    """Apply the substitution. Returns (new_text, issue)."""
    if match.expected_count <= 0:
        return text, None
    if isinstance(match, LiteralMatch):
        return text.replace(match.needle, match.replacement, match.expected_count), None
    compiled, issue = _compile_regex(match.pattern)
    if compiled is None:
        return None, issue
    return compiled.sub(match.replacement, text, count=match.expected_count), None


def _sha256(text: str, encoding: str) -> str:
    return hashlib.sha256(text.encode(encoding, errors="replace")).hexdigest()


class ReplaceInFileStateChanger(RollbackableStateChanger):
    def __init__(
        self,
        params: ReplaceInFileParameters,
        file_system: FileSystem | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()
        self._captured_pre_image: str | None = None

    @property
    def params(self) -> ReplaceInFileParameters:
        return self._params

    @override
    def name(self) -> str:
        return f"replace-in-file:{self._params.path}"

    @override
    def assess_state(self) -> StateAssessment:
        path = self._params.path
        issues = self._precondition_issues()
        if issues:
            return self._invalid(issues)

        try:
            text = self._fs.read_text_file(path, encoding=self._params.encoding)
        except FsError as e:
            return self._invalid([f"decode failed: {e}"])

        new_text, apply_issue = _apply(text, self._params.match)
        if apply_issue is not None:
            return self._invalid([apply_issue])
        assert new_text is not None

        if new_text == text:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"substitution already in place in {path}",
            )

        count, count_issue = _count_matches(text, self._params.match)
        if count_issue is not None:
            return self._invalid([count_issue])
        assert count is not None
        if count != self._params.match.expected_count:
            return self._invalid(
                [f"expected {self._params.match.expected_count} matches, found {count}"]
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to substitute in {path}",
        )

    def _precondition_issues(self) -> list[str]:
        path = self._params.path
        match = self._params.match
        issues: list[str] = []

        if not self._fs.exists(path):
            issues.append(f"path does not exist: {path}")
        elif not self._fs.is_file(path):
            issues.append(f"path is not a regular file: {path}")
        elif not self._fs.is_writable(path):
            issues.append(f"path is not writable: {path}")

        if match.expected_count < 0:
            issues.append(f"expected_count must be >= 0, got {match.expected_count}")

        if isinstance(match, RegexMatch):
            _, regex_issue = _compile_regex(match.pattern)
            if regex_issue is not None:
                issues.append(regex_issue)

        if isinstance(match, LiteralMatch) and match.needle == "":
            issues.append("literal needle must not be empty")

        return issues

    def _invalid(self, issues: list[str]) -> StateAssessment:
        return StateAssessment(
            state=ExistingState.INVALID,
            description=f"cannot replace in {self._params.path}",
            issues=issues,
        )

    @override
    def transition(self) -> Result:
        path = self._params.path
        try:
            text = self._fs.read_text_file(path, encoding=self._params.encoding)
        except FsError as e:
            return Result.failure("READ_FAILED", f"failed to read {path}: {e}")

        count, count_issue = _count_matches(text, self._params.match)
        if count_issue is not None or count != self._params.match.expected_count:
            return Result.failure(
                "MATCH_VANISHED",
                f"match count changed: expected {self._params.match.expected_count}, found {count}",
            )

        new_text, apply_issue = _apply(text, self._params.match)
        if apply_issue is not None or new_text is None:
            return Result.failure("MATCH_VANISHED", f"apply failed: {apply_issue}")

        if new_text == text:
            return Result.skipped(f"no change required in {path}")

        pre_sha = _sha256(text, self._params.encoding)
        try:
            self._fs.write_text_file(path, new_text, encoding=self._params.encoding)
        except FsError as e:
            return Result.failure("WRITE_FAILED", f"failed to write {path}: {e}")

        self._captured_pre_image = text
        return Result(
            status=ResultStatus.SUCCESS,
            code="OK",
            message=f"substituted in {path}",
            details={"pre_sha256": pre_sha},
        )

    @override
    def rollback(self) -> StateChanger:
        return ReplaceInFileRollbackStateChanger(
            self._params,
            pre_image=self._captured_pre_image,
            file_system=self._fs,
        )


class ReplaceInFileRollbackStateChanger(StateChanger):
    def __init__(
        self,
        params: ReplaceInFileParameters,
        pre_image: str | None = None,
        file_system: FileSystem | None = None,
    ) -> None:
        self._params = params
        self._pre_image = pre_image
        self._fs: FileSystem = file_system or RealFileSystem()

    @override
    def name(self) -> str:
        return f"replace-in-file-rollback:{self._params.path}"

    @override
    def assess_state(self) -> StateAssessment:
        path = self._params.path

        if self._pre_image is None:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"nothing to roll back; no pre-image captured for {path}",
            )

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
                description=f"cannot roll back replace in {path}",
                issues=issues,
            )

        try:
            current = self._fs.read_text_file(path, encoding=self._params.encoding)
        except FsError as e:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot read {path}",
                issues=[f"cannot read existing file: {e}"],
            )

        if current == self._pre_image:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"file already matches pre-image at {path}",
            )

        expected_post, _ = _apply(self._pre_image, self._params.match)
        if expected_post is not None and current == expected_post:
            return StateAssessment(
                state=ExistingState.READY,
                description=f"ready to restore pre-image at {path}",
            )

        return StateAssessment(
            state=ExistingState.INVALID,
            description=f"file drifted at {path}",
            issues=[
                f"file content matches neither pre- nor post-image at {path}; refusing to overwrite"
            ],
        )

    @override
    def transition(self) -> Result:
        path = self._params.path
        if self._pre_image is None:
            return Result.skipped(f"no pre-image captured for {path}")
        try:
            self._fs.read_text_file(path, encoding=self._params.encoding)
        except FsNotFound:
            return Result.skipped(f"{path} already gone")
        except FsError as e:
            return Result.failure("READ_FAILED", f"failed to read {path}: {e}")

        try:
            self._fs.write_text_file(path, self._pre_image, encoding=self._params.encoding)
        except FsError as e:
            return Result.failure("WRITE_FAILED", f"failed to write {path}: {e}")
        return Result.success(f"restored pre-image at {path}")
