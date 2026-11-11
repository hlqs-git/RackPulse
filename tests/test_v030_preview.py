import asyncio
import json
from argparse import Namespace
from datetime import date
import httpx
from rackpulse.cli import execute
from rackpulse.notifications import DeliveryService,FeishuAdapter
from rackpulse.repository import Repository


def test_cli_cards_equal_actual_payload_and_raw_is_unchanged(tmp_path,monkeypatch):
    url='sqlite:///'+str(tmp_path/'preview.db')
    repo=Repository(url);repo.initialize()
    configuration={'racks':[{'rack_id':'GB200-1-1','gpu_host_pattern':'.*','psu_vendor':'delta'}]}
    config=tmp_path/'racks.yaml';config.write_text(json.dumps(configuration),encoding='utf-8')
    monkeypatch.setenv('DATABASE_URL',url);monkeypatch.setenv('RACK_CONFIG',str(config))
    report={'day':'2026-11-10','configuration':configuration,'summaries':[],'text':'legacy stored body'}
    repo.publish_report(date(2026,11,10),report)
    payloads=[]
    def receive(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200,json={'code':0})
    async def run():
        args=Namespace(command='report',date=date(2026,11,10),format='cards',force=False)
        preview=await execute(args)
        async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as client:
            assert (await DeliveryService(repo,FeishuAdapter('http://example.test',client=client)).send_report(args.date))['status']=='sent'
        assert preview==payloads
        args.format='raw'
        assert await execute(args)==report
        args.format='text'
        text=await execute(args)
        for card in payloads:
            for element in card['card']['elements']:
                assert element['text']['content'] in text
    asyncio.run(run())
