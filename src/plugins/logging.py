import asyncio
import contextlib
import time
from collections import defaultdict

from loguru import logger
from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.errors import BadRequest, ChatAdminRequired, Forbidden
from pyrogram.types import Message, User

from src.core.bot import bot
from src.core.context import get_context
from src.core.plugin import Plugin, register
from src.plugins.admin_panel.repository import (
    get_chat_settings,
    update_chat_setting,
    update_settings,
)
from src.utils.decorators import admin_permission_required, get_sender_id, safe_handler
from src.utils.i18n import at
from src.utils.permissions import Permission


class LoggingPlugin(Plugin):
    """Plugin to send administrative audit logs with rate-limiting and intelligent batching."""

    name = "logging"
    priority = 90

    def __init__(self):
        super().__init__()
        self.log_queue = asyncio.Queue()
        self._worker_task = None
        self._batch_buffers = defaultdict(list)
        self._batch_last_flush = defaultdict(float)
        self._chat_title_cache = {}

    async def setup(self, client: Client, ctx) -> None:
        """
        Initialize the logging worker and begin processing the log queue.

        Args:
            client (Client): The Pyrogram client instance.
            ctx (Context): The application context.
        """
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._log_worker(client, ctx))
            logger.debug("Logging: Batched worker started.")

    async def teardown(self) -> None:
        """
        Gracefully shut down the logging worker and wait for the task to finish.
        """
        if self._worker_task:
            self._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task
            self._worker_task = None
            logger.debug("Logging: Batched worker stopped.")

    async def _log_worker(self, client: Client, ctx) -> None:
        """
        Infinite loop worker that processes the log queue.

        Collects moderation events, groups them by chat ID, and flushes them
        periodically (every 5 seconds or when a batch reaches 5 items).

        Args:
            client (Client): The Pyrogram client instance.
            ctx (Context): The application context.
        """
        while True:
            try:
                try:
                    event_data = await asyncio.wait_for(self.log_queue.get(), timeout=2.0)
                    chat_id = event_data["chat_id"]
                    self._batch_buffers[chat_id].append(event_data)
                    self.log_queue.task_done()
                except TimeoutError:
                    pass

                now = time.time()
                for chat_id, buffer in list(self._batch_buffers.items()):
                    if not buffer:
                        continue

                    if now - self._batch_last_flush[chat_id] > 5.0 or len(buffer) >= 5:
                        await self._flush_chat_batch(client, ctx, chat_id, buffer)
                        self._batch_buffers[chat_id] = []
                        self._batch_last_flush[chat_id] = now

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Logging: Worker encountered an error: {e}")
                await asyncio.sleep(2.0)

    async def _flush_chat_batch(
        self, client: Client, ctx, chat_id: int, events: list[dict]
    ) -> None:
        """
        Send a batch of moderation events to the designated log channel for a chat.

        Args:
            client (Client): The Pyrogram client instance.
            ctx (Context): The application context.
            chat_id (int): The ID of the chat whose events are being logged.
            events (list[dict]): A list of event data dictionaries to be formatted and sent.

        Side Effects:
            - Fetches chat settings from the database.
            - Sends a formatted message to the logging channel.
        """
        settings = await get_chat_settings(ctx, chat_id)
        if not settings or not settings.logChannelId:
            return

        chat_title = self._chat_title_cache.get(chat_id, f"Chat {chat_id}")

        header = await at(chat_id, "logging.batch_header", chat=chat_title)

        items = []
        for ev in events:
            reason_str = ""
            if ev["reason"]:
                reason_label = await at(chat_id, "logging.reason_label")
                reason_str = f"\n  {reason_label} {ev['reason']}"

            item = await at(
                chat_id,
                "logging.batch_item",
                action=ev["action"].upper(),
                target=ev["target_mention"],
                actor=ev["actor_mention"],
                reason=reason_str,
            )
            items.append(item)

        final_text = header + "\n\n" + "\n".join(items)

        try:
            await client.send_message(settings.logChannelId, final_text)
            await asyncio.sleep(0.5)
        except (Forbidden, ChatAdminRequired, BadRequest) as e:
            logger.debug(
                f"Logging: Removing invalid log channel {settings.logChannelId} "
                f"for chat {chat_id} due to persistent error: {e}"
            )
            await update_settings(ctx, chat_id, logChannelId=None, logChannelName=None)
        except Exception as e:
            logger.error(f"Logging: Failed to flush batch to {settings.logChannelId}: {e}")


# --- Administrative Commands ---


async def _can_use_log_target(client: Client, target_id: int, user_id: int | None) -> bool:
    """The caller must administer the target (with posting rights for channels)."""
    if user_id is None:
        return False
    try:
        member = await client.get_chat_member(target_id, user_id)
    except Exception:
        return False
    if member.status == ChatMemberStatus.OWNER:
        return True
    if member.status != ChatMemberStatus.ADMINISTRATOR:
        return False
    try:
        target = await client.get_chat(target_id)
    except Exception:
        return False
    if target.type == ChatType.CHANNEL:
        return bool(member.privileges and member.privileges.can_post_messages)
    return True


@bot.on_message(filters.command("setlog") & filters.group)
@safe_handler
@admin_permission_required(Permission.CAN_CHANGE_INFO)
async def set_log_handler(client: Client, message: Message) -> None:
    """
    Designate a channel to receive moderation logs for the current group.

    The channel ID can be provided as an argument or by replying to a
    forwarded message from the desired channel.
    """
    if len(message.command) < 2:
        if message.reply_to_message and message.reply_to_message.forward_from_chat:
            channel_id = message.reply_to_message.forward_from_chat.id
        else:
            return
    else:
        try:
            channel_id = int(message.command[1])
        except ValueError:
            return
    if not await _can_use_log_target(client, channel_id, get_sender_id(message)):
        await message.reply(await at(message.chat.id, "log.err_target_not_admin"))
        return
    ctx = get_context()
    await update_chat_setting(ctx, message.chat.id, "logChannelId", channel_id)
    await message.reply(await at(message.chat.id, "log.set"))


@bot.on_message(filters.command("unsetlog") & filters.group)
@safe_handler
@admin_permission_required(Permission.CAN_CHANGE_INFO)
async def unset_log_handler(client: Client, message: Message) -> None:
    """
    Remove the current logging channel designation for the group.
    """
    ctx = get_context()
    await update_chat_setting(ctx, message.chat.id, "logChannelId", None)
    await message.reply(await at(message.chat.id, "log.unset"))


async def log_event(
    ctx,
    client: Client,
    chat_id: int,
    action: str,
    target: User | str,
    actor: User | str,
    reason: str | None = None,
    chat_title: str | None = None,
) -> None:
    """
    Push a moderation event into the logging queue.
    """
    if chat_title:
        logging_plugin._chat_title_cache[chat_id] = chat_title
    elif chat_id not in logging_plugin._chat_title_cache:
        settings = await get_chat_settings(ctx, chat_id)
        if settings and settings.title:
            logging_plugin._chat_title_cache[chat_id] = settings.title
        else:
            logging_plugin._chat_title_cache[chat_id] = f"Chat {chat_id}"

    target_mention = target.mention if isinstance(target, User) else f"`{target}`"
    actor_mention = actor.mention if isinstance(actor, User) else f"`{actor}`"

    event_data = {
        "chat_id": chat_id,
        "action": action,
        "target_mention": target_mention,
        "actor_mention": actor_mention,
        "reason": reason,
        "timestamp": time.time(),
    }

    await logging_plugin.log_queue.put(event_data)


logging_plugin = LoggingPlugin()
register(logging_plugin)
