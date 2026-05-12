"""Trigger event sub-service.

Owns trigger CRUD and channel-message ingestion. Extracted from
``ControlPlaneService`` without behaviour change; method names match the
original facade methods exactly.
"""

from __future__ import annotations

from typing import Any

from src.control_plane.models import TriggerEvent
from src.control_plane.redaction import RedactionService
from src.control_plane.store import ControlPlaneStore


class TriggersService:
    def __init__(self, store: ControlPlaneStore, redaction: RedactionService) -> None:
        self._store = store
        self._redaction = redaction

    def list_triggers(self) -> list[TriggerEvent]:
        snapshot = self._store.read()
        return sorted(snapshot.triggers.values(), key=lambda item: item.created_at, reverse=True)

    def create_trigger_event(
        self,
        *,
        source: str,
        message: str,
        channel_name: str | None = None,
        chat_id: str | None = None,
        user_id: str | None = None,
        classification: str = "manual",
        metadata: dict[str, Any] | None = None,
    ) -> TriggerEvent:
        trigger = TriggerEvent(
            source=source,
            channel_name=channel_name,
            chat_id=chat_id,
            user_id=user_id,
            classification=classification,
            message=message,
            masked_message=self._redaction.redact_text(message),
            metadata=metadata or {},
        )

        def mutate(snapshot):
            snapshot.triggers[trigger.id] = trigger

        self._store.mutate(mutate)
        return trigger

    def record_channel_message(self, msg: Any, *, thread_id: str | None = None) -> TriggerEvent:
        metadata = {
            "thread_id": thread_id,
            "msg_type": getattr(msg, "msg_type", None),
            "topic_id": getattr(msg, "topic_id", None),
            "thread_ts": getattr(msg, "thread_ts", None),
        }
        return self.create_trigger_event(
            source=getattr(msg, "channel_name", "channel"),
            channel_name=getattr(msg, "channel_name", None),
            chat_id=getattr(msg, "chat_id", None),
            user_id=getattr(msg, "user_id", None),
            message=getattr(msg, "text", ""),
            classification="channel_message",
            metadata=metadata,
        )
