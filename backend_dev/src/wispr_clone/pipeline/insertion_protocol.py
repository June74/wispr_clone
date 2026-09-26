"""Serialize insertion claims, destination checks, and one-shot delivery."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol, TypeVar

from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.contracts.run import AttemptOutcome
from wispr_clone.history.repo import HistoryRepo
from wispr_clone.history.retention import is_expired
from wispr_clone.insertion.destination import DestinationSnapshot
from wispr_clone.insertion.inserter import (
    DispatchResult,
    PreviousFocus,
    bring_forward,
    confirm,
    dispatch,
    restore,
)
from wispr_clone.insertion.uia import UiaApi
from wispr_clone.insertion.verifier import verify
from wispr_clone.insertion.win32 import Win32Api


class ProtocolOutcome(StrEnum):
    INSERTED = "inserted"
    UNCERTAIN = "uncertain"
    FAILED = "failed"
    CANCELLED = "cancelled"
    AWAITING = "awaiting"
    HELD = "held"
    ABANDONED = "abandoned"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class ProtocolResult:
    outcome: ProtocolOutcome
    attempt_id: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class WaitingRun:
    run_id: str
    text: str
    snapshot: DestinationSnapshot
    request_id: str
    awaiting_since: float


T = TypeVar("T")


class Offload(Protocol):
    async def __call__(self, operation: Callable[[], T]) -> T: ...


class InsertionProtocol:
    def __init__(
        self,
        history: HistoryRepo,
        win32: Win32Api,
        uia: UiaApi,
        *,
        offload: Offload,
        clock: Callable[[], float],
        new_id: Callable[[], str],
        idle_threshold_ms: int = 1000,
        return_settle_ms: int = 300,
        wait_limit_s: float = 600.0,
        bring_forward_settle_s: float = 0.1,
        paste_settle_s: float = 0.5,
    ) -> None:
        self._history = history
        self._win32 = win32
        self._uia = uia
        self._offload = offload
        self._clock = clock
        self._new_id = new_id
        self._idle_threshold_ms = idle_threshold_ms
        self._return_settle_ms = return_settle_ms
        self._wait_limit_s = wait_limit_s
        self._bring_forward_settle_s = bring_forward_settle_s
        self._paste_settle_s = paste_settle_s
        self._lock = asyncio.Lock()

    async def attempt(
        self,
        run_id: str,
        text: str,
        snapshot: DestinationSnapshot,
        *,
        request_id: str,
        kind: Literal["automatic", "explicit"],
        is_cancelled: Callable[[], bool],
    ) -> ProtocolResult:
        async with self._lock:
            return await self._attempt_locked(
                run_id,
                text,
                snapshot,
                request_id=request_id,
                kind=kind,
                is_cancelled=is_cancelled,
            )

    async def _attempt_locked(
        self,
        run_id: str,
        text: str,
        snapshot: DestinationSnapshot,
        *,
        request_id: str,
        kind: Literal["automatic", "explicit"],
        is_cancelled: Callable[[], bool],
        idle_start: int | None = None,
    ) -> ProtocolResult:
        if is_cancelled():
            return ProtocolResult(ProtocolOutcome.CANCELLED, None, "cancelled")
        initial = await self._offload(lambda: verify(snapshot, self._win32, self._uia))
        if initial.status == "changed":
            return ProtocolResult(ProtocolOutcome.AWAITING, None, "window changed")
        if initial.status == "closed":
            return ProtocolResult(ProtocolOutcome.HELD, None, "window closed")
        if initial.status == "unverifiable":
            return ProtocolResult(ProtocolOutcome.HELD, None, "unverifiable")

        try:
            claim = await self._history.claim_attempt(
                run_id,
                attempt_id=self._new_id(),
                request_id=request_id,
                kind=kind,
                target=snapshot.to_json(),
            )
        except WisprError as error:
            if error.error_code == ErrorCode.DUPLICATE_REQUEST:
                return ProtocolResult(
                    ProtocolOutcome.DUPLICATE, None, "automatic attempt exists"
                )
            if error.error_code in (ErrorCode.RUN_EXPIRED, ErrorCode.RUN_NOT_FOUND):
                return ProtocolResult(ProtocolOutcome.ABANDONED, None, "expired")
            return ProtocolResult(ProtocolOutcome.HELD, None, "claim failed")
        except Exception:
            return ProtocolResult(ProtocolOutcome.HELD, None, "claim failed")
        attempt_id = claim.attempt.attempt_id
        if claim.deduplicated:
            return ProtocolResult(
                ProtocolOutcome.DUPLICATE, attempt_id, "duplicate request"
            )

        try:
            cancelled = is_cancelled()
        except Exception:
            cancelled = True
        if cancelled:
            await self._resolve(attempt_id, AttemptOutcome.CANCELLED)
            return ProtocolResult(ProtocolOutcome.CANCELLED, attempt_id, "cancelled")
        try:
            run = await self._history.get(run_id)
            # History protects in-flight rows from its ordinary retention sweep.
            # The protocol must still enforce the dispatch-time expiry boundary.
            if is_expired(run.created_at, self._clock()):
                await self._resolve(attempt_id, AttemptOutcome.CANCELLED)
                try:
                    await self._history.enforce_retention()
                except Exception:
                    # Expiry is already determined; retention errors are private.
                    pass
                return ProtocolResult(ProtocolOutcome.ABANDONED, attempt_id, "expired")
        except WisprError as error:
            if error.error_code in (ErrorCode.RUN_EXPIRED, ErrorCode.RUN_NOT_FOUND):
                return ProtocolResult(ProtocolOutcome.ABANDONED, attempt_id, "expired")
            await self._resolve(attempt_id, AttemptOutcome.FAILED)
            return ProtocolResult(ProtocolOutcome.FAILED, attempt_id, "history error")
        except Exception:
            await self._resolve(attempt_id, AttemptOutcome.FAILED)
            return ProtocolResult(ProtocolOutcome.FAILED, attempt_id, "history error")

        try:
            check = await self._offload(
                lambda: verify(snapshot, self._win32, self._uia)
            )
        except Exception:
            await self._resolve(attempt_id, AttemptOutcome.FAILED)
            return ProtocolResult(ProtocolOutcome.FAILED, attempt_id, "unverifiable")
        if check.status != "same":
            await self._resolve(attempt_id, AttemptOutcome.FAILED)
            reason = (
                "window closed"
                if check.status == "closed"
                else (
                    "unverifiable"
                    if check.status == "unverifiable"
                    else "window changed"
                )
            )
            return ProtocolResult(ProtocolOutcome.FAILED, attempt_id, reason)
        if idle_start is not None:
            try:
                idle_now = await self._offload(self._win32.idle_ms)
            except Exception:
                await self._resolve(attempt_id, AttemptOutcome.FAILED)
                return ProtocolResult(
                    ProtocolOutcome.FAILED, attempt_id, "input during jump"
                )
            if idle_now < idle_start:
                await self._resolve(attempt_id, AttemptOutcome.FAILED)
                return ProtocolResult(
                    ProtocolOutcome.FAILED, attempt_id, "input during jump"
                )

        try:
            cancelled = is_cancelled()
        except Exception:
            cancelled = True
        if cancelled:
            await self._resolve(attempt_id, AttemptOutcome.CANCELLED)
            return ProtocolResult(ProtocolOutcome.CANCELLED, attempt_id, "cancelled")

        try:
            sent: DispatchResult = await self._offload(
                lambda: dispatch(
                    text,
                    snapshot,
                    self._win32,
                    self._uia,
                    paste_settle_s=self._paste_settle_s,
                )
            )
        except Exception:
            await self._resolve(attempt_id, AttemptOutcome.UNCERTAIN)
            return ProtocolResult(
                ProtocolOutcome.UNCERTAIN, attempt_id, "dispatch error"
            )
        if sent.events_accepted == 0:
            await self._resolve(attempt_id, AttemptOutcome.FAILED)
            return ProtocolResult(ProtocolOutcome.FAILED, attempt_id, "no events")
        try:
            confirmed = await self._offload(
                lambda: confirm(text, sent, snapshot, self._uia)
            )
        except Exception:
            await self._resolve(attempt_id, AttemptOutcome.UNCERTAIN)
            return ProtocolResult(
                ProtocolOutcome.UNCERTAIN, attempt_id, "not confirmed"
            )
        if confirmed == "inserted":
            await self._resolve(attempt_id, AttemptOutcome.INSERTED)
            return ProtocolResult(ProtocolOutcome.INSERTED, attempt_id, "")
        await self._resolve(attempt_id, AttemptOutcome.UNCERTAIN)
        return ProtocolResult(ProtocolOutcome.UNCERTAIN, attempt_id, "not confirmed")

    async def _resolve(self, attempt_id: str, outcome: AttemptOutcome) -> None:
        try:
            await self._history.resolve_attempt(attempt_id, outcome)
        except Exception:
            # Preserve the observed dispatch result; startup recovery handles in_flight.
            pass

    async def deliver_next(
        self,
        waiting: Sequence[WaitingRun],
        *,
        is_cancelled: Callable[[str], bool],
    ) -> tuple[str, ProtocolResult] | None:
        if not waiting:
            return None
        w = min(enumerate(waiting), key=lambda pair: (pair[1].awaiting_since, pair[0]))[
            1
        ]
        async with self._lock:
            if is_cancelled(w.run_id):
                result = ProtocolResult(ProtocolOutcome.CANCELLED, None, "cancelled")
            elif self._clock() - w.awaiting_since > self._wait_limit_s:
                result = ProtocolResult(ProtocolOutcome.HELD, None, "wait limit")
            else:
                verified = await self._offload(
                    lambda: verify(w.snapshot, self._win32, self._uia)
                )
                if verified.status == "closed":
                    result = ProtocolResult(ProtocolOutcome.HELD, None, "window closed")
                elif verified.status == "unverifiable":
                    result = ProtocolResult(ProtocolOutcome.HELD, None, "unverifiable")
                elif verified.status == "same":
                    idle = await self._offload(self._win32.idle_ms)
                    if idle < self._return_settle_ms:
                        result = ProtocolResult(
                            ProtocolOutcome.AWAITING, None, "window changed"
                        )
                    else:
                        result = await self._attempt_locked(
                            w.run_id,
                            w.text,
                            w.snapshot,
                            request_id=w.request_id,
                            kind="automatic",
                            is_cancelled=lambda: is_cancelled(w.run_id),
                        )
                else:
                    idle = await self._offload(self._win32.idle_ms)
                    if idle < self._idle_threshold_ms:
                        result = ProtocolResult(
                            ProtocolOutcome.AWAITING, None, "window changed"
                        )
                    else:
                        idle_start = await self._offload(self._win32.idle_ms)
                        previous: PreviousFocus | None = await self._offload(
                            lambda: bring_forward(
                                w.snapshot,
                                self._win32,
                                self._uia,
                                settle_s=self._bring_forward_settle_s,
                            )
                        )
                        if previous is None:
                            result = ProtocolResult(
                                ProtocolOutcome.HELD, None, "bring forward failed"
                            )
                        else:
                            try:
                                after_jump = await self._offload(
                                    lambda: verify(w.snapshot, self._win32, self._uia)
                                )
                                if after_jump.status != "same":
                                    reason = (
                                        "window closed"
                                        if after_jump.status == "closed"
                                        else "unverifiable"
                                    )
                                    result = ProtocolResult(
                                        ProtocolOutcome.HELD, None, reason
                                    )
                                else:
                                    idle_after = await self._offload(
                                        self._win32.idle_ms
                                    )
                                    if idle_after < idle_start:
                                        result = ProtocolResult(
                                            ProtocolOutcome.AWAITING,
                                            None,
                                            "input during jump",
                                        )
                                    else:
                                        result = await self._attempt_locked(
                                            w.run_id,
                                            w.text,
                                            w.snapshot,
                                            request_id=w.request_id,
                                            kind="automatic",
                                            is_cancelled=lambda: is_cancelled(w.run_id),
                                            idle_start=idle_start,
                                        )
                            finally:
                                await self._offload(
                                    lambda: restore(previous, self._win32, self._uia)
                                )
            return w.run_id, result
