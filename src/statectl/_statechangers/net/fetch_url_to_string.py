from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, override
from urllib.parse import urlsplit

from statectl._interfaces.clock import Clock
from statectl._interfaces.fs import FileSystem, FsError, FsNotFound
from statectl._interfaces.http import (
    HttpClient,
    HttpError,
    HttpNetworkError,
    HttpNotFound,
    HttpServerError,
)
from statectl._modules import RealClock, RealFileSystem, RealHttpClient
from statectl._state_changer import (
    ExistingState,
    Parameters,
    Result,
    RollbackableStateChanger,
    StateAssessment,
    StateChanger,
)


@dataclass(frozen=True)
class FetchUrlToStringParameters(Parameters):
    url: str
    cache_path: Path
    max_age: timedelta | None = None
    headers: Mapping[str, str] = field(default_factory=dict)
    encoding: str = "utf-8"
    timeout: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "headers", MappingProxyType(dict(self.headers))
        )


def _is_http_url(url: str) -> bool:
    scheme = urlsplit(url).scheme.lower()
    return scheme in ("http", "https")


class FetchUrlToStringStateChanger(RollbackableStateChanger):
    def __init__(
        self,
        params: FetchUrlToStringParameters,
        file_system: FileSystem | None = None,
        http_client: HttpClient | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()
        self._http: HttpClient = http_client or RealHttpClient()
        self._clock: Clock = clock or RealClock()

    @property
    def params(self) -> FetchUrlToStringParameters:
        return self._params

    @override
    def name(self) -> str:
        return f"fetch-url-to-string:{self._params.cache_path}"

    @override
    def assess_state(self) -> StateAssessment:
        params = self._params
        cache_path = params.cache_path
        issues: list[str] = []

        if not _is_http_url(params.url):
            issues.append(f"url scheme must be http or https: {params.url}")

        parent = cache_path.parent
        if not self._fs.exists(parent):
            issues.append(f"cache_path parent directory does not exist: {parent}")
        elif not self._fs.is_dir(parent):
            issues.append(f"cache_path parent is not a directory: {parent}")
        elif not self._fs.is_writable(parent):
            issues.append(f"cache_path parent is not writable: {parent}")

        cache_exists = self._fs.exists(cache_path)
        if cache_exists and not self._fs.is_file(cache_path):
            issues.append(f"cache path is not a regular file: {cache_path}")

        if issues:
            return StateAssessment(
                state=ExistingState.INVALID,
                description=f"cannot fetch {params.url} to {cache_path}",
                issues=issues,
            )

        if cache_exists and self._is_cache_fresh():
            return StateAssessment(
                state=ExistingState.ALREADY_APPLIED,
                description=f"cache is fresh: {cache_path}",
            )

        return StateAssessment(
            state=ExistingState.READY,
            description=f"ready to fetch {params.url} to {cache_path}",
        )

    def _is_cache_fresh(self) -> bool:
        params = self._params
        if params.max_age is None:
            return True
        mtime = self._fs.mtime(params.cache_path)
        if mtime is None:
            return False
        age = self._clock.now() - mtime
        return age <= params.max_age

    @override
    def transition(self) -> Result:
        params = self._params
        try:
            body = self._http.get_bytes(
                params.url, headers=params.headers, timeout=params.timeout
            )
        except HttpNotFound as e:
            return Result.failure("HTTP_NOT_FOUND", str(e))
        except HttpServerError as e:
            return Result.failure("HTTP_SERVER_ERROR", str(e))
        except HttpNetworkError as e:
            return Result.failure("HTTP_NETWORK_ERROR", str(e))
        except HttpError as e:
            return Result.failure("HTTP_ERROR", str(e))

        try:
            body.decode(params.encoding)
        except (UnicodeDecodeError, LookupError) as e:
            return Result.failure(
                "DECODE_FAILED",
                f"body did not decode as {params.encoding}: {e}",
            )

        try:
            self._fs.write_binary_file(params.cache_path, body)
        except FsError as e:
            return Result.failure(
                "WRITE_FAILED", f"failed to write {params.cache_path}: {e}"
            )

        return Result.success(
            f"fetched {params.url} ({len(body)} bytes) -> {params.cache_path}"
        )

    @override
    def rollback(self) -> StateChanger:
        return FetchUrlToStringRollbackStateChanger(self._params, file_system=self._fs)


class FetchUrlToStringRollbackStateChanger(StateChanger):
    def __init__(
        self,
        params: FetchUrlToStringParameters,
        file_system: FileSystem | None = None,
    ) -> None:
        self._params = params
        self._fs: FileSystem = file_system or RealFileSystem()

    @override
    def name(self) -> str:
        return f"fetch-url-to-string-rollback:{self._params.cache_path}"

    @override
    def assess_state(self) -> StateAssessment:
        path = self._params.cache_path
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
            self._fs.delete_file(self._params.cache_path)
        except FsNotFound:
            return Result.skipped(f"{self._params.cache_path} already gone")
        except FsError as e:
            return Result.failure(
                "UNLINK_FAILED",
                f"failed to remove {self._params.cache_path}: {e}",
            )
        return Result.success(f"removed {self._params.cache_path}")
