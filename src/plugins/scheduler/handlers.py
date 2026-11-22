import json
import re

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from src.core.bot import bot
from src.core.context import get_context
from src.db.models import ChatNightLock, Reminder
from src.utils.decorators import safe_handler
from src.utils.i18n import at
from src.utils.input import (
    capture_next_input,
    finalize_input_capture,
    is_waiting_for_input,
)
from src.utils.local_cache import get_cache
from src.utils.telegram_storage import extract_message_data


@bot.on_message(
    filters.private & is_waiting_for_input(["chatnightlockStart", "chatnightlockEnd"]), group=-50
)
@safe_handler
async def night_lock_input_handler(client: Client, message: Message) -> None:
    state = message.input_state
    chat_id = state["chat_id"]
    field = state["field"]
    user_id = message.from_user.id
    ctx = get_context()
    value = message.text

    if not re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", str(value)):
        await message.reply(await at(user_id, "panel.input_invalid_time"))
        return

    scheduled = True
    async with ctx.db() as session:
        lock = await session.get(ChatNightLock, chat_id)
        if not lock:
            lock = ChatNightLock(chatId=chat_id)
        if field == "chatnightlockStart":
            lock.startTime = str(value)
        else:
            lock.endTime = str(value)
        session.add(lock)
        await session.commit()

        if lock.isEnabled:
            from src.plugins.scheduler.manager import SchedulerManager

            scheduled = await SchedulerManager.sync_group(ctx, chat_id)

    from src.plugins.admin_panel.handlers.keyboards import chatnightlock_menu_kb

    kb = await chatnightlock_menu_kb(ctx, chat_id)

    text = await at(user_id, "panel.nightlock_text")

    await finalize_input_capture(
        client,
        message,
        user_id,
        state["prompt_msg_id"],
        text,
        kb,
        success_text=await at(
            user_id, "panel.input_success" if scheduled else "panel.schedule_refresh_failed"
        ),
    )


@bot.on_message(filters.private & is_waiting_for_input("reminderText"), group=-50)
@safe_handler
async def reminder_text_input_handler(client: Client, message: Message) -> None:
    state = message.input_state
    user_id = message.from_user.id
    chat_id = state["chat_id"]

    r = get_cache()
    data = await extract_message_data(message)
    await r.set(f"temp_rem_data:{user_id}", json.dumps(data), ttl=300)

    # Update state for next step (reminderTime)
    await capture_next_input(
        user_id, chat_id, "reminderTime", state["prompt_msg_id"], state["page"]
    )

    prompt_text = await at(user_id, "panel.input_prompt_reminderTime")
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    await at(user_id, "common.btn_cancel"),
                    callback_data="panel:cancel_input:reminders",
                )
            ]
        ]
    )

    if state["prompt_msg_id"]:
        await client.edit_message_text(
            user_id, state["prompt_msg_id"], prompt_text, reply_markup=kb
        )
    else:
        await message.reply(prompt_text, reply_markup=kb)

    with __import__("contextlib").suppress(Exception):
        await message.delete()


@bot.on_message(filters.private & is_waiting_for_input("reminderTime"), group=-50)
@safe_handler
async def reminder_time_input_handler(client: Client, message: Message) -> None:
    state = message.input_state
    user_id = message.from_user.id
    chat_id = state["chat_id"]
    ctx = get_context()
    value = message.text

    if not re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", str(value)):
        await message.reply(await at(user_id, "panel.input_invalid_time"))
        return

    r = get_cache()
    data_str = await r.get(f"temp_rem_data:{user_id}")
    if not data_str:
        await message.reply(await at(user_id, "panel.input_inactive"))
        return

    data = json.loads(data_str)
    async with ctx.db() as session:
        rem = Reminder(
            chatId=chat_id,
            messageType=data["type"],
            text=data.get("text"),
            fileId=data.get("file_id"),
            additionalData=data.get("additional_data"),
            sendTime=str(value),
        )
        session.add(rem)
        await session.commit()

        from src.plugins.scheduler.manager import SchedulerManager

        scheduled = await SchedulerManager.sync_group(ctx, chat_id)
    await r.delete(f"temp_rem_data:{user_id}")

    from src.plugins.admin_panel.handlers.keyboards import reminders_menu_kb

    kb = await reminders_menu_kb(ctx, chat_id, user_id=user_id)

    await finalize_input_capture(
        client,
        message,
        user_id,
        state["prompt_msg_id"],
        await at(user_id, "panel.reminder_text"),
        kb,
        success_text=await at(
            user_id, "panel.input_success" if scheduled else "panel.schedule_refresh_failed"
        ),
    )
