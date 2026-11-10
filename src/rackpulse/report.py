"""Compact notification views; raw persisted events are never modified."""
from collections import defaultdict

MISSING = {'gpu_missing', 'psu_missing', 'monitoring_missing', 'gpu_device_missing', 'psu_device_missing'}
MONITORING = MISSING | {'datasource_error', 'brand_conflict', 'device_overcount'}
NAMES = {'gpu_missing':'GPU采集不足', 'psu_missing':'PSU采集不足', 'monitoring_missing':'监控数据缺失', 'gpu_device_missing':'GPU采集缺失', 'psu_device_missing':'PSU采集缺失', 'node_collection_missing':'节点采集异常', 'rack_collection_missing':'机柜采集异常', 'datasource_error':'数据源查询失败', 'brand_conflict':'品牌配置冲突', 'device_overcount':'采集数量超配', 'low_load':'低负载', 'high_load':'高负载', 'power_increase':'功率上升', 'power_decrease':'功率下降'}
SOURCES = {'full_psu':'完整PSU', 'partial_psu':'部分PSU', 'gpu_proxy':'GPU代理'}


def notification_events(events, minimum_minutes=5):
    selected = [dict(e) for e in events if e['severity']=='Critical' or (e['severity']!='Info' and (e['type'] not in MISSING or e['duration_minutes']>=minimum_minutes))]
    groups, other = defaultdict(list), []
    for e in selected:
        device = (e.get('device') or '').split('/')
        if e['type']=='gpu_device_missing' and len(device)>=3:
            groups[(e['rack_id'], e['started_at'], e.get('recovered_at'), e['severity'])].append(e)
        else:
            other.append(e)
    for key, values in sorted(groups.items(), key=lambda x: str(x[0])):
        nodes = {e['device'].rsplit('/', 1)[0] for e in values}
        if any(sum(v['device'].rsplit('/', 1)[0] == node for v in values) < 4 for node in nodes):
            other.extend(values)
            continue
        e = dict(values[0])
        e.update(type='rack_collection_missing' if len(nodes)>1 else 'node_collection_missing', device=None if len(nodes)>1 else next(iter(nodes)), affected_devices=len({v['device'] for v in values}), affected_nodes=len(nodes))
        # A rack count event with the same interval is the parent of these details.
        other = [p for p in other if not (p['type']=='gpu_missing' and p['rack_id']==key[0] and p['started_at']==key[1] and p.get('recovered_at')==key[2] and p['severity']!='Critical')]
        other.append(e)
    return sorted(other, key=lambda e: (0 if e['severity']=='Critical' else 1, -e['duration_minutes'], e['rack_id'], e['started_at'], e['type'], e.get('device') or ''))


def split_notification(text, max_bytes=14000):
    """Respect UTF-8 limits and preserve complete rows whenever possible."""
    parts, current = [], ''
    for line in text.split('\n'):
        if len(line.encode()) > max_bytes:
            raise ValueError('notification_row_too_long')
        candidate = current+'\n'+line if current else line
        if len(candidate.encode()) > max_bytes:
            parts.append(current)
            current = line
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def render_report(day, summaries, previous=None):
    if not summaries:
        return f'RackPulse 日报 | {day}\n数据缺失：无机柜汇总。'
    all_events = [e for s in summaries for e in s['events']]
    events = notification_events(all_events)
    monitoring = sum(any(e['type'] in MONITORING or e['type'] in ('node_collection_missing', 'rack_collection_missing') for e in notification_events(s['events'])) for s in summaries)
    weight = sum(s.get('valid_gpu_minutes',0) for s in summaries)
    utilization = sum((s['gpu_average_utilization'] or 0)*s.get('valid_gpu_minutes',0) for s in summaries)/weight if weight else None
    def number(value, digits=1):
        return '—' if value is None else f'{value:.{digits}f}'
    lines = [f'RackPulse 日报 | {day} 北京时间', f'机柜 {len(summaries)} | 监控异常 {monitoring} | 设备异常：无直接设备健康指标，未判定', f'GPU平均利用率 {number(utilization)}% | 采集缺失仅表示监控数据异常', '机柜汇总（功率kW / 能耗MWh；完整/部分/代理分别计量）', '机柜 | 利用率% | GPU/PSU完整率% | 均值/峰值kW · MWh | 状态']
    old = {s['rack_id']:s for s in previous['summaries']} if previous else {}
    for s in summaries:
        power = []
        for source,label in SOURCES.items():
            p=s['power'][source]
            if p['minutes']>0:
                power.append(f"{label} {number(p['average_watts']/1000 if p['average_watts'] is not None else None)}/{number(p['maximum_watts']/1000 if p['maximum_watts'] is not None else None)} · {p['energy_kwh']/1000:.3f}")
        state='监控异常' if any(e['type'] in MONITORING or e['type'] in ('node_collection_missing', 'rack_collection_missing') for e in notification_events(s['events'])) else '指标波动' if notification_events(s['events']) else '短缺采' if any(e['type'] in MISSING for e in s['events']) else '采集正常'
        lines.append(f"{s['rack_id']} | {number(s['gpu_average_utilization'])} | {s['gpu_completeness']*100:.0f}/{s['psu_completeness']*100:.0f} | {'; '.join(power) or '—'} | {state}")
    for source,label in SOURCES.items():
        valid=[s['power'][source] for s in summaries if s['power'][source]['minutes']>0]
        if valid:
            lines.append(f"{label}可观测能耗 {sum(p['energy_kwh'] for p in valid)/1000:.3f} MWh")
    comparable=[(s,old[s['rack_id']]) for s in summaries if s['rack_id'] in old and s['power']['full_psu']['minutes']==1440 and old[s['rack_id']]['power']['full_psu']['minutes']==1440 and s['psu_vendor']==old[s['rack_id']]['psu_vendor'] and s['full_psu_device_sets']==old[s['rack_id']]['full_psu_device_sets']]
    if comparable:
        delta=sum(s['power']['full_psu']['energy_kwh']-p['power']['full_psu']['energy_kwh'] for s,p in comparable)/1000
        lines.append(f'昨日同口径能耗变化 {delta:+.3f} MWh（{len(comparable)}柜）')
    short=sum(e['type'] in MISSING and e['severity']!='Critical' and e['duration_minutes']<5 for e in all_events)
    lines.append(f'数据质量：短暂缺采 {short} 条；采样完整率见表。详细事件 {len(all_events)} 条保存在数据库。')
    lines.append(f'重点事件 {len(events)} 条（缺采≥5分钟；Critical不按时长过滤）')
    # Reserve the tenth row for a lossless severity count when overflow exists.
    limit=10 if len(events)<=10 else 9
    for e in events[:limit]:
        start=e['started_at'][11:16]
        end=e['recovered_at'][11:16] if e.get('recovered_at') else '未恢复'
        scope=f" {e['device'].split('/')[-1]}" if e.get('device') else ''
        affected=f"（{e['affected_nodes']}节点/{e['affected_devices']}GPU）" if 'affected_nodes' in e else ''
        lines.append(f"! [{e['severity']}] {e['rack_id']}{scope} {NAMES.get(e['type'],e['type'])}{affected} {start}→{end} {e['duration_minutes']}分钟")
    if len(events)>10:
        remaining=events[9:]
        critical=sum(e['severity']=='Critical' for e in remaining)
        lines.append(f'! 其余 {len(remaining)} 条（Critical {critical} 条，均已保留），请查数据库详细事件。')
    return '\n'.join(lines)
