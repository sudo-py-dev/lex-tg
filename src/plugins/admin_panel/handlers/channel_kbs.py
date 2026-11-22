from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.config import config
from src.utils.i18n import at
from src.utils.media import parse_watermark_config


async def channel_settings_kb(
    ctx, channel_id: int, user_id: int, *, picker_page: int | None = None
) -> InlineKeyboardMarkup:
    """Keyboard for specific channel settings."""
    wm_menu_label = await at(user_id, "panel.btn_watermark_menu")
    if wm_menu_label == "panel.btn_watermark_menu":
        # Backward-compatible fallback for locales that don't have the new menu-only key yet.
        wm_menu_label = await at(user_id, "panel.btn_watermark")
        wm_menu_label = wm_menu_label.strip().rstrip(":").rstrip("：").strip()

    return InlineKeyboardMarkup(
        [
            # Row 1: Reactions & Signature
            [
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_cat_reactions"),
                    callback_data=f"panel:channel_reactions:{channel_id}",
                ),
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_signature_menu"),
                    callback_data=f"panel:channel_signature:{channel_id}",
                ),
            ],
            # Row 2: Watermark & Buttons
            [
                InlineKeyboardButton(
                    wm_menu_label,
                    callback_data=f"panel:channel_watermark:{channel_id}",
                ),
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_buttons"),
                    callback_data=f"panel:channel_buttons:{channel_id}",
                ),
            ],
            # Row 3: Service Cleaner
            [
                InlineKeyboardButton(
                    await at(user_id, "common.service_cleaner"),
                    callback_data=f"panel:chs:{channel_id}",
                )
            ],
            # Row 4: Back
            [
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_switch_chat"),
                    callback_data="panel:my_chats"
                    if picker_page is None
                    else f"panel:list_channels:{picker_page}",
                ),
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_close"), callback_data="panel:close"
                ),
            ],
        ]
    )


async def channel_reactions_kb(ctx, channel_id: int, user_id: int) -> InlineKeyboardMarkup:
    """Keyboard for reaction settings."""
    from src.db.repositories.chats import get_chat_settings as get_channel_settings

    s = await get_channel_settings(ctx, channel_id)

    status = "✅" if s.reactionsEnabled else "❌"
    mode_label = await at(user_id, f"reaction_mode_{s.reactionMode}")

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_reactions_status", status=status),
                    callback_data=f"panel:toggle_ch:reactionsEnabled:{channel_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_reaction_mode", mode=mode_label),
                    callback_data=f"panel:toggle_ch:reactionMode:{channel_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_edit_emojis"),
                    callback_data=f"panel:input:reactions:{channel_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_back"),
                    callback_data=f"panel:channel_settings:{channel_id}",
                )
            ],
        ]
    )


async def channel_signature_kb(ctx, channel_id: int, user_id: int) -> InlineKeyboardMarkup:
    """Keyboard for signature settings."""
    from src.db.repositories.chats import get_chat_settings as get_channel_settings

    s = await get_channel_settings(ctx, channel_id)

    status = "✅" if s.signatureEnabled else "❌"

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_signature_status", status=status),
                    callback_data=f"panel:toggle_ch:signatureEnabled:{channel_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_edit_signature"),
                    callback_data=f"panel:input:signatureText:{channel_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_back"),
                    callback_data=f"panel:channel_settings:{channel_id}",
                )
            ],
        ]
    )


async def channel_watermark_kb(ctx, channel_id: int, user_id: int) -> InlineKeyboardMarkup:
    from src.db.repositories.chats import get_chat_settings as get_channel_settings

    s = await get_channel_settings(ctx, channel_id)
    cfg = parse_watermark_config(s.watermarkText)
    wm_color = cfg.color
    wm_style = cfg.style

    # Status icons
    image_status = "✅" if cfg.image_enabled else "❌"
    video_status = "✅" if cfg.video_enabled else "❌"

    buttons = [
        # Media Toggles
        [
            InlineKeyboardButton(
                await at(user_id, "panel.btn_wm_image", status=image_status),
                callback_data=f"panel:toggle_wm_image:{channel_id}",
            )
        ],
        # Image Management
        [
            InlineKeyboardButton(
                await at(user_id, "panel.btn_set_wm_image"),
                callback_data=f"panel:input:watermarkImage:{channel_id}",
            ),
            InlineKeyboardButton(
                await at(user_id, "panel.btn_clear_wm_image"),
                callback_data=f"panel:clear_wm_image:{channel_id}",
            ),
        ],
        # Position & Layout
        [
            InlineKeyboardButton(
                await at(
                    user_id,
                    "panel.btn_wm_position",
                    value=await at(
                        user_id, f"panel.wm_location_{s.watermarkPosition or 'bottom_right'}"
                    ),
                ),
                callback_data=f"panel:cycle_wm:position:{channel_id}",
            ),
        ],
        # Opacity & Size
        [
            InlineKeyboardButton(
                await at(
                    user_id,
                    "panel.btn_wm_opacity",
                    value=int(
                        (s.watermarkOpacity if s.watermarkOpacity is not None else 0.7) * 100
                    ),
                ),
                callback_data=f"panel:input:watermarkOpacity:{channel_id}",
            ),
            InlineKeyboardButton(
                await at(
                    user_id,
                    "panel.btn_wm_size",
                    value=s.watermarkSize or 10,
                ),
                callback_data=f"panel:input:watermarkSize:{channel_id}",
            ),
        ],
    ]

    if config.ENABLE_VIDEO_WATERMARK:
        buttons.append(
            [
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_wm_video", status=video_status),
                    callback_data=f"panel:toggle_wm_video:{channel_id}",
                )
            ]
        )

    buttons.extend(
        [
            # Text Setting
            [
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_set_watermark"),
                    callback_data=f"panel:input:watermarkText:{channel_id}",
                ),
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_clear_text"),
                    callback_data=f"panel:clear_wm_text:{channel_id}",
                ),
            ],
            # Color & Style
            [
                InlineKeyboardButton(
                    await at(
                        user_id,
                        "panel.btn_wm_color",
                        value=await at(user_id, f"panel.wm_color_{wm_color}"),
                    ),
                    callback_data=f"panel:cycle_wm:color:{channel_id}",
                ),
                InlineKeyboardButton(
                    await at(
                        user_id,
                        "panel.btn_wm_style",
                        value=await at(user_id, f"panel.wm_style_{wm_style}"),
                    ),
                    callback_data=f"panel:cycle_wm:style:{channel_id}",
                ),
            ],
        ]
    )

    if config.ENABLE_VIDEO_WATERMARK:
        # Video Quality & Motion
        buttons.append(
            [
                InlineKeyboardButton(
                    await at(
                        user_id,
                        "panel.btn_wm_video_quality",
                        value=await at(user_id, f"panel.wm_quality_{cfg.video_quality}"),
                    ),
                    callback_data=f"panel:cycle_wm:video_quality:{channel_id}",
                ),
                InlineKeyboardButton(
                    await at(
                        user_id,
                        "panel.btn_wm_video_motion",
                        value=await at(user_id, f"panel.wm_motion_{cfg.video_motion}"),
                    ),
                    callback_data=f"panel:cycle_wm:video_motion:{channel_id}",
                ),
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                await at(user_id, "panel.btn_back"),
                callback_data=f"panel:channel_settings:{channel_id}",
            )
        ]
    )
    return InlineKeyboardMarkup(buttons)


async def channel_buttons_kb(ctx, channel_id: int, user_id: int) -> InlineKeyboardMarkup:
    from src.db.repositories.chats import get_chat_settings

    s = await get_chat_settings(ctx, channel_id)
    import json

    try:
        rows = json.loads(s.buttons or "[]")
    except Exception:
        rows = []

    buttons = []
    # List each button with controls
    for r_idx, row in enumerate(rows):
        for b_idx, btn in enumerate(row):
            label = btn.get("text", "Button")
            style_str = btn.get("style", "default")

            # Localized style name
            style_name = await at(user_id, f"panel.btn_button_style_{style_str}")
            if style_name == f"panel.btn_button_style_{style_str}":
                style_name = style_str.title()

            buttons.append(
                [
                    InlineKeyboardButton(label, url=btn.get("url", "https://t.me")),
                    InlineKeyboardButton(
                        f"🎨 {style_name}",
                        callback_data=f"panel:cycle_ch_btn_style:{channel_id}:{r_idx}:{b_idx}",
                    ),
                    InlineKeyboardButton(
                        "🗑️", callback_data=f"panel:delete_ch_btn:{channel_id}:{r_idx}:{b_idx}"
                    ),
                ]
            )

    # Add button
    buttons.append(
        [
            InlineKeyboardButton(
                await at(user_id, "panel.btn_add_button"),
                callback_data=f"panel:input:buttonsText:{channel_id}",
            )
        ]
    )

    buttons.append(
        [
            InlineKeyboardButton(
                await at(user_id, "panel.btn_back"),
                callback_data=f"panel:channel_settings:{channel_id}",
            )
        ]
    )
    return InlineKeyboardMarkup(buttons)
