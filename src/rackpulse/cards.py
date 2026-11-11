"""Feishu static interactive cards and identical textual preview."""
import json
from .report import notification_events, NAMES, MONITORING, SOURCES


def _fmt(v,scale=1,digits=1):
    return '—' if v is None else f'{v/scale:.{digits}f}'


def _card(title,lines):
    return {'msg_type':'interactive','card':{'config':{'wide_screen_mode':True},'header':{'title':{'tag':'plain_text','content':title}},'elements':[{'tag':'div','text':{'tag':'lark_md','content':line}} for line in lines]}}


def render_cards(view, max_bytes=18000):
    day=view['day']; report=view['report']; summaries=report.get('summaries',[])
    records={s['rack_id']:s for s in summaries}
    ids={r['rack_id'] for r in view.get('inventory',[])}|set(records)
    if not ids:
        ids={f'GB200-{p}-{i}' for p in (1,2) for i in range(1,17)}
    events=notification_events([dict(e,duration_minutes=e.get('day_duration_minutes') if e.get('day_duration_minutes') is not None else e.get('duration_minutes',0)) for s in summaries for e in s.get('events',[])])
    monitoring={e['rack_id'] for e in events if e['type'] in MONITORING or 'collection_missing' in e['type']}
    abnormal={e['rack_id'] for e in events}
    weight=sum(s.get('valid_gpu_minutes',0) for s in summaries if s.get('gpu_average_utilization') is not None)
    util=sum(s['gpu_average_utilization']*s.get('valid_gpu_minutes',0) for s in summaries if s.get('gpu_average_utilization') is not None)/weight if weight else None
    full=[s['power']['full_psu'] for s in summaries if s.get('power',{}).get('full_psu',{}).get('minutes',0)>0]
    energy=sum(p['energy_kwh'] for p in full if p['energy_kwh'] is not None) if full else None
    old={s['rack_id']:s for s in (view.get('previous') or {}).get('summaries',[])}
    comparable=[s for s in summaries if s['rack_id'] in old and s['power']['full_psu']['minutes']==1440 and old[s['rack_id']]['power']['full_psu']['minutes']==1440 and s['psu_vendor']==old[s['rack_id']]['psu_vendor'] and s['full_psu_device_sets']==old[s['rack_id']]['full_psu_device_sets']]
    delta=sum(s['power']['full_psu']['energy_kwh']-old[s['rack_id']]['power']['full_psu']['energy_kwh'] for s in comparable) if comparable else None
    main=[f'机柜 **{len(ids)}** · 异常机柜 **{len(abnormal)}**（监控{len(monitoring)}） · GPU利用率 **{_fmt(util)}%**',f'完整PSU可观测能耗 **{_fmt(energy,1000,3)} MWh**\n昨日同口径变化 {_fmt(delta,1000,3)} MWh（{len(comparable)}柜）',f"任务执行：{report.get('execution_status','历史记录/未知')} · 采集：{report.get('collection_status','未知')}\n监控链路：{'降级' if monitoring else '未知' if not summaries else '未发现重点异常'} · 设备健康：未知（无直接健康指标）"]
    def event_line(e):
        day_duration=e.get('day_duration_minutes'); total=e.get('total_duration_minutes')
        return f"[{e['severity']}] {e['rack_id']} {NAMES.get(e['type'],e['type'])}\n首次 {e.get('first_occurred_at') or e['started_at']} · 当天 {_fmt(day_duration)}分钟 · 累计 {_fmt(total)}分钟\n恢复 {e.get('recovered_at') or '未证实恢复'}"
    main+= [event_line(e) for e in events[:10]] or ['无重点异常；数据缺失不能证明设备故障。']
    cards=[_card(f'RackPulse {day} 日报',main)]
    for pod in (1,2,'其他'):
        group=[r for r in ids if (r.startswith(f'GB200-{pod}-') if pod!='其他' else not r.startswith(('GB200-1-','GB200-2-')))]
        if not group: continue
        group.sort(key=lambda r:(r not in monitoring,int(r.split('-')[-1]) if r.split('-')[-1].isdigit() else 999,r))
        rows=[]
        for rack in group:
            s=records.get(rack)
            if not s:
                rows.append(f'**{rack}** · 未采集\n利用率/均值/峰值/能耗/GPU完整率/PSU完整率：—')
                continue
            power=[]
            for source,label in SOURCES.items():
                p=s.get('power',{}).get(source,{})
                if p.get('minutes',0)>0:
                    power.append(f"{label}：均值{_fmt(p.get('average_watts'),1000)} / 峰值{_fmt(p.get('maximum_watts'),1000)} kW · {_fmt(p.get('energy_kwh'),1000,3)} MWh · {p['minutes']}/1440分")
            rows.append(f"**{rack}** · {'监控异常' if rack in monitoring else '指标波动' if rack in abnormal else '采集状态见完整率'}\nGPU {_fmt(s.get('gpu_average_utilization'))}% · 完整率 GPU {_fmt(s.get('gpu_completeness')*100 if s.get('gpu_completeness') is not None else None)}% / PSU {_fmt(s.get('psu_completeness')*100 if s.get('psu_completeness') is not None else None)}%\n"+('\n'.join(power) or '功率/峰值/可观测能耗：—'))
        cards.append(_card(f'{day} POD{pod} 明细',rows))
    from .trends import build_trends, rank_idle_power
    history=view.get('history',[])
    if history or summaries:
        from datetime import date
        lines=[]
        for days in (7,30):
            points=build_trends(date.fromisoformat(day),history+[dict(report,day=day)],days)
            lines.append(f'**{days}日趋势（可观测量，不外推缺失日）**')
            for point in points:
                lines.append(f"{point['day']} GPU {_fmt(point['gpu_utilization'])}% · 完整PSU {_fmt(point['full_psu_mwh'],digits=3)} / 部分PSU {_fmt(point['partial_psu_mwh'],digits=3)} / GPU代理 {_fmt(point['gpu_proxy_mwh'],digits=3)} MWh · 完整覆盖{_fmt(point['full_psu_coverage']*100 if point['full_psu_coverage'] is not None else None)}%")
        cards.append(_card(f'{day} 7/30日趋势',lines))
    ranks=rank_idle_power(summaries,low=report.get('rules',{}).get('low',10),coverage=report.get('rules',{}).get('rank_coverage',.95))
    if ranks:
        cards.append(_card(f'{day} 低利用率高功耗排名',[f"{s['rack_id']} GPU {_fmt(s['gpu_average_utilization'])}% · 完整PSU {_fmt(s['power']['full_psu']['average_watts'],1000)} kW" for s in ranks[:10]]))
    if len(events)>10:
        cards.append(_card(f'{day} 重点异常续页',[event_line(e) for e in events[10:]]))
    result=[]
    for card in cards:
        elements=card['card']['elements']; current=[]
        for element in elements:
            candidate={**card,'card':{**card['card'],'elements':current+[element]}}
            if len(json.dumps(candidate,ensure_ascii=False).encode())>max_bytes:
                if not current: raise ValueError('card_element_too_large')
                result.append({**card,'card':{**card['card'],'elements':current}}); current=[]
            current.append(element)
            if len(json.dumps({**card,'card':{**card['card'],'elements':current}},ensure_ascii=False).encode())>max_bytes:
                raise ValueError('card_element_too_large')
        if current: result.append({**card,'card':{**card['card'],'elements':current}})
    return result


def render_preview(view):
    return '\n\n'.join(card['card']['header']['title']['content']+'\n'+'\n'.join(e['text']['content'] for e in card['card']['elements']) for card in render_cards(view))
