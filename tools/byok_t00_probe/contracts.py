"""Small, provider-neutral contracts for the T00 SDK protocol probe.

Continuation payloads are server-side protocol state.  The only public
projection in this module deliberately contains visible assistant text only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


EventKind = Literal["text_delta", "tool_delta", "terminal", "error"]


@dataclass(frozen=True)
class ModelEvent:
    kind: EventKind
    protocol: str
    text: str | None = None
    finish_reason: str | None = None
    error_code: str | None = None
    _raw: Any = field(default=None, repr=False, compare=False)

    def public_projection(self) -> dict[str, str]:
        """Return a safe event projection without raw protocol state."""
        result = {"type": self.kind, "protocol": self.protocol}
        if self.text is not None:
            result["text"] = self.text
        if self.finish_reason is not None:
            result["finish_reason"] = self.finish_reason
        if self.error_code is not None:
            result["error_code"] = self.error_code
        return result


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]
    _raw_arguments: str | dict[str, Any] = field(repr=False, compare=False)


@dataclass(frozen=True)
class ServerContinuation:
    """Protocol-native assistant state that may only be kept server-side."""

    protocol: str
    payload: dict[str, Any] = field(repr=False, compare=False)
    schema_version: int = 1

    def private_record(self) -> dict[str, Any]:
        """Copyable storage form for server code; never use in API responses."""
        return {
            "protocol": self.protocol,
            "schema_version": self.schema_version,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class ModelTurn:
    text: str
    finish_reason: str
    tool_calls: tuple[ToolCall, ...]
    usage: dict[str, Any] | None
    continuation: ServerContinuation = field(repr=False, compare=False)
    events: tuple[ModelEvent, ...] = field(default=(), repr=False, compare=False)

    def public_message(self) -> dict[str, str]:
        """The visible assistant message; raw continuation and tools stay private."""
        return {"role": "assistant", "content": self.text}


class ProviderError(Exception):
    """A sanitized, stable error.  Provider bodies and exception text are omitted."""

    def __init__(
        self,
        code: str,
        protocol: str,
        *,
        http_status: int | None = None,
        finish_reason: str | None = None,
    ) -> None:
        self.code = code
        self.protocol = protocol
        self.http_status = http_status
        self.finish_reason = finish_reason
        super().__init__(code)

    def __str__(self) -> str:
        return self.code

    def public_projection(self) -> dict[str, Any]:
        result: dict[str, Any] = {"error_code": self.code, "protocol": self.protocol}
        if self.http_status is not None:
            result["http_status"] = self.http_status
        if self.finish_reason is not None:
            result["finish_reason"] = self.finish_reason
        return result
