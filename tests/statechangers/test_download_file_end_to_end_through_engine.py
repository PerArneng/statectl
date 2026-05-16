from __future__ import annotations

from pathlib import Path

from statectl import StateCtl
from statectl._engine_result import NodeOutcome
from statectl._modules import DefaultLogger, InMemoryVariableRegistry
from statectl._statechangers import (
    DownloadFileParameters,
    DownloadFileStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_hashing import ScriptedHashing, sha256_of
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _engine(
    fs: InMemoryFileSystem,
    http: ScriptedHttpClient,
    hashing: ScriptedHashing,
) -> StateCtl:
    return StateCtl(
        logger=DefaultLogger("test"),
        file_system=fs,
        process_runner=ScriptedProcessRunner(),
        http_client=http,
        env=ScriptedEnv.linux(),
        hashing=hashing,
        clock=ScriptedClock(),
        variable_registry=InMemoryVariableRegistry(),
    )


def test_first_run_downloads_then_second_run_skips() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    http = ScriptedHttpClient(file_system=fs)
    http.register_download("http://x/a", b"payload")
    hashing = ScriptedHashing(file_system=fs)
    expected = sha256_of("payload")

    e1 = _engine(fs, http, hashing)
    e1.add(
        DownloadFileStateChanger(
            DownloadFileParameters(
                url="http://x/a",
                dest=Path("/work/a"),
                sha256=expected,
            ),
            file_system=fs,
            http_client=http,
            hashing=hashing,
        )
    )
    r1 = e1.start(max_workers=1)
    assert any(r.outcome is NodeOutcome.SUCCESS for r in r1.reports)
    assert fs.read_text_file(Path("/work/a")) == "payload"

    e2 = _engine(fs, http, hashing)
    e2.add(
        DownloadFileStateChanger(
            DownloadFileParameters(
                url="http://x/a",
                dest=Path("/work/a"),
                sha256=expected,
            ),
            file_system=fs,
            http_client=http,
            hashing=hashing,
        )
    )
    r2 = e2.start(max_workers=1)
    assert any(
        r.outcome is NodeOutcome.SKIPPED_ALREADY_APPLIED for r in r2.reports
    )


def test_engine_marks_failed_when_checksum_mismatch() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    http = ScriptedHttpClient(file_system=fs)
    http.register_download("http://x/a", b"actual")
    hashing = ScriptedHashing(file_system=fs)

    e = _engine(fs, http, hashing)
    e.add(
        DownloadFileStateChanger(
            DownloadFileParameters(
                url="http://x/a",
                dest=Path("/work/a"),
                sha256=sha256_of("expected"),
            ),
            file_system=fs,
            http_client=http,
            hashing=hashing,
        )
    )
    r = e.start(max_workers=1)
    failed = [x for x in r.reports if x.outcome is NodeOutcome.FAILED_TRANSITION]
    assert failed and failed[0].result is not None
    assert failed[0].result.code == "CHECKSUM_MISMATCH"
    assert not fs.exists(Path("/work/a"))


def test_engine_halts_on_invalid_url() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    http = ScriptedHttpClient(file_system=fs)
    hashing = ScriptedHashing(file_system=fs)
    e = _engine(fs, http, hashing)
    e.add(
        DownloadFileStateChanger(
            DownloadFileParameters(url="ftp://x/a", dest=Path("/work/a")),
            file_system=fs,
            http_client=http,
            hashing=hashing,
        )
    )
    r = e.start(max_workers=1)
    assert any(x.outcome is NodeOutcome.FAILED_INVALID for x in r.reports)
