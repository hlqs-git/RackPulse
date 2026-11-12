import json
from datetime import date
from rackpulse.cards import render_cards, render_preview
from rackpulse.report_model import build_report_view


def test_all_32_racks_and_same_preview_payload():
    inventory=[{'rack_id':f'GB200-{p}-{i}'} for p in (1,2) for i in range(1,17)]
    view=build_report_view(date(2026,11,10),{'summaries':[]},inventory=inventory)
    cards=render_cards(view)
    assert len(cards)==1
    encoded=json.dumps(cards,ensure_ascii=False)
    assert '32 个机柜' in encoded
    assert 'GB200-' not in encoded  # Common missing-report reason is aggregated.
    assert '设备健康' in render_preview(view)
    assert all(c['msg_type']=='interactive' for c in cards)
