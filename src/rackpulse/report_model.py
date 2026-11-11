"""Read-only adapters for historical report revisions."""
from copy import deepcopy
from datetime import datetime
from .timewindow import TZ, day_window


def normalize_event(event, day):
    e=deepcopy(event)
    for key in ('started_at','first_occurred_at','recovered_at'):
        if e.get(key):
            parsed=datetime.fromisoformat(e[key])
            e[key]=parsed.astimezone(TZ).isoformat() if parsed.tzinfo else None
    e.setdefault('first_occurred_at',e.get('started_at'))
    e.setdefault('total_duration_minutes',None if e['type']=='datasource_error' else e.get('duration_minutes'))
    if 'day_duration_minutes' not in e:
        e['day_duration_minutes']=None
        if e['type']!='datasource_error' and e.get('started_at') and e.get('recovered_at'):
            window=day_window(day)
            start=max(datetime.fromisoformat(e['started_at']),window.start)
            end=min(datetime.fromisoformat(e['recovered_at']),window.end)
            e['day_duration_minutes']=max(0,(end-start).total_seconds()/60)
    if e['type']=='datasource_error' and not e.get('time_basis'):
        e['day_duration_minutes']=e['total_duration_minutes']=None
        e['time_basis']='legacy_unverified'
    return e


def build_report_view(day, report, previous=None, history=None, inventory=None):
    report=deepcopy(report)
    summaries=report.get('summaries',[])
    for s in summaries:
        s['events']=[normalize_event(e,day) for e in s.get('events',[])]
        s['device_health']='unknown'
        for p in s.get('power',{}).values():
            if not p.get('minutes'):
                p['energy_kwh']=None
    if inventory is None and (not summaries or any(s['rack_id'].startswith('GB200-') for s in summaries)):
        inventory=[dict(rack_id=f'GB200-{p}-{i}') for p in (1,2) for i in range(1,17)]
    return dict(day=str(day), report=report, previous=previous, history=history or [], inventory=inventory or [], renderer_version='0.3.0')
