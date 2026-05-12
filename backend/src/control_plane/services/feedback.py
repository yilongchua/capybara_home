"""Feedback event sub-service.

Owns feedback CRUD. Extracted from ``ControlPlaneService`` without behaviour
change; method names match the original facade methods exactly.
"""

from __future__ import annotations

from typing import Any

from src.control_plane.models import FeedbackEvent
from src.control_plane.store import ControlPlaneStore


class FeedbackService:
    def __init__(self, store: ControlPlaneStore) -> None:
        self._store = store

    def list_feedback(self) -> list[FeedbackEvent]:
        snapshot = self._store.read()
        return sorted(snapshot.feedback.values(), key=lambda item: item.created_at, reverse=True)

    def add_feedback(
        self,
        *,
        target_type: str,
        target_id: str,
        value: str,
        comment: str = "",
        source: str = "web",
        metadata: dict[str, Any] | None = None,
    ) -> FeedbackEvent:
        feedback = FeedbackEvent(
            target_type=target_type,
            target_id=target_id,
            value=value,
            comment=comment,
            source=source,
            metadata=metadata or {},
        )

        def mutate(snapshot):
            snapshot.feedback[feedback.id] = feedback

        self._store.mutate(mutate)
        return feedback
