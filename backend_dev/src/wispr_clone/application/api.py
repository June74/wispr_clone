"""Validate command session and deadline metadata before dispatch."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from wispr_clone.contracts.common import (
    ErrorCode,
    Result,
    ThirdPartyError,
    WisprError,
)

Handler = Callable[[Mapping[str, object]], Awaitable[Mapping[str, object]]]
_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CommandSpec:
    handler: Handler
    mutating: bool
    needs_session: bool = True


class Api:
    def __init__(
        self,
        commands: Mapping[str, CommandSpec],
        *,
        session_token: str,
        clock: Callable[[], float],
        max_validity_s: float = 30.0,
    ) -> None:
        self._commands = dict(commands)
        self._session_token = session_token
        self._clock = clock
        self._max_validity_s = max_validity_s

    @property
    def session_token(self) -> str:
        return self._session_token

    async def call(
        self, name: str, payload: Mapping[str, object]
    ) -> Result[dict[str, object]]:
        spec = self._commands.get(name)
        if spec is None:
            return Result(False, None, ErrorCode.UNKNOWN_COMMAND)
        if spec.needs_session and payload.get("session_token") != self._session_token:
            return Result(False, None, ErrorCode.PREVIOUS_SESSION_TOKEN)
        if spec.mutating:
            deadline = payload.get("deadline")
            if isinstance(deadline, bool) or not isinstance(deadline, (int, float)):
                return Result(False, None, ErrorCode.VALIDATION)
            now = self._clock()
            if deadline < now:
                return Result(False, None, ErrorCode.EXPIRED_COMMAND)
            if deadline > now + self._max_validity_s:
                return Result(False, None, ErrorCode.VALIDATION)
        clean_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"session_token", "deadline"}
        }
        try:
            data = await spec.handler(clean_payload)
            return Result(True, dict(data), None)
        except (WisprError, ThirdPartyError) as error:
            _logger.warning("command failed: %s", error.error_code.value)
            return Result(False, None, error.error_code)
        except Exception:
            _logger.warning("command failed: %s", ErrorCode.STORAGE_ERROR.value)
            return Result(False, None, ErrorCode.STORAGE_ERROR)
