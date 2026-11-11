import asyncio
from datetime import date
from rackpulse.repository import Repository
from rackpulse.notifications import DeliveryService


def test_failed_card_retry_does_not_resend_confirmed_card(tmp_path):
    repo=Repository('sqlite:///'+str(tmp_path/'cards.db'));repo.initialize()
    repo.publish_report(date(2026,11,10),{'summaries':[],'text':'old'})
    class Adapter:
        def __init__(self): self.calls=[]; self.fail=True
        async def send(self,payload):
            self.calls.append(payload)
            if len(self.calls)==2 and self.fail:return {'status':'failed','error':'rate_limited'}
            return {'status':'sent'}
    adapter=Adapter()
    async def run():
        service=DeliveryService(repo,adapter)
        assert (await service.send_report(date(2026,11,10)))['status']=='sent'
        assert (await service.send_report(date(2026,11,10)))['status']=='skipped'
    asyncio.run(run())
    assert len(adapter.calls)==4
    assert isinstance(adapter.calls[0],dict)


def test_channel_identity_and_unknown_are_safe(tmp_path):
    repo=Repository('sqlite:///'+str(tmp_path/'identity.db'));repo.initialize()
    claim,_=repo.claim_card(date(2026,11,10),'batch','0',{},channel='a')
    repo.finish_card(claim,{'status':'unknown'})
    assert repo.claim_card(date(2026,11,10),'batch','0',{},channel='a')==(None,'unknown')
    other,status=repo.claim_card(date(2026,11,10),'batch','0',{},channel='b')
    assert other is not None and status=='sending'
