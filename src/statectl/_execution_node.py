from __future__ import annotations

from typing import Sequence

from statectl._state_changer import StateChanger


class ExecutionNode:
    """Internal graph node wrapping one `StateChanger`. Constructed by the
    engine when a changer is added; not part of the user-facing construction
    API. Exposed for introspection (e.g. reading `EngineResult.reports`)."""

    def __init__(
        self,
        changer: StateChanger,
        upstreams: Sequence["ExecutionNode"] = (),
    ) -> None:
        self._changer: StateChanger = changer
        self._upstreams: tuple[ExecutionNode, ...] = tuple(upstreams)

    @property
    def changer(self) -> StateChanger:
        return self._changer

    @property
    def upstreams(self) -> tuple["ExecutionNode", ...]:
        return self._upstreams

    def name(self) -> str:
        return self._changer.name()
