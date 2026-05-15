from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from statectl._interfaces.registry import VariableRegistry
from statectl._state_changer import Result, StateChanger


PublishCallback = Callable[[StateChanger, Result], Mapping[str, Any]]
DeferredFactory = Callable[[VariableRegistry], StateChanger]


class ExecutionNode:
    """Internal graph node wrapping one `StateChanger` (or a deferred factory
    that produces one). Constructed by the engine when a changer or deferred
    placeholder is added; not part of the user-facing construction API.
    Exposed for introspection (e.g. reading `EngineResult.reports`)."""

    def __init__(
        self,
        changer: StateChanger | None = None,
        upstreams: Sequence["ExecutionNode"] = (),
        factory: DeferredFactory | None = None,
        publishes: PublishCallback | None = None,
        placeholder_name: str = "",
    ) -> None:
        if changer is None and factory is None:
            raise ValueError("ExecutionNode needs either a changer or a factory")
        self._changer: StateChanger | None = changer
        self._factory: DeferredFactory | None = factory
        self._publishes: PublishCallback | None = publishes
        self._upstreams: tuple[ExecutionNode, ...] = tuple(upstreams)
        self._placeholder_name: str = placeholder_name

    @property
    def changer(self) -> StateChanger | None:
        return self._changer

    @property
    def factory(self) -> DeferredFactory | None:
        return self._factory

    @property
    def publishes(self) -> PublishCallback | None:
        return self._publishes

    @property
    def is_deferred(self) -> bool:
        return self._factory is not None

    @property
    def upstreams(self) -> tuple["ExecutionNode", ...]:
        return self._upstreams

    def resolve(self, changer: StateChanger) -> None:
        self._changer = changer

    def name(self) -> str:
        if self._changer is not None:
            return self._changer.name()
        return self._placeholder_name or "deferred"
