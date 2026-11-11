from datetime import date
from rackpulse.analysis import analyze_rack
from rackpulse.config import RackConfig
from rackpulse.timewindow import day_window
from rackpulse.report_model import normalize_event


def test_synthetic_november_09_10_day_and_total_are_separate():
    rack=RackConfig('r','.*','delta')
    first=analyze_rack(rack, [], day_window(date(2026,11,9)), [])
    second=analyze_rack(rack, [], day_window(date(2026,11,10)), [], previous_state=first['rule_state'])
    e=next(e for e in second['events'] if e['type']=='monitoring_missing')
    assert e['day_duration_minutes']==1440
    assert e['total_duration_minutes']==2880
    assert e['first_occurred_at']=='2026-11-09T00:00:00+08:00'


def test_legacy_query_error_is_unknown_not_all_day():
    old={'type':'datasource_error','started_at':'2026-11-09T00:00:00+00:00','duration_minutes':1440,'recovered_at':None}
    e=normalize_event(old,date(2026,11,9))
    assert e['day_duration_minutes'] is None
    assert old['duration_minutes']==1440


def test_unknown_tail_keeps_first_occurrence_without_counting_unknown():
    rack=RackConfig('r','.*','delta')
    w=day_window(date(2026,11,9))
    unknown=[(metric,w.timestamps[-1],int(w.end.timestamp())) for metric in ('gpu_utilization','gpu_power','psu_power')]
    first=analyze_rack(rack,[],w,[],unknown_windows=unknown)
    state=first['rule_state']['monitoring_missing|']
    assert state['day_duration_minutes']==1439
    assert state['recovered_at'] is None
    second=analyze_rack(rack,[],day_window(date(2026,11,10)),[],previous_state=first['rule_state'])
    e=next(e for e in second['events'] if e['type']=='monitoring_missing')
    assert e['total_duration_minutes']==2879
    assert e['first_occurred_at']=='2026-11-09T00:00:00+08:00'
