import asyncio
import base64
import hashlib
import hmac
import time
import httpx
from datetime import timedelta
from .report import render_report, split_notification


class FeishuAdapter:
    def __init__(self, url, secret=None, client=None, timeout=15):
        self.url, self.secret, self.client, self.timeout = url, secret, client, timeout

    async def send(self, text):
        if not self.url:
            return {'status': 'failed', 'error': 'webhook_unconfigured'}
        if self.client is None:
            async with httpx.AsyncClient() as client:
                return await self._send(client, text)
        return await self._send(self.client, text)

    async def _send(self, client, text):
        for attempt in range(3):
            payload = {'msg_type': 'text', 'content': {'text': text}}
            if self.secret:
                stamp = str(int(time.time()))
                key = f'{stamp}\n{self.secret}'.encode()
                payload.update(timestamp=stamp, sign=base64.b64encode(hmac.new(key, b'', hashlib.sha256).digest()).decode())
            try:
                response = await client.post(self.url, json=payload, timeout=self.timeout)
                if response.status_code == 429:
                    if attempt < 2:
                        await asyncio.sleep(2**attempt)
                        continue
                    return {'status': 'failed', 'error': 'rate_limited'}
                if response.status_code >= 500:
                    return {'status': 'unknown', 'error': 'remote_server_error'}
                if response.status_code != 200:
                    return {'status': 'failed', 'error': f'http_{response.status_code}'}
                body = response.json()
                code = body.get('code', body.get('StatusCode'))
                return {'status': 'sent'} if code == 0 else {'status': 'failed', 'error': 'business_rejected'}
            except (httpx.TransportError, ValueError):
                return {'status': 'unknown', 'error': 'delivery_uncertain'}
        return {'status': 'failed', 'error': 'retry_exhausted'}


class DeliveryService:
    def __init__(self, repository, adapter):
        self.repository, self.adapter = repository, adapter

    async def send_report(self, day, force=False):
        report = self.repository.get_report(day)
        if not report:
            return {'status': 'failed', 'error': 'report_missing'}
        text = report['text']
        if report.get('summaries'):
            previous = self.repository.get_report(day-timedelta(days=1))
            text = render_report(day, report['summaries'], previous)
            if report.get('complete') is False:
                text = '【采集不完整】\n' + text
        parts = split_notification(text)
        digest = hashlib.sha256(text.encode()).hexdigest()
        if force:
            digest += f':forced:{time.time_ns()}'
        if not self.repository.claim_delivery(str(day), 'feishu', digest):
            return {'status': 'skipped', 'error': 'already_claimed'}
        result = {'status': 'sent'}
        for index, part in enumerate(parts):
            result = await self.adapter.send(f'[{index+1}/{len(parts)}]\n{part}' if len(parts)>1 else part)
            self.repository.record_part(str(day), digest, index, result)
            if result['status'] != 'sent':
                break
        self.repository.finish_delivery(str(day), 'feishu', digest, result)
        return result
