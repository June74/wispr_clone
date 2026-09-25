"""JSON-data event payloads published to UI consumers."""

from typing import Protocol, TypedDict


class RunStateEvent(TypedDict):
    name: str
    run_id: str
    version: int
    status: str


class RunRecoveryEvent(TypedDict):
    name: str
    run_id: str
    version: int
    status: str
    actions: list[str]


class ModelStatusItem(TypedDict):
    model_id: str
    role: str
    ready: bool
    error_code: str | None


class ModelsStatusEvent(TypedDict):
    name: str
    models: list[ModelStatusItem]


class HistoryChangedEvent(TypedDict):
    name: str
    run_ids: list[str]
    reason: str


class AudioLevelEvent(TypedDict):
    name: str
    run_id: str | None
    bands: list[float]


EventPayload = (
    RunStateEvent
    | RunRecoveryEvent
    | ModelsStatusEvent
    | HistoryChangedEvent
    | AudioLevelEvent
)


class EventSink(Protocol):
    def publish(self, event: EventPayload) -> None: ...


EVENT_PAYLOAD_TYPES: dict[str, type] = {
    "run:state": RunStateEvent,
    "run:recovery": RunRecoveryEvent,
    "models:status": ModelsStatusEvent,
    "history:changed": HistoryChangedEvent,
    "audio:level": AudioLevelEvent,
}
