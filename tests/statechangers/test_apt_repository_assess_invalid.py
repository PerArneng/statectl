from __future__ import annotations

from pathlib import Path

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState
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


def _ok_fs() -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/etc"))
    fs.add_dir(Path("/etc/apt"))
    fs.add_dir(Path("/etc/apt/sources.list.d"))
    fs.add_dir(Path("/etc/apt/keyrings"))
    return fs


def _params(signing_key: InlineKey | UrlKey | None = None) -> AptRepositoryParameters:
    return AptRepositoryParameters(
        name="docker",
        uri="https://download.docker.com/linux/ubuntu",
        suite="jammy",
        components=("stable",),
        signing_key=signing_key or InlineKey(armored="X", fingerprint=FP),
    )


def _gpg_pr_with_fp(fp: str = FP) -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    pr.register_executable("gpg")
    pr.register(
        ("gpg", "--show-keys", "--with-colons"),
        ProcessResult(
            exit_code=0,
            stdout=f"pub:-:::::::\nfpr:::::::::{fp}:\n",
            stderr="",
            duration_ms=1,
        ),
    )
    return pr


def _build(
    fs: InMemoryFileSystem,
    pr: ScriptedProcessRunner,
    *,
    http: ScriptedHttpClient | None = None,
    env: ScriptedEnv | None = None,
    params: AptRepositoryParameters | None = None,
) -> AptRepositoryStateChanger:
    return AptRepositoryStateChanger(
        params or _params(),
        file_system=fs,
        process_runner=pr,
        http_client=http or ScriptedHttpClient(),
        env=env or ScriptedEnv.linux(),
    )


def test_invalid_when_platform_not_linux() -> None:
    fs = _ok_fs()
    pr = _gpg_pr_with_fp()
    changer = _build(fs, pr, env=ScriptedEnv.darwin())

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("Debian-family" in i for i in assessment.issues)


def test_invalid_when_gpg_missing() -> None:
    fs = _ok_fs()
    pr = ScriptedProcessRunner()  # no gpg

    changer = _build(fs, pr)
    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("gpg executable" in i for i in assessment.issues)


def test_invalid_when_keyring_parent_missing() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/etc"))
    fs.add_dir(Path("/etc/apt"))
    fs.add_dir(Path("/etc/apt/sources.list.d"))
    # no /etc/apt/keyrings
    pr = _gpg_pr_with_fp()

    changer = _build(fs, pr)
    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("keyring parent does not exist" in i for i in assessment.issues)


def test_invalid_when_sources_dir_not_writable() -> None:
    fs = _ok_fs()
    fs.set_writable(Path("/etc/apt/sources.list.d"), False)
    pr = _gpg_pr_with_fp()

    changer = _build(fs, pr)
    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("sources.list.d is not writable" in i for i in assessment.issues)


def test_invalid_when_url_key_uses_non_https() -> None:
    fs = _ok_fs()
    pr = _gpg_pr_with_fp()
    params = _params(
        signing_key=UrlKey(url="http://example.com/key.asc", fingerprint=FP)
    )

    changer = _build(fs, pr, params=params)
    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("key URL must be https" in i for i in assessment.issues)


def test_invalid_when_sources_file_has_different_content() -> None:
    fs = _ok_fs()
    fs.add_file(
        Path("/etc/apt/sources.list.d/docker.list"),
        content="deb http://other something main\n",
    )
    pr = _gpg_pr_with_fp()

    changer = _build(fs, pr)
    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any(
        "sources file exists with different content" in i for i in assessment.issues
    )


def test_invalid_when_keyring_has_wrong_fingerprint() -> None:
    fs = _ok_fs()
    fs.add_file(Path("/etc/apt/keyrings/docker.gpg"), content="binary")
    pr = _gpg_pr_with_fp(fp=WRONG_FP)

    changer = _build(fs, pr)
    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("keyring has wrong fingerprint" in i for i in assessment.issues)


def test_assess_collects_multiple_issues_in_one_pass() -> None:
    # Platform wrong, gpg missing — both should appear together.
    fs = _ok_fs()
    pr = ScriptedProcessRunner()  # no gpg
    changer = _build(fs, pr, env=ScriptedEnv.darwin())

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    issues_text = " | ".join(assessment.issues)
    assert "Debian-family" in issues_text
    assert "gpg executable" in issues_text
