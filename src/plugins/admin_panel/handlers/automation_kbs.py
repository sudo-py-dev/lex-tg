import itertools

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from src.db.models import Reminder
from src.utils.i18n import at

from ..repository import get_chat_settings
from ..validation import is_setting_allowed
from .pagination import get_pager


async def automation_category_kb(
    chat_id: int, user_id: int | None = None, chat_type: str = "supergroup"
) -> InlineKeyboardMarkup:
    at_id = user_id or chat_id
    buttons = []

    # Row 1: Reminders & Night Lock
    row1 = []
    if is_setting_allowed("reminders", chat_type):
        row1.append(
            InlineKeyboardButton(
                await at(at_id, "panel.btn_reminders"), callback_data="panel:reminders"
            )
        )
    if is_setting_allowed("chatnightlock", chat_type):
        row1.append(
            InlineKeyboardButton(
                await at(at_id, "panel.btn_nightlock"), callback_data="panel:chatnightlock"
            )
        )
    if row1:
        buttons.append(row1)

    # Row 2: Shabbat Lock
    if is_setting_allowed("chatshabbatlock", chat_type):
        buttons.append(
            [
                InlineKeyboardButton(
                    await at(at_id, "panel.btn_shabbatlock"), callback_data="panel:chatshabbatlock"
                )
            ]
        )

    # Row 3: Group Cleaner
    if is_setting_allowed("cleaner", chat_type):
        buttons.append(
            [
                InlineKeyboardButton(
                    await at(at_id, "panel.btn_group_cleaner"), callback_data="panel:cleaner"
                )
            ]
        )

    if chat_type in ("group", "supergroup"):
        buttons.append(
            [
                InlineKeyboardButton(
                    await at(at_id, "panel.btn_refresh_schedule"),
                    callback_data="panel:refresh_schedule",
                )
            ]
        )
    buttons.append(
        [InlineKeyboardButton(await at(at_id, "panel.btn_back"), callback_data="panel:main")]
    )
    return InlineKeyboardMarkup(buttons)


async def timezone_picker_kb(
    ctx,
    chat_id: int,
    page: int = 0,
    user_id: int | None = None,
    region: str | None = None,
    filter_query: str | None = None,
) -> InlineKeyboardMarkup:
    at_id = user_id or chat_id
    from zoneinfo import available_timezones

    settings = await get_chat_settings(ctx, chat_id)
    current_tz = settings.timezone

    if filter_query:
        import difflib

        q = filter_query.strip().lower().replace(" ", "_")
        scored_tzs = []

        for tz in available_timezones():
            if not ("/" in tz or tz == "UTC"):
                continue

            tz_lower = tz.lower()
            city = tz.split("/")[-1].lower()
            score = 0

            if q == city:
                score = 100
            elif city.startswith(q):
                score = 80
            elif q in city:
                score = 60
            elif q in tz_lower:
                score = 40
            else:
                ratio = difflib.SequenceMatcher(None, q, city).ratio()
                if ratio > 0.6:
                    score = int(ratio * 35)

            if score > 0:
                scored_tzs.append((score, tz))

        scored_tzs.sort(key=lambda x: (-x[0], x[1]))
        tzs = [tz for score, tz in scored_tzs]
    elif region:
        tzs = [
            tz
            for tz in available_timezones()
            if tz.startswith(f"{region}/") or (region == "UTC" and tz == "UTC")
        ]
        tzs.sort()
    else:
        regions = list({tz.split("/")[0] for tz in available_timezones() if "/" in tz})
        if "UTC" not in regions:
            regions.append("UTC")
        regions.sort()

        buttons = [
            [
                InlineKeyboardButton(
                    await at(at_id, "common.btn_search"),
                    callback_data="panel:timezone_search",
                )
            ]
        ]

        buttons.extend(
            [InlineKeyboardButton(r, callback_data=f"panel:timezone_region:{r}:0") for r in row]
            for row in itertools.batched(regions, 2)
        )

        buttons.append(
            [
                InlineKeyboardButton(
                    await at(at_id, "panel.btn_back"), callback_data="panel:category:settings"
                )
            ]
        )
        return InlineKeyboardMarkup(buttons)

    page_size = 20
    start = page * page_size
    end = start + page_size
    chunk = tzs[start:end]

    buttons = []
    buttons.append(
        [
            InlineKeyboardButton(
                await at(at_id, "common.btn_search"), callback_data="panel:timezone_search"
            )
        ]
    )

    buttons.extend(
        [
            InlineKeyboardButton(
                (f"✅ {tz.split('/')[-1].replace('_', ' ')}" if "/" in tz else tz)
                if tz == current_tz
                else (tz.split("/")[-1].replace("_", " ") if "/" in tz else tz),
                callback_data=f"panel:set_tz:{tz}",
            )
            for tz in row
        ]
        for row in itertools.batched(chunk, 3)
    )

    cb_prefix = (
        f"panel:timezone_region:{region}" if region else f"panel:timezone_filter:{filter_query}"
    )
    nav = await get_pager(page, len(tzs), page_size, cb_prefix)
    if nav:
        buttons.append(nav)

    buttons.append(
        [InlineKeyboardButton(await at(at_id, "panel.btn_back"), callback_data="panel:timezone:0")]
    )
    return InlineKeyboardMarkup(buttons)


async def reminders_menu_kb(
    ctx, chat_id: int, user_id: int | None = None, back_callback: str = "panel:category:automation"
) -> InlineKeyboardMarkup:
    at_id = user_id or chat_id
    async with ctx.db() as session:
        result = await session.execute(select(Reminder).where(Reminder.chatId == chat_id))
        reminders = result.scalars().all()

    buttons = [
        [
            InlineKeyboardButton(
                await at(
                    at_id,
                    "panel.btn_reminder_item",
                    id=rem.id,
                    time=rem.sendTime,
                    status=await at(
                        at_id, "panel.status_enabled" if rem.isActive else "panel.status_disabled"
                    ),
                ),
                callback_data=f"panel:toggle_reminder:{rem.id}",
            ),
            InlineKeyboardButton(
                await at(at_id, "common.btn_delete"),
                callback_data=f"panel:delete_reminder:{rem.id}",
            ),
        ]
        for rem in reminders
    ]

    if len(reminders) < 3:
        buttons.append(
            [
                InlineKeyboardButton(
                    await at(at_id, "panel.btn_add_reminder"),
                    callback_data="panel:input:reminderText",
                )
            ]
        )

    buttons.append(
        [InlineKeyboardButton(await at(at_id, "panel.btn_back"), callback_data=back_callback)]
    )
    return InlineKeyboardMarkup(buttons)


async def chatnightlock_menu_kb(
    ctx, chat_id: int, user_id: int | None = None, back_callback: str = "panel:category:automation"
) -> InlineKeyboardMarkup:
    at_id = user_id or chat_id
    from src.db.models import ChatNightLock

    async with ctx.db() as session:
        lock = await session.get(ChatNightLock, chat_id)
        if not lock:
            lock = ChatNightLock(chatId=chat_id)
            session.add(lock)
            await session.commit()

    status = await at(at_id, "panel.status_enabled" if lock.isEnabled else "panel.status_disabled")

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    await at(at_id, "panel.btn_nightlock_toggle", status=status),
                    callback_data="panel:toggle_chatnightlock",
                )
            ],
            [
                InlineKeyboardButton(
                    await at(at_id, "panel.btn_nightlock_start", time=lock.startTime),
                    callback_data="panel:input:chatnightlockStart",
                ),
                InlineKeyboardButton(
                    await at(at_id, "panel.btn_nightlock_end", time=lock.endTime),
                    callback_data="panel:input:chatnightlockEnd",
                ),
            ],
            [InlineKeyboardButton(await at(at_id, "panel.btn_back"), callback_data=back_callback)],
        ]
    )


async def chatshabbatlock_menu_kb(
    ctx, chat_id: int, user_id: int | None = None, back_callback: str = "panel:category:automation"
) -> InlineKeyboardMarkup:
    at_id = user_id or chat_id
    from src.db.models import ChatShabbatLock

    async with ctx.db() as session:
        lock = await session.get(ChatShabbatLock, chat_id)
        if not lock:
            lock = ChatShabbatLock(chatId=chat_id)
            session.add(lock)
            await session.commit()

    status = await at(at_id, "panel.status_enabled" if lock.isEnabled else "panel.status_disabled")

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    await at(at_id, "panel.btn_shabbatlock_toggle", status=status),
                    callback_data="panel:toggle_chatshabbatlock",
                )
            ],
            [InlineKeyboardButton(await at(at_id, "panel.btn_back"), callback_data=back_callback)],
        ]
    )


async def cleaner_menu_kb(
    ctx, chat_id: int, user_id: int | None = None, back_callback: str = "panel:category:automation"
) -> InlineKeyboardMarkup:
    at_id = user_id or chat_id
    from src.db.models import ChatCleaner

    async with ctx.db() as session:
        cleaner = await session.get(ChatCleaner, chat_id)
        if not cleaner:
            cleaner = ChatCleaner(chatId=chat_id)
            session.add(cleaner)
            await session.commit()

    s_del = await at(
        at_id, "panel.status_enabled" if cleaner.cleanDeleted else "panel.status_disabled"
    )
    s_fake = await at(
        at_id, "panel.status_enabled" if cleaner.cleanFake else "panel.status_disabled"
    )

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    await at(at_id, "panel.btn_clean_deleted", status=s_del),
                    callback_data="panel:toggle_cleaner:deleted",
                ),
                InlineKeyboardButton(
                    await at(at_id, "panel.btn_clean_fake", status=s_fake),
                    callback_data="panel:toggle_cleaner:fake",
                ),
            ],
            [
                InlineKeyboardButton(
                    await at(at_id, "panel.btn_clean_inactive", days=cleaner.cleanInactiveDays),
                    callback_data="panel:input:cleanerInactive",
                ),
                InlineKeyboardButton(
                    await at(at_id, "panel.btn_clean_time", time=cleaner.cleanerRunTime),
                    callback_data="panel:input:cleanerRunTime",
                ),
            ],
            [InlineKeyboardButton(await at(at_id, "panel.btn_back"), callback_data=back_callback)],
        ]
    )
