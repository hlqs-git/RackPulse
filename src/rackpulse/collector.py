import asyncio
import json
from .domain import DeviceSample

METRICS = {'gpu_utilization': 'gpu_utilization_percent', 'gpu_power': 'gpu_power_watts'}


class Collector:
    def __init__(self, client, config, concurrency=4, freshness=120):
        self.client, self.config = client, config
        self.limit = asyncio.Semaphore(concurrency)
        self.freshness = freshness

    async def collect_block(self, rack, metric, window):
        psu = metric == 'psu_power'
        name = f'{rack.psu_vendor}_psu_input_power_watts' if psu else METRICS[metric]
        selector = f'{name}{{rack={json.dumps(rack.rack_id)}}}' if psu else f'{name}{{host=~{json.dumps(rack.gpu_host_pattern)}}}'
        async with self.limit:
            series = await self.client.query_range(selector, window.start, window.timestamps[-1], 60)
            stamps = await self.client.query_range(f'timestamp({selector})', window.start, window.timestamps[-1], 60)
        def identity(labels):
            return tuple(sorted((k, v) for k, v in labels.items() if k != '__name__'))
        freshness = {identity(s['metric']): {int(t): float(v) for t, v in s['values']} for s in stamps}
        result = []
        for s in series:
            labels = s['metric']
            host = labels.get('host')
            device_id = labels.get('psu_id' if psu else 'gpu_id')
            if not host or device_id is None:
                raise ValueError('missing_device_identity')
            if not psu and self.config.rack_for_host(host) != rack:
                raise ValueError('ambiguous_gpu_mapping')
            device = f'{rack.rack_id}/{host}/{device_id}'
            original = freshness.get(identity(labels), {})
            for t, v in s['values']:
                t = int(t)
                age = t-original.get(t, float('-inf'))
                if 0 <= age <= self.freshness:
                    result.append(DeviceSample(metric, device, t, float(v)))
        return result

    async def check_brand(self, rack, window):
        other = 'liteon' if rack.psu_vendor == 'delta' else 'delta'
        query = f'{other}_psu_input_power_watts{{rack={json.dumps(rack.rack_id)}}}'
        async with self.limit:
            result = await self.client.query_range(query, window.start, window.timestamps[-1], 60)
        return any(s.get('values') for s in result)
