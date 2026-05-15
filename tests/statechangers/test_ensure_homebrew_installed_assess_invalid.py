from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ExistingState
from statectl._statechangers import (
    EnsureHomebrewInstalledParameters,
    EnsureHomebrewInstalledStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


PREFIX = Path("/opt/homebrew")


def _build(
    *,
    fs: InMemoryFileSystem | None = None,
    env: ScriptedEnv | None = None,
    install_script_url: str = (
        "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh"
    ),
    accept_eula: bool = True,
    brew_prefix: Path = PREFIX,
) -> EnsureHomebrewInstalledStateChanger:
    fs = fs or InMemoryFileSystem()
    if Path("/opt") not in fs._nodes:  # noqa: SLF001
        fs.add_dir(Path("/opt"))
    return EnsureHomebrewInstalledStateChanger(
        EnsureHomebrewInstalledParameters(
            brew_prefix=brew_prefix,
            install_script_url=install_script_url,
            accept_eula=accept_eula,
        ),
        file_system=fs,
        process_runner=ScriptedProcessRunner(),
        http_client=ScriptedHttpClient(),
        env=env or ScriptedEnv.darwin(),
    )


def test_invalid_on_linux() -> None:
    changer = _build(env=ScriptedEnv.linux())

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("macOS-only" in i for i in assessment.issues)


def test_invalid_when_install_script_url_is_not_https() -> None:
    changer = _build(install_script_url="http://example.com/install.sh")

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("must be https" in i for i in assessment.issues)


def test_invalid_when_prefix_parent_not_writable() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/opt"), writable=False)
    changer = _build(fs=fs)

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("prefix parent not writable" in i for i in assessment.issues)


def test_invalid_when_prefix_parent_missing() -> None:
    fs = InMemoryFileSystem()
    changer = _build(fs=fs, brew_prefix=Path("/missing/homebrew"))

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("prefix parent not writable" in i for i in assessment.issues)


def test_invalid_when_accept_eula_false_and_brew_absent() -> None:
    changer = _build(accept_eula=False)

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("accept_eula=True" in i for i in assessment.issues)


def test_invalid_collects_multiple_issues_in_one_pass() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/opt"), writable=False)
    changer = _build(
        fs=fs,
        env=ScriptedEnv.linux(),
        install_script_url="http://example.com/install.sh",
        accept_eula=False,
    )

    assessment = changer.assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("macOS-only" in i for i in assessment.issues)
    assert any("must be https" in i for i in assessment.issues)
    assert any("prefix parent not writable" in i for i in assessment.issues)
    assert any("accept_eula=True" in i for i in assessment.issues)
