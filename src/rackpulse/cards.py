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
    inventory={r['rack_id']:r for r in view.get('inventory',[])}
    def counts(rack,label):
        record=records.get(rack)
        expected=inventory.get(rack,{}).get('expected_'+label,72 if label=='gpu' else 48)
        if not record:return dict(expected=expected,actual=None,normal=None,degraded=None,unavailable=None)
        if record.get('monitoring_counts',{}).get(label):return record['monitoring_counts'][label]
        actual=record.get(label+'_count')
        # Historical rack averages cannot recover per-device quality categories.
        return dict(expected=expected,actual=actual,normal=None,degraded=None,unavailable=None)
    def shown(value):return '—' if value is None else str(value)
    main=[f'机柜总数：{len(ids)} · 设备健康：未判定（采集缺失不等于硬件故障）']
    for label,title,unit in [('gpu','GPU','张'),('psu','PSU','路')]:
        values=[counts(r,label) for r in sorted(ids)]
        def total(key):return sum(c[key] for c in values) if all(c.get(key) is not None for c in values) else None
        main.append(f"**{title} 监控**\n{title} 应监控：{shown(total('expected'))}{unit} · 实际采集：{shown(total('actual'))}{unit}\n监控正常：{shown(total('normal'))} · 监控降级：{shown(total('degraded'))} · 监控不可用：{shown(total('unavailable'))}")
    statuses={}
    for rack in ids:
        if rack not in records:statuses[rack]='无日报数据，待确认';continue
        parts=[]
        for label,title,unit in [('gpu','GPU','张'),('psu','PSU','路')]:
            c=counts(rack,label)
            if c['actual'] is None:parts.append(title+'统计未知')
            elif c['actual']>c['expected']:parts.append(title+'数量超配')
            elif c['actual']<c['expected']:parts.append(f"{title}缺{c['expected']-c['actual']}{unit}")
            if c.get('query_complete') is False:parts.append(title+'查询不完整')
            if c.get('degraded',0):parts.append(title+'采集降级')
            elif records[rack].get(label+'_completeness',1)<.95:parts.append(title+'采样覆盖不足')
        if any(e.get('type')=='datasource_error' for e in records[rack].get('events',[])):parts.append('数据源查询异常')
        statuses[rack]='；'.join(parts) or '数量齐全'
    main.append('**机柜汇总**\n机柜 | GPU应监控 | GPU实际 | PSU应监控 | PSU实际 | 监控状态')
    def order(r):
        bits=r.split('-')
        return (statuses[r]=='数量齐全',int(bits[-2]) if len(bits)>2 and bits[-2].isdigit() else 999,int(bits[-1]) if bits[-1].isdigit() else 999,r)
    for rack in sorted(ids,key=order):
        gpu,psu=counts(rack,'gpu'),counts(rack,'psu')
        main.append(f"**{rack}** | {gpu['expected']} | {shown(gpu['actual'])} | {psu['expected']} | {shown(psu['actual'])} | {statuses[rack]}")
    main.append('口径：实际采集=当天至少1次有效采样；正常=单设备采样完整率≥95%；降级=已采到但不足95%；不可用=确认全天无有效采样。历史报告缺少设备级统计或查询失败时对应分类显示—，不推算。')
    cards=[_card(f'RackPulse 每日监控概览｜{day}',main)]
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
