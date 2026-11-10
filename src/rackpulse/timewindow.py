from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')


@dataclass(frozen=True)
class DayWindow:
    start: datetime
    end: datetime

    @property
    def timestamps(self):
        return list(range(int(self.start.timestamp()), int(self.end.timestamp()), 60))


def day_window(day: date) -> DayWindow:
    start = datetime.combine(day, time(), TZ)
    return DayWindow(start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc))
