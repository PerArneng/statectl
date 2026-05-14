from abc import ABC, abstractmethod
from typing import Any


class Logger(ABC):
    @abstractmethod
    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None: ...

    @abstractmethod
    def info(self, msg: str, *args: Any, **kwargs: Any) -> None: ...

    @abstractmethod
    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None: ...

    @abstractmethod
    def error(self, msg: str, *args: Any, **kwargs: Any) -> None: ...

    @abstractmethod
    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None: ...
