from pyrogram.enums import ChatType
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.utils.i18n import at

from ..repository import get_chat_settings, get_user_admin_chat_page
from ..validation import is_setting_allowed
from .automation_kbs import (
    automation_category_kb as automation_category_kb,
)
from .automation_kbs import (
    chatnightlock_menu_kb as chatnightlock_menu_kb,
)
from .automation_kbs import (
    chatshabbatlock_menu_kb as chatshabbatlock_menu_kb,
)
from .automation_kbs import (
    cleaner_menu_kb as cleaner_menu_kb,
)
from .automation_kbs import (
    reminders_menu_kb as reminders_menu_kb,
)
from .automation_kbs import (
    timezone_picker_kb as timezone_picker_kb,
)
from .channel_kbs import (
    channel_buttons_kb as channel_buttons_kb,
)
from .channel_kbs import (
    channel_reactions_kb as channel_reactions_kb,
)
from .channel_kbs import (
    channel_settings_kb as channel_settings_kb,
)
from .channel_kbs import (
    channel_signature_kb as channel_signature_kb,
)
from .channel_kbs import (
    channel_watermark_kb as channel_watermark_kb,
)
from .pagination import get_pager as get_pager


async def main_menu_kb(
    chat_id: int,
    user_id: int | None = None,
    chat_type: ChatType | str | None = None,
    *,
    picker_page: int | None = None,
) -> InlineKeyboardMarkup:
    at_id = user_id or chat_id
    chat_type_str = "supergroup"
    if chat_type:
        chat_type_str = (
            chat_type.name.lower() if hasattr(chat_type, "name") else str(chat_type).lower()
        )

    buttons = []

    # Row 1: Safety & Moderation
    row1 = []
    if is_setting_allowed("security", chat_type_str):
        row1.append(
            InlineKeyboardButton(
                await at(at_id, "panel.btn_cat_security"),
                callback_data="panel:category:security",
            )
        )
    if is_setting_allowed("moderation", chat_type_str):
        row1.append(
            InlineKeyboardButton(
                await at(at_id, "panel.btn_cat_moderation"),
                callback_data="panel:category:moderation",
            )
        )
    if row1:
        buttons.append(row1)

    # Row 2: Greetings & Automation
    row2 = []
    if is_setting_allowed("greetings", chat_type_str):
        row2.append(
            InlineKeyboardButton(
                await at(at_id, "panel.btn_cat_greetings"),
                callback_data="panel:category:greetings",
            )
        )
    if is_setting_allowed("automation", chat_type_str):
        row2.append(
            InlineKeyboardButton(
                await at(at_id, "panel.btn_cat_scheduler"),
                callback_data="panel:category:automation",
            )
        )
    if row2:
        buttons.append(row2)

    # Row 3: AI & Settings
    row3 = []
    if is_setting_allowed("ai", chat_type_str):
        row3.append(
            InlineKeyboardButton(
                await at(at_id, "panel.btn_cat_ai"),
                callback_data="panel:category:ai",
            )
        )
    if is_setting_allowed("settings", chat_type_str):
        row3.append(
            InlineKeyboardButton(
                await at(at_id, "panel.btn_cat_settings"),
                callback_data="panel:category:settings",
            )
        )
    if row3:
        buttons.append(row3)

    last_row = []
    if user_id:
        last_row.append(
            InlineKeyboardButton(
                await at(at_id, "panel.btn_switch_chat"),
                callback_data="panel:my_chats"
                if picker_page is None
                else f"panel:list_groups:{picker_page}",
            )
        )

    last_row.append(
        InlineKeyboardButton(await at(at_id, "panel.btn_close"), callback_data="panel:close")
    )
    buttons.append(last_row)

    return InlineKeyboardMarkup(buttons)


async def my_chats_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_list_groups"), callback_data="panel:list_groups"
                )
            ],
            [
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_list_channels"),
                    callback_data="panel:list_channels",
                )
            ],
            [
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_language"), callback_data="panel:language:user"
                ),
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_close"), callback_data="panel:close"
                ),
            ],
        ]
    )


async def security_category_kb(
    chat_id: int, user_id: int | None = None, chat_type: str = "supergroup"
) -> InlineKeyboardMarkup:
    at_id = user_id or chat_id
    buttons = []

    # Row 1: Flood & Raid
    row1 = []
    if is_setting_allowed("flood", chat_type):
        row1.append(
            InlineKeyboardButton(await at(at_id, "panel.btn_flood"), callback_data="panel:flood")
        )
    if is_setting_allowed("raid", chat_type):
        row1.append(
            InlineKeyboardButton(await at(at_id, "panel.btn_raid"), callback_data="panel:raid")
        )
    if row1:
        buttons.append(row1)

    # Row 2: Captcha & URL Scanner
    row2 = []
    if is_setting_allowed("captcha", chat_type):
        row2.append(
            InlineKeyboardButton(
                await at(at_id, "panel.btn_captcha"), callback_data="panel:captcha"
            )
        )
    if is_setting_allowed("urlscanner", chat_type):
        row2.append(
            InlineKeyboardButton(
                await at(at_id, "panel.btn_urlscanner"), callback_data="panel:urlscanner"
            )
        )
    if row2:
        buttons.append(row2)

    # Row 3: AI Guard
    if is_setting_allowed("ai_security", chat_type):
        buttons.append(
            [
                InlineKeyboardButton(
                    (await at(at_id, "panel.btn_ai_guard_toggle")).split(":")[0],
                    callback_data="panel:category:ai_security",
                )
            ]
        )

    buttons.append(
        [InlineKeyboardButton(await at(at_id, "panel.btn_back"), callback_data="panel:main")]
    )
    return InlineKeyboardMarkup(buttons)


async def moderation_category_kb(
    chat_id: int, user_id: int | None = None, chat_type: str = "supergroup"
) -> InlineKeyboardMarkup:
    at_id = user_id or chat_id
    buttons = []

    # Row 1: Warns & Blacklist
    row1 = []
    if is_setting_allowed("warns", chat_type):
        row1.append(
            InlineKeyboardButton(await at(at_id, "panel.btn_warns"), callback_data="panel:warns")
        )
    if is_setting_allowed("blacklist", chat_type):
        row1.append(
            InlineKeyboardButton(
                await at(at_id, "panel.btn_blacklist"), callback_data="panel:blacklist:0"
            )
        )
    if row1:
        buttons.append(row1)

    # Row 2: Stickers & Entity Block
    row2 = []
    if is_setting_allowed("stickers", chat_type):
        row2.append(
            InlineKeyboardButton(
                await at(at_id, "panel.btn_stickers"), callback_data="panel:stickers:0"
            )
        )
    if is_setting_allowed("entityblock", chat_type):
        row2.append(
            InlineKeyboardButton(
                await at(at_id, "panel.btn_entityblock"), callback_data="panel:entityblock:0"
            )
        )
    if row2:
        buttons.append(row2)

    # Row 3: Langblock & Slowmode
    row3 = []
    if is_setting_allowed("langblock", chat_type):
        row3.append(
            InlineKeyboardButton(
                await at(at_id, "panel.btn_langblock"), callback_data="panel:langblock:0"
            )
        )
    if is_setting_allowed("slowmode", chat_type):
        row3.append(
            InlineKeyboardButton(
                await at(at_id, "panel.btn_slowmode"), callback_data="panel:slowmode"
            )
        )
    if row3:
        buttons.append(row3)

    # Row 4: Purge
    if is_setting_allowed("purgeMessagesCount", chat_type):
        buttons.append(
            [
                InlineKeyboardButton(
                    await at(at_id, "panel.btn_purge"),
                    callback_data="panel:input:purgeMessagesCount",
                )
            ]
        )

    buttons.append(
        [InlineKeyboardButton(await at(at_id, "panel.btn_back"), callback_data="panel:main")]
    )
    return InlineKeyboardMarkup(buttons)


async def greetings_category_kb(
    chat_id: int, user_id: int | None = None, chat_type: str = "supergroup"
) -> InlineKeyboardMarkup:
    at_id = user_id or chat_id
    buttons = []

    # Row 1: Welcome & Rules
    row1 = []
    if is_setting_allowed("welcome", chat_type):
        row1.append(
            InlineKeyboardButton(
                await at(at_id, "panel.btn_welcome"), callback_data="panel:welcome"
            )
        )
    if is_setting_allowed("rules", chat_type):
        row1.append(
            InlineKeyboardButton(await at(at_id, "panel.btn_rules"), callback_data="panel:rules")
        )
    if row1:
        buttons.append(row1)

    # Row 2: Filters
    if is_setting_allowed("filters", chat_type):
        buttons.append(
            [
                InlineKeyboardButton(
                    await at(at_id, "panel.btn_filters"), callback_data="panel:filters"
                )
            ]
        )

    buttons.append(
        [InlineKeyboardButton(await at(at_id, "panel.btn_back"), callback_data="panel:main")]
    )
    return InlineKeyboardMarkup(buttons)


async def settings_category_kb(
    chat_id: int, user_id: int | None = None, chat_type: str = "supergroup"
) -> InlineKeyboardMarkup:
    at_id = user_id or chat_id
    buttons = []

    # Row 1: Language & Timezone
    row1 = []
    if is_setting_allowed("language", chat_type):
        row1.append(
            InlineKeyboardButton(
                await at(at_id, "panel.btn_language"), callback_data="panel:language:chat"
            )
        )
    if is_setting_allowed("timezone", chat_type):
        row1.append(
            InlineKeyboardButton(
                await at(at_id, "panel.btn_timezone"), callback_data="panel:timezone:0"
            )
        )
    if row1:
        buttons.append(row1)

    # Row 2: Logging & Service Cleaner
    row2 = []
    if is_setting_allowed("logging", chat_type):
        row2.append(
            InlineKeyboardButton(
                await at(at_id, "panel.btn_logging"), callback_data="panel:logging"
            )
        )
    if is_setting_allowed("svc", chat_type):
        row2.append(
            InlineKeyboardButton(
                await at(at_id, "common.service_cleaner"), callback_data="panel:svc:settings"
            )
        )
    if row2:
        buttons.append(row2)

    # Row 3: Admin Management
    buttons.append(
        [
            InlineKeyboardButton(
                await at(at_id, "panel.btn_admins_mgmt"), callback_data="panel:admins_mgmt"
            )
        ]
    )

    buttons.append(
        [InlineKeyboardButton(await at(at_id, "panel.btn_back"), callback_data="panel:main")]
    )
    return InlineKeyboardMarkup(buttons)


async def my_groups_kb(ctx, client, user_id: int, page: int = 0) -> InlineKeyboardMarkup:
    return await chat_picker_kb(ctx, client, user_id, page, channel=False)


async def chat_picker_kb(
    ctx, client, user_id: int, page: int, *, channel: bool
) -> InlineKeyboardMarkup:
    types = [ChatType.CHANNEL] if channel else [ChatType.GROUP, ChatType.SUPERGROUP]
    page_size = 8
    chats, total, page = await get_user_admin_chat_page(
        ctx, client, user_id, types, page=page, page_size=page_size
    )
    list_route = "panel:list_channels" if channel else "panel:list_groups"
    select_route = "panel:select_channel" if channel else "panel:select_chat"
    label_key = "panel.channel_list_item" if channel else "panel.chat_list_item"
    buttons = [
        [
            InlineKeyboardButton(
                await at(user_id, label_key, title=title),
                callback_data=f"{select_route}:{chat_id}:{page}",
            )
        ]
        for chat_id, title in chats
    ]
    if pager := await get_pager(page, total, page_size, list_route):
        buttons.append(pager)
    if not chats:
        empty_key = "panel.channels_empty" if channel else "panel.groups_empty"
        buttons.append(
            [InlineKeyboardButton(await at(user_id, empty_key), callback_data="panel:noop")]
        )
    add_key = "panel.btn_add_to_channel" if channel else "panel.btn_add_to_group"
    start = "startchannel" if channel else "startgroup"
    buttons.append(
        [
            InlineKeyboardButton(
                await at(user_id, add_key), url=f"https://t.me/{client.me.username}?{start}=true"
            )
        ]
    )
    buttons.append(
        [
            InlineKeyboardButton(
                await at(user_id, "panel.btn_back"), callback_data="panel:my_chats"
            ),
            InlineKeyboardButton(await at(user_id, "panel.btn_close"), callback_data="panel:close"),
        ]
    )
    return InlineKeyboardMarkup(buttons)


async def flood_kb(ctx, chat_id: int, user_id: int | None = None) -> InlineKeyboardMarkup:
    at_id = user_id or chat_id
    settings = await get_chat_settings(ctx, chat_id)
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    await at(at_id, "panel.btn_threshold", n=settings.floodThreshold),
                    callback_data="panel:input:floodThreshold",
                ),
                InlineKeyboardButton(
                    await at(at_id, "panel.btn_window", n=settings.floodWindow),
                    callback_data="panel:input:floodWindow",
                ),
            ],
            [
                InlineKeyboardButton(
                    await at(
                        at_id,
                        "panel.change_action",
                        action=await at(at_id, f"action.{settings.floodAction.lower()}"),
                    ),
                    callback_data="panel:action:floodAction:0",
                ),
            ],
            [
                InlineKeyboardButton(
                    await at(at_id, "help.btn_antiflood"), callback_data="help:setting:flood"
                )
            ],
            [
                InlineKeyboardButton(
                    await at(at_id, "panel.btn_back"), callback_data="panel:category:security"
                )
            ],
        ]
    )


async def welcome_kb(
    ctx, chat_id: int, user_id: int | None = None, back_callback: str = "panel:category:greetings"
) -> InlineKeyboardMarkup:
    at_id = user_id or chat_id
    settings = await get_chat_settings(ctx, chat_id)
    sw = await at(
        at_id, "panel.status_enabled" if settings.welcomeEnabled else "panel.status_disabled"
    )
    sg = await at(
        at_id, "panel.status_enabled" if settings.goodbyeEnabled else "panel.status_disabled"
    )
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    await at(at_id, "panel.btn_welcome_toggle", status=sw),
                    callback_data="panel:tgs:welcomeEnabled",
                ),
                InlineKeyboardButton(
                    await at(at_id, "panel.btn_goodbye_toggle", status=sg),
                    callback_data="panel:tgs:goodbyeEnabled",
                ),
            ],
            [
                InlineKeyboardButton(
                    await at(at_id, "panel.btn_set_welcome"),
                    callback_data="panel:input:welcomeText",
                ),
            ],
            [InlineKeyboardButton(await at(at_id, "panel.btn_back"), callback_data=back_callback)],
        ]
    )


async def rules_kb(
    chat_id: int, user_id: int | None = None, back_callback: str = "panel:category:greetings"
) -> InlineKeyboardMarkup:
    at_id = user_id or chat_id
    from src.core.context import get_context
    from src.db.repositories.rules import get_rules

    ctx = get_context()
    rules = await get_rules(ctx, chat_id)
    private_mode = rules.privateMode if rules else False

    status_key = "panel.status_enabled" if private_mode else "panel.status_disabled"
    status = await at(at_id, status_key)

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    await at(at_id, "panel.btn_rules_private_toggle", status=status),
                    callback_data="panel:toggle_private_rules",
                ),
            ],
            [
                InlineKeyboardButton(
                    await at(at_id, "panel.btn_set_rules"),
                    callback_data="panel:input:rulesText",
                ),
            ],
            [InlineKeyboardButton(await at(at_id, "panel.btn_back"), callback_data=back_callback)],
        ]
    )


async def filters_menu_kb(
    ctx,
    chat_id: int,
    page: int = 0,
    user_id: int | None = None,
    back_callback: str = "panel:category:greetings",
) -> InlineKeyboardMarkup:
    at_id = user_id or chat_id
    from src.db.repositories.filters import get_filters_count, get_filters_paginated

    page_size = 10
    total_count = await get_filters_count(ctx, chat_id)
    filters_list = await get_filters_paginated(ctx, chat_id, page, page_size)

    buttons = [
        [
            InlineKeyboardButton(
                await at(at_id, "panel.btn_add_filter"), callback_data=f"panel:add_filter:{page}"
            )
        ]
    ]

    buttons.extend(
        [
            InlineKeyboardButton(
                f"📜 {f.keyword}", callback_data=f"panel:edit_filter:{f.id}:{page}"
            ),
            InlineKeyboardButton(
                "🗑️",
                callback_data=f"panel:delete_filter:{f.id}:{page}",
            ),
        ]
        for f in filters_list
    )

    if nav := await get_pager(page, total_count, page_size, "panel:filters"):
        buttons.append(nav)

    if total_count > 0:
        buttons.append(
            [
                InlineKeyboardButton(
                    await at(at_id, "panel.btn_clear_filters"), callback_data="panel:clear_filters"
                )
            ]
        )

    buttons.append(
        [InlineKeyboardButton(await at(at_id, "panel.btn_back"), callback_data=back_callback)]
    )
    return InlineKeyboardMarkup(buttons)


async def ai_security_kb(
    ctx, chat_id: int, user_id: int, back_callback: str = "panel:category:security"
) -> InlineKeyboardMarkup:
    """Keyboard for AI Security settings."""
    from src.db.repositories.ai_guard import get_ai_guard_settings

    s = await get_ai_guard_settings(ctx, chat_id)
    status_icon = "✅" if s.isTextEnabled else "❌"
    img_status_icon = "✅" if s.isImageEnabled else "❌"
    action_label = await at(user_id, f"action.{s.action}")

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_ai_guard_toggle", status=status_icon),
                    callback_data="panel:toggle_ai_guard",
                )
            ],
            [
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_ai_image_guard_toggle", status=img_status_icon),
                    callback_data="panel:toggle_ai_image_guard",
                )
            ],
            [
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_set_groq_key"),
                    callback_data="panel:set_groq_key",
                ),
                InlineKeyboardButton(
                    await at(user_id, "common.btn_action", action=action_label),
                    callback_data="panel:cycle_ai_guard_action",
                ),
            ],
            [
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_ai_guard_setup"),
                    callback_data="panel:ai_guard_setup",
                )
            ],
            [
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_back"), callback_data=back_callback
                )
            ],
        ]
    )


async def filter_options_kb(ctx, chat_id: int, user_id: int, page: int) -> InlineKeyboardMarkup:
    """Keyboard for the third step of the filter creation wizard (Settings)."""
    from src.utils.local_cache import get_cache

    r = get_cache()
    settings_raw = await r.get(f"temp_filter_settings:{user_id}")
    import json

    settings = json.loads(settings_raw) if settings_raw else {}

    match_mode = settings.get("matchMode", "contains")
    case_sensitive = settings.get("caseSensitive", False)
    is_admin_only = settings.get("isAdminOnly", False)

    buttons = []

    admin_btn_key = (
        "panel.btn_filter_admins_only" if is_admin_only else "panel.btn_filter_all_users"
    )
    buttons.append(
        [
            InlineKeyboardButton(
                await at(user_id, admin_btn_key),
                callback_data=f"panel:toggle_filter:admin:{page}",
            )
        ]
    )

    # Case Sensitive Toggle
    case_btn_key = (
        "panel.btn_filter_case_sensitive" if case_sensitive else "panel.btn_filter_case_insensitive"
    )
    buttons.append(
        [
            InlineKeyboardButton(
                await at(user_id, case_btn_key),
                callback_data=f"panel:toggle_filter:case:{page}",
            )
        ]
    )

    # Match Mode Toggle
    match_btn_key = (
        "panel.btn_filter_match_full" if match_mode == "full" else "panel.btn_filter_match_contains"
    )
    buttons.append(
        [
            InlineKeyboardButton(
                await at(user_id, match_btn_key), callback_data=f"panel:toggle_filter:match:{page}"
            )
        ]
    )

    # Save & Cancel
    buttons.append(
        [
            InlineKeyboardButton(
                await at(user_id, "common.btn_save"), callback_data=f"panel:save_filter:{page}"
            ),
            InlineKeyboardButton(
                await at(user_id, "common.btn_cancel"), callback_data=f"panel:filters:{page}"
            ),
        ]
    )

    return InlineKeyboardMarkup(buttons)


async def channels_menu_kb(ctx, client, user_id: int, page: int = 0) -> InlineKeyboardMarkup:
    return await chat_picker_kb(ctx, client, user_id, page, channel=True)


async def admins_management_kb(
    chat_id: int, user_id: int, page: int, total: int, page_size: int
) -> InlineKeyboardMarkup:
    buttons = []
    if pager := await get_pager(page, total, page_size, "panel:admins_mgmt"):
        buttons.append(pager)
    buttons.append(
        [
            InlineKeyboardButton(
                await at(user_id, "panel.btn_refresh_admins"),
                callback_data=f"panel:admins_refresh:{chat_id}:{page}",
            )
        ]
    )
    buttons.append(
        [
            InlineKeyboardButton(
                await at(user_id, "panel.btn_back"), callback_data="panel:category:settings"
            )
        ]
    )
    return InlineKeyboardMarkup(buttons)
