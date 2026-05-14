from __future__ import annotations

from typing import Sequence

from statectl.state_changer import StateChanger


class ExecutionNode:
    """A node in the engine's execution DAG. Wraps one `StateChanger` and
    declares its upstream nodes. Identity is the node object itself."""

    def __init__(
        self,
        changer: StateChanger,
        depends_on: Sequence["ExecutionNode"] = (),
    ) -> None:
        self._changer: StateChanger = changer
        self._upstreams: list[ExecutionNode] = []
        if depends_on:
            self.depends_on(*depends_on)

    def depends_on(self, *nodes: "ExecutionNode") -> "ExecutionNode":
        for node in nodes:
            if node is self:
                raise ValueError(
                    f"ExecutionNode {self.name()!r} cannot depend on itself"
                )
            if node not in self._upstreams:
                self._upstreams.append(node)
        return self

    @property
    def changer(self) -> StateChanger:
        return self._changer

    @property
    def upstreams(self) -> tuple["ExecutionNode", ...]:
        return tuple(self._upstreams)

    def name(self) -> str:
        return self._changer.name()
