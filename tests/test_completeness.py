import io
import logging
import json
from datetime import date
from rackpulse.logging import configure_logging
from rackpulse.analysis import analyze_rack
from rackpulse.domain import DeviceSample
from rackpulse.config import RackConfig
from rackpulse.timewindow import day_window


def test_gpu_power_stats_and_device_missing_intervals():
    w = day_window(date(2026, 11, 9))
    samples = [DeviceSample('gpu_power', 'g0', w.timestamps[0], 600), DeviceSample('gpu_utilization', 'g0', w.timestamps[0], 50)]
    s = analyze_rack(RackConfig('r', '.*', 'delta'), samples, w, [])
    assert s['gpu_average_power_watts'] == 600
    assert any(e.get('device') == 'g0' and e['type'] == 'gpu_device_missing' for e in s['events'])
    assert s['power_baseline_status'] == 'insufficient_history'


def test_json_logs_never_include_exception_secret(monkeypatch):
    monkeypatch.setenv('FEISHU_WEBHOOK_URL', 'https://secret.example/token')
    stream = io.StringIO()
    logger = configure_logging(stream)
    try:
        raise ValueError('https://secret.example/token')
    except ValueError:
        logger.exception('source_failed https://secret.example/token')
    result = stream.getvalue()
    assert 'secret.example' not in result
    assert json.loads(result)['event'].startswith('source_failed')
