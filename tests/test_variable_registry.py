from __future__ import annotations

import threading
from pathlib import Path

import pytest

from statectl._interfaces.registry import (
    DuplicateVariableError,
    VariableNotFoundError,
    VariableTypeError,
)
from statectl._modules import InMemoryVariableRegistry


def test_bind_then_get_round_trips() -> None:
    reg = InMemoryVariableRegistry()
    reg.bind("data_dir", Path("/var/db"))
    assert reg.get("data_dir") == Path("/var/db")


def test_get_missing_raises_with_name() -> None:
    reg = InMemoryVariableRegistry()
    with pytest.raises(VariableNotFoundError) as exc:
        reg.get("missing")
    assert exc.value.name == "missing"
    assert "missing" in str(exc.value)


def test_require_typed_match_returns_value() -> None:
    reg = InMemoryVariableRegistry()
    p = Path("/var/db")
    reg.bind("data_dir", p)
    out: Path = reg.require("data_dir", as_type=Path)
    assert out is p


def test_require_type_mismatch_raises() -> None:
    reg = InMemoryVariableRegistry()
    reg.bind("data_dir", "not-a-path")
    with pytest.raises(VariableTypeError) as exc:
        reg.require("data_dir", as_type=Path)
    assert exc.value.expected is Path
    assert exc.value.actual is str


def test_require_missing_raises_not_found_not_type() -> None:
    reg = InMemoryVariableRegistry()
    with pytest.raises(VariableNotFoundError):
        reg.require("missing", as_type=Path)


def test_has() -> None:
    reg = InMemoryVariableRegistry()
    assert not reg.has("x")
    reg.bind("x", 1)
    assert reg.has("x")


def test_double_bind_raises_duplicate() -> None:
    reg = InMemoryVariableRegistry()
    reg.bind("x", 1)
    with pytest.raises(DuplicateVariableError) as exc:
        reg.bind("x", 2)
    assert exc.value.name == "x"


def test_snapshot_is_read_only() -> None:
    reg = InMemoryVariableRegistry()
    reg.bind("x", 1)
    snap = reg.snapshot()
    assert dict(snap) == {"x": 1}
    with pytest.raises(TypeError):
        snap["y"] = 2  # type: ignore[index]


def test_concurrent_binds_are_race_free() -> None:
    reg = InMemoryVariableRegistry()
    n_threads = 50
    per_thread = 20
    errors: list[Exception] = []

    def worker(tid: int) -> None:
        try:
            for i in range(per_thread):
                reg.bind(f"t{tid}-i{i}", (tid, i))
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    snap = reg.snapshot()
    assert len(snap) == n_threads * per_thread
    for tid in range(n_threads):
        for i in range(per_thread):
            assert snap[f"t{tid}-i{i}"] == (tid, i)
