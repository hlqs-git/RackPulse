from rackpulse.cards import render_cards


def view(summary):
    return dict(day='2026-11-12',report={'summaries':[summary]},inventory=[{'rack_id':'GB200-1-1'}])


def record():
    return dict(rack_id='GB200-1-1',gpu_count=72,psu_count=48,gpu_completeness=1,psu_completeness=1,events=[],monitoring_counts={label:dict(expected=n,actual=n,normal=n,degraded=0,unavailable=0,query_complete=True) for label,n in [('gpu',72),('psu',48)]})


def test_healthy_is_short_and_has_no_rack_table():
    card=render_cards(view(record()))[0]['card']
    assert card['header']['template']=='green'
    text=str(card)
    assert '正常 · 无监控异常' in text
    assert 'GB200-1-1' not in text
    assert '设备正常' not in text


def test_missing_is_red_and_query_failure_is_pending():
    s=record();s['monitoring_counts']['gpu']['actual']=70
    card=render_cards(view(s))[0]['card']
    assert card['header']['template']=='red'
    assert 'GPU 少采集 2 张' in str(card)
    s['monitoring_counts']['gpu']['query_complete']=False
    card=render_cards(view(s))[0]['card']
    assert card['header']['template']=='orange'
    assert '待确认' in str(card)


def test_legacy_counts_alone_never_prove_healthy():
    s=record();del s['monitoring_counts']
    assert '待确认' in str(render_cards(view(s)))
