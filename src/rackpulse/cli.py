import argparse
import asyncio
import json
import os
from datetime import date
from .config import load_config
from .repository import Repository
from .collector import Collector
from .thanos import ThanosClient
from .jobs import DailyJob
from .notifications import FeishuAdapter, DeliveryService
from .timewindow import day_window


def main():
    from .logging import configure_logging
    configure_logging()
    parser = argparse.ArgumentParser(prog='rackpulse')
    parser.add_argument('command', choices=['validate-config', 'discover', 'run', 'report', 'send', 'test-webhook'])
    parser.add_argument('--date', type=date.fromisoformat)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--format', choices=['text','cards','raw'], default='text')
    args = parser.parse_args()
    try:
        result = asyncio.run(execute(args))
        print(result if isinstance(result,str) else json.dumps(result, ensure_ascii=False, indent=2))
    except Exception:
        parser.exit(1, '操作失败：请检查配置、数据库和数据源；为保护凭据不输出远端错误正文。\n')


async def execute(args):
    cfg = load_config(os.getenv('RACK_CONFIG', 'config/racks.yaml'))
    if args.command == 'validate-config':
        cfg.validate_ready()
        return {'status': 'valid', 'racks': len(cfg.racks)}
    adapter = FeishuAdapter(os.getenv('FEISHU_WEBHOOK_URL'), os.getenv('FEISHU_SIGNING_SECRET'))
    if args.command == 'test-webhook':
        return await adapter.send('【测试】RackPulse 飞书连接测试')
    if args.date is None:
        raise ValueError('date_required')
    source = ThanosClient(os.environ.get('THANOS_URL', ''), token=os.getenv('THANOS_TOKEN'))
    if args.command == 'discover':
        w = day_window(args.date)
        result = {}
        for vendor in ('liteon', 'delta'):
            series = await source.query_range(f'{vendor}_psu_input_power_watts', w.start, w.timestamps[-1], 3600)
            for s in series:
                rack = s['metric'].get('rack', 'unknown')
                result.setdefault(rack, set()).add(vendor)
        return {rack: sorted(vendors) for rack, vendors in result.items()}
    repo = Repository(os.environ['DATABASE_URL'])
    if args.command == 'report':
        report = repo.get_report(args.date)
        if report is None: raise ValueError('report_missing')
        if getattr(args,'format','text') == 'raw': return report
        from .report_model import build_report_view
        from .cards import render_cards, render_preview
        from datetime import timedelta
        inventory = report.get('configuration',{}).get('racks') or [dict(rack_id=r.rack_id) for r in cfg.racks]
        view = build_report_view(args.date,report,repo.get_report(args.date-timedelta(days=1)),repo.history(args.date,30),inventory)
        return render_cards(view) if args.format == 'cards' else render_preview(view)
    if args.command == 'send':
        return await DeliveryService(repo, adapter).send_report(args.date, args.force)
    return {'task_id': await DailyJob(repo, cfg, Collector(source, cfg)).run(args.date)}


if __name__ == '__main__':
    main()
