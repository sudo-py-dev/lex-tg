import re

from sqlalchemy import func, select

from src.core.context import AppContext
from src.db.models import Blacklist
from src.utils.message_rules import detect_pattern_type, invalidate_rules


async def add_blacklist(
    ctx: AppContext,
    chat_id: int,
    pattern: str,
    action: str = "delete",
    is_regex: bool = False,
    is_wildcard: bool = False,
) -> Blacklist | None:
    """Add a pattern to the blacklist for a chat. Limits to 200 entries."""
    pattern = pattern.strip()
    if not pattern:
        raise ValueError("blacklist_empty_pattern")
    if is_regex:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError("blacklist_invalid_regex") from exc
    else:
        pattern = pattern.lower()
    async with ctx.db() as session:
        count_stmt = select(func.count()).select_from(Blacklist).where(Blacklist.chatId == chat_id)
        count_result = await session.execute(count_stmt)
        count = count_result.scalar() or 0

        if count >= 200:
            raise ValueError("blacklist_limit_reached")

        dup_stmt = select(Blacklist).where(
            Blacklist.chatId == chat_id, Blacklist.pattern == pattern
        )
        dup_result = await session.execute(dup_stmt)
        if dup_result.scalars().first():
            raise ValueError("blacklist_already_exists")

        blacklist = Blacklist(
            chatId=chat_id,
            pattern=pattern,
            action=action,
            isRegex=is_regex,
            isWildcard=is_wildcard,
        )
        session.add(blacklist)
        await session.commit()
        await invalidate_rules("blacklist", chat_id)
        await session.refresh(blacklist)
        return blacklist


async def remove_blacklist(ctx: AppContext, chat_id: int, pattern: str) -> bool:
    """Remove a pattern from the blacklist."""
    async with ctx.db() as session:
        stmt = select(Blacklist).where(Blacklist.chatId == chat_id, Blacklist.pattern == pattern)
        result = await session.execute(stmt)
        objs = result.scalars().all()
        if not objs:
            return False
        for obj in objs:
            await session.delete(obj)
        await session.commit()
        await invalidate_rules("blacklist", chat_id)
        return True


async def get_all_blacklist(ctx: AppContext, chat_id: int) -> list[Blacklist]:
    """Get all blacklisted patterns for a chat."""
    async with ctx.db() as session:
        stmt = select(Blacklist).where(Blacklist.chatId == chat_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def get_blacklist_count(ctx: AppContext, chat_id: int) -> int:
    """Get the count of blacklisted patterns for a chat."""
    async with ctx.db() as session:
        stmt = select(func.count()).select_from(Blacklist).where(Blacklist.chatId == chat_id)
        result = await session.execute(stmt)
        return result.scalar() or 0


async def batch_add_blacklist(
    ctx: AppContext,
    chat_id: int,
    patterns: list[str],
    action: str = "delete",
) -> tuple[int, int]:
    """
    Add multiple patterns to the blacklist.
    Skips existing patterns and respects the 200 limit.
    Returns (added_count, skipped_count).
    """
    async with ctx.db() as session:
        existing_stmt = select(Blacklist.pattern).where(Blacklist.chatId == chat_id)
        existing_res = await session.execute(existing_stmt)
        existing_patterns = set(existing_res.scalars().all())
        count_stmt = select(func.count()).select_from(Blacklist).where(Blacklist.chatId == chat_id)
        count_res = await session.execute(count_stmt)
        current_count = count_res.scalar() or 0

        added = 0
        skipped = 0

        for p in patterns:
            is_regex, is_wildcard, p = detect_pattern_type(p)
            if not p:
                skipped += 1
                continue
            if is_regex:
                try:
                    re.compile(p)
                except re.error:
                    skipped += 1
                    continue
            if p in existing_patterns:
                skipped += 1
                continue

            if current_count >= 200:
                skipped += 1
                continue

            pattern = p
            obj = Blacklist(
                chatId=chat_id,
                pattern=pattern,
                action=action,
                isRegex=is_regex,
                isWildcard=is_wildcard,
            )
            session.add(obj)
            current_count += 1
            added += 1
            existing_patterns.add(pattern)

        await session.commit()
        if added:
            await invalidate_rules("blacklist", chat_id)
        return added, skipped
