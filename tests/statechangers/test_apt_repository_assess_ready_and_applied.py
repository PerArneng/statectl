from __future__ import annotations

from pathlib import Path

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState
from statectl._statechangers import (
    AptRepositoryParameters,
    AptRepositoryStateChanger,
    InlineKey,
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
EXPECTED_SOURCES_WITH_ARCH = (
    "deb [arch=amd64,arm64 signed-by=/etc/apt/keyrings/docker.gpg] "
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
            exit_code=0,
            stdout=f"fpr:::::::::{fp}:\n",
            stderr="",
            duration_ms=1,
        ),
    )
    return pr


def _changer(
    fs: InMemoryFileSystem,
    pr: ScriptedProcessRunner,
    *,
    architectures: tuple[str, ...] = (),
) -> AptRepositoryStateChanger:
    return AptRepositoryStateChanger(
        AptRepositoryParameters(
            name="docker",
            uri="https://download.docker.com/linux/ubuntu",
            suite="jammy",
            components=("stable",),
            architectures=architectures,
            signing_key=InlineKey(armored="X", fingerprint=FP),
        ),
        file_system=fs,
        process_runner=pr,
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.linux(),
    )


def test_ready_on_fresh_system() -> None:
    fs = _ok_fs()
    pr = _pr_with_fp()
    changer = _changer(fs, pr)

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.READY


def test_already_applied_when_sources_and_keyring_match() -> None:
    fs = _ok_fs()
    fs.add_file(
        Path("/etc/apt/sources.list.d/docker.list"), content=EXPECTED_SOURCES
    )
    fs.add_file(Path("/etc/apt/keyrings/docker.gpg"), content="binary")
    pr = _pr_with_fp()

    changer = _changer(fs, pr)
    assessment = changer.assess_state()

    assert assessment.state is ExistingState.ALREADY_APPLIED


def test_ready_when_keyring_present_but_sources_missing() -> None:
    fs = _ok_fs()
    fs.add_file(Path("/etc/apt/keyrings/docker.gpg"), content="binary")
    pr = _pr_with_fp()

    changer = _changer(fs, pr)
    assessment = changer.assess_state()

    assert assessment.state is ExistingState.READY


def test_ready_when_sources_present_but_keyring_missing() -> None:
    fs = _ok_fs()
    fs.add_file(
        Path("/etc/apt/sources.list.d/docker.list"), content=EXPECTED_SOURCES
    )
    pr = _pr_with_fp()

    changer = _changer(fs, pr)
    assessment = changer.assess_state()

    assert assessment.state is ExistingState.READY


def test_sources_format_with_architectures_round_trips() -> None:
    fs = _ok_fs()
    fs.add_file(
        Path("/etc/apt/sources.list.d/docker.list"),
        content=EXPECTED_SOURCES_WITH_ARCH,
    )
    fs.add_file(Path("/etc/apt/keyrings/docker.gpg"), content="binary")
    pr = _pr_with_fp()

    changer = _changer(fs, pr, architectures=("amd64", "arm64"))
    assessment = changer.assess_state()

    assert assessment.state is ExistingState.ALREADY_APPLIED


def test_fingerprint_normalises_spacing_and_case() -> None:
    fs = _ok_fs()
    fs.add_file(
        Path("/etc/apt/sources.list.d/docker.list"), content=EXPECTED_SOURCES
    )
    fs.add_file(Path("/etc/apt/keyrings/docker.gpg"), content="binary")
    # gpg reports lowercase fingerprint with no spaces; param has uppercase with
    # spaces. Both must canonicalise to the same value.
    pr = _pr_with_fp(fp=FP.lower())
    changer = AptRepositoryStateChanger(
        AptRepositoryParameters(
            name="docker",
            uri="https://download.docker.com/linux/ubuntu",
            suite="jammy",
            components=("stable",),
            signing_key=InlineKey(
                armored="X",
                fingerprint="ABCD EF12 3456 7890 ABCD EF12 3456 7890 ABCD EF12",
            ),
        ),
        file_system=fs,
        process_runner=pr,
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.linux(),
    )

    assert changer.assess_state().state is ExistingState.ALREADY_APPLIED
