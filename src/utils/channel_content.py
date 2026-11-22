from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pyrogram.enums import ButtonStyle
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

if TYPE_CHECKING:
    from pyrogram.types import Message

    from src.db.models import ChatSettings


@dataclass(frozen=True, slots=True)
class ChannelContentPlan:
    is_media: bool
    is_caption_host: bool
    target_content: str | None
    reply_markup: InlineKeyboardMarkup | None


def build_content_plan(
    settings: ChatSettings, message: Message, is_caption_host: bool
) -> ChannelContentPlan:
    is_media = any(
        (
            message.photo,
            message.video,
            message.document,
            message.animation,
            message.audio,
            message.voice,
            message.video_note,
        )
    )
    return ChannelContentPlan(
        is_media,
        is_caption_host,
        calculate_target_content(settings, message, is_media, is_caption_host),
        build_buttons_keyboard(settings.buttons) if is_caption_host else None,
    )


def calculate_target_content(
    settings: ChatSettings, message: Message, is_media: bool, is_caption_host: bool
) -> str | None:
    """
    Calculates the new text/caption for the message including the signature.
    Returns None if no update is required.
    """
    if not (settings.signatureEnabled and settings.signatureText and is_caption_host):
        return None

    current = ""
    if is_media:
        if message.caption:
            current = getattr(message.caption, "html", message.caption)
    else:
        if message.text:
            current = getattr(message.text, "html", message.text)
    limit = 1024 if is_media else 4096

    sig_text = settings.signatureText
    sig = f"\n\n{sig_text}"

    if sig_text not in current and len(current) + len(sig) <= limit:
        return f"{current}{sig}"

    return None


def build_buttons_keyboard(buttons_json: str | None) -> InlineKeyboardMarkup | None:
    try:
        rows = json.loads(buttons_json or "[]")
    except (ValueError, TypeError):
        return None
    if not isinstance(rows, list):
        return None

    keyboard = []
    for row in rows:
        if not isinstance(row, list):
            continue
        buttons = []
        for entry in row:
            if not isinstance(entry, dict) or not entry.get("url"):
                continue
            try:
                style = ButtonStyle(entry.get("style", "default"))
            except (ValueError, TypeError):
                style = ButtonStyle.DEFAULT
            buttons.append(
                InlineKeyboardButton(entry.get("text") or "Button", url=entry["url"], style=style)
            )
        if buttons:
            keyboard.append(buttons)
    return InlineKeyboardMarkup(keyboard) if keyboard else None
