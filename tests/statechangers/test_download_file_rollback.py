from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ExistingState, ResultStatus
from statectl._statechangers import (
    DownloadFileParameters,
    DownloadFileRollbackStateChanger,
    DownloadFileStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_hashing import ScriptedHashing, sha256_of
from tests.fakes.scripted_http_client import ScriptedHttpClient


def _stack(
    body: bytes = b"hi",
    sha256: str | None = None,
) -> tuple[
    DownloadFileStateChanger,
    InMemoryFileSystem,
    ScriptedHttpClient,
    ScriptedHashing,
]:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    http = ScriptedHttpClient(file_system=fs)
    http.register_download("http://x/a", body)
    hashing = ScriptedHashing(file_system=fs)
    changer = DownloadFileStateChanger(
        DownloadFileParameters(
            url="http://x/a",
            dest=Path("/work/a"),
            sha256=sha256,
        ),
        file_system=fs,
        http_client=http,
        hashing=hashing,
    )
    return changer, fs, http, hashing


def test_rollback_after_apply_removes_file() -> None:
    changer, fs, *_ = _stack()
    assert changer.transition().status is ResultStatus.SUCCESS

    rb = changer.rollback()
    assert rb.assess_state().state is ExistingState.READY
    assert rb.transition().status is ResultStatus.SUCCESS
    assert not fs.exists(Path("/work/a"))


def test_rollback_already_applied_when_dest_absent() -> None:
    changer, *_ = _stack()
    rb = changer.rollback()
    assert rb.assess_state().state is ExistingState.ALREADY_APPLIED


def test_rollback_detects_drift_when_content_changed() -> None:
    changer, fs, _, hashing = _stack(body=b"hi")
    changer.transition()
    fs._nodes[Path("/work/a")].content = "DRIFTED"

    rb = changer.rollback()
    a = rb.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("drifted" in i for i in a.issues)


def test_rollback_without_observed_sha_skips_drift_check() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/a"), content="something")
    rb = DownloadFileRollbackStateChanger(
        DownloadFileParameters(url="http://x/a", dest=Path("/work/a")),
        expected_sha256=None,
        file_system=fs,
        hashing=ScriptedHashing(file_system=fs),
    )
    assert rb.assess_state().state is ExistingState.READY


def test_rollback_skips_if_file_disappears_between_assess_and_transition() -> None:
    changer, fs, *_ = _stack()
    changer.transition()
    rb = changer.rollback()
    assert rb.assess_state().state is ExistingState.READY
    fs.delete_file(Path("/work/a"))

    result = rb.transition()
    assert result.status is ResultStatus.SKIPPED


def test_observed_sha_captured_on_success_for_drift_detection() -> None:
    expected = sha256_of("hi")
    changer, *_ = _stack(body=b"hi", sha256=expected)
    changer.transition()
    rb = changer.rollback()
    assert isinstance(rb, DownloadFileRollbackStateChanger)
    assert rb._expected_sha256 == expected
