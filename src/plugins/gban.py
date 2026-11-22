import asyncio
import contextlib

from loguru import logger
from pyrogram import Client, filters
from pyrogram.errors import BadRequest, FloodWait, Forbidden, RPCError
from pyrogram.types import Message, User

from src.config import config
from src.core.bot import bot
from src.core.context import get_context
from src.core.plugin import Plugin, register
from src.db.repositories.gban import (
    add_gban,
    add_sudo,
    is_gbanned,
    is_sudo,
    remove_gban,
)
from src.utils.decorators import resolve_target, safe_handler
from src.utils.i18n import at


class GbanPlugin(Plugin):
    name = "gban"
    priority = 60

    async def setup(self, client: Client, ctx) -> None:
        pass


@bot.on_message(filters.command("gban") & filters.private)
@safe_handler
@resolve_target
async def gban_handler(client: Client, message: Message, target_user: User) -> None:
    if not message.from_user or not await is_sudo(get_context(), message.from_user.id):
        return
    reason = (
        " ".join(message.command[2:])
        if len(message.command) > 2
        else await at(message.chat.id, "common.no_reason")
    )
    await add_gban(get_context(), target_user.id, reason, message.from_user.id)
    await message.reply(
        await at(message.chat.id, "gban.success", mention=target_user.mention, reason=reason)
    )


@bot.on_message(filters.command("ungban") & filters.private)
@safe_handler
@resolve_target
async def ungban_handler(client: Client, message: Message, target_user: User) -> None:
    if not message.from_user or not await is_sudo(get_context(), message.from_user.id):
        return
    if await remove_gban(get_context(), target_user.id):
        await message.reply(
            await at(message.chat.id, "gban.ungban_success", mention=target_user.mention)
        )


@bot.on_message(filters.command("addsudo") & filters.private & filters.user(config.OWNER_ID))
@safe_handler
@resolve_target
async def addsudo_handler(client: Client, message: Message, target_user: User) -> None:
    if message.from_user and message.from_user.id == config.OWNER_ID:
        await add_sudo(get_context(), target_user.id, message.from_user.id)
        await message.reply(await at(message.chat.id, "gban.addsudo", mention=target_user.mention))


@bot.on_message(filters.group & filters.new_chat_members, group=-50)
@safe_handler
async def gban_interceptor(client: Client, message: Message) -> None:
    if not message.from_user or message.from_user.is_bot:
        return
    ctx = get_context()
    for m in message.new_chat_members:
        if await is_gbanned(ctx, m.id):
            try:
                await client.ban_chat_member(message.chat.id, m.id)
                await message.reply(await at(message.chat.id, "gban.joined", mention=m.mention))
            except (BadRequest, Forbidden):
                pass
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                with contextlib.suppress(Exception):
                    await client.ban_chat_member(message.chat.id, m.id)
            except RPCError as e:
                logger.exception(f"Gban error: {e}")


register(GbanPlugin())
