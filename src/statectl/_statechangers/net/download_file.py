from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, override

from statectl._interfaces.fs import FileSystem, FsError, FsNotFound
from statectl._interfaces.hashing import Hashing, HashingError
from statectl._interfaces.http import (
    HttpClient,
    HttpNetworkError,
    HttpNotFound,
    HttpServerError,
)
from statectl._modules import RealFileSystem, RealHashing, RealHttpClient
from statectl._state_changer import (
    ExistingState,
    Parameters,
    Result,
    RollbackableStateChanger,
    StateAssessment,
    StateChanger,
)


_HEX_DIGITS = set("0123456789abcdef")


@dataclass(frozen=True)
class DownloadFileParameters(Parameters):
    """Parameters for DownloadFile.

    Note: `assess_state` re-hashes the existing dest on every call when
    `sha256` is set — cheap for small files, but consider this if the
    expected payload is large and the changer is polled frequently.

    When `overwrite_mismatch=True`, an unhashable existing dest (e.g.
    transient IO error) is treated as a reason to proceed, not abort —
    the user has already opted into clobbering whatever is there.
    """

    url: str
    dest: Path
    sha256: str | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
    mode: int | None = None
    overwrite_mismatch: bool = False

    def __post_init__(self) -> None:
        if self.sha256 is not None:
            object.__setattr__(self, "sha256", self.sha256.lower())


def _looks_like_http_url(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


def _is_valid_sha256(value: str) -> bool:
    if len(value) != 64:
        return False
    return all(c in _HEX_DIGITS for c in value.lower())


class DownloadFileStateChanger(RollbackableStateChanger):
    def __init__(
        self,
        params: DownloadFileParameters,
        file_system: FileSystem | None = None,
        http_client: HttpClient | None = None,
        hashing: Hashing | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()
        self._http: HttpClient = http_client or RealHttpClient()
        self._hashing: Hashing = hashing or RealHashing()
        self._observed_sha256: str | None = None

    @property
    def params(self) -> DownloadFileParameters:
        return self._params

    @override
    def name(self) -> str:
        return f"download-file:{self._params.dest}"

    @override
    def assess_state(self) -> StateAssessment:
        p = self._params
        dest = p.dest
        issues: list[str] = []

        if not _looks_like_http_url(p.url):
            issues.append(f"unsupported scheme in url: {p.url}")
        if p.sha256 is not None and not _is_valid_sha256(p.sha256):
            issues.append(f"malformed sha256: {p.sha256}")

        dest_exists = self._fs.exists(dest)
        dest_is_file = dest_exists and self._fs.is_file(dest)
        if dest_exists and not dest_is_file:
            issues.append(f"dest exists but is not a regular file: {dest}")
        if not dest_exists:
            issues.extend(self._parent_issues(dest.parent))

        sha_ok = self._collect_sha_issues(dest_is_file, issues)

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot download {p.url} to {dest}",
                issues=issues,
            )

        if dest_is_file:
            mode_ok = p.mode is None or self._fs.stat_mode(dest) == p.mode
            content_ok = p.sha256 is None or sha_ok
            if mode_ok and content_ok:
                return StateAssessment(
                    state=ExistingState.ALREADY_APPLIED,
                    description=f"{dest} already in place",
                )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to download {p.url} to {dest}",
        )

    def _parent_issues(self, parent: Path) -> list[str]:
        if not self._fs.exists(parent):
            return [f"parent directory does not exist: {parent}"]
        if not self._fs.is_dir(parent):
            return [f"parent path is not a directory: {parent}"]
        if not self._fs.is_writable(parent):
            return [f"parent directory is not writable: {parent}"]
        return []

    def _collect_sha_issues(
        self,
        dest_is_file: bool,
        issues: list[str],
    ) -> bool:
        p = self._params
        if not dest_is_file or p.sha256 is None or not _is_valid_sha256(p.sha256):
            return True
        try:
            actual = self._hashing.sha256_file(p.dest)
        except HashingError as e:
            if p.overwrite_mismatch:
                return False
            issues.append(f"cannot hash existing dest: {e}")
            return False
        if actual == p.sha256:
            return True
        if not p.overwrite_mismatch:
            issues.append(
                f"dest exists with sha256 {actual}, expected {p.sha256}"
            )
        return False

    @override
    def transition(self) -> Result:
        p = self._params
        try:
            self._http.download_to_file(
                p.url,
                p.dest,
                headers=p.headers if p.headers else None,
            )
        except HttpNotFound as e:
            return Result.failure("HTTP_NOT_FOUND", f"download failed: {e}")
        except HttpServerError as e:
            return Result.failure("HTTP_SERVER_ERROR", f"download failed: {e}")
        except HttpNetworkError as e:
            return Result.failure("HTTP_NETWORK_ERROR", f"download failed: {e}")
        except FsError as e:
            return Result.failure("WRITE_FAILED", f"failed to write {p.dest}: {e}")

        try:
            actual = self._hashing.sha256_file(p.dest)
        except HashingError as e:
            return Result.failure(
                "HASH_FAILED", f"could not hash {p.dest} after download: {e}"
            )
        self._observed_sha256 = actual

        if p.sha256 is not None and actual != p.sha256:
            unlink_error = self._try_unlink(p.dest)
            self._observed_sha256 = None
            if unlink_error is None:
                detail = f"removed {p.dest}"
            else:
                detail = (
                    f"leftover file at {p.dest} could not be removed: {unlink_error}"
                )
            return Result.failure(
                "CHECKSUM_MISMATCH",
                f"downloaded sha256 {actual}, expected {p.sha256} ({detail})",
            )

        if p.mode is not None:
            try:
                self._fs.chmod(p.dest, p.mode)
            except FsError as e:
                return Result.failure(
                    "CHMOD_FAILED", f"failed to chmod {p.dest}: {e}"
                )

        return Result.success(f"downloaded {p.url} -> {p.dest}")

    def _try_unlink(self, path: Path) -> FsError | None:
        try:
            self._fs.delete_file(path)
        except FsNotFound:
            return None
        except FsError as e:
            return e
        return None

    @override
    def rollback(self) -> StateChanger:
        return DownloadFileRollbackStateChanger(
            self._params,
            expected_sha256=self._observed_sha256,
            file_system=self._fs,
            hashing=self._hashing,
        )


class DownloadFileRollbackStateChanger(StateChanger):
    def __init__(
        self,
        params: DownloadFileParameters,
        *,
        expected_sha256: str | None = None,
        file_system: FileSystem | None = None,
        hashing: Hashing | None = None,
    ) -> None:
        self._params = params
        self._expected_sha256: str | None = expected_sha256
        self._fs: FileSystem = file_system or RealFileSystem()
        self._hashing: Hashing = hashing or RealHashing()

    @override
    def name(self) -> str:
        return f"download-file-rollback:{self._params.dest}"

    @override
    def assess_state(self) -> StateAssessment:
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

        if not issues and self._expected_sha256 is not None:
            try:
                current = self._hashing.sha256_file(dest)
            except HashingError as e:
                issues.append(f"cannot hash {dest}: {e}")
            else:
                if current != self._expected_sha256:
                    issues.append(
                        f"dest drifted, refusing to delete: sha256 {current}, "
                        f"expected {self._expected_sha256}"
                    )

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

    @override
    def transition(self) -> Result:
        try:
            self._fs.delete_file(self._params.dest)
        except FsNotFound:
            return Result.skipped(f"{self._params.dest} already gone")
        except FsError as e:
            return Result.failure(
                "UNLINK_FAILED", f"failed to remove {self._params.dest}: {e}"
            )
        return Result.success(f"removed {self._params.dest}")
