import hashlib
import json
from dataclasses import asdict
from datetime import date, timedelta
from .analysis import analyze_rack
from .domain import DeviceSample
from .report import render_report
from .timewindow import day_window, DayWindow
import logging


class DailyJob:
    def __init__(self, repository, config, collector):
        self.repository, self.config, self.collector = repository, config, collector

    async def run(self, day, task_id=None):
        self.config.validate_ready()
        task_id = task_id or self.repository.create_task(day)
        repo = self.repository
        try:
            with repo.acquire_day(day):
                repo.update_task(task_id, 'running')
                window = day_window(day)
                fingerprint = hashlib.sha256(json.dumps(asdict(self.config), sort_keys=True).encode()).hexdigest()
                prefix = f'{day}:{fingerprint}:'
                summaries, errors = [], []
                history = repo.history(day)
                previous_state = repo.get_state(day-timedelta(days=1))
                for rack in self.config.racks:
                    samples, rack_errors = [], []
                    try:
                        brand_conflict = await self.collector.check_brand(rack, window)
                    except Exception:
                        brand_conflict = False
                        rack_errors.append(f'{rack.rack_id}:brand_check_failed')
                    for hour in range(24):
                        block = DayWindow(window.start+timedelta(hours=hour), window.start+timedelta(hours=hour+1))
                        for metric in ('gpu_utilization', 'gpu_power', 'psu_power'):
                            if metric == 'psu_power' and brand_conflict:
                                continue
                            key = f'{prefix}{rack.rack_id}:{hour}:{metric}'
                            payload = repo.checkpoint(key)
                            if payload is None:
                                try:
                                    values = await self.collector.collect_block(rack, metric, block)
                                    payload = [asdict(s) for s in values]
                                    repo.save_checkpoint(task_id, key, payload)
                                except Exception:
                                    rack_errors.append(f'{rack.rack_id}:{hour}:{metric}:query_failed')
                                    continue
                            samples.extend(DeviceSample(**s) for s in payload)
                    s = analyze_rack(rack, samples, window, [x for h in history for x in h['summaries'] if x['rack_id'] == rack.rack_id], self.config.rules, previous_state=previous_state.get(rack.rack_id))
                    if rack_errors or brand_conflict:
                        s['events'].append({'rack_id': rack.rack_id, 'device': None, 'type': 'brand_conflict' if brand_conflict else 'datasource_error', 'severity': 'Critical', 'started_at': window.start.isoformat(), 'recovered_at': None, 'duration_minutes': 1440, 'suggestion': '核对PSU品牌配置及数据源连接；此日报采集不完整。'})
                    errors.extend(rack_errors)
                    if brand_conflict:
                        errors.append(f'{rack.rack_id}:brand_conflict')
                    summaries.append(s)
                previous = repo.get_report(day-timedelta(days=1))
                payload = {'day': str(day), 'timezone': 'Asia/Shanghai', 'config_fingerprint': fingerprint, 'rules': self.config.rules, 'configuration': asdict(self.config), 'summaries': summaries, 'errors': errors, 'complete': not errors, 'comparable_changes': comparisons(summaries, previous), 'text': render_report(day, summaries, previous)}
                if errors:
                    payload['text'] = '【采集不完整】\n' + payload['text']
                existing = repo.get_report(day)
                if errors and existing and existing.get('complete'):
                    repo.update_task(task_id, 'failed', 'incomplete_rerun_preserved_previous')
                    return task_id
                state = {s['rack_id']: s['rule_state'] for s in summaries}
                repo.publish_report(day, payload, state=state)
                if not errors:
                    repo.clear_checkpoints(prefix)
                repo.update_task(task_id, 'partial' if errors else 'succeeded')
                logging.getLogger('rackpulse').info('daily_task_finished task=%s status=%s', task_id, 'partial' if errors else 'succeeded')
        except Exception:
            repo.update_task(task_id, 'failed', 'task_failed_check_configuration_and_source')
            logging.getLogger('rackpulse').error('daily_task_failed task=%s', task_id)
        return task_id


def comparisons(summaries, previous):
    old = {s['rack_id']: s for s in previous['summaries']} if previous else {}
    result = {}
    for s in summaries:
        p = old.get(s['rack_id'])
        values = {}
        for source, power in s['power'].items():
            comparable = p and power['minutes'] == 1440 and p['power'][source]['minutes'] == 1440 and s['full_psu_device_sets'] == p['full_psu_device_sets'] and source == 'full_psu'
            values[source] = {'comparable': bool(comparable), 'energy_delta_kwh': power['energy_kwh']-p['power'][source]['energy_kwh'] if comparable else None}
        result[s['rack_id']] = values
    return result
