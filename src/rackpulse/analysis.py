"""Minute-grid statistics. Missing values are never imputed."""
import math
from collections import defaultdict
from statistics import mean, median
from datetime import datetime
from .timewindow import TZ


def analyze_rack(rack, samples, window, history, rules=None, previous_state=None):
    rules = rules or {'low': 10, 'high': 80, 'load_minutes': 60, 'missing_minutes': 10}
    previous_state = previous_state or {}
    grid = defaultdict(dict)
    conflicts = set()
    valid_times = set(window.timestamps)
    for sample in samples:
        v = sample.value
        if sample.timestamp not in valid_times or not math.isfinite(v) or v < 0:
            continue
        if sample.metric == 'gpu_utilization' and v > 100:
            continue
        key = (sample.timestamp, sample.metric, sample.device)
        if key in conflicts:
            continue
        bucket = grid[(sample.timestamp, sample.metric)]
        if sample.device in bucket and bucket[sample.device] != v:
            del bucket[sample.device]
            conflicts.add(key)
        else:
            bucket[sample.device] = v
    power = {s: {'values': [], 'energy_kwh': 0, 'minutes': 0} for s in ('full_psu', 'partial_psu', 'gpu_proxy')}
    gpu_ids, psu_ids, utils = set(), set(), []
    gpu_powers = []
    gpu_minutes = psu_minutes = high = low = 0
    flags = defaultdict(list)
    full_sets = set()
    baseline_days = [h for h in history if h.get('psu_vendor') == rack.psu_vendor and h['power']['full_psu']['minutes'] >= 1368 and len(h.get('full_psu_device_sets', [])) == 1]
    baselines = defaultdict(list)
    for h in baseline_days:
        baselines[tuple(h['full_psu_device_sets'][0])].append(h['power']['full_psu']['average_watts'])
    for t in window.timestamps:
        u = grid[(t, 'gpu_utilization')]
        p = grid[(t, 'psu_power')]
        g = grid[(t, 'gpu_power')]
        flags['device_overcount'].append(len(u) > rack.expected_gpu or len(p) > rack.expected_psu or len(g) > rack.expected_gpu)
        gpu_powers.extend(g.values())
        gpu_ids.update(u); psu_ids.update(p)
        gpu_minutes += min(len(u), rack.expected_gpu)
        psu_minutes += min(len(p), rack.expected_psu)
        utils.extend(u.values())
        high += sum(v >= rules['high'] for v in u.values())
        low += sum(v < rules['low'] for v in u.values())
        source = 'full_psu' if len(p) == rack.expected_psu else 'partial_psu' if 0 < len(p) < rack.expected_psu else 'gpu_proxy' if not p and g else None
        if source:
            watts = sum((g if source == 'gpu_proxy' else p).values())
            power[source]['values'].append(watts)
            power[source]['energy_kwh'] += watts / 60000
            power[source]['minutes'] += 1
        if source == 'full_psu':
            full_sets.add(tuple(sorted(p)))
        reference = baselines.get(tuple(sorted(p)), []) if source == 'full_psu' else []
        baseline = median(reference) if len(reference) >= 3 else None
        deviation = (sum(p.values()) / baseline - 1) if baseline and baseline > 0 else None
        flags['power_increase'].append(deviation is not None and deviation > rules.get('power_change', .30))
        flags['power_decrease'].append(deviation is not None and deviation < -rules.get('power_change', .30))
        flags['gpu_missing'].append(len(u) < rack.expected_gpu)
        flags['psu_missing'].append(len(p) < rack.expected_psu)
        flags['monitoring_missing'].append(not (u or p or g))
        flags['low_load'].append(bool(u) and mean(u.values()) < rules['low'])
        flags['high_load'].append(bool(u) and mean(u.values()) >= rules['high'])
    for value in power.values():
        values = value.pop('values')
        value['average_watts'] = mean(values) if values else None
        value['maximum_watts'] = max(values) if values else None
    events = []
    thresholds = {'device_overcount': 1, 'power_increase': 1, 'power_decrease': 1, 'gpu_missing': 1, 'psu_missing': 1, 'monitoring_missing': rules['missing_minutes'], 'low_load': rules['load_minutes'], 'high_load': rules['load_minutes']}
    state = {}
    def intervals(kind, values, device=None):
        key = f'{kind}|{device or ""}'
        previous = previous_state.get(key)
        start = 0 if previous else None
        def iso(index):
            return datetime.fromtimestamp(int(window.start.timestamp())+index*60, TZ).isoformat()
        for i, active in enumerate(values+[False]):
            if active and start is None:
                start = i
            if not active and start is not None:
                carry = previous if start == 0 else None
                duration = i-start+(carry['duration_minutes'] if carry else 0)
                event = {'rack_id': rack.rack_id, 'device': device, 'type': kind, 'severity': 'Critical' if kind == 'monitoring_missing' else 'Info' if kind.endswith('load') else 'Warning', 'started_at': carry['started_at'] if carry else iso(start), 'recovered_at': iso(i) if i < 1440 else None, 'duration_minutes': duration, 'suggestion': '可能为负载变化或采集链路异常，请核对原始监控与设备状态。'}
                if duration >= thresholds.get(kind, 1):
                    events.append(event)
                if i == 1440:
                    state[key] = event
                start = None
                previous = None
    for kind, values in flags.items():
        intervals(kind, values)
    for metric, identities, kind in [('gpu_utilization', gpu_ids, 'gpu_device_missing'), ('psu_power', psu_ids, 'psu_device_missing')]:
        identities = identities | {e['device'] for e in previous_state.values() if isinstance(e, dict) and e.get('type') == kind and e.get('device')}
        for device in sorted(identities):
            intervals(kind, [device not in grid[(t, metric)] for t in window.timestamps], device)
    for event in events:
        event.setdefault('metric_value', None)
        event['rule_version'] = '1'
    return {'rack_id': rack.rack_id, 'psu_vendor': rack.psu_vendor, 'valid_gpu_minutes': gpu_minutes, 'gpu_count': len(gpu_ids), 'psu_count': len(psu_ids), 'gpu_completeness': gpu_minutes/(rack.expected_gpu*1440), 'psu_completeness': psu_minutes/(rack.expected_psu*1440), 'gpu_average_utilization': mean(utils) if utils else None, 'gpu_maximum_utilization': max(utils) if utils else None, 'gpu_average_power_watts': mean(gpu_powers) if gpu_powers else None, 'gpu_maximum_power_watts': max(gpu_powers) if gpu_powers else None, 'high_load_ratio': high/len(utils) if utils else None, 'low_load_ratio': low/len(utils) if utils else None, 'missing_minutes': sum(flags['monitoring_missing']), 'power': power, 'events': events, 'full_psu_device_sets': [list(s) for s in sorted(full_sets)], 'duplicate_conflicts': len(conflicts), 'power_baseline_status': 'available' if any(len(v)>=3 for v in baselines.values()) else 'insufficient_history', 'rule_state': state}
