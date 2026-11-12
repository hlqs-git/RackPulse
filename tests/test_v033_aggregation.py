from rackpulse.cards import render_preview,render_cards


def report(count=32):
    records=[]
    for i in range(count):
        records.append(dict(rack_id=f'GB200-{1+i//16}-{1+i%16}',gpu_count=72,psu_count=48,gpu_completeness=1,psu_completeness=1,events=[],monitoring_counts={k:dict(expected=n,actual=n,normal=n,degraded=0,unavailable=0,query_complete=True) for k,n in [('gpu',72),('psu',48)]}))
    return dict(day='2026-11-12',report={'summaries':records},inventory=[dict(rack_id=s['rack_id']) for s in records])


def test_normal_five_lines_and_separate_gap():
    text=render_preview(report())
    assert len(text.splitlines())<=6
    assert '2304 / 2304' in text and '1536 / 1536' in text
    assert '缺口 0' in text
    assert 'GB200-' not in text


def test_common_reasons_are_aggregated_without_losing_counts():
    view=report();view['report']['complete']=False
    for s in view['report']['summaries']:del s['monitoring_counts']
    text=render_preview(view)
    for reason in ('日报采集不完整','GPU历史数据不足','PSU历史数据不足'):
        assert text.count(reason)==1
    assert '32 个机柜' in text
    assert len(text.splitlines())<=15


def test_mixed_reasons_cap_details_but_preserve_all_types():
    view=report(8)
    for i,s in enumerate(view['report']['summaries']):
        s['monitoring_counts']['gpu']['actual']-=i+1
    view['report']['summaries'][-1]['events']=[{'type':'datasource_error','metric':'gpu_power'}]
    text=render_preview(view)
    assert 'GB200-1-8' in text
    assert '其余' in text
    for i in range(1,9):assert f'GPU 少采集 {i} 张' in text
    assert len(text.splitlines())<=15
    assert render_cards(view)[0]['card']['header']['template']=='orange'


def test_overcount_never_offsets_another_racks_shortage():
    view=report(2)
    view['report']['summaries'][0]['monitoring_counts']['gpu']['actual']=70
    view['report']['summaries'][1]['monitoring_counts']['gpu']['actual']=74
    text=render_preview(view)
    assert '144 / 144' in text
    assert '缺口 2' in text
