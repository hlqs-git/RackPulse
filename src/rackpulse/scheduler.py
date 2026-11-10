from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from .timewindow import TZ


def make_scheduler(callback):
    scheduler = AsyncIOScheduler(timezone=TZ)
    async def daily():
        await callback((datetime.now(TZ)-timedelta(days=1)).date())
    scheduler.add_job(daily, 'cron', hour=8, minute=0, id='daily', max_instances=1, coalesce=True, misfire_grace_time=3600)
    return scheduler
