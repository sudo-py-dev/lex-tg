"""Conversation routing, bounded history, and request-local context."""

import asyncio
import contextlib
import json
import re
from contextlib import asynccontextmanager

from pyrogram import raw
from pyrogram.enums import ChatAction

_locks = {}


@asynccontextmanager
async def conversation_lock(key):
    entry = _locks.setdefault(key, [asyncio.Lock(), 0])
    entry[1] += 1
    try:
        async with entry[0]:
            yield
    finally:
        entry[1] -= 1
        if not entry[1]:
            _locks.pop(key, None)


def conversation_scope(message):
    sender = message.from_user or message.sender_chat
    return (
        message.chat.id,
        getattr(message, "message_thread_id", None) or 0,
        sender.id if sender else 0,
    )


def is_addressed(message, me) -> bool:
    text = message.text or message.caption or ""
    if not text.strip() or text.lstrip().startswith("/"):
        return False
    username = me.username
    mention = bool(username and re.search(rf"(?<![\w@])@{re.escape(username)}(?!\w)", text, re.I))
    quoted = message.reply_to_message
    return mention or bool(quoted and quoted.from_user and quoted.from_user.id == me.id)


def request_content(message, me) -> str:
    sender = message.from_user or message.sender_chat
    text = (message.text or message.caption or "").strip()
    if me.username:
        text = re.sub(rf"(?<![\w@])@{re.escape(me.username)}(?!\w)", "", text, flags=re.I).strip()
    content = {
        "speaker": getattr(sender, "first_name", None)
        or getattr(sender, "title", None)
        or "Participant",
        "message": text[:6000] or "Hello!",
    }
    quoted = message.reply_to_message
    if quoted:
        author = quoted.from_user or quoted.sender_chat
        content["reply_to"] = {
            "speaker": getattr(author, "first_name", None)
            or getattr(author, "title", None)
            or "Participant",
            "from_assistant": bool(quoted.from_user and quoted.from_user.id == me.id),
            "text": (quoted.text or quoted.caption or "[Attachment; contents unavailable]")[:2000],
        }
    return json.dumps(content, ensure_ascii=False)


def compact_history(messages, max_messages=24, max_chars=12000):
    # Keep complete recent user/assistant pairs, never a stranded assistant turn.
    pairs = []
    for index in range(0, len(messages) - 1, 2):
        user, assistant = messages[index : index + 2]
        if user.get("role") == "user" and assistant.get("role") == "assistant":
            pairs.append([user, assistant])
    result, total = [], 0
    for pair in reversed(pairs[-(max_messages // 2) :]) if max_messages >= 2 else []:
        size = sum(len(str(message.get("content", ""))) for message in pair)
        if total + size > max_chars:
            break
        result[0:0] = pair
        total += size
    return result


@asynccontextmanager
async def typing_indicator(client, message):
    async def keep_typing():
        while True:
            with contextlib.suppress(Exception):
                thread_id = getattr(message, "message_thread_id", None)
                if thread_id:
                    await client.invoke(
                        raw.functions.messages.SetTyping(
                            peer=await client.resolve_peer(message.chat.id),
                            action=raw.types.SendMessageTypingAction(),
                            top_msg_id=thread_id,
                        )
                    )
                else:
                    await client.send_chat_action(message.chat.id, ChatAction.TYPING)
            await asyncio.sleep(4)

    task = asyncio.create_task(keep_typing())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
