import asyncio
import contextlib

from loguru import logger
from pyrogram import Client, filters
from pyrogram.errors import BadRequest, FloodWait, Forbidden
from pyrogram.types import Message, User
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.core.bot import bot
from src.core.context import get_context
from src.core.plugin import Plugin, register
from src.db.models import FedAdmin, FedBan, FedChat, Federation
from src.utils.decorators import (
    admin_permission_required,
    resolve_target,
    safe_handler,
)
from src.utils.i18n import at
from src.utils.permissions import Permission


class FederationPlugin(Plugin):
    """Plugin to manage global bans across multiple groups (Federations)."""

    name = "federation"
    priority = 40

    async def setup(self, client: Client, ctx) -> None:
        pass


async def create_fed(ctx, name: str, owner_id: int) -> Federation:
    async with ctx.db() as s:
        f = Federation(name=name, ownerId=owner_id)
        s.add(f)
        await s.commit()
        await s.refresh(f)
        return f


async def join_fed(ctx, fid: str, cid: int, actor_id: int) -> Federation | None:
    async with ctx.db() as s:
        federation = await s.get(Federation, fid, with_for_update=True)
        if federation is None or federation.ownerId != actor_id:
            return None
        c = await s.scalar(select(FedChat).where(FedChat.chatId == cid).with_for_update())
        if c:
            c.fedId = fid
        else:
            c = FedChat(fedId=fid, chatId=cid)
        s.add(c)
        await s.commit()
        await s.refresh(federation)
        return federation


async def get_fed_by_chat(ctx, cid: int) -> Federation | None:
    async with ctx.db() as s:
        c = (
            (
                await s.execute(
                    select(FedChat).where(FedChat.chatId == cid).options(selectinload(FedChat.fed))
                )
            )
            .scalars()
            .first()
        )
        return c.fed if c else None


async def fban_user(ctx, cid: int, uid: int, reason: str, by: int) -> Federation | None:
    async with ctx.db() as s:
        federation = await s.scalar(
            select(Federation).join(FedChat).where(FedChat.chatId == cid).with_for_update()
        )
        if federation is None:
            return None
        fid = federation.id
        if federation.ownerId != by and not await s.scalar(
            select(FedAdmin.id).where(FedAdmin.fedId == fid, FedAdmin.userId == by).limit(1)
        ):
            return None
        b = (
            (await s.execute(select(FedBan).where(FedBan.fedId == fid, FedBan.userId == uid)))
            .scalars()
            .first()
        )
        if b:
            b.reason, b.bannedBy = reason, by
        else:
            b = FedBan(fedId=fid, userId=uid, reason=reason, bannedBy=by)
        s.add(b)
        await s.commit()
        await s.refresh(federation)
        return federation


async def is_fbanned(ctx, fid: str, uid: int) -> bool:
    async with ctx.db() as s:
        return (
            await s.execute(select(FedBan).where(FedBan.fedId == fid, FedBan.userId == uid))
        ).scalars().first() is not None


@bot.on_message(filters.command("newfed") & filters.private)
@safe_handler
async def newfed_handler(client: Client, message: Message) -> None:
    if len(message.command) < 2:
        return
    f = await create_fed(get_context(), " ".join(message.command[1:]), message.from_user.id)
    await message.reply(await at(message.chat.id, "federation.created", name=f.name, id=f.id))


@bot.on_message(filters.command("joinfed") & filters.group)
@safe_handler
@admin_permission_required(Permission.CAN_CHANGE_INFO)
async def joinfed_handler(client: Client, message: Message) -> None:
    if len(message.command) < 2 or not message.from_user:
        return
    federation = await join_fed(
        get_context(), message.command[1], message.chat.id, message.from_user.id
    )
    if federation is None:
        return await message.reply(await at(message.chat.id, "common.err_access_denied"))
    await message.reply(await at(message.chat.id, "federation.joined", name=federation.name))


@bot.on_message(filters.command("fban") & filters.group)
@safe_handler
@admin_permission_required(Permission.CAN_BAN)
@resolve_target
async def fban_handler(client: Client, message: Message, target_user: User) -> None:
    ctx = get_context()
    if not message.from_user:
        return
    if not await get_fed_by_chat(ctx, message.chat.id):
        return await message.reply(await at(message.chat.id, "federation.not_joined"))
    r = (
        " ".join(message.command[2:])
        if len(message.command) > 2
        else await at(message.chat.id, "common.no_reason")
    )
    f = await fban_user(ctx, message.chat.id, target_user.id, r, message.from_user.id)
    if f is None:
        return await message.reply(await at(message.chat.id, "common.err_access_denied"))
    await message.reply(
        await at(message.chat.id, "federation.banned", mention=target_user.mention, fed=f.name)
    )


@bot.on_message(filters.group & filters.new_chat_members, group=-60)
@safe_handler
async def federation_interceptor(client: Client, message: Message) -> None:
    ctx = get_context()
    if not (f := await get_fed_by_chat(ctx, message.chat.id)):
        return
    for m in message.new_chat_members:
        if await is_fbanned(ctx, f.id, m.id):
            try:
                await client.ban_chat_member(message.chat.id, m.id)
                await message.reply(
                    await at(message.chat.id, "federation.interceptor_banned", mention=m.mention)
                )
            except (BadRequest, Forbidden):
                pass
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                with contextlib.suppress(Exception):
                    await client.ban_chat_member(message.chat.id, m.id)
            except Exception as e:
                logger.exception(f"Fed ban err: {e}")


register(FederationPlugin())
