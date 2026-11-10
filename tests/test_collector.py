import asyncio
from datetime import date
import httpx
from rackpulse.collector import Collector
from rackpulse.config import AppConfig, RackConfig
from rackpulse.thanos import ThanosClient
from rackpulse.timewindow import day_window


def test_collector_rejects_stale_sample_and_preserves_zero():
    w = day_window(date(2026, 11, 9))
    first = w.timestamps[0]
    def handler(request):
        is_timestamp = request.url.params['query'].startswith('timestamp(')
        return httpx.Response(200, json={'status': 'success', 'data': {'resultType': 'matrix', 'result': [{'metric': {'host': 'node1', 'gpu_id': 'GPU_0'}, 'values': [[first, str(first-121) if is_timestamp else '99'], [first+60, str(first+60) if is_timestamp else '0']]}]}})
    async def run():
        rack = RackConfig('r', 'node.*', 'delta')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            c = Collector(ThanosClient('http://source', client=client), AppConfig([rack]))
            result = await c.collect_block(rack, 'gpu_utilization', w)
            assert len(result) == 1
            assert result[0].value == 0
            assert result[0].timestamp == first+60
    asyncio.run(run())
