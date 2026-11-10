from datetime import date
from rackpulse.analysis import analyze_rack
from rackpulse.config import RackConfig
from rackpulse.domain import DeviceSample
from rackpulse.timewindow import day_window


def test_power_increase_requires_compatible_baseline():
    w = day_window(date(2026, 11, 9))
    r = RackConfig('r', '.*', 'delta', expected_psu=1)
    data = [DeviceSample('psu_power', 'p0', t, 1400) for t in w.timestamps]
    history = [{'psu_vendor': 'delta', 'full_psu_device_sets': [['p0']], 'power': {'full_psu': {'minutes': 1440, 'average_watts': 1000}}}]*3
    s = analyze_rack(r, data, w, history)
    assert any(e['type'] == 'power_increase' for e in s['events'])
    assert not any(e['type'] == 'power_increase' for e in analyze_rack(r, data, w, history[:2])['events'])


def test_load_duration_threshold():
    w = day_window(date(2026, 11, 9))
    data = [DeviceSample('gpu_utilization', 'g0', t, 80) for t in w.timestamps[:60]]
    r = RackConfig('r', '.*', 'liteon')
    assert any(e['type'] == 'high_load' and e['duration_minutes'] == 60 for e in analyze_rack(r, data, w, [])['events'])
    assert not any(e['type'] == 'high_load' for e in analyze_rack(r, data[:-1], w, [])['events'])
