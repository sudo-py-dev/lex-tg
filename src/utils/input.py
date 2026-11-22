import asyncio
import contextlib
import json
from uuid import uuid4

from loguru import logger
from pyrogram import filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import (
    FloodWait,
    MessageIdInvalid,
    MessageNotModified,
    RPCError,
)
from pyrogram.types import (
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)

from src.utils.i18n import at
from src.utils.local_cache import get_cache
from src.utils.panel_session import bind_panel


def is_waiting_for_input(fields: str | list[str] | None = None):
    """
    Custom filter to check if a user is currently in an active input flow.
    If match, attaches 'input_state' dictionary to the message object.

    Args:
        fields: Specific field name or list of field names to match.
                If None, matches any active input state for the user.
    """

    async def func(flt, client, message: Message) -> bool:
        fid = getattr(flt, "filter_id", "unknown")
        logger.debug(f"Input Filter Trace: {fid} triggered")
        if not message.from_user:
            return False

        user_id = message.from_user.id
        r = get_cache()

        state_raw = await r.get(f"panel_input:{user_id}")
        if not state_raw:
            return False

        try:
            if isinstance(state_raw, str) and state_raw.startswith("{"):
                state = json.loads(state_raw)
            elif isinstance(state_raw, dict):
                state = state_raw
            else:
                parts = str(state_raw).split(":")
                state = {
                    "chat_id": int(parts[0]),
                    "field": parts[1],
                    "prompt_msg_id": int(parts[2]) if len(parts) > 2 and parts[2] != "0" else None,
                    "page": int(parts[3]) if len(parts) > 3 else 0,
                }
        except Exception as e:
            logger.error(f"Input Filter [{fid}]: Failed to parse state for user {user_id}: {e}")
            return False

        current_field = state.get("field")
        filter_fields = getattr(flt, "fields", None)

        if filter_fields:
            allowed = [filter_fields] if isinstance(filter_fields, str) else filter_fields
            if current_field not in allowed:
                logger.trace(
                    f"Input Filter [{fid}]: Field mismatch for user {user_id}. Current: {current_field}, Allowed: {allowed}"
                )
                return False

        try:
            member = await client.get_chat_member(state["chat_id"], user_id)
        except RPCError:
            await message.reply(await at(user_id, "panel.error_generic"))
            return False
        if member.status not in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR):
            if await r.delete_if_value(f"panel_input:{user_id}", state_raw):
                await message.reply(await at(user_id, "common.err_access_denied"))
            return False
        if await r.get(f"panel_input:{user_id}") != state_raw:
            return False

        logger.debug(
            f"Input Filter [{fid}]: Match success for user {user_id}, field: {current_field}"
        )
        message.input_state = state
        message.input_capture_value = state_raw
        return True

    filter_id = (
        f"input_{fields}"
        if isinstance(fields, str)
        else f"input_{'_'.join(fields) if fields else 'any'}"
    )
    logger.debug(f"Input Filter: Initializing instance for fields {fields}")
    return filters.create(func, fields=fields, filter_id=filter_id)


async def capture_next_input(
    user_id: int, chat_id: int, field: str, prompt_msg_id: int | None = None, page: int = 0
) -> None:
    """
    Arms the capture state in Local Cache to intercept the next private message from the user.
    Stores state as JSON for better field expansion and robustness.
    """
    r = get_cache()
    state = {
        "capture_id": uuid4().hex,
        "chat_id": chat_id,
        "field": field,
        "prompt_msg_id": prompt_msg_id or 0,
        "page": page,
    }

    logger.debug(
        f"Input Capture: Arming capture for user {user_id}, field: {field}, chat: {chat_id}"
    )
    await r.set(f"panel_input:{user_id}", json.dumps(state), ttl=300)


async def cancel_input_capture(user_id: int, prompt_msg_id: int) -> bool:
    """Clear a pending capture only when it belongs to this prompt."""
    cache = get_cache()
    key = f"panel_input:{user_id}"
    raw = await cache.get(key)
    if isinstance(raw, str):
        with contextlib.suppress(json.JSONDecodeError):
            state = json.loads(raw)
            if isinstance(state, dict) and state.get("prompt_msg_id") == prompt_msg_id:
                return await cache.delete_if_value(key, raw)
    return False


async def finalize_input_capture(
    client,
    message: Message,
    user_id: int,
    prompt_msg_id: int | None,
    panel_text: str,
    kb: InlineKeyboardMarkup,
    success_text: str | None = None,
) -> None:
    """
    Finalize input flow:
    1. Delete the user's input message if possible.
    2. Send an optional success notification.
    3. Update the original panel message or send a new one.
    4. Remove the capture state from cache.
    """

    r = get_cache()
    capture_value = getattr(message, "input_capture_value", None)
    if capture_value is not None:
        await r.delete_if_value(f"panel_input:{user_id}", capture_value)

    with contextlib.suppress(RPCError):
        await message.delete()

    link_preview = LinkPreviewOptions(is_disabled=True)
    if success_text:
        panel_text = f"{success_text}\n\n{panel_text}"

    if prompt_msg_id and prompt_msg_id > 0:

        async def edit() -> None:
            await client.edit_message_text(
                chat_id=user_id,
                message_id=prompt_msg_id,
                text=panel_text,
                reply_markup=kb,
                link_preview_options=link_preview,
            )

        try:
            try:
                await edit()
            except FloodWait as error:
                if error.value > 3:
                    raise
                await asyncio.sleep(error.value + 1)
                await edit()
        except MessageNotModified:
            return
        except MessageIdInvalid:
            pass
        else:
            return

    panel = await client.send_message(
        user_id, panel_text, reply_markup=kb, link_preview_options=link_preview
    )
    if state := getattr(message, "input_state", None):
        await bind_panel(user_id, panel.id, state["chat_id"])
