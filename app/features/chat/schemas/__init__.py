"""Public schema surface for the chat slice.

Re-exports the request DTO and the stream-contract models so existing
``from app.features.chat.schemas import ChatTurnRequest`` imports keep resolving.
"""

from app.features.chat.schemas.events import (
    DoneEvent,
    DonePayload,
    ErrorEvent,
    ErrorPayload,
    TokenEvent,
)
from app.features.chat.schemas.references import Reference, TargetType
from app.features.chat.schemas.request import ChatTurnRequest
from app.features.chat.schemas.widgets import (
    Allocation,
    AllocationSliderPayload,
    AllocationSliderWidget,
    ProductCardPayload,
    ProductCardWidget,
    ProductMatchPayloadItem,
    Widget,
)

__all__ = [
    "Allocation",
    "AllocationSliderPayload",
    "AllocationSliderWidget",
    "ChatTurnRequest",
    "DoneEvent",
    "DonePayload",
    "ErrorEvent",
    "ErrorPayload",
    "ProductCardPayload",
    "ProductCardWidget",
    "ProductMatchPayloadItem",
    "Reference",
    "TargetType",
    "TokenEvent",
    "Widget",
]
