import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pyrogram.enums import ChatType

from src.plugins.admin_panel.handlers import commands
from src.plugins.admin_panel.handlers.callbacks import inputs
from src.utils import input as panel_input
from src.utils.local_cache import AsyncSnapshotCache


@pytest.mark.asyncio
@pytest.mark.parametrize("chat_id", [-42, -10012345])
async def test_admin_panel_remembers_private_user(mocker, chat_id):
    ctx = object()
    mocker.patch.object(commands, "get_context", return_value=ctx)
    mocker.patch.object(
        commands, "resolve_chat_type", new_callable=AsyncMock, return_value=ChatType.GROUP
    )
    check = mocker.patch.object(commands, "is_admin", new_callable=AsyncMock, return_value=True)
    save = mocker.patch.object(commands, "set_active_chat", new_callable=AsyncMock)
    dashboard = mocker.patch.object(commands, "send_admin_dashboard", new_callable=AsyncMock)
    # Bot-authored messages appear when opening settings after language selection.
    message = SimpleNamespace(
        chat=SimpleNamespace(id=123, type=ChatType.PRIVATE),
        from_user=SimpleNamespace(id=999),
    )
    client = object()
    await commands.open_settings_panel(client, message, chat_id, chat_type="channel")
    check.assert_awaited_once_with(client, chat_id, 123)
    save.assert_awaited_once_with(ctx, 123, chat_id, chat_type="group")
    dashboard.assert_awaited_once_with(client, 123, chat_id, chat_type=ChatType.GROUP, is_pm=True)


@pytest.mark.asyncio
async def test_rejected_group_does_not_replace_connection(mocker):
    mocker.patch.object(commands, "get_context")
    mocker.patch.object(commands, "is_admin", new_callable=AsyncMock, return_value=False)
    mocker.patch.object(commands, "at", new_callable=AsyncMock, return_value="Denied")
    mocker.patch.object(commands, "my_groups_kb", new_callable=AsyncMock)
    save = mocker.patch.object(commands, "set_active_chat", new_callable=AsyncMock)
    dashboard = mocker.patch.object(commands, "send_admin_dashboard", new_callable=AsyncMock)
    message = SimpleNamespace(
        chat=SimpleNamespace(id=123, type=ChatType.PRIVATE), reply=AsyncMock()
    )
    await commands.open_settings_panel(object(), message, -10012345)
    save.assert_not_awaited()
    dashboard.assert_not_awaited()


@pytest.mark.asyncio
async def test_active_group_survives_new_database_sessions(db_engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from src.plugins.connections import get_active_chat, set_active_chat

    first_ctx = SimpleNamespace(db=async_sessionmaker(db_engine, expire_on_commit=False))
    await set_active_chat(first_ctx, 123, -42, chat_type="group")
    new_ctx = SimpleNamespace(db=async_sessionmaker(db_engine, expire_on_commit=False))
    assert await get_active_chat(new_ctx, 123) == (-42, "group")
    assert await get_active_chat(new_ctx, 456) == (None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("newer_prompt", [False, True])
@pytest.mark.parametrize(
    ("input_route", "chat_type", "return_route"),
    [
        ("blacklistInput:2", ChatType.SUPERGROUP, "blacklist:2"),
        ("watermarkOpacity:-10012345", ChatType.CHANNEL, "channel_watermark:-10012345"),
    ],
)
async def test_cancel_panel_input_preserves_return_route(
    mocker, newer_prompt, input_route, chat_type, return_route
):
    cache = AsyncSnapshotCache()
    mocker.patch.object(panel_input, "get_cache", return_value=cache)
    mocker.patch.object(inputs, "at", side_effect=lambda _, key: key)
    mocker.patch.object(inputs, "resolve_chat_type", return_value=chat_type)
    edit = mocker.patch.object(inputs, "safe_edit")
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        message=SimpleNamespace(id=10, chat=SimpleNamespace(type=ChatType.PRIVATE)),
        matches=[re.fullmatch(r"panel:input:(\w+):(-?\d+)", f"panel:input:{input_route}")],
        answer=AsyncMock(),
    )
    chat_id = -10012345 if chat_type == ChatType.CHANNEL else -42
    context = inputs.AdminPanelContext(chat_id, 123, object(), True)
    await inputs.on_panel_input(object(), callback, context)
    button = edit.call_args.kwargs["reply_markup"].inline_keyboard[0][0]
    assert button.callback_data == f"panel:cancel_input:{return_route}"
    assert await cache.exists("panel_input:123")

    if newer_prompt:
        await panel_input.capture_next_input(123, -42, "warnLimit", prompt_msg_id=11)
    callback.matches = [re.fullmatch(r"panel:cancel_input:(.+)", button.callback_data)]
    await inputs.on_cancel_input(object(), callback)

    assert await cache.exists("panel_input:123") is newer_prompt
    message_key = "panel.input_inactive" if newer_prompt else "panel.input_cancelled"
    assert edit.call_args.args == (callback, message_key)
    back = edit.call_args.kwargs["reply_markup"].inline_keyboard[0][0]
    assert back.callback_data == f"panel:{return_route}"


async def test_private_settings_callback_keeps_original_chat_after_switch(mocker):
    from pyrogram.types import CallbackQuery

    from src.plugins.admin_panel import decorators
    from src.utils import panel_session

    cache = AsyncSnapshotCache()
    mocker.patch.object(panel_session, "get_cache", return_value=cache)
    await panel_session.bind_panel(123, 10, -42, picker_page=2)
    await panel_session.bind_panel(123, 11, -77)
    active_chat = mocker.patch.object(decorators, "get_active_chat", return_value=(-77, "group"))
    mocker.patch.object(decorators, "get_context", return_value=object())
    mocker.patch.object(decorators, "get_chat_info", return_value=(ChatType.GROUP, "Group"))
    allowed = mocker.patch.object(decorators, "is_admin", return_value=True)
    target = AsyncMock()

    @decorators.admin_panel_context
    async def handler(client, callback, ctx):
        await target(ctx.chat_id, ctx.picker_page)

    callback = CallbackQuery(
        id="callback",
        from_user=SimpleNamespace(id=123),
        chat_instance="private",
        message=SimpleNamespace(id=10, chat=SimpleNamespace(type=ChatType.PRIVATE)),
    )
    client = object()
    await handler(client, callback)
    target.assert_awaited_once_with(-42, 2)
    allowed.assert_awaited_once_with(client, -42, 123)
    active_chat.assert_not_awaited()


async def test_input_submission_checks_current_admin_role(mocker):
    from pyrogram.enums import ChatMemberStatus

    cache = AsyncSnapshotCache()
    mocker.patch.object(panel_input, "get_cache", return_value=cache)
    mocker.patch.object(panel_input, "at", return_value="Permission denied")
    await panel_input.capture_next_input(123, -42, "warnLimit", prompt_msg_id=10)
    member = SimpleNamespace(status=ChatMemberStatus.MEMBER)
    client = SimpleNamespace(get_chat_member=AsyncMock(return_value=member))
    message = SimpleNamespace(from_user=SimpleNamespace(id=123), reply=AsyncMock())
    capture_filter = panel_input.is_waiting_for_input("warnLimit")
    assert not await capture_filter(client, message)
    client.get_chat_member.assert_awaited_once_with(-42, 123)
    message.reply.assert_awaited_once_with("Permission denied")
    assert not await cache.exists("panel_input:123")


async def test_post_write_rate_limit_does_not_replay_callback(mocker):
    from pyrogram.errors import FloodWait

    from src.plugins.admin_panel.handlers.callbacks import common

    mocker.patch.object(common, "at", return_value="Refresh the panel")
    write = AsyncMock()

    @common.safe_callback
    async def handler(client, callback):
        await write()
        raise FloodWait(10)

    callback = SimpleNamespace(from_user=SimpleNamespace(id=123), answer=AsyncMock())
    await handler(object(), callback)
    write.assert_awaited_once()
    callback.answer.assert_awaited_once_with("Refresh the panel", show_alert=True)


@pytest.mark.parametrize("choice", ["yes", "no"])
async def test_bulk_purge_confirmation_is_consumed_once(mocker, choice):
    from pyrogram.enums import ChatMemberStatus
    from pyrogram.errors import BadRequest

    from src.plugins import purge

    token = "a" * 32
    cache = AsyncSnapshotCache()
    mocker.patch.object(purge, "get_cache", return_value=cache)
    mocker.patch.object(purge, "at", side_effect=lambda _, key, **fmt: key)
    mocker.patch.object(purge, "has_permission", return_value=True)
    await cache.set(f"purge_confirm:123:{token}", (-42, 105))
    message = SimpleNamespace(chat=SimpleNamespace(type=ChatType.PRIVATE), edit_text=AsyncMock())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        matches=[
            re.fullmatch(
                r"panel:purge_confirm:(yes|no):([0-9a-f]{32})",
                f"panel:purge_confirm:{choice}:{token}",
            )
        ],
        message=message,
        answer=AsyncMock(),
    )
    client = SimpleNamespace(
        get_chat_member=AsyncMock(return_value=SimpleNamespace(status=ChatMemberStatus.OWNER)),
        send_message=AsyncMock(return_value=SimpleNamespace(id=300, delete=AsyncMock())),
        delete_messages=AsyncMock(side_effect=[None, BadRequest()]),
    )

    await purge.confirm_panel_purge(client, callback)
    await purge.confirm_panel_purge(client, callback)
    if choice == "yes":
        assert client.delete_messages.await_count == 2
        assert message.edit_text.call_args.args == ("panel.purge_result_partial",)
    else:
        client.delete_messages.assert_not_awaited()
        assert message.edit_text.call_args.args == ("panel.input_cancelled",)
    callback.answer.assert_awaited_with("panel.input_inactive", show_alert=True)


async def test_missing_panel_message_reports_reopen_without_repeating_write(mocker):
    from pyrogram.errors import MessageIdInvalid

    from src.plugins.admin_panel.handlers.callbacks import common

    mocker.patch.object(common, "at", return_value="Reopen settings")
    write = AsyncMock()
    callback = SimpleNamespace(
        message=SimpleNamespace(edit_text=AsyncMock(side_effect=MessageIdInvalid())),
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
    )

    @common.safe_callback
    async def handler(client, update):
        await write()
        await common.safe_edit(update, "Updated")

    await handler(object(), callback)
    write.assert_awaited_once()
    callback.message.edit_text.assert_awaited_once()
    callback.answer.assert_awaited_once_with("Reopen settings", show_alert=True)


async def test_expired_prompt_does_not_consume_later_message(mocker):
    cache = AsyncSnapshotCache()
    mocker.patch.object(panel_input, "get_cache", return_value=cache)
    await panel_input.capture_next_input(123, -42, "warnLimit", prompt_msg_id=10)
    await cache.expire("panel_input:123", 0)
    client = SimpleNamespace(get_chat_member=AsyncMock())
    message = SimpleNamespace(from_user=SimpleNamespace(id=123))
    assert not await panel_input.is_waiting_for_input("warnLimit")(client, message)
    client.get_chat_member.assert_not_awaited()


async def test_flood_help_returns_to_origin(mocker):
    from src.plugins import help as help_plugin

    mocker.patch.object(help_plugin, "at", side_effect=lambda _, key: key)
    message = SimpleNamespace(chat=SimpleNamespace(id=123), edit_text=AsyncMock())
    callback = SimpleNamespace(data="help:setting:flood", message=message, answer=AsyncMock())
    await help_plugin.help_callback_handler(object(), callback)
    callback.answer.assert_awaited_once()
    assert message.edit_text.call_args.args == ("help.antiflood_text",)
    back = message.edit_text.call_args.kwargs["reply_markup"].inline_keyboard[0][0]
    assert back.callback_data == "panel:flood"


async def test_admin_roster_preserves_mixed_direction_names_and_reports_refresh_failure(mocker):
    from src.plugins.admin_panel.handlers.callbacks import admins

    name = "אלכס Alexander Example Long Name"
    cache = AsyncSnapshotCache()
    await cache.set("admins_last_sync:-42", "2026-11-22 12:00 UTC")
    mocker.patch.object(admins, "get_cache", return_value=cache)
    mocker.patch.object(
        admins, "at", side_effect=lambda _, key, **values: f"{key} {values.get('date', '')}".strip()
    )
    mocker.patch.object(
        admins,
        "get_admins_for_chat",
        return_value=[SimpleNamespace(username=None, firstName=name, userId=123, status="owner")],
    )
    mocker.patch.object(admins, "admins_management_kb", return_value=None)
    edit = mocker.patch.object(admins, "safe_edit")
    refresh = mocker.patch.object(admins, "force_refresh", return_value=set())
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        matches=[
            re.fullmatch(r"panel:admins_refresh:(-?\d+)(?::(\d+))?", "panel:admins_refresh:-42:0")
        ],
        answer=AsyncMock(),
    )
    context = inputs.AdminPanelContext(-42, 123, object(), True)
    await admins.render_admin_roster(callback, context)
    text = edit.call_args.args[1]
    assert f"\u2068{name}\u2069" in text and "2026-11-22 12:00 UTC" in text

    await admins.on_admins_refresh(object(), callback, context)
    refresh.assert_awaited_once()
    callback.answer.assert_awaited_once_with("panel.admin_refresh_failed", show_alert=True)
    assert not await cache.exists("refresh_admins_cooldown:-42")


async def test_warning_action_picker_sets_explicit_value_and_reopens(db_engine, mocker):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from src.db.repositories.chats import get_chat_settings
    from src.plugins.admin_panel.handlers.callbacks import action_picker, moderation

    ctx = SimpleNamespace(db=async_sessionmaker(db_engine, expire_on_commit=False))
    mocker.patch.object(action_picker, "check_user_permission", return_value=True)
    mocker.patch.object(
        moderation,
        "at",
        side_effect=lambda _, key, **values: f"{key} {values.get('action', '')}".strip(),
    )
    mocker.patch.object(moderation, "warns_kb", return_value=None)
    edit = mocker.patch.object(moderation, "safe_edit")
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        matches=[
            re.fullmatch(r"panel:action:(\w+):(\d+)(?::(\w+))?", "panel:action:warnAction:0:ban")
        ],
        answer=AsyncMock(),
    )
    panel = inputs.AdminPanelContext(-42, 123, ctx, True, ChatType.GROUP)
    await action_picker.on_action_picker(object(), callback, panel)
    assert (await get_chat_settings(ctx, -42)).warnAction == "ban"
    assert edit.call_args.args[1] == "panel.warns_text action.ban"
