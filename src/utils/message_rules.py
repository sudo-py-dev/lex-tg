"""Bounded, memory-only compiled message rules; repositories invalidate after commits."""

import fnmatch
import re
import time
from dataclasses import dataclass
from typing import Any

import regex

from src.core.blacklist_defaults import (
    PRESET_PREFIX,
    describe_block_pattern,
    normalize_preset_text,
)
from src.utils.local_cache import get_cache

RULE_TTL = 60
REGEX_BUDGET = 0.02


def rule_key(kind: str, chat_id: int) -> str:
    return f"message_rules:{kind}:{chat_id}"


async def invalidate_rules(kind: str, chat_id: int) -> None:
    await get_cache().delete(rule_key(kind, chat_id))


def detect_pattern_type(pattern: str) -> tuple[bool, bool, str]:
    pattern = pattern.strip()
    is_regex = any(c in "^$+.?{}[]()|" for c in pattern)
    return is_regex, ("*" in pattern and not is_regex), pattern if is_regex else pattern.lower()


@dataclass(frozen=True)
class BlockRule:
    pattern: str
    literal: str | None
    matcher: Any = None
    is_regex: bool = False
    normalize: bool = False

    @classmethod
    def compile(cls, row):
        if row.isRegex:
            try:
                return cls(
                    describe_block_pattern(row.pattern),
                    None,
                    regex.compile(row.pattern, regex.I),
                    True,
                    row.pattern.startswith(PRESET_PREFIX),
                )
            except regex.error:
                # Preserve literal fallback for invalid patterns already in the database.
                return cls(row.pattern, row.pattern.lower())
        if row.isWildcard:
            return cls(row.pattern, None, re.compile(fnmatch.translate(row.pattern), re.I | re.S))
        return cls(row.pattern, row.pattern.lower())


def match_block(rules: tuple[BlockRule, ...], text: str) -> BlockRule | None:
    folded = text.lower()
    normalized = None
    deadline = time.monotonic() + REGEX_BUDGET
    for rule in rules:
        if rule.literal is not None:
            if rule.literal and rule.literal in folded:
                return rule
        elif rule.is_regex:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                continue
            try:
                if rule.normalize and normalized is None:
                    normalized = normalize_preset_text(text)
                if rule.matcher.search(
                    normalized if rule.normalize else text, timeout=min(0.005, remaining)
                ):
                    return rule
            except TimeoutError:
                continue
        elif rule.matcher.search(text):
            return rule
    return None


@dataclass(frozen=True)
class ReplyRule:
    keyword: str
    text: str
    response_type: str
    file_id: str | None
    admin_only: bool
    matcher: Any
    full_match: bool

    @classmethod
    def compile(cls, row):
        settings = row.settings or {}
        # Lookarounds also work for punctuation/emoji keywords, unlike \b...\b.
        pattern = re.escape(row.keyword)
        full_match = settings.get("matchMode") == "full"
        if not full_match:
            pattern = rf"(?<!\w){pattern}(?!\w)"
        return cls(
            row.keyword,
            row.text,
            row.responseType,
            row.fileId,
            bool(settings.get("isAdminOnly")),
            re.compile(pattern, 0 if settings.get("caseSensitive") else re.I),
            full_match,
        )

    def matches(self, text: str) -> bool:
        if not self.keyword:
            return False
        return bool(self.matcher.fullmatch(text) if self.full_match else self.matcher.search(text))


async def get_block_rules(ctx, chat_id: int) -> tuple[BlockRule, ...]:
    async def load():
        from src.db.repositories.blacklist import get_all_blacklist

        return tuple(BlockRule.compile(row) for row in await get_all_blacklist(ctx, chat_id))

    return await get_cache().get_or_load(rule_key("blacklist", chat_id), load, ttl=RULE_TTL)


async def get_reply_rules(ctx, chat_id: int) -> tuple[ReplyRule, ...]:
    async def load():
        from src.db.repositories.filters import get_all_filters

        return tuple(ReplyRule.compile(row) for row in await get_all_filters(ctx, chat_id))

    return await get_cache().get_or_load(rule_key("filters", chat_id), load, ttl=RULE_TTL)


@dataclass(frozen=True)
class BlockSettings:
    action: str
    scan_buttons: bool


async def get_block_settings(ctx, chat_id: int) -> BlockSettings:
    async def load():
        from sqlalchemy import select

        from src.db.models import ChatSettings
        from src.db.repositories.chats import get_chat_settings

        # Avoid loading every settings relationship for two scalar options.
        async with ctx.db() as session:
            result = await session.execute(
                select(ChatSettings.blacklistAction, ChatSettings.blacklistScanButtons).where(
                    ChatSettings.id == chat_id
                )
            )
            row = result.one_or_none()
        if row is not None:
            return BlockSettings(row[0].lower(), row[1])
        settings = await get_chat_settings(ctx, chat_id)
        return BlockSettings(settings.blacklistAction.lower(), settings.blacklistScanButtons)

    return await get_cache().get_or_load(rule_key("settings", chat_id), load, ttl=RULE_TTL)
