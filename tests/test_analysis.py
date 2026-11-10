from datetime import date
import pytest
from rackpulse.analysis import analyze_rack
from rackpulse.config import RackConfig
from rackpulse.domain import DeviceSample
from rackpulse.timewindow import day_window


def test_power_sources_are_integrated_separately():
    w = day_window(date(2026, 11, 9))
    rack = RackConfig('GB200-1-1', 'node.*', 'delta')
    samples = [DeviceSample('psu_power', f'p{i}', t, 1250) for t in w.timestamps[:60] for i in range(48)]
    samples += [DeviceSample('gpu_power', 'g0', w.timestamps[60], 600)]
    result = analyze_rack(rack, samples, w, [])
    assert result['power']['full_psu']['energy_kwh'] == pytest.approx(60)
    assert result['power']['gpu_proxy']['energy_kwh'] == pytest.approx(.01)
    assert result['psu_completeness'] == pytest.approx(60/1440)
    assert result['missing_minutes'] == 1379


def test_zero_is_valid_but_invalid_samples_are_excluded():
    w = day_window(date(2026, 11, 9))
    result = analyze_rack(RackConfig('r', '.*', 'liteon'), [
        DeviceSample('gpu_utilization', 'g0', w.timestamps[0], 0),
        DeviceSample('gpu_utilization', 'g1', w.timestamps[0], float('nan')),
        DeviceSample('psu_power', 'p0', w.timestamps[0], -1),
    ], w, [])
    assert result['gpu_average_utilization'] == 0
    assert result['gpu_count'] == 1
    assert result['psu_count'] == 0
    assert result['gpu_completeness'] == pytest.approx(1/(72*1440))


def test_missing_interval_is_critical_and_open():
    w = day_window(date(2026, 11, 9))
    result = analyze_rack(RackConfig('r', '.*', 'delta'), [], w, [])
    event = next(e for e in result['events'] if e['type'] == 'monitoring_missing')
    assert event['severity'] == 'Critical'
    assert event['duration_minutes'] == 1440
    assert event['recovered_at'] is None
