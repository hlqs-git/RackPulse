STATUS_NAMES = {
    'gpu_missing': 'GPU采集数量不足', 'psu_missing': 'PSU采集数量不足',
    'monitoring_missing': '监控数据缺失', 'low_load': 'GPU低负载',
    'high_load': 'GPU高负载', 'power_increase': '功率高于历史基线',
    'power_decrease': '功率低于历史基线', 'device_overcount': '采集数量超出配置',
    'gpu_device_missing': 'GPU设备采集缺失', 'psu_device_missing': 'PSU设备采集缺失',
    'brand_conflict': 'PSU品牌配置冲突', 'datasource_error': '数据源查询失败',
}


def render_report(day, summaries, previous=None):
    lines = [f'RackPulse GPU 数据中心日报 | {day}', '时区：Asia/Shanghai；统计上一自然日；缺失数据不补零。']
    if not summaries:
        return '\n'.join(lines + ['数据缺失：没有可用的机柜汇总。'])
    abnormal = sum(s['missing_minutes'] < 1440 and any(e['severity'] in ('Warning', 'Critical') for e in s['events']) for s in summaries)
    unknown = sum(s['missing_minutes'] == 1440 for s in summaries)
    lines.append(f'机柜 {len(summaries)}；正常 {len(summaries)-abnormal-unknown}；异常 {abnormal}；无法评估 {unknown}。Info 高负载表示负载状态。')
    names = {'full_psu': '完整PSU实测', 'partial_psu': '部分PSU实测（非机柜总功率）', 'gpu_proxy': 'GPU代理（非机柜总功率）'}
    def fmt(v):
        return '数据缺失' if v is None else f'{v:.2f}'
    total_weight = sum(s.get('valid_gpu_minutes', 0) for s in summaries)
    if total_weight:
        utilization = sum((s['gpu_average_utilization'] or 0)*s['valid_gpu_minutes'] for s in summaries)/total_weight
        lines.append(f'全局GPU平均利用率 {utilization:.2f}%；有效设备分钟 {total_weight}。')
    old = {s['rack_id']: s for s in previous['summaries']} if previous else {}
    for s in summaries:
        lines += [f"\n{s['rack_id']} | PSU {s['psu_vendor']}", f"GPU日内有效数量 {s['gpu_count']}/72；PSU {s['psu_count']}/48", f"GPU平均利用率 {fmt(s['gpu_average_utilization'])}%；采样完整率 GPU {s['gpu_completeness']:.1%} / PSU {s['psu_completeness']:.1%}"]
        for source, p in s['power'].items():
            lines.append(f"{names[source]}：均值 {fmt(p['average_watts'])} W，峰值 {fmt(p['maximum_watts'])} W；可观测能耗 {p['energy_kwh']:.3f} kWh，覆盖 {p['minutes']}/1440 分钟")
        previous_rack = old.get(s['rack_id'])
        comparable = previous_rack and s['power']['full_psu']['minutes'] == 1440 and previous_rack['power']['full_psu']['minutes'] == 1440 and s['full_psu_device_sets'] == previous_rack['full_psu_device_sets'] and s['psu_vendor'] == previous_rack['psu_vendor']
        if comparable:
            delta = s['power']['full_psu']['energy_kwh']-previous_rack['power']['full_psu']['energy_kwh']
            lines.append(f'昨日对比：同口径完整PSU能耗变化 {delta:+.3f} kWh。')
        else:
            lines.append('昨日对比：不可比（缺少完整全天同品牌、同设备集合的PSU数据）。')
        for e in s['events']:
            name = STATUS_NAMES.get(e['type'], e['type'])
            device = f"；设备 {e['device']}" if e.get('device') else ''
            lines.append(f"[{e['severity']}] {name}{device} {e['started_at']} → {e['recovered_at'] or '未恢复'}；{e['duration_minutes']}分钟。")
    for source in names:
        total = sum(s['power'][source]['energy_kwh'] for s in summaries)
        lines.append(f'全局{names[source]}可观测能耗合计：{total:.3f} kWh。')
    return '\n'.join(lines)
