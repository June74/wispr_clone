"""In-memory event sink enforcing JSON-compatible event data."""

from __future__ import annotations

import json
from typing import Any

from wispr_clone.contracts.events import (
    EVENT_PAYLOAD_TYPES,
    EventPayload,
    EventSink,
)


class FakeEventSink:
    """Record published events in order after validating JSON data."""

    def __init__(self) -> None:
        self.events: list[EventPayload] = []

    def publish(self, event: EventPayload) -> None:
        if not isinstance(event, dict):
            raise TypeError("event must be a dict")
        name = event.get("name")
        if not isinstance(name, str) or name not in EVENT_PAYLOAD_TYPES:
            raise ValueError("event name is not a known event")
        required = set(EVENT_PAYLOAD_TYPES[name].__annotations__)
        if not required.issubset(event):
            raise ValueError("event is missing required fields")
        encoded = json.dumps(event, allow_nan=False)
        decoded: Any = json.loads(encoded)
        if decoded != event:
            raise ValueError("event payload must contain JSON data")
        self.events.append(event)

    def by_name(self, name: str) -> list[EventPayload]:
        return [event for event in self.events if event.get("name") == name]


_event_sink_protocol_check: EventSink = FakeEventSink()
