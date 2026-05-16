from __future__ import annotations

from pathlib import Path

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState, ResultStatus
from statectl._statechangers import (
    AptRepositoryParameters,
    AptRepositoryRollbackStateChanger,
    AptRepositoryStateChanger,
    InlineKey,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


FP = "ABCDEF1234567890ABCDEF1234567890ABCDEF12"
WRONG_FP = "DEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEF"

EXPECTED_SOURCES = (
    "deb [signed-by=/etc/apt/keyrings/docker.gpg] "
    "https://download.docker.com/linux/ubuntu jammy stable\n"
)


def _ok_fs() -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/etc"))
    fs.add_dir(Path("/etc/apt"))
    fs.add_dir(Path("/etc/apt/sources.list.d"))
    fs.add_dir(Path("/etc/apt/keyrings"))
    return fs


def _pr_with_fp(fp: str = FP) -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    pr.register_executable("gpg")
    pr.register(
        ("gpg", "--show-keys", "--with-colons"),
        ProcessResult(
            exit_code=0, stdout=f"fpr:::::::::{fp}:\n", stderr="", duration_ms=1
        ),
    )
    return pr


def _params() -> AptRepositoryParameters:
    return AptRepositoryParameters(
        name="docker",
        uri="https://download.docker.com/linux/ubuntu",
        suite="jammy",
        components=("stable",),
        signing_key=InlineKey(armored="X", fingerprint=FP),
    )


def _rollback(
    fs: InMemoryFileSystem, pr: ScriptedProcessRunner
) -> AptRepositoryRollbackStateChanger:
    return AptRepositoryRollbackStateChanger(
        _params(),
        file_system=fs,
        process_runner=pr,
        env=ScriptedEnv.linux(),
    )


def test_rollback_already_applied_when_nothing_present() -> None:
    fs = _ok_fs()
    pr = _pr_with_fp()
    rb = _rollback(fs, pr)

    assert rb.assess_state().state is ExistingState.ALREADY_APPLIED


def test_rollback_ready_when_both_files_match() -> None:
    fs = _ok_fs()
    fs.add_file(
        Path("/etc/apt/sources.list.d/docker.list"), content=EXPECTED_SOURCES
    )
    fs.add_file(Path("/etc/apt/keyrings/docker.gpg"), content="binary")
    pr = _pr_with_fp()
    rb = _rollback(fs, pr)

    assert rb.assess_state().state is ExistingState.READY


def test_rollback_invalid_when_sources_drifted() -> None:
    fs = _ok_fs()
    fs.add_file(
        Path("/etc/apt/sources.list.d/docker.list"), content="deb something else\n"
    )
    pr = _pr_with_fp()
    rb = _rollback(fs, pr)

    assessment = rb.assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("drifted" in i for i in assessment.issues)


def test_rollback_invalid_when_keyring_drifted() -> None:
    fs = _ok_fs()
    fs.add_file(Path("/etc/apt/keyrings/docker.gpg"), content="binary")
    pr = _pr_with_fp(fp=WRONG_FP)
    rb = _rollback(fs, pr)

    assessment = rb.assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("drifted" in i for i in assessment.issues)


def test_rollback_transition_unlinks_both() -> None:
    fs = _ok_fs()
    fs.add_file(
        Path("/etc/apt/sources.list.d/docker.list"), content=EXPECTED_SOURCES
    )
    fs.add_file(Path("/etc/apt/keyrings/docker.gpg"), content="binary")
    pr = _pr_with_fp()
    rb = _rollback(fs, pr)

    result = rb.transition()

    assert result.status is ResultStatus.SUCCESS
    assert not fs.exists(Path("/etc/apt/sources.list.d/docker.list"))
    assert not fs.exists(Path("/etc/apt/keyrings/docker.gpg"))


def test_rollback_transition_tolerates_partial_absence() -> None:
    fs = _ok_fs()
    fs.add_file(
        Path("/etc/apt/sources.list.d/docker.list"), content=EXPECTED_SOURCES
    )
    pr = _pr_with_fp()
    rb = _rollback(fs, pr)

    result = rb.transition()

    assert result.status is ResultStatus.SUCCESS
    assert not fs.exists(Path("/etc/apt/sources.list.d/docker.list"))


def test_forward_rollback_returns_typed_inverse() -> None:
    fs = _ok_fs()
    pr = _pr_with_fp()
    forward = AptRepositoryStateChanger(
        _params(),
        file_system=fs,
        process_runner=pr,
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.linux(),
    )

    inverse = forward.rollback()

    assert isinstance(inverse, AptRepositoryRollbackStateChanger)
