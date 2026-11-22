import contextlib
import re
import time
from datetime import UTC, datetime

from pyrogram import Client, filters
from pyrogram.types import (
    ChatPrivileges,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
)

from src.core.bot import bot
from src.core.context import get_context
from src.core.plugin import Plugin, register
from src.utils.decorators import admin_permission_required, resolve_target, safe_handler
from src.utils.i18n import at
from src.utils.input import finalize_input_capture, is_waiting_for_input
from src.utils.permissions import Permission, has_permission


class AdminPlugin(Plugin):
    """Plugin for core administrative commands and information."""

    name = "admin"
    priority = 100

    async def setup(self, client: Client, ctx) -> None:
        pass


@bot.on_message(filters.command("start") & filters.private)
@safe_handler
async def start_handler(client: Client, message: Message) -> None:
    user_id = message.from_user.id
    ctx = get_context()
    payload = message.command[1] if len(message.command) > 1 else None

    from src.db.models import UserSettings
    from src.plugins.language import language_picker_kb, set_user_lang
    from src.utils.i18n import at, list_locales

    async with ctx.db() as session:
        user_settings = await session.get(UserSettings, user_id)

    if not user_settings:
        # First-time user: Detect language
        tg_lang = (message.from_user.language_code or "en").split("-")[0].lower()
        supported_langs = list_locales()
        default_lang = tg_lang if tg_lang in supported_langs else "en"

        await set_user_lang(ctx, user_id, default_lang)

        # Show language picker for onboarding (with optional payload preservation)
        mode = f"onboarding:{payload}" if payload else "onboarding"
        kb = await language_picker_kb(ctx, user_id, scope="user", mode=mode)
        return await message.reply(
            await at(user_id, "language.onboarding_picker_header"), reply_markup=kb
        )

    # Process deep-links for existing users
    if payload and payload.startswith("settings_"):
        cid = payload.replace("settings_", "")
        if cid.startswith("-") and cid.lstrip("-").isdigit():
            from src.plugins.admin_panel.handlers import open_settings_panel

            with contextlib.suppress(Exception):
                return await open_settings_panel(client, message, int(cid))

    await send_start_message(client, message)


async def send_start_message(client: Client, message: Message, edit: bool = False) -> None:
    me, cid = client.me, message.chat.id
    txt = await at(cid, "admin.start_text", bot_name=me.first_name)
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(await at(cid, "help.start_btn"), callback_data="help:main")],
            [
                InlineKeyboardButton(
                    await at(cid, "panel.btn_my_groups"), callback_data="panel:my_chats"
                ),
                InlineKeyboardButton(
                    await at(cid, "help.about_btn"), callback_data="help:cat:about:start"
                ),
            ],
            [InlineKeyboardButton(await at(cid, "donate.btn"), callback_data="donate:main")],
        ]
    )
    with contextlib.suppress(Exception):
        await (message.edit_text if edit else message.reply)(txt, reply_markup=kb)


@bot.on_message(filters.command("ping") & filters.group)
@safe_handler
async def ping_handler(client: Client, message: Message) -> None:
    latency = (time.time() - message.date.timestamp()) * 1000
    await message.reply(await at(message.chat.id, "ping.response", ms=f"{latency:.2f}"))


@bot.on_message(filters.command("id"))
@safe_handler
async def id_handler(client: Client, message: Message) -> None:
    replied = (
        await at(message.chat.id, "admin.replied_id", id=message.reply_to_message.from_user.id)
        if message.reply_to_message and message.reply_to_message.from_user
        else ""
    )
    await message.reply(
        await at(
            message.chat.id,
            "admin.id_info",
            user_id=message.from_user.id,
            chat_id=message.chat.id,
            replied=replied,
        )
    )


@bot.on_message(filters.command(["pin", "permapin"]) & filters.group)
@safe_handler
@admin_permission_required(Permission.CAN_PIN)
async def pin_handler(client: Client, message: Message) -> None:
    if not await has_permission(client, message.chat.id, Permission.CAN_PIN):
        return await message.reply(await at(message.chat.id, "error.bot_no_permission"))
    if message.reply_to_message:
        await client.pin_chat_message(
            message.chat.id, message.reply_to_message.id, disable_notification=True
        )


@bot.on_message(filters.command("unpin") & filters.group)
@safe_handler
@admin_permission_required(Permission.CAN_PIN)
async def unpin_handler(client: Client, message: Message) -> None:
    if not await has_permission(client, message.chat.id, Permission.CAN_PIN):
        return await message.reply(await at(message.chat.id, "error.bot_no_permission"))
    await client.unpin_chat_message(
        message.chat.id, message.reply_to_message.id if message.reply_to_message else None
    )


@bot.on_message(filters.command("unpinall") & filters.group)
@safe_handler
@admin_permission_required(Permission.CAN_PIN)
async def unpinall_handler(client: Client, message: Message) -> None:
    if not await has_permission(client, message.chat.id, Permission.CAN_PIN):
        return await message.reply(await at(message.chat.id, "error.bot_no_permission"))
    if await client.unpin_all_chat_messages(message.chat.id):
        await message.reply(await at(message.chat.id, "admin.unpinned_all"))


@bot.on_message(filters.command(["promote", "demote"]) & filters.group)
@safe_handler
@admin_permission_required(Permission.CAN_PROMOTE)
@resolve_target
async def promotion_handler(client: Client, message: Message, target_user: User) -> None:
    is_p = "promote" in message.command[0]

    title = ""
    if is_p:
        cmd = message.command
        title = " ".join(
            cmd[2:] if len(cmd) > 2 and cmd[1].startswith("@") else cmd[1:] if len(cmd) > 1 else []
        )

    await client.promote_chat_member(
        message.chat.id,
        target_user.id,
        privileges=ChatPrivileges(
            can_manage_chat=is_p,
            can_delete_messages=is_p,
            can_manage_video_chats=is_p,
            can_restrict_members=is_p,
            can_promote_members=False,
            can_change_info=False,
            can_invite_users=is_p,
            can_pin_messages=is_p,
        ),
    )
    if is_p and title:
        await client.set_administrator_custom_title(message.chat.id, target_user.id, title)
    await message.reply(
        await at(
            message.chat.id,
            f"admin.{'promoted' if is_p else 'demoted'}",
            mention=target_user.mention,
        )
    )


@bot.on_message(filters.command("invitelink") & filters.group)
@safe_handler
@admin_permission_required(Permission.CAN_INVITE)
async def invitelink_handler(client: Client, message: Message) -> None:
    if not await has_permission(client, message.chat.id, Permission.CAN_INVITE):
        return await message.reply(await at(message.chat.id, "error.bot_no_permission"))
    await message.reply(
        await at(
            message.chat.id,
            "admin.invite_link_header",
            link=await client.export_chat_invite_link(message.chat.id),
        )
    )


@bot.on_message(filters.command(["info", "userinfo", "chatinfo"]) & filters.group)
@safe_handler
async def info_handler(client: Client, message: Message) -> None:
    cid = message.chat.id
    if "chat" in message.command[0]:
        return await message.reply(
            await at(
                cid,
                "admin.chat_info",
                title=message.chat.title,
                id=cid,
                type=message.chat.type.name,
                username=message.chat.username or "None",
                count=await client.get_chat_members_count(cid),
            )
        )

    # User info
    @resolve_target
    async def _info(_, __, u: User):
        not_set = await at(cid, "common.not_set")

        def val(v):
            return v if v else not_set

        await message.reply(
            await at(
                cid,
                "admin.user_info",
                id=u.id,
                first_name=u.first_name,
                last_name=val(u.last_name),
                username=f"@{u.username}" if u.username else not_set,
                dc_id=val(u.dc_id),
                is_bot=await at(cid, f"common.{'yes' if u.is_bot else 'no'}"),
            )
        )

    await _info(client, message)


# --- Admin Panel Input Handlers ---


@bot.on_message(filters.private & is_waiting_for_input("cleanerInactive"), group=-50)
@safe_handler
async def cleaner_inactive_input_handler(client: Client, message: Message) -> None:
    state = message.input_state
    chat_id = state["chat_id"]
    user_id = message.from_user.id
    ctx = get_context()
    value = message.text

    if not str(value).isdigit() or int(value) < 0:
        await message.reply(await at(user_id, "panel.input_invalid_number"))
        return

    from src.db.models import ChatCleaner

    async with ctx.db() as session:
        cleaner = await session.get(ChatCleaner, chat_id)
        if not cleaner:
            cleaner = ChatCleaner(chatId=chat_id)
        cleaner.cleanInactiveDays = int(value)
        session.add(cleaner)
        await session.commit()

    from src.plugins.admin_panel.handlers.keyboards import cleaner_menu_kb

    kb = await cleaner_menu_kb(ctx, chat_id)

    s_del = await at(
        user_id, "panel.status_enabled" if cleaner.cleanDeleted else "panel.status_disabled"
    )
    s_fake = await at(
        user_id, "panel.status_enabled" if cleaner.cleanFake else "panel.status_disabled"
    )
    text = await at(
        user_id,
        "panel.cleaner_text",
        s_del=s_del,
        s_fake=s_fake,
        days=cleaner.cleanInactiveDays,
        time=cleaner.cleanerRunTime,
    )

    await finalize_input_capture(
        client,
        message,
        user_id,
        state["prompt_msg_id"],
        text,
        kb,
        success_text=await at(user_id, "panel.input_success"),
    )


@bot.on_message(filters.private & is_waiting_for_input("cleanerRunTime"), group=-50)
@safe_handler
async def cleaner_time_input_handler(client: Client, message: Message) -> None:
    state = message.input_state
    chat_id = state["chat_id"]
    user_id = message.from_user.id
    ctx = get_context()
    value = str(message.text).strip()

    if not re.match(r"^([01]\d|2[0-3]):([0-5]\d)$", value):
        await message.reply(await at(user_id, "panel.input_invalid_time"))
        return

    from src.db.models import ChatCleaner

    async with ctx.db() as session:
        cleaner = await session.get(ChatCleaner, chat_id)
        if not cleaner:
            cleaner = ChatCleaner(chatId=chat_id)

        # Enforce once-per-day change limit
        now = datetime.now(UTC).replace(tzinfo=None)
        if cleaner.cleanerTimeChangedAt and cleaner.cleanerTimeChangedAt.date() == now.date():
            await message.reply(await at(user_id, "panel.error_cleaner_time_cooldown"))
            return

        cleaner.cleanerRunTime = value
        cleaner.cleanerTimeChangedAt = now
        session.add(cleaner)
        await session.commit()

        from src.plugins.scheduler.manager import SchedulerManager

        scheduled = await SchedulerManager.sync_group(ctx, chat_id)

    from src.plugins.admin_panel.handlers.keyboards import cleaner_menu_kb

    kb = await cleaner_menu_kb(ctx, chat_id)
    s_del = await at(
        user_id, "panel.status_enabled" if cleaner.cleanDeleted else "panel.status_disabled"
    )
    s_fake = await at(
        user_id, "panel.status_enabled" if cleaner.cleanFake else "panel.status_disabled"
    )
    text = await at(
        user_id,
        "panel.cleaner_text",
        s_del=s_del,
        s_fake=s_fake,
        days=cleaner.cleanInactiveDays,
        time=cleaner.cleanerRunTime,
    )

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


register(AdminPlugin())
