from datetime import date
from rackpulse.trends import build_trends


def test_missing_history_day_stays_null():
    result=build_trends(date(2026,11,10),[],7)
    assert len(result)==7
    assert result[-1]['day']=='2026-11-10'
    assert result[-1]['full_psu_mwh'] is None
