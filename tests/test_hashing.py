from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from statectl._interfaces.hashing import HashingNotFound
from tests.fakes.failing_hashing import FailingHashing
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_hashing import ScriptedHashing, sha256_of


def test_scripted_hashes_content_in_filesystem() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/a"), content="hello")
    h = ScriptedHashing(file_system=fs)
    expected = hashlib.sha256(b"hello").hexdigest()
    assert h.sha256_file(Path("/work/a")) == expected


def test_scripted_raises_when_missing() -> None:
    fs = InMemoryFileSystem()
    h = ScriptedHashing(file_system=fs)
    with pytest.raises(HashingNotFound):
        h.sha256_file(Path("/missing"))


def test_overrides_take_precedence() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/a"), content="actual")
    h = ScriptedHashing(file_system=fs, overrides={Path("/work/a"): "deadbeef"})
    assert h.sha256_file(Path("/work/a")) == "deadbeef"


def test_failing_hashing_injects_one_shot_error() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_file(Path("/work/a"), content="x")
    inner = ScriptedHashing(file_system=fs)
    h = FailingHashing(inner)
    h.fail(HashingNotFound("nope", path=Path("/work/a")))
    with pytest.raises(HashingNotFound):
        h.sha256_file(Path("/work/a"))
    assert h.sha256_file(Path("/work/a")) == sha256_of("x")
