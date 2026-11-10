from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.blacklist_defaults import (
    BAD_WORDS_BLOCKS,
    WORD_PACKAGES,
    describe_block_pattern,
    normalize_preset_text,
)
from src.db.models import ChatSettings
from src.db.repositories.blacklist import batch_add_blacklist, get_blacklist_count, remove_blacklist
from src.utils.local_cache import AsyncSnapshotCache
from src.utils.message_rules import BlockRule, get_block_rules, match_block


def rules(level):
    return tuple(
        BlockRule.compile(SimpleNamespace(pattern=p, isRegex=True, isWildcard=False))
        for p in BAD_WORDS_BLOCKS[level]
    )


@pytest.mark.parametrize("level", ["low", "medium", "hard"])
def test_packages_are_unique_cumulative_and_fit_the_chat_limit(level):
    patterns = BAD_WORDS_BLOCKS[level]
    assert len(patterns) == len(set(patterns))
    assert len(patterns) <= 200
    assert all(rule.is_regex and rule.normalize for rule in rules(level))
    assert all(
        describe_block_pattern(pattern)
        in sum((list(words) for words in WORD_PACKAGES.values()), [])
        for pattern in patterns
    )
    if level != "low":
        previous = "low" if level == "medium" else "medium"
        assert set(BAD_WORDS_BLOCKS[previous]) < set(patterns)


@pytest.mark.parametrize(
    "level,term", [(level, term) for level, terms in WORD_PACKAGES.items() for term in terms]
)
def test_every_package_term_blocks_as_a_word(level, term):
    assert match_block(rules(level), f"({term.upper()})")


@pytest.mark.parametrize(
    "level,text",
    [
        ("low", "1d10t"),
        ("low", "i.d.i.o.t"),
        ("medium", "f.u.c.k"),
        ("medium", "f u c k"),
        ("medium", "fuuuck"),
        ("medium", "sh1t"),
        ("medium", "sh!t"),
        ("medium", "f\u200bu\u200cc\u200dk"),
        ("medium", "ｆｕｃｋ"),
        ("medium", "fúçk"),
        ("medium", "SHIT"),
        ("low", "מְטֻמְטָם"),
        ("low", "וְהַמְטֻמְטָם"),
        ("medium", "כוס\u200bאמק"),
        ("hard", "FREE---PORN"),
        ("hard", "double__your__money"),
        ("hard", "double\u200byour\u200bmoney"),
        ("medium", "sonofabitch"),
        ("hard", "רֶוַח מֻבְטָח"),
    ],
)
def test_presets_block_common_disguises(level, text):
    assert match_block(rules(level), text)


@pytest.mark.parametrize(
    "text",
    [
        "hello everyone",
        "classic music",
        "class assignment",
        "shell scripting",
        "Scunthorpe is a town",
        "Dickens wrote novels",
        "a cocktail recipe",
        "discuss cryptocurrency",
        "learning about crypto",
        "an article about casinos",
        "this investment has risks",
        "כוס מים בבקשה",
        "אני אחראי על הקבוצה",
        "שלום לכולם",
        "אפשר להזמין קפה",
    ],
)
def test_presets_avoid_substrings_and_generic_topic_bans(text):
    assert match_block(rules("hard"), text) is None


def test_normalization_is_scoped_to_presets_and_reasons_are_readable():
    raw = BlockRule.compile(SimpleNamespace(pattern="^fuck$", isRegex=True, isWildcard=False))
    assert match_block((raw,), "f\u200buck") is None
    match = match_block(rules("medium"), "f\u200buck")
    assert match.pattern == "fuck"
    assert normalize_preset_text("מְטֻמְטָם") == "מטמטם"


def test_long_message_cannot_hide_last_package_entry():
    term = WORD_PACKAGES["hard"][-1]
    assert match_block(rules("hard"), ("ordinary content " * 230) + term)


async def test_packages_install_idempotently_and_refresh_cached_rules(db_engine, mocker):
    cache = AsyncSnapshotCache()
    mocker.patch("src.utils.message_rules.get_cache", return_value=cache)
    ctx = SimpleNamespace(db=async_sessionmaker(db_engine, expire_on_commit=False))
    async with ctx.db() as session:
        session.add(ChatSettings(id=-123))
        await session.commit()
    assert await get_block_rules(ctx, -123) == ()
    low = BAD_WORDS_BLOCKS["low"]
    assert await batch_add_blacklist(ctx, -123, low) == (len(low), 0)
    assert match_block(await get_block_rules(ctx, -123), "idiot")
    hard = BAD_WORDS_BLOCKS["hard"]
    assert await batch_add_blacklist(ctx, -123, hard) == (len(hard) - len(low), len(low))
    assert await batch_add_blacklist(ctx, -123, hard) == (0, len(hard))
    assert await get_blacklist_count(ctx, -123) == len(hard)
    assert match_block(await get_block_rules(ctx, -123), "רווח מובטח")


async def test_remove_preset_by_readable_word(db_engine, mocker):
    cache = AsyncSnapshotCache()
    mocker.patch("src.utils.message_rules.get_cache", return_value=cache)
    ctx = SimpleNamespace(db=async_sessionmaker(db_engine, expire_on_commit=False))
    async with ctx.db() as session:
        session.add(ChatSettings(id=-123))
        await session.commit()
    await batch_add_blacklist(ctx, -123, BAD_WORDS_BLOCKS["low"])
    assert match_block(await get_block_rules(ctx, -123), "stupid")
    assert await remove_blacklist(ctx, -123, "stupid")
    assert match_block(await get_block_rules(ctx, -123), "stupid") is None
    assert match_block(await get_block_rules(ctx, -123), "idiot")
