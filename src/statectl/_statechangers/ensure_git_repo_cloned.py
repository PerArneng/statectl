from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import override

from statectl._interfaces.fs import FileSystem, FsError, FsNotFound
from statectl._interfaces.process import (
    ProcessDecodeError,
    ProcessLaunchError,
    ProcessNotFound,
    ProcessResult,
    ProcessRunner,
    ProcessTimeout,
)
from statectl._modules import RealFileSystem, RealProcessRunner
from statectl._state_changer import (
    ExistingState,
    Parameters,
    Result,
    ResultStatus,
    RollbackableStateChanger,
    StateAssessment,
    StateChanger,
)


_OUTPUT_CAP = 4096
_COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_REPO_URL_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"^[A-Za-z][A-Za-z0-9+\-.]*://"),
    re.compile(r"^[\w.\-]+@[\w.\-]+:.+"),
    re.compile(r"^/[^\s]+$"),
)


def _truncate(text: str) -> str:
    if len(text) <= _OUTPUT_CAP:
        return text
    return text[:_OUTPUT_CAP] + f"...[truncated, total {len(text)} chars]"


def _is_recognized_url(url: str) -> bool:
    return any(p.match(url) for p in _REPO_URL_RES)


@dataclass(frozen=True)
class Branch:
    name: str


@dataclass(frozen=True)
class Tag:
    name: str


@dataclass(frozen=True)
class Commit:
    sha: str


GitRef = Branch | Tag | Commit


@dataclass(frozen=True)
class EnsureGitRepoClonedParameters(Parameters):
    repo_url: str
    dest_dir: Path
    ref: GitRef
    shallow: bool = False
    update_existing: bool = True


@dataclass(frozen=True)
class _ProbeError:
    message: str


def _probe(pr: ProcessRunner, argv: tuple[str, ...]) -> ProcessResult | _ProbeError:
    try:
        return pr.run(argv)
    except ProcessNotFound as e:
        return _ProbeError(f"git probe failed (not found): {e}")
    except ProcessTimeout as e:
        return _ProbeError(f"git probe timed out: {e}")
    except ProcessDecodeError as e:
        return _ProbeError(f"git probe decode error: {e}")
    except ProcessLaunchError as e:
        return _ProbeError(f"git probe launch error: {e}")


def _ref_label(ref: GitRef) -> str:
    if isinstance(ref, Branch):
        return f"branch {ref.name}"
    if isinstance(ref, Tag):
        return f"tag {ref.name}"
    return f"commit {ref.sha}"


def _ref_token(ref: GitRef) -> str:
    if isinstance(ref, Commit):
        return ref.sha
    return ref.name


def _invalid(dest_dir: Path, issues: list[str]) -> StateAssessment:
    return StateAssessment(
        state=ExistingState.INVALID,
        description=f"cannot ensure git repo {dest_dir}",
        issues=issues,
    )


class EnsureGitRepoClonedStateChanger(RollbackableStateChanger):
    def __init__(
        self,
        params: EnsureGitRepoClonedParameters,
        file_system: FileSystem | None = None,
        process_runner: ProcessRunner | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()
        self._pr: ProcessRunner = process_runner or RealProcessRunner()

    @property
    def params(self) -> EnsureGitRepoClonedParameters:
        return self._params

    @override
    def name(self) -> str:
        token = _ref_token(self._params.ref)
        return f"ensure-git-repo-cloned:{self._params.dest_dir}@{token}"

    def _validate_inputs(self) -> list[str]:
        params = self._params
        issues: list[str] = []
        if self._pr.which("git") is None:
            issues.append("git binary not on PATH")
        if not params.repo_url.strip():
            issues.append("repo_url is empty")
        elif not _is_recognized_url(params.repo_url):
            issues.append(
                f"repo_url is not a recognised git URL: {params.repo_url!r}"
            )
        if isinstance(params.ref, Commit) and not _COMMIT_SHA_RE.match(
            params.ref.sha
        ):
            issues.append(f"invalid commit SHA: {params.ref.sha!r}")
        return issues

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        issues = self._validate_inputs()
        if issues:
            return _invalid(params.dest_dir, issues)

        if not self._fs.exists(params.dest_dir):
            return StateAssessment(
                state=ExistingState.READY,
                description=(
                    f"ready to clone {params.repo_url} into {params.dest_dir}"
                ),
            )
        return self._assess_existing()

    def _assess_existing(self) -> StateAssessment:
        params = self._params
        if not self._fs.exists(params.dest_dir / ".git"):
            return _invalid(
                params.dest_dir,
                [f"dest exists but is not a git repo: {params.dest_dir}"],
            )

        origin_check = self._check_origin()
        if origin_check is not None:
            return origin_check

        return self._assess_head_and_worktree()

    def _check_origin(self) -> StateAssessment | None:
        params = self._params
        probe = _probe(
            self._pr,
            ("git", "-C", str(params.dest_dir), "remote", "get-url", "origin"),
        )
        if isinstance(probe, _ProbeError):
            return _invalid(params.dest_dir, [probe.message])
        if probe.exit_code != 0:
            return _invalid(
                params.dest_dir,
                [f"could not read origin URL: {_truncate(probe.stderr)}"],
            )
        actual = probe.stdout.strip()
        if actual != params.repo_url:
            return _invalid(
                params.dest_dir,
                [
                    f"origin URL mismatch: {actual!r}, expected "
                    f"{params.repo_url!r}"
                ],
            )
        return None

    def _assess_head_and_worktree(self) -> StateAssessment:
        params = self._params
        status_probe = _probe(
            self._pr,
            ("git", "-C", str(params.dest_dir), "status", "--porcelain"),
        )
        if isinstance(status_probe, _ProbeError):
            return _invalid(params.dest_dir, [status_probe.message])
        dirty = status_probe.exit_code == 0 and status_probe.stdout.strip() != ""

        head_match = self._head_matches_ref()
        if isinstance(head_match, _ProbeError):
            return _invalid(params.dest_dir, [head_match.message])
        if head_match:
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=(
                    f"git repo {params.dest_dir} already at "
                    f"{_ref_label(params.ref)}"
                ),
            )

        if not params.update_existing:
            return _invalid(
                params.dest_dir,
                [
                    f"HEAD does not match {_ref_label(params.ref)} and "
                    f"update_existing=False"
                ],
            )
        if dirty:
            return _invalid(
                params.dest_dir,
                [
                    f"working tree has uncommitted changes: "
                    f"{params.dest_dir}"
                ],
            )
        return StateAssessment(
            state=ExistingState.READY,
            description=(
                f"ready to update {params.dest_dir} to "
                f"{_ref_label(params.ref)}"
            ),
        )

    def _head_matches_ref(self) -> bool | _ProbeError:
        ref = self._params.ref
        if isinstance(ref, Branch):
            return self._head_matches_branch(ref)
        if isinstance(ref, Tag):
            return self._head_matches_tag(ref)
        return self._head_matches_commit(ref)

    def _head_matches_branch(self, ref: Branch) -> bool | _ProbeError:
        dest = str(self._params.dest_dir)
        current = _probe(
            self._pr, ("git", "-C", dest, "branch", "--show-current")
        )
        if isinstance(current, _ProbeError):
            return current
        if current.exit_code != 0 or current.stdout.strip() != ref.name:
            return False
        local = _probe(self._pr, ("git", "-C", dest, "rev-parse", ref.name))
        if isinstance(local, _ProbeError):
            return local
        remote = _probe(
            self._pr, ("git", "-C", dest, "rev-parse", f"origin/{ref.name}")
        )
        if isinstance(remote, _ProbeError):
            return remote
        if local.exit_code != 0 or remote.exit_code != 0:
            return False
        return local.stdout.strip() == remote.stdout.strip()

    def _head_matches_tag(self, ref: Tag) -> bool | _ProbeError:
        dest = str(self._params.dest_dir)
        head = _probe(self._pr, ("git", "-C", dest, "rev-parse", "HEAD"))
        if isinstance(head, _ProbeError):
            return head
        tag = _probe(self._pr, ("git", "-C", dest, "rev-parse", ref.name))
        if isinstance(tag, _ProbeError):
            return tag
        if head.exit_code != 0 or tag.exit_code != 0:
            return False
        return head.stdout.strip() == tag.stdout.strip()

    def _head_matches_commit(self, ref: Commit) -> bool | _ProbeError:
        dest = str(self._params.dest_dir)
        head = _probe(self._pr, ("git", "-C", dest, "rev-parse", "HEAD"))
        if isinstance(head, _ProbeError):
            return head
        if head.exit_code != 0:
            return False
        return head.stdout.strip().lower() == ref.sha.lower()

    def _run_git(
        self, argv: tuple[str, ...], failure_code: str
    ) -> tuple[ProcessResult | None, Result | None]:
        try:
            result = self._pr.run(argv)
        except ProcessNotFound as e:
            return None, Result.failure("GIT_NOT_FOUND", str(e))
        except ProcessTimeout as e:
            return None, Result.failure("PROCESS_TIMEOUT", str(e))
        except ProcessDecodeError as e:
            return None, Result.failure("PROCESS_DECODE_ERROR", str(e))
        except ProcessLaunchError as e:
            return None, Result.failure("PROCESS_LAUNCH_ERROR", str(e))
        if result.exit_code != 0:
            return result, Result(
                status=ResultStatus.FAILURE,
                code=failure_code,
                message=f"{' '.join(argv)} exited {result.exit_code}",
                details={
                    "exit_code": str(result.exit_code),
                    "stdout": _truncate(result.stdout),
                    "stderr": _truncate(result.stderr),
                },
            )
        return result, None

    @override
    def transition(self) -> Result:
        if not self._fs.exists(self._params.dest_dir):
            return self._clone_and_checkout()
        return self._fetch_and_checkout()

    def _clone_and_checkout(self) -> Result:
        params = self._params
        argv: list[str] = ["git", "clone"]
        shallow_branchlike = params.shallow and not isinstance(params.ref, Commit)
        if shallow_branchlike:
            argv += ["--depth", "1", "--branch", _ref_token(params.ref)]
        argv += [params.repo_url, str(params.dest_dir)]
        _, fail = self._run_git(tuple(argv), "GIT_CLONE_FAILED")
        if fail is not None:
            return fail
        if not shallow_branchlike:
            _, co_fail = self._run_git(
                (
                    "git",
                    "-C",
                    str(params.dest_dir),
                    "checkout",
                    _ref_token(params.ref),
                ),
                "GIT_CHECKOUT_FAILED",
            )
            if co_fail is not None:
                return co_fail
        return Result.success(
            f"cloned {params.repo_url} into {params.dest_dir} at "
            f"{_ref_label(params.ref)}"
        )

    def _fetch_and_checkout(self) -> Result:
        params = self._params
        dest = str(params.dest_dir)
        _, fetch_fail = self._run_git(
            ("git", "-C", dest, "fetch", "origin"), "GIT_FETCH_FAILED"
        )
        if fetch_fail is not None:
            return fetch_fail
        _, co_fail = self._run_git(
            ("git", "-C", dest, "checkout", _ref_token(params.ref)),
            "GIT_CHECKOUT_FAILED",
        )
        if co_fail is not None:
            return co_fail
        if isinstance(params.ref, Branch):
            _, ff_fail = self._run_git(
                (
                    "git",
                    "-C",
                    dest,
                    "merge",
                    "--ff-only",
                    f"origin/{params.ref.name}",
                ),
                "GIT_CHECKOUT_FAILED",
            )
            if ff_fail is not None:
                return ff_fail
        return Result.success(
            f"updated {params.dest_dir} to {_ref_label(params.ref)}"
        )

    @override
    def rollback(self) -> StateChanger:
        return EnsureGitRepoClonedRollbackStateChanger(
            self._params, file_system=self._fs, process_runner=self._pr
        )


class EnsureGitRepoClonedRollbackStateChanger(StateChanger):
    def __init__(
        self,
        params: EnsureGitRepoClonedParameters,
        file_system: FileSystem | None = None,
        process_runner: ProcessRunner | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()
        self._pr: ProcessRunner = process_runner or RealProcessRunner()

    @property
    def params(self) -> EnsureGitRepoClonedParameters:
        return self._params

    @override
    def name(self) -> str:
        return f"ensure-git-repo-cloned-rollback:{self._params.dest_dir}"

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        if not self._fs.exists(params.dest_dir):
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=(
                    f"nothing to roll back; {params.dest_dir} does not exist"
                ),
            )
        if self._fs.exists(params.dest_dir / ".git"):
            dirty_issue = self._dirty_issue()
            if dirty_issue is not None:
                return StateAssessment(
                    state=ExistingState.INVALID,
                    description=f"cannot roll back {params.dest_dir}",
                    issues=[dirty_issue],
                )
        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to delete {params.dest_dir}",
        )

    def _dirty_issue(self) -> str | None:
        params = self._params
        if self._pr.which("git") is None:
            return "git binary not on PATH"
        status = _probe(
            self._pr,
            ("git", "-C", str(params.dest_dir), "status", "--porcelain"),
        )
        if isinstance(status, _ProbeError):
            return status.message
        if status.exit_code == 0 and status.stdout.strip():
            return (
                f"working tree has uncommitted changes: {params.dest_dir}"
            )
        return None

    @override
    def transition(self) -> Result:
        params = self._params
        try:
            self._fs.delete_folder(params.dest_dir, recursive=True)
        except FsNotFound:
            return Result.skipped(f"{params.dest_dir} already gone")
        except FsError as e:
            return Result.failure(
                "RMTREE_FAILED",
                f"failed to delete {params.dest_dir}: {e}",
            )
        return Result.success(f"deleted {params.dest_dir}")
