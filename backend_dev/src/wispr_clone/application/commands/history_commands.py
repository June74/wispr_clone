"""Handlers for retained history commands."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from wispr_clone.application.api import CommandSpec
from wispr_clone.application.commands.run_commands import RunCommands
from wispr_clone.contracts.common import ErrorCode, WisprError
from wispr_clone.history.repo import HistoryRepo, RunRecord
from wispr_clone.pipeline.run_controller import RunController


class HistoryCommands:
    """Expose run history and privacy-preserving clipboard operations."""

    def __init__(
        self,
        history: HistoryRepo,
        controller: RunController,
        runs: RunCommands,
        *,
        copy_to_clipboard: Callable[[str], Awaitable[None]],
    ) -> None:
        self._history = history
        self._controller = controller
        self._runs = runs
        self._copy_to_clipboard = copy_to_clipboard

    def specs(self) -> dict[str, CommandSpec]:
        return {
            "history_list": CommandSpec(self._list, mutating=False),
            "history_get": CommandSpec(self._get, mutating=False),
            "history_delete": CommandSpec(self._delete, mutating=True),
            "history_delete_all": CommandSpec(self._delete_all, mutating=True),
            "history_copy": CommandSpec(self._copy, mutating=True),
        }

    async def _list(self, _: Mapping[str, object]) -> Mapping[str, object]:
        records = await self._history.list_runs()
        return {"runs": [self._item(record) for record in records]}

    async def _get(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        run_id = _run_id(payload)
        record = await self._history.get(run_id)
        return self._item(record, include_all_text=True)

    async def _delete(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        run_id = _run_id(payload)
        self._controller.abort(run_id)
        self._runs.invalidate(run_id)
        result = await self._history.delete_run(run_id)
        return {"run_ids": list(result.run_ids), "audio_pending": result.audio_pending}

    async def _delete_all(self, _: Mapping[str, object]) -> Mapping[str, object]:
        records = await self._history.list_runs()
        for record in records:
            self._controller.abort(record.id)
            self._runs.invalidate(record.id)
        result = await self._history.delete_all()
        return {"run_ids": list(result.run_ids), "audio_pending": result.audio_pending}

    async def _copy(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        run_id = _run_id(payload)
        text = await self._controller.copy_text(run_id)
        await self._copy_to_clipboard(text)
        return {"run_id": run_id}

    def _item(
        self, record: RunRecord, *, include_all_text: bool = False
    ) -> dict[str, object]:
        item = self._controller.run_snapshot(record)
        selected = {
            "original": record.original_text,
            "adjusted": record.adjusted_text,
            "cleaned": record.cleaned_text,
        }.get(record.output_selection or "", record.original_text)
        item["text"] = selected
        if include_all_text:
            item.update(
                {
                    "original_text": record.original_text,
                    "adjusted_text": record.adjusted_text,
                    "cleaned_text": record.cleaned_text,
                }
            )
        return item


def _run_id(payload: Mapping[str, object]) -> str:
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise WisprError(ErrorCode.VALIDATION, "history.command", "run_id")
    return run_id
