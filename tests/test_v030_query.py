import asyncio
from datetime import date
from rackpulse.jobs import DailyJob
from rackpulse.config import AppConfig,RackConfig
from rackpulse.repository import Repository


def test_single_query_failure_has_observation_not_full_day(tmp_path):
    class Collector:
        async def check_brand(self,rack,window): return False
        async def collect_block(self,rack,metric,window):
            if metric=='gpu_utilization' and window.start.hour==16: raise ValueError('query_failed')
            return []
    repo=Repository('sqlite:///'+str(tmp_path/'test.db')); repo.initialize()
    asyncio.run(DailyJob(repo,AppConfig([RackConfig('r','.*','delta')]),Collector()).run(date(2026,11,9)))
    report=repo.get_report(date(2026,11,9))
    event=next(e for e in report['summaries'][0]['events'] if e['type']=='datasource_error')
    assert event['duration_minutes']==0
    assert event['day_duration_minutes'] is None
    assert event['affected_window']['end'] != event['started_at']
    assert report['collection_status']=='partial'
