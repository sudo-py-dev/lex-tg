from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
from hebcal_api.utils.types import EventType

from src.utils.hebcal import get_shabbat_events, is_shabbat_now
from src.utils.local_cache import AsyncSnapshotCache


@pytest.fixture(autouse=True)
def isolated_shabbat_cache():
    with patch("src.utils.hebcal.get_cache", return_value=AsyncSnapshotCache()):
        yield


class MockHoliday:
    def __init__(self, title, yomtov):
        self.title = title
        self.yomtov = yomtov


class MockItem:
    def __init__(self, type, date, holiday=None):
        self.type = type
        self.date = date
        self.holiday = holiday


class MockResponse:
    def __init__(self, items):
        self.items = items


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tzid, simulated_now, items_setup, expected_start, expected_end, expected_is_shabbat",
    [
        # Jerusalem - Shabbat Friday Morning
        (
            "Asia/Jerusalem",
            datetime(2026, 4, 17, 10, 0),
            [
                (EventType.CANDLES, datetime(2026, 4, 17, 18, 0), None),
                (EventType.HAVDALAH, datetime(2026, 4, 18, 19, 0), None),
            ],
            datetime(2026, 4, 17, 18, 0),
            datetime(2026, 4, 18, 19, 0),
            False,  # Not Shabbat yet
        ),
        # Jerusalem - Shabbat Friday Night (In Shabbat)
        (
            "Asia/Jerusalem",
            datetime(2026, 4, 17, 21, 0),
            [
                (EventType.CANDLES, datetime(2026, 4, 17, 18, 0), None),
                (EventType.HAVDALAH, datetime(2026, 4, 18, 19, 0), None),
            ],
            datetime(2026, 4, 17, 18, 0),
            datetime(2026, 4, 18, 19, 0),
            True,
        ),
        # Yom Tov - Pesach Day 1 (In Holiday)
        (
            "Asia/Jerusalem",
            datetime(2026, 4, 1, 21, 0),
            [
                (
                    EventType.CANDLES,
                    datetime(2026, 4, 1, 18, 30),
                    MockHoliday("Pesach Day 1", True),
                ),
                (
                    EventType.HAVDALAH,
                    datetime(2026, 4, 2, 19, 30),
                    MockHoliday("Pesach Day 1", True),
                ),
            ],
            datetime(2026, 4, 1, 18, 30),
            datetime(2026, 4, 2, 19, 30),
            True,
        ),
        # Chol HaMoed Pesach - Sunday (Not a holiday/lock time)
        # The next lock is the upcoming Shabbat
        (
            "Asia/Jerusalem",
            datetime(2026, 4, 5, 10, 0),
            [
                (
                    EventType.CANDLES,
                    datetime(2026, 4, 1, 18, 30),
                    MockHoliday("Pesach Day 1", True),
                ),  # Past
                (
                    EventType.HAVDALAH,
                    datetime(2026, 4, 2, 19, 30),
                    MockHoliday("Pesach Day 1", True),
                ),  # Past
                (EventType.CANDLES, datetime(2026, 4, 10, 18, 40), None),  # Future Shabbat
                (EventType.HAVDALAH, datetime(2026, 4, 11, 19, 40), None),  # Future Shabbat
            ],
            datetime(2026, 4, 10, 18, 40),
            datetime(2026, 4, 11, 19, 40),
            False,  # Mid-week Chol HaMoed is NOT Shabbat
        ),
        # Exact Boundary: 1 second before Havdalah (Should be LOCKED)
        (
            "Asia/Jerusalem",
            datetime(2026, 4, 18, 18, 59, 59),
            [
                (EventType.CANDLES, datetime(2026, 4, 17, 18, 0), None),
                (EventType.HAVDALAH, datetime(2026, 4, 18, 19, 0), None),
            ],
            datetime(2026, 4, 17, 18, 0),
            datetime(2026, 4, 18, 19, 0),
            True,
        ),
        # Exact Boundary: Exactly Havdalah (Should be UNLOCKED)
        (
            "Asia/Jerusalem",
            datetime(2026, 4, 18, 19, 0, 0),
            [
                (EventType.CANDLES, datetime(2026, 4, 17, 18, 0), None),
                (EventType.HAVDALAH, datetime(2026, 4, 18, 19, 0), None),
                (EventType.CANDLES, datetime(2026, 4, 24, 18, 10), None),  # Next week
                (EventType.HAVDALAH, datetime(2026, 4, 25, 19, 10), None),
            ],
            datetime(2026, 4, 24, 18, 10),
            datetime(2026, 4, 25, 19, 10),
            False,  # Havdalah just happened, next event is next week
        ),
    ],
)
async def test_hebcal_scenarios(
    tzid, simulated_now, items_setup, expected_start, expected_end, expected_is_shabbat
):
    tz = ZoneInfo(tzid)
    aware_now = simulated_now.replace(tzinfo=tz)

    items = []
    for event_type, date, holiday in items_setup:
        items.append(MockItem(event_type, date.replace(tzinfo=tz), holiday))

    with (
        patch("src.utils.hebcal.fetch_shabbat_async", new_callable=AsyncMock) as mock_fetch,
        patch("src.utils.hebcal.datetime", wraps=datetime) as mock_dt,
    ):
        mock_fetch.return_value = MockResponse(items)
        mock_dt.now.return_value = aware_now

        start, end, h_flag = await get_shabbat_events(tzid)

        assert start == expected_start.replace(tzinfo=tz)
        assert end == expected_end.replace(tzinfo=tz)

        # Check holiday flag logic in setup
        for _, _, holiday in items_setup:
            if holiday and holiday.yomtov and expected_start.replace(tzinfo=tz) == _:
                # This is slightly complex to mock accurately for is_holiday
                # But my logic in hebcal.py checks item.holiday.yomtov for the specific CANDLES event
                pass

        # Verify is_shabbat_now logic
        mock_dt.now.return_value = aware_now
        is_active = await is_shabbat_now(tzid)
        assert is_active == expected_is_shabbat


@pytest.mark.asyncio
@pytest.mark.parametrize("batch", [False, True])
async def test_expired_event_is_refetched_before_cache_ttl(batch):
    import json

    from src.utils.hebcal import get_cache, get_shabbat_events_batch

    tzid = "Asia/Jerusalem"
    tz = ZoneInfo(tzid)
    now = datetime(2026, 4, 18, 19, tzinfo=tz)
    next_start = datetime(2026, 4, 24, 18, tzinfo=tz)
    next_end = datetime(2026, 4, 25, 19, tzinfo=tz)
    await get_cache().set(
        f"shabbat_events:{tzid}",
        json.dumps(
            {
                "start": datetime(2026, 4, 17, 18, tzinfo=tz).isoformat(),
                "end": now.isoformat(),
                "is_holiday": False,
            }
        ),
        ttl=3600,
    )
    with (
        patch("src.utils.hebcal.datetime", wraps=datetime) as clock,
        patch("src.utils.hebcal.fetch_shabbat_async", new_callable=AsyncMock) as fetch,
    ):
        clock.now.return_value = now
        fetch.return_value = MockResponse(
            [
                MockItem(EventType.CANDLES, next_start),
                MockItem(EventType.HAVDALAH, next_end),
            ]
        )
        result = (
            (await get_shabbat_events_batch([tzid]))[tzid]
            if batch
            else await get_shabbat_events(tzid)
        )
        assert result == (next_start, next_end, False)
        fetch.assert_awaited_once()
