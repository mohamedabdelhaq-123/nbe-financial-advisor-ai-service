"""Chat conversation models — friendly re-exports of the generated mirror."""

from app.backend_db._generated_models import Conversations as Conversation
from app.backend_db._generated_models import MessageReferences as MessageReference
from app.backend_db._generated_models import Messages as Message

__all__ = [
    "Conversation",
    "Message",
    "MessageReference",
]
