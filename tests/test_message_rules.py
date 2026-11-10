import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pyrogram import StopPropagation
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.db.models import ChatSettings
from src.db.repositories import blacklist as blocks
from src.db.repositories import filters as replies
from src.db.repositories.chats import toggle_setting, update_chat_setting, update_settings
from src.plugins import blacklist, filters
from src.utils.local_cache import AsyncSnapshotCache
from src.utils.message_rules import (
    BlockRule,
    ReplyRule,
    detect_pattern_type,
    get_block_rules,
    get_block_settings,
    get_reply_rules,
    match_block,
)


def block(pattern, regex=False, wildcard=False):
    return BlockRule.compile(SimpleNamespace(pattern=pattern, isRegex=regex, isWildcard=wildcard))


def reply(keyword, **settings):
    return ReplyRule.compile(
        SimpleNamespace(
            keyword=keyword, settings=settings, text="Reply", responseType="text", fileId=None
        )
    )


@pytest.mark.parametrize(
    "keyword,text,expected",
    [
        ("cat", "category", False),
        ("cat", "a CAT!", True),
        ("c++", "use C++ today", True),
        ("c++", "xc++", False),
        ("🙂", "🙂", True),
        ("שלום", "שלום!", True),
        ("שלום", "בשלום", False),
        ("hello world", "hello world!", True),
        ("", "anything", False),
    ],
)
def test_filter_boundaries(keyword, text, expected):
    assert reply(keyword).matches(text) == expected


def test_filter_full_case_sensitive_and_multiline():
    assert reply("Hello", matchMode="full", caseSensitive=True).matches("Hello")
    assert not reply("Hello", matchMode="full", caseSensitive=True).matches("hello")
    assert not reply("hello", matchMode="full").matches("hello\n")
    assert reply("hello", matchMode="full").matches("HELLO")


@pytest.mark.parametrize(
    "rule,text,expected",
    [
        (block("a.b"), "axb", False),
        (block("a.b"), "A.B", True),
        (block("a.b", regex=True), "axb", True),
        (block("spam*", wildcard=True), "some SPAM\nmessage", True),
        (block("[", regex=True), "a[b", True),
        (block(""), "anything", False),
        (block(r"\S+", regex=True), "   ", False),
    ],
)
def test_block_pattern_modes(rule, text, expected):
    assert bool(match_block((rule,), text)) == expected


def test_pattern_detection_preserves_regex_escape_case():
    assert detect_pattern_type(r"^\S+$") == (True, False, r"^\S+$")
    assert detect_pattern_type(" SPAM* ") == (False, True, "spam*")


def test_pathological_regex_has_budget_and_does_not_hide_later_literal():
    bad = block(r"(a|aa)+$", regex=True)
    literal = block("blocked")
    started = time.monotonic()
    assert match_block((bad,) * 200 + (literal,), "blocked " + "a" * 1000 + "!") == literal
    assert time.monotonic() - started < 0.5


@pytest.fixture
async def rule_context(db_engine, mocker):
    cache = AsyncSnapshotCache()
    mocker.patch("src.utils.message_rules.get_cache", return_value=cache)
    ctx = SimpleNamespace(db=async_sessionmaker(db_engine, expire_on_commit=False))
    async with ctx.db() as session:
        session.add_all([ChatSettings(id=-123), ChatSettings(id=-456)])
        await session.commit()
    return ctx


async def test_filter_cache_invalidates_all_edit_paths_and_isolates_chats(rule_context):
    ctx = rule_context
    assert await get_reply_rules(ctx, -123) == ()
    one = await replies.add_filter(ctx, -123, "one", "1")
    two = await replies.add_filter(ctx, -456, "two", "2")
    assert [r.keyword for r in await get_reply_rules(ctx, -123)] == ["one"]
    assert [r.keyword for r in await get_reply_rules(ctx, -456)] == ["two"]
    assert await replies.update_filter_by_id(ctx, one.id, "new", "3")
    assert [r.keyword for r in await get_reply_rules(ctx, -123)] == ["new"]
    assert await replies.remove_filter_by_id(ctx, one.id)
    assert await get_reply_rules(ctx, -123) == ()
    await replies.add_filter(ctx, -123, "again", "4")
    await get_reply_rules(ctx, -123)
    assert await replies.remove_filter(ctx, -123, "again")
    assert await get_reply_rules(ctx, -123) == ()
    await replies.add_filter(ctx, -123, "last", "5")
    await get_reply_rules(ctx, -123)
    assert await replies.remove_all_filters(ctx, -123) == 1
    assert await get_reply_rules(ctx, -123) == ()
    assert (await get_reply_rules(ctx, -456))[0].keyword == two.keyword


async def test_blacklist_batch_duplicates_empty_invalid_and_cache_invalidation(rule_context):
    ctx = rule_context
    assert await get_block_rules(ctx, -123) == ()
    assert await blocks.batch_add_blacklist(
        ctx, -123, ["SPAM", "spam", " spam ", "", "[", r"^\S+$"]
    ) == (2, 4)
    rules = await get_block_rules(ctx, -123)
    assert [r.pattern for r in rules] == ["spam", r"^\S+$"]
    assert await blocks.remove_blacklist(ctx, -123, "spam")
    assert [r.pattern for r in await get_block_rules(ctx, -123)] == [r"^\S+$"]
    await blocks.add_blacklist(ctx, -123, "literal.a")
    assert not match_block((await get_block_rules(ctx, -123))[-1:], "literalXa")
    for pattern, is_regex in [("", False), ("[", True)]:
        with pytest.raises(ValueError):
            await blocks.add_blacklist(ctx, -123, pattern, is_regex=is_regex)


async def test_blacklist_batch_respects_limit(rule_context):
    ctx = rule_context
    assert await blocks.batch_add_blacklist(ctx, -123, [f"word{i}" for i in range(199)]) == (199, 0)
    assert await blocks.batch_add_blacklist(ctx, -123, ["new", "new", "overflow"]) == (1, 2)
    assert await blocks.get_blacklist_count(ctx, -123) == 200


async def test_settings_cache_refreshes_after_each_mutation(rule_context):
    ctx = rule_context
    assert not (await get_block_settings(ctx, -123)).scan_buttons
    await toggle_setting(ctx, -123, "blacklistScanButtons")
    assert (await get_block_settings(ctx, -123)).scan_buttons
    await update_chat_setting(ctx, -123, "blacklistAction", "ban")
    assert (await get_block_settings(ctx, -123)).action == "ban"
    await update_settings(ctx, -123, blacklistAction="warn", blacklistScanButtons=False)
    settings = await get_block_settings(ctx, -123)
    assert settings.action == "warn" and not settings.scan_buttons


async def test_warm_rules_do_not_query_database(rule_context, db_engine):
    ctx = rule_context
    await replies.add_filter(ctx, -123, "hello", "Hi")
    await blocks.add_blacklist(ctx, -123, "spam")
    await get_reply_rules(ctx, -123)
    await get_block_rules(ctx, -123)
    await get_block_settings(ctx, -123)
    queries = []

    def count(*args):
        queries.append(args[2])

    event.listen(db_engine.sync_engine, "before_cursor_execute", count)
    try:
        for _ in range(100):
            assert (await get_reply_rules(ctx, -123))[0].matches("hello")
            assert match_block(await get_block_rules(ctx, -123), "no match") is None
            await get_block_settings(ctx, -123)
        assert queries == []
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", count)


async def test_benign_blacklist_messages_skip_sender_permission_lookup(rule_context, mocker):
    await blocks.add_blacklist(rule_context, -123, "spam")
    mocker.patch.object(blacklist, "get_context", return_value=rule_context)
    sender = mocker.patch.object(blacklist, "resolve_sender", new_callable=AsyncMock)
    msg = SimpleNamespace(
        text="ordinary message", caption=None, reply_markup=None, chat=SimpleNamespace(id=-123)
    )
    await blacklist.blacklist_interceptor(object(), msg)
    sender.assert_not_awaited()


async def test_blacklist_scans_caption_buttons_and_respects_admin_exemption(rule_context, mocker):
    await blocks.add_blacklist(rule_context, -123, "spam")
    await update_settings(rule_context, -123, blacklistScanButtons=True)
    mocker.patch.object(blacklist, "get_context", return_value=rule_context)
    sender = mocker.patch.object(
        blacklist, "resolve_sender", new_callable=AsyncMock, return_value=(123, "User", False)
    )
    action = mocker.patch.object(
        blacklist, "execute_moderation_action", new_callable=AsyncMock, return_value=True
    )
    mocker.patch.object(blacklist, "at", new_callable=AsyncMock, return_value="Reason")
    msg = SimpleNamespace(
        text=None,
        caption="caption",
        chat=SimpleNamespace(id=-123),
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("SPAM", url="https://example.com")]]
        ),
    )
    with pytest.raises(StopPropagation):
        await blacklist.blacklist_interceptor(object(), msg)
    action.assert_awaited_once()
    sender.return_value = (123, "Admin", True)
    action.reset_mock()
    await blacklist.blacklist_interceptor(object(), msg)
    action.assert_not_awaited()


@pytest.mark.parametrize("admin", [True, False])
async def test_admin_only_filters_support_sender_chat_and_check_only_matches(
    rule_context, mocker, admin
):
    await replies.add_filter(rule_context, -123, "hello", "reply", settings={"isAdminOnly": True})
    mocker.patch.object(filters, "get_context", return_value=rule_context)
    check = mocker.patch.object(filters, "is_admin", new_callable=AsyncMock, return_value=admin)
    mocker.patch.object(filters.TelegramFormatter, "parse_message", return_value={})
    send = mocker.patch.object(filters.TelegramFormatter, "send_parsed", new_callable=AsyncMock)
    client = SimpleNamespace(me=SimpleNamespace(username="bot"))
    msg = SimpleNamespace(
        id=1,
        text="unrelated",
        from_user=None,
        sender_chat=SimpleNamespace(id=-123),
        chat=SimpleNamespace(id=-123, title="Group"),
    )
    await filters.filters_interceptor(client, msg)
    check.assert_not_awaited()
    msg.text = "HELLO"
    if admin:
        with pytest.raises(StopPropagation):
            await filters.filters_interceptor(client, msg)
        send.assert_awaited_once()
    else:
        await filters.filters_interceptor(client, msg)
        send.assert_not_awaited()
    check.assert_awaited_once_with(client, -123, -123)


@pytest.mark.parametrize("command", ['/stop "hello world"', "/stop hello world"])
async def test_stop_filter_handles_multiword_keywords(rule_context, mocker, command):
    import inspect

    await replies.add_filter(rule_context, -123, "hello world", "reply")
    await get_reply_rules(rule_context, -123)
    mocker.patch.object(filters, "get_context", return_value=rule_context)
    mocker.patch.object(filters, "has_permission", new_callable=AsyncMock, return_value=True)
    mocker.patch.object(filters, "at", new_callable=AsyncMock, return_value="Removed")
    message = SimpleNamespace(
        command=command.split(), text=command, chat=SimpleNamespace(id=-123), reply=AsyncMock()
    )
    await inspect.unwrap(filters.stop_filter_handler)(object(), message)
    assert await get_reply_rules(rule_context, -123) == ()
    message.reply.assert_awaited_once()


@pytest.mark.parametrize("foreign_chat", [False, True])
async def test_blacklist_panel_delete_invalidates_only_authorized_chat(
    rule_context, mocker, foreign_chat
):
    from src.plugins.admin_panel.decorators import AdminPanelContext
    from src.plugins.admin_panel.handlers.callbacks import moderation

    target_chat = -456 if foreign_chat else -123
    entry = await blocks.add_blacklist(rule_context, target_chat, "blocked")
    await get_block_rules(rule_context, target_chat)
    mocker.patch.object(moderation, "blacklist_kb", new_callable=AsyncMock)
    mocker.patch.object(moderation, "at", new_callable=AsyncMock, return_value="Result")
    callback = SimpleNamespace(
        matches=[SimpleNamespace(group=lambda n: str(entry.id) if n == 1 else "0")],
        from_user=SimpleNamespace(id=123),
        answer=AsyncMock(),
        message=SimpleNamespace(edit_reply_markup=AsyncMock()),
    )
    ap_ctx = AdminPanelContext(chat_id=-123, at_id=123, ctx=rule_context, is_pm=True)
    await moderation.on_blacklist_remove(object(), callback, ap_ctx)
    assert bool(await get_block_rules(rule_context, target_chat)) == foreign_chat


async def test_cold_burst_shares_only_three_queries(rule_context, db_engine):
    import asyncio

    queries = []

    def count(*args):
        queries.append(args[2])

    async def read_rules():
        await get_block_rules(rule_context, -123)
        await get_block_settings(rule_context, -123)
        await get_reply_rules(rule_context, -123)

    event.listen(db_engine.sync_engine, "before_cursor_execute", count)
    try:
        await asyncio.gather(*(read_rules() for _ in range(50)))
        assert len(queries) == 3
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", count)
