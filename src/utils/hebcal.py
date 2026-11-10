import asyncio
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from hebcal_api import ShabbatRequest, fetch_shabbat_async
from hebcal_api.utils.types import EventType
from loguru import logger

from src.utils.local_cache import get_cache

# Cache TTL for Shabbat times
_SHABBAT_CACHE_TTL_NORMAL = 12 * 60 * 60  # 12 hours - normal days
_SHABBAT_CACHE_TTL_SHABBAT = 60 * 60  # 1 hour - Friday/Shabbat for real-time accuracy


def _get_shabbat_cache_ttl(tzid: str) -> int:
    """Get appropriate cache TTL based on current day.

    Use short TTL (1 hour) on Friday (Yom Shishi) and Shabbat
    for real-time accuracy. Use long TTL (12 hours) on other days.
    """
    try:
        from zoneinfo import ZoneInfo

        target_tz = ZoneInfo(tzid)
        now = datetime.now(target_tz)
        # weekday(): 0=Monday, 4=Friday, 5=Saturday
        if now.weekday() in (4, 5):  # Friday or Saturday
            return _SHABBAT_CACHE_TTL_SHABBAT
    except Exception:
        pass
    return _SHABBAT_CACHE_TTL_NORMAL


async def get_shabbat_events(
    tzid: str,
) -> tuple[datetime | None, datetime | None, bool]:
    """
    Fetches the Shabbat/Holiday entrance and exit times relevant to the current time.
    Results are cached by timezone to avoid rate limits from repeated API calls.
    Returns (start_time, end_time, is_holiday).
    """
    cache = get_cache()
    cache_key = f"shabbat_events:{tzid}"

    # Try to get from cache first
    try:
        cached_data = await cache.get(cache_key)
        if cached_data:
            data = json.loads(cached_data)
            start_str = data.get("start")
            end_str = data.get("end")
            is_holiday = data.get("is_holiday", False)

            if start_str and end_str:
                target_tz = ZoneInfo(tzid)
                cached_start = datetime.fromisoformat(start_str).replace(tzinfo=target_tz)
                cached_end = datetime.fromisoformat(end_str).replace(tzinfo=target_tz)
                if cached_end > datetime.now(target_tz):
                    logger.debug(f"Shabbat times for {tzid} served from cache")
                    return cached_start, cached_end, is_holiday
    except Exception as e:
        logger.debug(f"Cache read error for {tzid}: {e}")

    # Fetch from API if not in cache
    try:
        city = tzid.split("/")[-1].replace("_", " ") if "/" in tzid else tzid
        request = ShabbatRequest(city=city, tzid=tzid, c="on", s="on")
        response = await fetch_shabbat_async(request)
    except Exception:
        # Fallback to Jerusalem if the provided city/timezone is invalid
        try:
            tzid = "Asia/Jerusalem"
            request = ShabbatRequest(city="Jerusalem", tzid=tzid, c="on", s="on")
            response = await fetch_shabbat_async(request)
        except Exception:
            return None, None, False

    target_tz = ZoneInfo(tzid)
    now = datetime.now(target_tz)

    start_time: datetime | None = None
    end_time: datetime | None = None
    is_holiday = False

    for item in response.items:
        if item.type == EventType.HAVDALAH and item.date > now:
            end_time = item.date
            break

    if not end_time:
        return None, None, False

    for item in response.items:
        if item.type == EventType.CANDLES and item.date < end_time:
            start_time = item.date
            if item.holiday and item.holiday.yomtov:
                is_holiday = True

    # Store in cache with dynamic TTL based on day of week
    if start_time and end_time:
        try:
            cache_data = {
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
                "is_holiday": is_holiday,
            }
            ttl = _get_shabbat_cache_ttl(tzid)
            await cache.setex(cache_key, ttl, json.dumps(cache_data))
            logger.debug(
                f"Shabbat times for {tzid} cached for {ttl}s ({'short' if ttl < 3600 else 'long'})"
            )
        except Exception as e:
            logger.debug(f"Cache write error for {tzid}: {e}")

    return start_time, end_time, is_holiday


async def get_shabbat_events_batch(
    tzids: list[str],
) -> dict[str, tuple[datetime | None, datetime | None, bool]]:
    """
    Batch fetch Shabbat events for multiple timezones efficiently.
    Deduplicates timezones and uses cache to minimize API calls.
    Returns a dict mapping tzid -> (start_time, end_time, is_holiday).
    """
    cache = get_cache()
    unique_tzids = set(tzids)
    results: dict[str, tuple[datetime | None, datetime | None, bool]] = {}
    tzids_to_fetch: list[str] = []

    # Check cache for all unique timezones first
    for tzid in unique_tzids:
        cache_key = f"shabbat_events:{tzid}"
        try:
            cached_data = await cache.get(cache_key)
            if cached_data:
                data = json.loads(cached_data)
                start_str = data.get("start")
                end_str = data.get("end")
                is_holiday = data.get("is_holiday", False)

                if start_str and end_str:
                    target_tz = ZoneInfo(tzid)
                    cached_start = datetime.fromisoformat(start_str).replace(tzinfo=target_tz)
                    cached_end = datetime.fromisoformat(end_str).replace(tzinfo=target_tz)
                    if cached_end > datetime.now(target_tz):
                        results[tzid] = (cached_start, cached_end, is_holiday)
                        logger.debug(f"Batch: Shabbat times for {tzid} served from cache")
                        continue
        except Exception as e:
            logger.debug(f"Batch cache read error for {tzid}: {e}")

        tzids_to_fetch.append(tzid)

    # Fetch remaining timezones from API
    if tzids_to_fetch:
        logger.info(f"Batch fetching Shabbat times for {len(tzids_to_fetch)} unique timezones")

    for tzid in tzids_to_fetch:
        result = await _fetch_single_timezone(tzid)
        results[tzid] = result

        # Small delay between requests to avoid rate limiting
        if len(tzids_to_fetch) > 1:
            await asyncio.sleep(0.5)

    return results


async def _fetch_single_timezone(
    tzid: str,
) -> tuple[datetime | None, datetime | None, bool]:
    """Fetch Shabbat events for a single timezone and cache the result."""
    cache = get_cache()
    cache_key = f"shabbat_events:{tzid}"

    try:
        city = tzid.split("/")[-1].replace("_", " ") if "/" in tzid else tzid
        request = ShabbatRequest(city=city, tzid=tzid, c="on", s="on")
        response = await fetch_shabbat_async(request)
    except Exception:
        # Fallback to Jerusalem if the provided city/timezone is invalid
        try:
            tzid = "Asia/Jerusalem"
            request = ShabbatRequest(city="Jerusalem", tzid=tzid, c="on", s="on")
            response = await fetch_shabbat_async(request)
        except Exception:
            return None, None, False

    target_tz = ZoneInfo(tzid)
    now = datetime.now(target_tz)

    start_time: datetime | None = None
    end_time: datetime | None = None
    is_holiday = False

    for item in response.items:
        if item.type == EventType.HAVDALAH and item.date > now:
            end_time = item.date
            break

    if not end_time:
        return None, None, False

    for item in response.items:
        if item.type == EventType.CANDLES and item.date < end_time:
            start_time = item.date
            if item.holiday and item.holiday.yomtov:
                is_holiday = True

    # Store in cache with dynamic TTL based on day of week
    if start_time and end_time:
        try:
            cache_data = {
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
                "is_holiday": is_holiday,
            }
            ttl = _get_shabbat_cache_ttl(tzid)
            await cache.setex(cache_key, ttl, json.dumps(cache_data))
            logger.debug(
                f"Cached Shabbat times for {tzid} ({'short' if ttl < 3600 else 'long'} TTL)"
            )
        except Exception as e:
            logger.debug(f"Cache write error for {tzid}: {e}")

    return start_time, end_time, is_holiday


async def is_shabbat_now(tzid: str) -> bool:
    """Checks if it is currently Shabbat or a Holiday in the given timezone."""
    start, end, _ = await get_shabbat_events(tzid)
    if not start or not end:
        return False

    try:
        target_tz = ZoneInfo(tzid)
    except Exception:
        # Fallback to Jerusalem if tzid is invalid
        target_tz = ZoneInfo("Asia/Jerusalem")

    now = datetime.now(target_tz)
    return start <= now < end
