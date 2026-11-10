import os
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.plugins.scheduler.manager import SchedulerManager
from src.plugins.scheduler.repository import SchedulerRepository


def context():
    return SimpleNamespace(scheduler=AsyncIOScheduler(timezone=ZoneInfo("Asia/Jerusalem")))


async def test_initial_shabbat_sync_is_aware_and_not_duplicated_per_group(mocker):
    ctx = context()
    ctx.scheduler.start(paused=True)
    for name in (
        "get_active_timed_actions",
        "get_active_reminders",
        "get_active_night_locks",
        "get_active_group_cleaners",
    ):
        mocker.patch.object(SchedulerRepository, name, new_callable=AsyncMock, return_value=[])
    mocker.patch.object(
        SchedulerRepository, "get_all_group_settings", new_callable=AsyncMock, return_value={}
    )
    mocker.patch.object(
        SchedulerRepository,
        "get_active_shabbat_locks",
        new_callable=AsyncMock,
        return_value=[SimpleNamespace(chatId=-i) for i in range(1, 51)],
    )
    before = datetime.now(UTC)
    await SchedulerManager.sync_all(ctx)
    jobs = [
        job for job in ctx.scheduler.get_jobs() if job.trigger.__class__.__name__ == "DateTrigger"
    ]
    assert len(jobs) == 1
    run_date = jobs[0].trigger.run_date
    assert before <= run_date <= datetime.now(UTC)
    # Repeat initialization replaces the same job instead of accumulating refreshes.
    await SchedulerManager.sync_all(ctx)
    assert (
        len(
            [
                job
                for job in ctx.scheduler.get_jobs()
                if job.trigger.__class__.__name__ == "DateTrigger"
            ]
        )
        == 1
    )

    ctx.scheduler.shutdown(wait=False)


async def test_group_shabbat_sync_uses_an_immediate_aware_date(mocker):
    ctx = context()
    mocker.patch.object(
        SchedulerRepository,
        "get_group_data",
        new_callable=AsyncMock,
        return_value=("Asia/Jerusalem", [], None, object(), None),
    )
    before = datetime.now(UTC)
    await SchedulerManager.sync_group(ctx, -123)
    run_date = ctx.scheduler.get_job("shabbat_sync:-123").trigger.run_date
    assert before <= run_date <= datetime.now(UTC)


async def test_timed_action_delay_is_independent_of_machine_timezone():
    ctx = context()
    old_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "Asia/Jerusalem"
        time.tzset()
        before = datetime.now(UTC).timestamp()
        SchedulerManager.schedule_timed_action(ctx, -123, 456, "mute", 60)
        run_date = ctx.scheduler.get_job("lift_mute:-123:456").trigger.run_date
        assert 59 <= run_date.timestamp() - before <= 61
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()


async def test_clearing_group_jobs_does_not_remove_similarly_numbered_groups():
    ctx = context()

    async def task():
        pass

    for job_id in [
        "cleaner:-123",
        "cleaner:-1234",
        "shabbat_lock:-1234:123456",
        "lift_mute:-123:456",
        "lift_mute:-1234:456",
        "global_shabbat_sync",
    ]:
        ctx.scheduler.add_job(task, trigger="interval", hours=1, id=job_id)
    SchedulerManager.clear_group_jobs(ctx, -123)
    assert {job.id for job in ctx.scheduler.get_jobs()} == {
        "cleaner:-1234",
        "shabbat_lock:-1234:123456",
        "lift_mute:-1234:456",
        "global_shabbat_sync",
    }


async def test_sync_unknown_group_is_a_noop(db_engine):
    ctx = context()
    ctx.db = async_sessionmaker(db_engine, expire_on_commit=False)
    await SchedulerManager.sync_group(ctx, -99999)
    assert ctx.scheduler.get_jobs() == []
