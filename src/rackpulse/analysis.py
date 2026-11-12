"""Minute-grid statistics. Missing values are never imputed."""
import math
from collections import defaultdict
from statistics import mean, median
from datetime import datetime
from .timewindow import TZ


def analyze_rack(rack, samples, window, history, rules=None, previous_state=None, unknown_windows=None):
    rules = rules or {'low': 10, 'high': 80, 'load_minutes': 60, 'missing_minutes': 10}
    previous_state = previous_state or {}
    unknown_windows = unknown_windows or []
    def unknown(metric,t):
        return any(m==metric and a<=t<b for m,a,b in unknown_windows)
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
    for kind,values in flags.items():
        for i,t in enumerate(window.timestamps):
            metric='gpu_utilization' if kind in ('gpu_missing','low_load','high_load') else 'psu_power' if kind in ('psu_missing','power_increase','power_decrease') else None
            if unknown(metric,t) if metric else any(unknown(m,t) for m in ('gpu_utilization','gpu_power','psu_power')):
                values[i]=None
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
        first=previous['started_at'] if previous else None
        known_before=previous['duration_minutes'] if previous else 0
        day_count=0
        uncertain=bool(previous and previous.get('observation_status')=='unknown')
        def iso(index):
            return datetime.fromtimestamp(int(window.start.timestamp())+index*60,TZ).isoformat()
        def finish(index, recovered):
            total=known_before+day_count
            event=dict(rack_id=rack.rack_id,device=device,type=kind,severity='Critical' if kind=='monitoring_missing' else 'Info' if kind.endswith('load') else 'Warning',started_at=first,first_occurred_at=first,recovered_at=iso(index) if recovered else None,duration_minutes=total,day_duration_minutes=day_count,total_duration_minutes=total,time_basis='observed_minutes',observation_status='unknown' if uncertain else 'observed',suggestion='请核对原始监控。')
            if total>=thresholds.get(kind,1):events.append(event)
            if not recovered:state[key]=event
        for i,active in enumerate(values):
            if active is None:
                if first is not None:uncertain=True
                continue
            if active:
                if first is None:first=iso(i)
                day_count+=1
            elif first is not None:
                finish(i,True)
                first=None;known_before=0;day_count=0;uncertain=False
        if first is not None:finish(1440,False)
    for kind, values in flags.items():
        intervals(kind, values)
    for metric, identities, kind in [('gpu_utilization', gpu_ids, 'gpu_device_missing'), ('psu_power', psu_ids, 'psu_device_missing')]:
        identities = identities | {e['device'] for e in previous_state.values() if isinstance(e, dict) and e.get('type') == kind and e.get('device')}
        for device in sorted(identities):
            intervals(kind, [None if unknown(metric,t) else device not in grid[(t, metric)] for t in window.timestamps], device)
    for event in events:
        event.setdefault('metric_value', None)
        event['rule_version'] = '1'
    monitoring_counts={}
    for label,metric,expected in [('gpu','gpu_utilization',rack.expected_gpu),('psu','psu_power',rack.expected_psu)]:
        counts=defaultdict(int)
        for t in window.timestamps:
            for device in grid[(t,metric)]:counts[device]+=1
        complete=not any(m==metric for m,a,b in unknown_windows)
        normal=sum(n/1440>=rules.get('normal_coverage',.95) for n in counts.values())
        monitoring_counts[label]=dict(expected=expected,actual=len(counts),normal=normal,degraded=len(counts)-normal,unavailable=max(0,expected-len(counts)) if complete and len(counts)<=expected else None,query_complete=complete)
    return {'monitoring_counts':monitoring_counts, 'rack_id': rack.rack_id, 'psu_vendor': rack.psu_vendor, 'valid_gpu_minutes': gpu_minutes, 'gpu_count': len(gpu_ids), 'psu_count': len(psu_ids), 'gpu_completeness': gpu_minutes/(rack.expected_gpu*1440), 'psu_completeness': psu_minutes/(rack.expected_psu*1440), 'gpu_average_utilization': mean(utils) if utils else None, 'gpu_maximum_utilization': max(utils) if utils else None, 'gpu_average_power_watts': mean(gpu_powers) if gpu_powers else None, 'gpu_maximum_power_watts': max(gpu_powers) if gpu_powers else None, 'high_load_ratio': high/len(utils) if utils else None, 'low_load_ratio': low/len(utils) if utils else None, 'missing_minutes': sum(v is True for v in flags['monitoring_missing']), 'power': power, 'events': events, 'full_psu_device_sets': [list(s) for s in sorted(full_sets)], 'duplicate_conflicts': len(conflicts), 'power_baseline_status': 'available' if any(len(v)>=3 for v in baselines.values()) else 'insufficient_history', 'rule_state': state}
