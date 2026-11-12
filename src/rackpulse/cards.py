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
    issues={}; pending={}
    for rack in sorted(ids):
        record=records.get(rack)
        if record is None:
            pending[rack]=['无日报数据'];continue
        confirmed=[]; uncertain=[]
        if report.get('complete') is False or report.get('errors'):
            uncertain.append('日报采集不完整')
        events=record.get('events',[])
        if any(e.get('type')=='datasource_error' for e in events):uncertain.append('查询失败')
        if any(e.get('type')=='brand_conflict' for e in events):uncertain.append('PSU品牌配置冲突')
        for label,title,unit in [('gpu','GPU','张'),('psu','PSU','路')]:
            c=counts(rack,label)
            if c.get('query_complete') is not True:
                uncertain.append(title+('查询不完整' if c.get('query_complete') is False else '历史数据不足'))
                continue
            actual=c.get('actual');expected=c['expected']
            if actual is None or actual==0:
                uncertain.append(title+'无有效数据');continue
            if actual<expected:confirmed.append(f'{title} 少采集 {expected-actual} {unit}')
            elif actual>expected:confirmed.append(title+'采集数量超配')
            if c.get('degraded') is None or c.get('normal') is None:uncertain.append(title+'完整性未知')
            elif c['degraded']>0:confirmed.append(title+'采集降级')
            completeness=record.get(label+'_completeness')
            if completeness is None:uncertain.append(title+'采样覆盖未知')
            elif completeness<.95 and title+'采集降级' not in confirmed:confirmed.append(title+'采样覆盖不足')
        if confirmed:issues[rack]=confirmed
        if uncertain:pending[rack]=uncertain
    attention=set(issues)|set(pending)
    status='待确认' if pending else '异常' if issues else '正常'
    headline=f'{status} · {len(attention)} 个机柜需关注' if attention else '正常 · 无监控异常'
    main=[f'**{headline}**']
    for label,title in [('gpu','GPU'),('psu','PSU')]:
        values=[counts(r,label) for r in sorted(ids)]
        def total(key):return sum(c[key] for c in values) if all(c.get(key) is not None for c in values) else None
        main.append(f"{title} 采集\n**{shown(total('actual'))} / {shown(total('expected'))}**")
    if attention:
        main.append('**异常详情 / 待确认**')
        for rack in sorted(attention):
            reasons=issues.get(rack,[])+[f'待确认：{reason}' for reason in pending.get(rack,[])]
            main.append(f"**{rack}**：{'；'.join(reasons)}")
    main.append(f'{len(ids)} 个机柜 · 监控异常 {len(issues)} 个'+(f' · 待确认 {len(pending)} 个' if pending else ''))
    main.append('设备健康：未判定；以上仅反映监控采集状态。')
    card=_card(f'RackPulse 每日监控｜{day}',main)
    card['card']['header']['template']={'正常':'green','异常':'red','待确认':'orange'}[status]
    cards=[card]
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
