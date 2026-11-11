import asyncio
import json
from copy import deepcopy
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
            payload = deepcopy(text) if isinstance(text,dict) else {'msg_type': 'text', 'content': {'text': text}}
            if self.secret:
                stamp = str(int(time.time()))
                key = f'{stamp}\n{self.secret}'.encode()
                payload.update(timestamp=stamp, sign=base64.b64encode(hmac.new(key, b'', hashlib.sha256).digest()).decode())
            if len(json.dumps(payload,ensure_ascii=False).encode())>20000:
                return {'status':'failed','error':'payload_too_large'}
            try:
                response = await client.post(self.url, json=payload, timeout=self.timeout)
                if response.status_code == 429:
                    if isinstance(text,dict):return {'status':'failed','error':'rate_limited'}
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
                if code==11232 and isinstance(text,dict):return {'status':'failed','error':'rate_limited'}
                if code==11232 and attempt<2:
                    await asyncio.sleep(2**attempt)
                    continue
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
        if 'summaries' not in report:
            return {'status':'failed','error':'legacy_report_requires_structured_summaries'}
        from .cards import render_cards
        from .report_model import build_report_view
        inventory=report.get('configuration',{}).get('racks')
        view=build_report_view(day,report,self.repository.get_report(day-timedelta(days=1)),self.repository.history(day,30),inventory)
        cards=render_cards(view)
        batch=hashlib.sha256(json.dumps(cards,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if force: batch+=f':forced:{time.time_ns()}'
        channel='feishu:'+hashlib.sha256(getattr(self.adapter,'url','feishu-default').encode()).hexdigest()
        any_sent=False
        for index,card in enumerate(cards):
            claim,status=self.repository.claim_card(day,batch,str(index),card,channel=channel)
            if claim is None:
                if status=='sent': continue
                return {'status':status if status in ('unknown','failed') else 'skipped','error':'card_unavailable','card_index':index}
            while True:
                try:
                    result=await self.adapter.send(card)
                except Exception:
                    result={'status':'unknown','error':'adapter_interrupted'}
                self.repository.finish_card(claim,result)
                if result['status']=='sent':break
                if result.get('error')!='rate_limited':return dict(result,card_index=index)
                await asyncio.sleep(1)
                claim,status=self.repository.claim_card(day,batch,str(index),card,channel=channel)
                if claim is None:return dict(result,card_index=index)
            any_sent=True
        return {'status':'sent' if any_sent else 'skipped','cards':len(cards)}
