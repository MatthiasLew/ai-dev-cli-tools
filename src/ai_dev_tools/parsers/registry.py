from __future__ import annotations

from collections.abc import Iterable
from typing import Generic, Protocol, TypeVar

from ai_dev_tools.utils.subprocess import CommandResult

ParsedResult = TypeVar("ParsedResult")
ParsedResult_co = TypeVar("ParsedResult_co", covariant=True)


class RegisteredParser(Protocol[ParsedResult_co]):
    @property
    def tool_name(self) -> str: ...

    def can_parse(self, command: CommandResult) -> bool: ...

    def parse(self, command: CommandResult) -> ParsedResult_co: ...


class ParserRegistry(Generic[ParsedResult]):
    def __init__(self, parsers: Iterable[RegisteredParser[ParsedResult]] = ()) -> None:
        self._parsers = list(parsers)

    @property
    def parsers(self) -> tuple[RegisteredParser[ParsedResult], ...]:
        return tuple(self._parsers)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(parser.tool_name for parser in self._parsers)

    def register(
        self,
        parser: RegisteredParser[ParsedResult],
        *,
        prepend: bool = True,
        replace: bool = False,
    ) -> None:
        matching = [item for item in self._parsers if item.tool_name == parser.tool_name]
        if matching and not replace:
            raise ValueError(f"Parser already registered: {parser.tool_name}")
        if matching:
            self._parsers = [item for item in self._parsers if item.tool_name != parser.tool_name]
        if prepend:
            self._parsers.insert(0, parser)
        else:
            self._parsers.append(parser)

    def unregister(self, tool_name: str) -> None:
        original = len(self._parsers)
        self._parsers = [item for item in self._parsers if item.tool_name != tool_name]
        if len(self._parsers) == original:
            raise KeyError(tool_name)

    def parse(self, command: CommandResult) -> ParsedResult:
        for parser in self._parsers:
            if parser.can_parse(command):
                return parser.parse(command)
        raise LookupError("No output parser accepted the command")
