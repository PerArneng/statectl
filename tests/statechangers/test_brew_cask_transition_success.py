from __future__ import annotations

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ResultStatus
from statectl._statechangers import BrewCaskParameters, BrewCaskStateChanger
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _changer(
    pr: ScriptedProcessRunner,
    *,
    name: str = "google-chrome",
    version: str | None = None,
    tap: str | None = None,
) -> BrewCaskStateChanger:
    return BrewCaskStateChanger(
        BrewCaskParameters(name=name, version=version, tap=tap),
        process_runner=pr,
    )


def _pr() -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    pr.register_executable("brew")
    return pr


def test_success_when_brew_install_exits_zero() -> None:
    pr = _pr()
    pr.register(
        ("brew", "install"),
        ProcessResult(exit_code=0, stdout="==> Installing", stderr="", duration_ms=42),
    )
    result = _changer(pr).transition()

    assert result.status is ResultStatus.SUCCESS
    assert result.code == "OK"
    assert result.details["exit_code"] == "0"
    assert result.details["duration_ms"] == "42"


def test_success_records_install_call_with_cask_ref() -> None:
    pr = _pr()
    pr.register(
        ("brew", "install"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    _changer(pr, name="google-chrome").transition()

    install_calls = [c for c in pr.calls if c.argv[:2] == ("brew", "install")]
    assert len(install_calls) == 1
    assert install_calls[0].argv == ("brew", "install", "--cask", "google-chrome")


def test_success_uses_tap_qualified_ref_when_tap_set() -> None:
    pr = _pr()
    pr.register(
        ("brew", "install"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    _changer(pr, name="thing", tap="acme/private").transition()

    install_calls = [c for c in pr.calls if c.argv[:2] == ("brew", "install")]
    assert install_calls[0].argv == ("brew", "install", "--cask", "acme/private/thing")


def test_long_stdout_is_truncated_in_details() -> None:
    pr = _pr()
    huge = "x" * 100_000
    pr.register(
        ("brew", "install"),
        ProcessResult(exit_code=0, stdout=huge, stderr="", duration_ms=0),
    )

    result = _changer(pr).transition()

    assert len(result.details["stdout"]) < len(huge)
    assert "truncated" in result.details["stdout"]
