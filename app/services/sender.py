"""Outgoing event sender implementations."""

import logging
from typing import Protocol


class EventSender(Protocol):
    def send(self, event_type: str, payload: dict[str, object]) -> None: ...


class SenderError(Exception):
    """Raised when an outgoing event cannot be delivered."""


class LoggingSender:
    """Development sender that records published events in the application log."""

    def send(self, event_type: str, payload: dict[str, object]) -> None:
        logging.getLogger(__name__).info(
            "Published outbox event %s: %s",
            event_type,
            payload,
        )
