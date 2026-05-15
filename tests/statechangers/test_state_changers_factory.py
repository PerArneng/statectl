from __future__ import annotations

from pathlib import Path

from statectl import StateCtl
from statectl._interfaces.process import ProcessResult
from statectl._statechangers import (
    AtEnd,
    DeletePathParameters,
    DeletePathStateChanger,
    EnsureDirectoryStateChanger,
    EnsureLineInFileParameters,
    EnsureLineInFileStateChanger,
    LiteralMatch,
    NewTextFileRollbackStateChanger,
    NewTextFileStateChanger,
    ReplaceInFileParameters,
    ReplaceInFileStateChanger,
    RunCommandStateChanger,
    StateChangers,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def test_engine_changers_returns_factory_wired_to_engine_capabilities() -> None:
    fs = InMemoryFileSystem()
    pr = ScriptedProcessRunner()
    engine = StateCtl.new(file_system=fs, process_runner=pr)
    sc = engine.changers()
    assert isinstance(sc, StateChangers)


def test_new_file_routes_through_fake_filesystem() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    pr = ScriptedProcessRunner()
    engine = StateCtl.new(file_system=fs, process_runner=pr)

    changer = engine.changers().new_file("/work/out.txt", "hello\n")
    assert isinstance(changer, NewTextFileStateChanger)

    engine.add(changer)
    engine.start(max_workers=1)

    assert fs.read_text_file(Path("/work/out.txt")) == "hello\n"


def test_new_file_rollback_inherits_fake_filesystem() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/out.txt"), content="hello\n")
    pr = ScriptedProcessRunner()
    engine = StateCtl.new(file_system=fs, process_runner=pr)

    forward = engine.changers().new_file("/work/out.txt", "hello\n")
    rollback = forward.rollback()
    assert isinstance(rollback, NewTextFileRollbackStateChanger)

    engine.add(rollback)
    engine.start(max_workers=1)

    assert not fs.exists(Path("/work/out.txt"))


def test_ensure_directory_routes_through_fake_filesystem() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    pr = ScriptedProcessRunner()
    engine = StateCtl.new(file_system=fs, process_runner=pr)

    changer = engine.changers().ensure_directory("/work/a/b", mode=0o700)
    assert isinstance(changer, EnsureDirectoryStateChanger)

    engine.add(changer)
    engine.start(max_workers=1)

    assert fs.is_dir(Path("/work/a/b"))
    assert fs.stat_mode(Path("/work/a/b")) == 0o700


def test_run_shlex_splits_string_command() -> None:
    fs = InMemoryFileSystem()
    pr = ScriptedProcessRunner()
    pr.register_executable("echo")
    pr.register(("echo",), ProcessResult(exit_code=0, stdout="hi", stderr="", duration_ms=0))
    engine = StateCtl.new(file_system=fs, process_runner=pr)

    changer = engine.changers().run("echo hello world")
    assert isinstance(changer, RunCommandStateChanger)

    engine.add(changer)
    engine.start(max_workers=1)

    assert pr.calls[0].argv == ("echo", "hello", "world")


def test_run_accepts_sequence_verbatim_for_embedded_spaces() -> None:
    fs = InMemoryFileSystem()
    pr = ScriptedProcessRunner()
    pr.register_executable("echo")
    pr.register(("echo",), ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0))
    engine = StateCtl.new(file_system=fs, process_runner=pr)

    changer = engine.changers().run(["echo", "hi there"])
    engine.add(changer)
    engine.start(max_workers=1)

    assert pr.calls[0].argv == ("echo", "hi there")


def test_run_creates_hint_marks_already_applied() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/marker"), content="")
    pr = ScriptedProcessRunner()
    pr.register_executable("touch")
    engine = StateCtl.new(file_system=fs, process_runner=pr)

    changer = engine.changers().run(["touch", "/work/marker"], creates="/work/marker")
    engine.add(changer)
    engine.start(max_workers=1)

    assert pr.calls == []


def test_delete_path_returns_changer_with_params() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/junk"), content="x")
    pr = ScriptedProcessRunner()
    engine = StateCtl.new(file_system=fs, process_runner=pr)

    changer = engine.changers().delete_path("/work/junk", "file")
    assert isinstance(changer, DeletePathStateChanger)
    assert isinstance(changer.params, DeletePathParameters)
    assert changer.params.path == Path("/work/junk")
    assert changer.params.kind == "file"
    assert changer.params.recursive is False
    assert changer.params.missing_ok is True

    engine.add(changer)
    engine.start(max_workers=1)

    assert not fs.exists(Path("/work/junk"))


def test_delete_path_passes_recursive_and_missing_ok() -> None:
    fs = InMemoryFileSystem()
    pr = ScriptedProcessRunner()
    engine = StateCtl.new(file_system=fs, process_runner=pr)

    changer = engine.changers().delete_path(
        "/work/dir", "dir", recursive=True, missing_ok=False
    )
    assert changer.params.recursive is True
    assert changer.params.missing_ok is False
    assert changer.params.kind == "dir"


def test_ensure_line_in_file_returns_changer_with_params() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/cfg"), content="a\nb\n")
    pr = ScriptedProcessRunner()
    engine = StateCtl.new(file_system=fs, process_runner=pr)

    changer = engine.changers().ensure_line_in_file(
        "/work/cfg", "c", AtEnd()
    )
    assert isinstance(changer, EnsureLineInFileStateChanger)
    assert isinstance(changer.params, EnsureLineInFileParameters)
    assert changer.params.path == Path("/work/cfg")
    assert changer.params.line == "c"
    assert isinstance(changer.params.placement, AtEnd)
    assert changer.params.strict_anchor is True
    assert changer.params.encoding == "utf-8"

    engine.add(changer)
    engine.start(max_workers=1)

    assert fs.read_text_file(Path("/work/cfg")) == "a\nb\nc\n"


def test_ensure_line_in_file_passes_strict_anchor_and_encoding() -> None:
    fs = InMemoryFileSystem()
    pr = ScriptedProcessRunner()
    engine = StateCtl.new(file_system=fs, process_runner=pr)

    changer = engine.changers().ensure_line_in_file(
        "/work/cfg", "x", AtEnd(), strict_anchor=False, encoding="latin-1"
    )
    assert changer.params.strict_anchor is False
    assert changer.params.encoding == "latin-1"


def test_replace_in_file_returns_changer_with_params() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/cfg"), content="hello world\n")
    pr = ScriptedProcessRunner()
    engine = StateCtl.new(file_system=fs, process_runner=pr)

    match = LiteralMatch(needle="world", expected_count=1, replacement="there")
    changer = engine.changers().replace_in_file("/work/cfg", match)
    assert isinstance(changer, ReplaceInFileStateChanger)
    assert isinstance(changer.params, ReplaceInFileParameters)
    assert changer.params.path == Path("/work/cfg")
    assert changer.params.match is match
    assert changer.params.encoding == "utf-8"

    engine.add(changer)
    engine.start(max_workers=1)

    assert fs.read_text_file(Path("/work/cfg")) == "hello there\n"


def test_replace_in_file_passes_encoding() -> None:
    fs = InMemoryFileSystem()
    pr = ScriptedProcessRunner()
    engine = StateCtl.new(file_system=fs, process_runner=pr)

    match = LiteralMatch(needle="x", expected_count=1, replacement="y")
    changer = engine.changers().replace_in_file(
        "/work/cfg", match, encoding="latin-1"
    )
    assert changer.params.encoding == "latin-1"
