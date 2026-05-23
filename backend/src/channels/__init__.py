"""IM Channel integration for CapyHome.

Provides a pluggable channel system that connects external messaging platforms
(Slack, Telegram) to the CapyHome agent via the ChannelManager,
which uses ``langgraph-sdk`` to communicate with the underlying LangGraph Server.
"""

from src.channels.base import Channel
from src.channels.message_bus import InboundMessage, MessageBus, OutboundMessage

__all__ = [
    "Channel",
    "InboundMessage",
    "MessageBus",
    "OutboundMessage",
]
