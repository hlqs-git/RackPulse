"""Only runs against an explicitly supplied disposable PostgreSQL database."""
import os
import subprocess
from datetime import date
import pytest


@pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'),reason='isolated PostgreSQL not configured')
def test_upgrade_downgrade_preserves_reports_and_new_card_tables(monkeypatch,tmp_path):
    from alembic import command
    from alembic.config import Config
    from rackpulse.repository import Repository
    from rackpulse.analysis import analyze_rack
    from rackpulse.config import RackConfig
    from rackpulse.timewindow import day_window
    monkeypatch.setenv('DATABASE_URL',os.environ['TEST_DATABASE_URL'])
    cfg=Config('alembic.ini');command.upgrade(cfg,'head')
    repo=Repository(os.environ['TEST_DATABASE_URL'])
    summary=analyze_rack(RackConfig('r','.*','delta'),[],day_window(date(2026,11,9)),[])
    summary['events'].append(dict(rack_id='r',device=None,type='datasource_error',severity='Critical',started_at='2026-11-11T08:00:00+08:00',recovered_at=None,duration_minutes=0,day_duration_minutes=None,total_duration_minutes=None))
    payload={'day':'2026-11-09','summaries':[summary]}
    repo.publish_report(date(2026,11,9),payload)
    claim,_=repo.claim_card(date(2026,11,9),'migration-test','0',{'msg_type':'interactive'})
    if claim:repo.finish_card(claim,{'status':'sent'})
    command.downgrade(cfg,'0001')
    assert repo.get_report(date(2026,11,9))==payload
    # Old renderer really reads a v3 report, including unknown query duration.
    old=tmp_path/'old_report.py'
    old.write_bytes(subprocess.check_output(['git','show','v0.2.0:src/rackpulse/report.py']))
    import importlib.util
    spec=importlib.util.spec_from_file_location('old_report',old);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert '2026-11-09' in module.render_report(date(2026,11,9),[summary])
    if os.getenv('REQUIRE_COMPAT_IMAGE')=='true':
        script="""
import subprocess,asyncio
subprocess.run(['alembic','upgrade','head'],check=True)
from rackpulse.api import create_app
from rackpulse.repository import Repository
from rackpulse.report import render_report
from datetime import date
import os
r=Repository(os.environ['DATABASE_URL']).get_report(date(2026,11,9))
assert '2026-11-09' in render_report(date(2026,11,9),r['summaries'])
async def verify():
    app=create_app()
    async with app.router.lifespan_context(app):
        assert app.title=='RackPulse'
asyncio.run(verify())
"""
        subprocess.run(['docker','run','--rm','--network','host','-e','DATABASE_URL='+os.environ['TEST_DATABASE_URL'],'-e','SCHEDULER_ENABLED=false','-e','RACK_CONFIG=config/racks.example.yaml','ghcr.io/hlqs-git/rackpulse:0.2.0','python','-c',script],check=True,timeout=180)
    command.upgrade(cfg,'head')
    assert repo.get_report(date(2026,11,9))==payload
    assert repo.claim_card(date(2026,11,9),'migration-test','0',{})==(None,'sent')
