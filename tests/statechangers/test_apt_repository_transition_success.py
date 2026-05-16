from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence, override

from statectl._interfaces.http import HttpResponse
from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState, ResultStatus
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

EXPECTED_SOURCES = (
    "deb [signed-by=/etc/apt/keyrings/docker.gpg] "
    "https://download.docker.com/linux/ubuntu jammy stable\n"
)


class _DearmorMaterialisingPR(ScriptedProcessRunner):
    """Wraps ScriptedProcessRunner so that gpg --dearmor materialises a
    fake keyring file in the backing filesystem (otherwise the in-memory
    FS never sees the file gpg "wrote")."""

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


def _pr(fs: InMemoryFileSystem, *, installed_fp: str = FP) -> _DearmorMaterialisingPR:
    pr = _DearmorMaterialisingPR(fs)
    pr.register_executable("gpg")
    pr.register(
        ("gpg", "--show-keys", "--with-colons"),
        ProcessResult(
            exit_code=0,
            stdout=f"fpr:::::::::{installed_fp}:\n",
            stderr="",
            duration_ms=1,
        ),
    )
    pr.register(
        ("gpg", "--dearmor"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=1),
    )
    return pr


def _inline_params() -> AptRepositoryParameters:
    return AptRepositoryParameters(
        name="docker",
        uri="https://download.docker.com/linux/ubuntu",
        suite="jammy",
        components=("stable",),
        signing_key=InlineKey(armored="ARMORED", fingerprint=FP),
    )


def test_inline_key_writes_sources_and_keyring() -> None:
    fs = _ok_fs()
    pr = _pr(fs)
    http = ScriptedHttpClient()
    changer = AptRepositoryStateChanger(
        _inline_params(),
        file_system=fs,
        process_runner=pr,
        http_client=http,
        env=ScriptedEnv.linux(),
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS, result
    assert fs.read_text_file(Path("/etc/apt/sources.list.d/docker.list")) == (
        EXPECTED_SOURCES
    )
    assert fs.exists(Path("/etc/apt/keyrings/docker.gpg"))
    assert result.details["installed_fingerprint"] == FP
    assert http.calls == []

    # Idempotency: re-assess after applying.
    assert changer.assess_state().state is ExistingState.ALREADY_APPLIED


def test_url_key_fetches_and_writes() -> None:
    fs = _ok_fs()
    pr = _pr(fs)
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
            signing_key=UrlKey(url="https://example.com/key.asc", fingerprint=FP),
        ),
        file_system=fs,
        process_runner=pr,
        http_client=http,
        env=ScriptedEnv.linux(),
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS, result
    assert len(http.calls) == 1
    assert http.calls[0].url == "https://example.com/key.asc"


def test_url_key_with_matching_sha256_succeeds() -> None:
    import hashlib

    body = "ARMORED-BODY"
    digest = hashlib.sha256(body.encode()).hexdigest()
    fs = _ok_fs()
    pr = _pr(fs)
    http = ScriptedHttpClient()
    http.register_response(
        "https://example.com/key.asc",
        HttpResponse(status_code=200, body=body, headers={}),
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
                sha256=digest,
            ),
        ),
        file_system=fs,
        process_runner=pr,
        http_client=http,
        env=ScriptedEnv.linux(),
    )

    result = changer.transition()

    assert result.status is ResultStatus.SUCCESS, result
