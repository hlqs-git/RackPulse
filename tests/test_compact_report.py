from copy import deepcopy
from datetime import date
from rackpulse.report import render_report, notification_events, split_notification


def event(host='n1', gpu=0, minutes=5, severity='Warning', kind='gpu_device_missing'):
    return dict(rack_id='GB200-1-1', device=f'GB200-1-1/{host}/GPU_{gpu}', type=kind, severity=severity, started_at='2026-11-09T01:00:00+08:00', recovered_at='2026-11-09T01:05:00+08:00', duration_minutes=minutes)


def summary():
    return dict(rack_id='GB200-1-1', psu_vendor='delta', gpu_count=72, psu_count=48, gpu_completeness=1, psu_completeness=1, missing_minutes=0, valid_gpu_minutes=103680, gpu_average_utilization=50, power={s: dict(minutes=1440 if s=='full_psu' else 0, average_watts=60000 if s=='full_psu' else None, maximum_watts=70000 if s=='full_psu' else None, energy_kwh=1440 if s=='full_psu' else 0) for s in ('full_psu','partial_psu','gpu_proxy')}, events=[], full_psu_device_sets=[['p']])


def test_group_node_then_rack_without_mutating_details():
    events = [event(gpu=i) for i in range(4)]
    original = deepcopy(events)
    grouped = notification_events(events)
    assert len(grouped) == 1 and grouped[0]['type'] == 'node_collection_missing'
    assert grouped[0]['affected_devices'] == 4
    assert events == original
    grouped = notification_events(events + [event('n2', i) for i in range(4)])
    assert len(grouped) == 1 and grouped[0]['type'] == 'rack_collection_missing'
    assert grouped[0]['affected_nodes'] == 2


def test_short_missing_hidden_but_critical_retained():
    assert notification_events([event(minutes=1)]) == []
    assert len(notification_events([event(minutes=1, severity='Critical')])) == 1


def test_short_missing_affects_quality_only_and_single_gpu_not_promoted():
    s = summary()
    s['events'] = [event(minutes=1)]
    text = render_report(date(2026,11,9), [s])
    assert '监控异常 0' in text
    assert '短缺采' in text
    assert notification_events([event()])[0]['type'] == 'gpu_device_missing'


def test_compact_table_units_and_top_ten():
    s = summary()
    s['events'] = [dict(event(kind='datasource_error'), started_at=f'2026-11-09T{i:02}:00:00+08:00', severity='Critical') for i in range(12)]
    text = render_report(date(2026,11,9), [s])
    assert '60.0' in text and '1.440' in text
    assert 'kW' in text and 'MWh' in text
    assert '0.000' not in text
    assert '监控异常' in text and '硬件故障' not in text
    assert 'Critical' in text and '12' in text
    assert sum(line.startswith('! ') for line in text.splitlines()) <= 10
    assert len(s['events']) == 12


def test_utf8_chunks_preserve_lines_and_content():
    text = '\n'.join(['中文行'*40]*40)
    parts = split_notification(text, max_bytes=1000)
    assert all(len(p.encode()) <= 1000 for p in parts)
    assert '\n'.join(parts) == text
