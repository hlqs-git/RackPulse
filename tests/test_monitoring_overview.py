from datetime import date
from rackpulse.analysis import analyze_rack
from rackpulse.config import RackConfig
from rackpulse.domain import DeviceSample
from rackpulse.timewindow import day_window
from rackpulse.cards import render_preview
from rackpulse.report_model import build_report_view


def test_device_categories_are_counted_individually():
    w=day_window(date(2026,11,11))
    data=[DeviceSample('gpu_utilization','g0',t,0) for t in w.timestamps]
    data += [DeviceSample('gpu_utilization','g1',w.timestamps[0],50)]
    s=analyze_rack(RackConfig('r','.*','delta',3,2),data,w,[])
    assert s['monitoring_counts']['gpu']==dict(expected=3,actual=2,normal=1,degraded=1,unavailable=1,query_complete=True)
    assert s['monitoring_counts']['psu']['unavailable']==2


def test_old_report_does_not_invent_device_categories():
    report={'summaries':[dict(rack_id='GB200-1-1',gpu_count=68,psu_count=48,gpu_completeness=.9,psu_completeness=1,events=[])]}
    text=render_preview(build_report_view(date(2026,11,11),report,inventory=[dict(rack_id='GB200-1-1')]))
    assert 'GPU 采集' in text and 'PSU 采集' in text
    assert '待确认' in text
    assert '历史' in text
    assert 'MWh' not in text and '趋势' not in text
