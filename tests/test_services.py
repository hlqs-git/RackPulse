import asyncio
from datetime import date
import httpx
import pytest
from rackpulse.thanos import ThanosClient, QueryError
from rackpulse.notifications import FeishuAdapter
from rackpulse.repository import Repository
from rackpulse.report import render_report


def test_thanos_rejects_warnings():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={'status': 'success', 'warnings': ['partial'], 'data': {'resultType': 'matrix', 'result': []}}))
    async def run():
        async with httpx.AsyncClient(transport=transport) as client:
            q = ThanosClient('http://thanos', client=client)
            with pytest.raises(QueryError):
                await q.query_range('up', 0, 60, 60)
    asyncio.run(run())


def test_thanos_retries_transient_failure():
    attempts = []
    def handler(request):
        attempts.append(request)
        return httpx.Response(503) if len(attempts) == 1 else httpx.Response(200, json={'status': 'success', 'data': {'resultType': 'matrix', 'result': []}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await ThanosClient('http://thanos', client=client, backoff=0).query_range('up', 0, 60, 60)
            assert result == []
    asyncio.run(run())
    assert len(attempts) == 2


def test_feishu_timeout_unknown_without_retry():
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout('secret-url')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await FeishuAdapter('http://secret', client=client).send('日报')
            assert result['status'] == 'unknown'
            assert 'secret' not in str(result)
    asyncio.run(run())
    assert len(calls) == 1


def test_feishu_business_failure():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'code': 19024, 'msg': 'bad'}))) as client:
            assert (await FeishuAdapter('http://secret', client=client).send('test'))['status'] == 'failed'
    asyncio.run(run())


def test_repository_revisions_and_delivery_claim(tmp_path):
    repo = Repository('sqlite:///' + str(tmp_path/'test.db'))
    repo.initialize()
    repo.publish_report(date(2026, 11, 9), {'text': 'a'})
    repo.publish_report(date(2026, 11, 9), {'text': 'b'})
    assert repo.get_report(date(2026, 11, 9))['text'] == 'b'
    assert repo.claim_delivery('2026-11-09', 'feishu', 'hash') is True
    assert repo.claim_delivery('2026-11-09', 'feishu', 'hash') is False


def test_report_missing_is_explicit():
    text = render_report(date(2026, 11, 9), [], None)
    assert '数据缺失' in text
    assert '2026-11-09' in text
