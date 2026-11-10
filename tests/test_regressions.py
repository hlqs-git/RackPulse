import asyncio
from datetime import date
from rackpulse.jobs import DailyJob
from rackpulse.config import AppConfig, RackConfig
from rackpulse.repository import Repository
from rackpulse.notifications import DeliveryService
from rackpulse.domain import DeviceSample
from rackpulse.analysis import analyze_rack
from rackpulse.timewindow import day_window
from rackpulse.report import render_report


def test_subthreshold_outage_continues_across_midnight():
    rack = RackConfig('r', '.*', 'delta', 1, 1)
    first = day_window(date(2026, 11, 8))
    data = [DeviceSample('gpu_utilization', 'g0', t, 50) for t in first.timestamps[:-5]]
    s = analyze_rack(rack, data, first, [])
    assert not any(e['type'] == 'monitoring_missing' for e in s['events'])
    second = day_window(date(2026, 11, 9))
    data = [DeviceSample('gpu_utilization', 'g0', t, 50) for t in second.timestamps[5:]]
    s2 = analyze_rack(rack, data, second, [], previous_state=s['rule_state'])
    event = next(e for e in s2['events'] if e['type'] == 'monitoring_missing')
    assert event['duration_minutes'] == 10
    assert event['started_at'] == '2026-11-08T23:55:00+08:00'
    assert event['recovered_at'] == '2026-11-09T00:05:00+08:00'


def test_device_overcount_is_anomaly():
    rack = RackConfig('r', '.*', 'delta', 1, 1)
    w = day_window(date(2026, 11, 9))
    data = [DeviceSample('psu_power', device, w.timestamps[0], 1000) for device in ('p0', 'p1')]
    s = analyze_rack(rack, data, w, [])
    assert any(e['type'] == 'device_overcount' for e in s['events'])


def test_report_renders_actual_previous_day_delta():
    rack = RackConfig('r', '.*', 'delta', 1, 1)
    w = day_window(date(2026, 11, 9))
    s = analyze_rack(rack, [DeviceSample('psu_power', 'p', t, 1000) for t in w.timestamps], w, [])
    import copy
    previous = copy.deepcopy(s)
    previous['power']['full_psu']['energy_kwh'] = 20
    report = render_report(date(2026, 11, 9), [s], {'summaries': [previous]})
    assert '+4.000 kWh' in report


def test_device_state_does_not_merge_identities():
    rack = RackConfig('r', '.*', 'delta', 2, 1)
    w = day_window(date(2026, 11, 9))
    previous = {'gpu_device_missing|g0': {'device': 'g0', 'type': 'gpu_device_missing', 'started_at': '2026-11-08T23:50:00+08:00', 'duration_minutes': 10}, 'gpu_device_missing|g1': {'device': 'g1', 'type': 'gpu_device_missing', 'started_at': '2026-11-08T23:55:00+08:00', 'duration_minutes': 5}}
    s = analyze_rack(rack, [], w, [], previous_state=previous)
    events = {e['device']: e for e in s['events'] if e['type'] == 'gpu_device_missing'}
    assert events['g0']['duration_minutes'] == 1450
    assert events['g1']['duration_minutes'] == 1445


class OneDeviceCollector:
    async def check_brand(self, rack, window):
        return False

    async def collect_block(self, rack, metric, window):
        return [DeviceSample(metric, 'g0' if metric.startswith('gpu') else 'p0', t, 50 if metric == 'gpu_utilization' else 1000) for t in window.timestamps]


def test_end_to_end_rerun_sends_same_report_once(tmp_path):
    repo = Repository('sqlite:///' + str(tmp_path/'e2e.db'))
    repo.initialize()
    config = AppConfig([RackConfig('r', '.*', 'delta', 1, 1)])
    sent = []
    class Sink:
        async def send(self, text):
            sent.append(text)
            return {'status': 'sent'}
    async def run():
        day = date(2026, 11, 9)
        job = DailyJob(repo, config, OneDeviceCollector())
        await job.run(day)
        assert repo.get_report(day)['summaries'][0]['power']['full_psu']['energy_kwh'] == __import__('pytest').approx(24)
        service = DeliveryService(repo, Sink())
        assert (await service.send_report(day))['status'] == 'sent'
        await job.run(day)
        assert (await service.send_report(day))['status'] == 'skipped'
    asyncio.run(run())
    assert len(sent) == 1
