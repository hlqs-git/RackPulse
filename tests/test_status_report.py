from datetime import date
from rackpulse.analysis import analyze_rack
from rackpulse.config import RackConfig
from rackpulse.report import render_report
from rackpulse.timewindow import day_window


def test_notification_reports_facts_without_diagnostic_suggestions():
    day = date(2026, 11, 9)
    summary = analyze_rack(RackConfig('r', '.*', 'delta'), [], day_window(day), [])
    text = render_report(day, [summary])
    assert '监控数据缺失' in text
    assert '可能为' not in text
    assert '建议' not in text
    assert '人工关注' not in text
    assert '采样完整率' in text
    assert '未恢复' in text
