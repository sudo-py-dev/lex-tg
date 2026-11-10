from pyrogram.enums import ChatType


def normalize_chat_type(chat_type: ChatType) -> ChatType:
    """Treat topic-enabled groups as supergroups throughout settings and storage."""
    return ChatType.SUPERGROUP if chat_type == ChatType.FORUM else chat_type
