import asyncio
from datetime import date
from fastapi.testclient import TestClient
from rackpulse.api import create_app
from rackpulse.config import AppConfig, RackConfig
from rackpulse.jobs import DailyJob
from rackpulse.repository import Repository


class EmptyCollector:
    async def check_brand(self, rack, window):
        return False

    async def collect_block(self, rack, metric, window):
        return []


def test_daily_job_persists_explicit_missing_report(tmp_path):
    repo = Repository('sqlite:///' + str(tmp_path/'jobs.db'))
    repo.initialize()
    config = AppConfig([RackConfig('r', 'node.*', 'delta')])
    job = DailyJob(repo, config, EmptyCollector())
    task_id = asyncio.run(job.run(date(2026, 11, 9)))
    assert repo.get_task(task_id)['status'] == 'succeeded'
    report = repo.get_report(date(2026, 11, 9))
    assert report['summaries'][0]['missing_minutes'] == 1440
    assert '未恢复' in report['text']


def test_api_auth_and_missing_report(tmp_path):
    repo = Repository('sqlite:///' + str(tmp_path/'api.db'))
    repo.initialize()
    app = create_app(repository=repo, config=AppConfig([]), api_token='test-token', scheduler_enabled=False)
    with TestClient(app) as client:
        assert client.get('/health').status_code == 200
        assert client.get('/reports/2026-11-09').status_code == 401
        assert client.get('/reports/2026-11-09', headers={'Authorization': 'Bearer test-token'}).status_code == 404
        assert client.post('/jobs', json={'day': '2026-11-09'}).status_code == 401
