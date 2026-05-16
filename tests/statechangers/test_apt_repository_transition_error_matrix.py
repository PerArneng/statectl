from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence, override

import pytest

from statectl._interfaces.http import (
    HttpNetworkError,
    HttpNotFound,
    HttpResponse,
    HttpServerError,
)
from statectl._interfaces.process import (
    ProcessDecodeError,
    ProcessLaunchError,
    ProcessNotFound,
    ProcessResult,
    ProcessTimeout,
)
from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    AptRepositoryParameters,
    AptRepositoryStateChanger,
    InlineKey,
    UrlKey,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


FP = "ABCDEF1234567890ABCDEF1234567890ABCDEF12"
WRONG_FP = "DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEF"


class _DearmorMaterialisingPR(ScriptedProcessRunner):
    def __init__(self, fs: InMemoryFileSystem) -> None:
        super().__init__()
        self._fs = fs

    @override
    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        timeout: float | None = None,
    ) -> ProcessResult:
        result = super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)
        argv_tuple = tuple(argv)
        if (
            len(argv_tuple) >= 4
            and argv_tuple[0] == "gpg"
            and argv_tuple[1] == "--dearmor"
            and argv_tuple[2] == "-o"
            and result.exit_code == 0
        ):
            self._fs.add_file(Path(argv_tuple[3]), content="binary")
        return result


def _ok_fs() -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/etc"))
    fs.add_dir(Path("/etc/apt"))
    fs.add_dir(Path("/etc/apt/sources.list.d"))
    fs.add_dir(Path("/etc/apt/keyrings"))
    return fs


def _pr_with_dearmor(
    fs: InMemoryFileSystem, installed_fp: str = FP
) -> _DearmorMaterialisingPR:
    pr = _DearmorMaterialisingPR(fs)
    pr.register_executable("gpg")
    pr.register(
        ("gpg", "--show-keys", "--with-colons"),
        ProcessResult(
            exit_code=0, stdout=f"fpr:::::::::{installed_fp}:\n", stderr="", duration_ms=1
        ),
    )
    pr.register(
        ("gpg", "--dearmor"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=1),
    )
    return pr


def _build_url(
    fs: InMemoryFileSystem, pr: ScriptedProcessRunner, http: ScriptedHttpClient
) -> AptRepositoryStateChanger:
    return AptRepositoryStateChanger(
        AptRepositoryParameters(
            name="docker",
            uri="https://download.docker.com/linux/ubuntu",
            suite="jammy",
            components=("stable",),
            signing_key=UrlKey(url="https://example.com/key.asc", fingerprint=FP),
        ),
        file_system=fs,
        process_runner=pr,
        http_client=http,
        env=ScriptedEnv.linux(),
    )


@pytest.mark.parametrize(
    "exc",
    [
        HttpNotFound("missing", url="https://example.com/key.asc"),
        HttpServerError("boom", url="https://example.com/key.asc"),
        HttpNetworkError("net", url="https://example.com/key.asc"),
    ],
)
def test_key_fetch_failures_map_to_key_fetch_failed(exc: Exception) -> None:
    fs = _ok_fs()
    pr = _pr_with_dearmor(fs)

    class _FailingHttp(ScriptedHttpClient):
        @override
        def get(self, url, headers=None, timeout=None):  # type: ignore[override]
            raise exc

    changer = _build_url(fs, pr, _FailingHttp())
    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "KEY_FETCH_FAILED"


def test_key_sha256_mismatch_returns_key_sha256_mismatch() -> None:
    fs = _ok_fs()
    pr = _pr_with_dearmor(fs)
    http = ScriptedHttpClient()
    http.register_response(
        "https://example.com/key.asc",
        HttpResponse(status_code=200, body="ARMORED", headers={}),
    )
    changer = AptRepositoryStateChanger(
        AptRepositoryParameters(
            name="docker",
            uri="https://download.docker.com/linux/ubuntu",
            suite="jammy",
            components=("stable",),
            signing_key=UrlKey(
                url="https://example.com/key.asc",
                fingerprint=FP,
                sha256="0" * 64,
            ),
        ),
        file_system=fs,
        process_runner=pr,
        http_client=http,
        env=ScriptedEnv.linux(),
    )

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "KEY_SHA256_MISMATCH"


def test_dearmor_non_zero_exit_returns_key_dearmor_failed() -> None:
    fs = _ok_fs()
    pr = _DearmorMaterialisingPR(fs)
    pr.register_executable("gpg")
    pr.register(
        ("gpg", "--dearmor"),
        ProcessResult(exit_code=2, stdout="", stderr="bad armor", duration_ms=1),
    )

    changer = AptRepositoryStateChanger(
        AptRepositoryParameters(
            name="docker",
            uri="https://download.docker.com/linux/ubuntu",
            suite="jammy",
            components=("stable",),
            signing_key=InlineKey(armored="X", fingerprint=FP),
        ),
        file_system=fs,
        process_runner=pr,
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.linux(),
    )

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "KEY_DEARMOR_FAILED"


def test_fingerprint_mismatch_returns_key_fingerprint_mismatch_and_unlinks() -> None:
    fs = _ok_fs()
    pr = _pr_with_dearmor(fs, installed_fp=WRONG_FP)

    changer = AptRepositoryStateChanger(
        AptRepositoryParameters(
            name="docker",
            uri="https://download.docker.com/linux/ubuntu",
            suite="jammy",
            components=("stable",),
            signing_key=InlineKey(armored="X", fingerprint=FP),
        ),
        file_system=fs,
        process_runner=pr,
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.linux(),
    )

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "KEY_FINGERPRINT_MISMATCH"
    assert not fs.exists(Path("/etc/apt/keyrings/docker.gpg"))


@pytest.mark.parametrize(
    "exc, expected_code",
    [
        (ProcessNotFound("nope", argv=("gpg",)), "PROCESS_NOT_FOUND"),
        (ProcessTimeout("slow", argv=("gpg",)), "PROCESS_TIMEOUT"),
        (ProcessDecodeError("decode", argv=("gpg",)), "PROCESS_DECODE_ERROR"),
        (ProcessLaunchError("launch", argv=("gpg",)), "PROCESS_LAUNCH_ERROR"),
    ],
)
def test_process_errors_during_dearmor_map_to_codes(
    exc: Exception, expected_code: str
) -> None:
    fs = _ok_fs()

    class _FailingPR(_DearmorMaterialisingPR):
        @override
        def run(
            self,
            argv: Sequence[str],
            *,
            cwd: Path | None = None,
            env: Mapping[str, str] | None = None,
            stdin: str | None = None,
            timeout: float | None = None,
        ) -> ProcessResult:
            if argv and argv[1] == "--dearmor":
                raise exc
            return super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)

    pr = _FailingPR(fs)
    pr.register_executable("gpg")
    changer = AptRepositoryStateChanger(
        AptRepositoryParameters(
            name="docker",
            uri="https://download.docker.com/linux/ubuntu",
            suite="jammy",
            components=("stable",),
            signing_key=InlineKey(armored="X", fingerprint=FP),
        ),
        file_system=fs,
        process_runner=pr,
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.linux(),
    )

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == expected_code


def test_unexpected_exception_propagates() -> None:
    fs = _ok_fs()

    class _RaisingPR(_DearmorMaterialisingPR):
        @override
        def run(
            self,
            argv: Sequence[str],
            *,
            cwd: Path | None = None,
            env: Mapping[str, str] | None = None,
            stdin: str | None = None,
            timeout: float | None = None,
        ) -> ProcessResult:
            raise RuntimeError("boom")

    pr = _RaisingPR(fs)
    pr.register_executable("gpg")
    changer = AptRepositoryStateChanger(
        AptRepositoryParameters(
            name="docker",
            uri="https://download.docker.com/linux/ubuntu",
            suite="jammy",
            components=("stable",),
            signing_key=InlineKey(armored="X", fingerprint=FP),
        ),
        file_system=fs,
        process_runner=pr,
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.linux(),
    )

    with pytest.raises(RuntimeError):
        changer.transition()
