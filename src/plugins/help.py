import contextlib

from pyrogram import Client, filters
from pyrogram.errors import MessageNotModified
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)

from src.core.bot import bot
from src.core.plugin import Plugin, register
from src.utils.about import get_about_text
from src.utils.decorators import safe_handler
from src.utils.i18n import at


class HelpPlugin(Plugin):
    """Plugin for the grid-based help system."""

    name = "help"
    priority = 200

    async def setup(self, client: Client, ctx) -> None:
        pass


HELP_SECTIONS = {
    "moderation": ("admin", "bans", "purges", "reports", "approval", "federations", "pin"),
    "protection": ("antiflood", "antiraid", "blacklist", "captcha", "locks"),
    "setup": (
        "connections",
        "greetings",
        "languages",
        "logging",
        "rules",
        "topics",
        "cleancmd",
        "cleansvc",
        "disabling",
        "impexp",
    ),
    "reference": ("about", "filters", "formatting", "misc", "notes", "privacy"),
}


async def get_help_kb(chat_id: int, section: str | None = None) -> InlineKeyboardMarkup:
    if section is None:
        buttons = [
            [
                InlineKeyboardButton(
                    await at(chat_id, f"help.section_{name}"), callback_data=f"help:section:{name}"
                )
            ]
            for name in HELP_SECTIONS
        ]
        back = "help:start"
    else:
        topics = [
            InlineKeyboardButton(
                await at(chat_id, f"help.btn_{topic}"), callback_data=f"help:cat:{topic}"
            )
            for topic in HELP_SECTIONS[section]
        ]
        buttons = [topics[i : i + 2] for i in range(0, len(topics), 2)]
        back = "help:main"
    buttons.append([InlineKeyboardButton(await at(chat_id, "help.back_btn"), callback_data=back)])
    return InlineKeyboardMarkup(buttons)


@bot.on_message(filters.command("help") & filters.private)
@safe_handler
async def help_handler(client: Client, message: Message) -> None:
    """Display help sections in a private chat."""
    chat_id = message.chat.id
    await message.reply(
        await at(chat_id, "help.main_text"), reply_markup=await get_help_kb(chat_id)
    )


@bot.on_callback_query(filters.regex(r"^help:"))
@safe_handler
async def help_callback_handler(client: Client, callback_query: CallbackQuery) -> None:
    """Handle navigation within the help menu."""
    await callback_query.answer()
    message = callback_query.message
    if message is None:
        return
    data = callback_query.data
    chat_id = message.chat.id

    if data == "help:start":
        from src.plugins.admin import send_start_message

        with contextlib.suppress(MessageNotModified):
            await send_start_message(client, message, edit=True)
        return

    if data == "help:main" or data.startswith("help:section:"):
        section = data.removeprefix("help:section:") if data.startswith("help:section:") else None
        if section is not None and section not in HELP_SECTIONS:
            return
        heading = f"help.section_{section}" if section else "help.main_text"
        with contextlib.suppress(MessageNotModified):
            await message.edit_text(
                await at(chat_id, heading), reply_markup=await get_help_kb(chat_id, section)
            )
        return

    if data == "help:setting:flood":
        topic = "antiflood"
        back = "panel:flood"
    elif data.startswith("help:cat:"):
        topic = data.removeprefix("help:cat:")
        if topic == "about:start":
            topic, back = "about", "help:start"
        else:
            section = next(
                (name for name, topics in HELP_SECTIONS.items() if topic in topics), None
            )
            if section is None:
                return
            back = f"help:section:{section}"
    else:
        return

    text = (
        await get_about_text(chat_id)
        if topic == "about"
        else await at(chat_id, f"help.{topic}_text")
    )
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton(await at(chat_id, "help.back_btn"), callback_data=back)]]
    )
    with contextlib.suppress(MessageNotModified):
        await message.edit_text(
            text, reply_markup=kb, link_preview_options=LinkPreviewOptions(is_disabled=True)
        )


register(HelpPlugin())
