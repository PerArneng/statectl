from __future__ import annotations

from pathlib import Path

from statectl import StateCtl
from statectl.interfaces.process import ProcessResult
from statectl.statechangers import (
    NewTextFileRollbackStateChanger,
    NewTextFileStateChanger,
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
