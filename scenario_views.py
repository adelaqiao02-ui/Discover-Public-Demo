"""Pure helpers for rendering scenario metadata correctly (no scoring)."""
import pandas as pd

ALIASES = {'ETC02': 'ETCO2', 'Temp': 'Temperature', 'Cap Refill': 'CapRefill'}

def seconds_from_hms(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parts = value.split(':')
        if len(parts) != 3:
            return None
        h, m, s = (int(v) for v in parts)
        if h < 0 or m not in range(60) or s not in range(60):
            return None
        return h * 3600 + m * 60 + s
    except (TypeError, ValueError):
        return None

def stamp(seconds):
    if seconds is None or pd.isna(seconds):
        return '—'
    seconds=int(seconds)
    return f'{seconds//3600:02d}:{(seconds//60)%60:02d}:{seconds%60:02d}'

def scenario_tables(doc):
    """Separate untimed setup, timestamped events and numeric observations."""
    events=[]; initial=[]; obs=[]
    for idx, item in enumerate(doc.get('history', [])):
        sec=seconds_from_hms(item.get('time', ''))
        intervention=str(item.get('intervention') or '').strip()
        exp=item.get('expected_change') or {}
        actual=item.get('actual_vitals_at_time') or {}
        entry={'event_id':idx,'time_s':sec,'time':stamp(sec),
               'name':intervention or ('Initial Configuration' if sec is None else 'Unnamed Event'),
               'type':'System / Unverified', 'reasoning':str(exp.get('Reasoning') or ''),
               'expected':exp,'actual':actual}
        (initial if sec is None else events).append(entry)
        for kind, values in [('Expected target', exp), ('Actual snapshot', actual)]:
            for name, val in values.items():
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    obs.append({'event_id':idx,'time_s':sec,'time':stamp(sec),'metric':ALIASES.get(name,name),
                                'kind':kind, 'value':float(val),
                                'target_timeframe': exp.get(name + '_timeframe', '') if kind=='Expected target' else ''})
    return events, initial, pd.DataFrame(obs,columns=['event_id','time_s','time','metric','kind','value','target_timeframe'])
