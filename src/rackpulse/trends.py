from datetime import timedelta


def build_trends(day,reports,days):
    indexed={r['day']:r for r in reports if r.get('day')}
    result=[]
    for offset in range(days-1,-1,-1):
        d=str(day-timedelta(days=offset));r=indexed.get(d);ss=r.get('summaries',[]) if r else []
        weight=sum(s.get('valid_gpu_minutes',0) for s in ss if s.get('gpu_average_utilization') is not None)
        point={'day':d,'gpu_utilization':sum(s['gpu_average_utilization']*s.get('valid_gpu_minutes',0) for s in ss if s.get('gpu_average_utilization') is not None)/weight if weight else None,'valid_gpu_minutes':weight,'rack_count':len(ss)}
        for source in ('full_psu','partial_psu','gpu_proxy'):
            valid=[s['power'][source] for s in ss if s.get('power',{}).get(source,{}).get('minutes',0)>0 and s['power'][source].get('energy_kwh') is not None]
            point[source+'_mwh']=sum(p['energy_kwh'] for p in valid)/1000 if valid else None
            point[source+'_coverage']=sum(p['minutes'] for p in valid)/(len(ss)*1440) if ss else None
        result.append(point)
    return result


def rank_idle_power(summaries,low=10,coverage=.95):
    eligible=[s for s in summaries if s.get('gpu_average_utilization') is not None and s['gpu_average_utilization']<low and s.get('gpu_completeness',0)>=coverage and s.get('power',{}).get('full_psu',{}).get('minutes',0)>=1440*coverage and s['power']['full_psu'].get('average_watts') is not None]
    return sorted(eligible,key=lambda s:(-s['power']['full_psu']['average_watts'],s['rack_id']))
