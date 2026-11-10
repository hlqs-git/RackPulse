import asyncio
import hmac
import os
from contextlib import asynccontextmanager
from datetime import date
from fastapi import FastAPI, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from .collector import Collector
from .config import load_config
from .jobs import DailyJob
from .notifications import DeliveryService, FeishuAdapter
from .repository import Repository
from .scheduler import make_scheduler
from .thanos import ThanosClient
from .logging import configure_logging


class DayRequest(BaseModel):
    day: date


class SendRequest(DayRequest):
    force: bool = False


def create_app(repository=None, config=None, api_token=None, scheduler_enabled=None):
    configure_logging()
    repo = repository or Repository(os.environ['DATABASE_URL'])
    cfg = config or load_config(os.getenv('RACK_CONFIG', 'config/racks.yaml'))
    token = api_token or os.getenv('API_TOKEN', '')
    enabled = scheduler_enabled if scheduler_enabled is not None else os.getenv('SCHEDULER_ENABLED', 'true').lower() == 'true'
    collector = Collector(ThanosClient(os.getenv('THANOS_URL', ''), token=os.getenv('THANOS_TOKEN')), cfg)
    job = DailyJob(repo, cfg, collector)
    adapter = FeishuAdapter(os.getenv('FEISHU_WEBHOOK_URL'), os.getenv('FEISHU_SIGNING_SECRET'))
    delivery = DeliveryService(repo, adapter)
    running = set()

    def spawn(coroutine):
        task = asyncio.create_task(coroutine)
        running.add(task)
        task.add_done_callback(running.discard)

    async def scheduled(day):
        existed = repo.get_report(day)
        task_id = await job.run(day)
        if not existed and repo.get_task(task_id)['status'] in ('succeeded', 'partial'):
            await delivery.send_report(day)

    @asynccontextmanager
    async def lifespan(app):
        repo.recover_deliveries()
        scheduler = make_scheduler(scheduled) if enabled else None
        if scheduler:
            cfg.validate_ready()
            scheduler.start()
        for task in repo.pending():
            spawn(job.run(date.fromisoformat(task['day']), task['id']))
        yield
        if scheduler:
            scheduler.shutdown(wait=False)
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)

    app = FastAPI(title='RackPulse', lifespan=lifespan)

    def auth(authorization: str = Header(default='')):
        if not token or not hmac.compare_digest(authorization, f'Bearer {token}'):
            raise HTTPException(401, 'unauthorized')

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.get('/ready')
    def ready():
        try:
            with repo.engine.connect() as conn:
                conn.execute(text('SELECT 1'))
            cfg.validate_ready()
            return {'status': 'ready'}
        except Exception:
            raise HTTPException(503, 'database_or_configuration_unavailable') from None

    @app.post('/jobs', status_code=202, dependencies=[Depends(auth)])
    async def generate(request: DayRequest):
        try:
            cfg.validate_ready()
        except ValueError:
            raise HTTPException(422, 'configuration_incomplete') from None
        task_id = repo.create_task(request.day)
        spawn(job.run(request.day, task_id))
        return {'task_id': task_id}

    @app.get('/jobs/{task_id}', dependencies=[Depends(auth)])
    def task(task_id: str):
        result = repo.get_task(task_id)
        if result is None:
            raise HTTPException(404, 'task_missing')
        return result

    @app.get('/reports/{day}', dependencies=[Depends(auth)])
    def report(day: date):
        result = repo.get_report(day)
        if result is None:
            raise HTTPException(404, 'report_missing')
        result['needs_recompute'] = repo.get_state(day).get('_needs_recompute', False)
        return result

    @app.post('/notifications/send', dependencies=[Depends(auth)])
    async def send(request: SendRequest):
        return await delivery.send_report(request.day, request.force)

    @app.post('/notifications/test', dependencies=[Depends(auth)])
    async def test():
        return await adapter.send('【测试】RackPulse 飞书连接测试，无生产日报。')

    return app
