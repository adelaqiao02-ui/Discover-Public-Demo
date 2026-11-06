"""Data validation & normalization. Raw source files are never changed."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

REQUIRED_GAZE = ['user_id', 'session_id', 'object_id', 'gaze_time', 'time_stamp']
REQUIRED_ACTION = ['group_id', 'session_id', 'learner_id', 'event_time_s', 'action_type', 'target', 'event_source']
SYNTHETIC_TAG = 'synthetic'


def read_csv(path):
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    frame.columns = [str(c).strip() for c in frame.columns]
    return frame


def audit_gaze_file(path, meta):
    """Full-file QA without modifying the file. Raw 0 session ID is not blindly corrected."""
    d = read_csv(path)
    missing = [c for c in REQUIRED_GAZE if c not in d.columns]
    summary = {'file': path.name, 'group': meta.get('group'), 'mapped_session': meta.get('session'),
               'provenance': meta.get('provenance'), 'rows': len(d), 'missing_columns': ', '.join(missing)}
    if missing:
        return summary, pd.DataFrame()
    durations = pd.to_numeric(d['gaze_time'], errors='coerce')
    stamps = pd.to_datetime(d['time_stamp'], errors='coerce', format='mixed')
    raw_ids = sorted(set(d.get('raw_session_id', d['session_id']).astype(str)))
    summary.update({'raw_session_ids': ', '.join(raw_ids[:12]),
        'mapped_session_ids': ', '.join(sorted(set(d['session_id']))[:12]),
        'missing_user': int(d['user_id'].eq('').sum()),
        'missing_object': int(d['object_id'].eq('').sum()),
        'bad_timestamps': int(stamps.isna().sum()),
        'bad_or_nonpositive_duration': int((durations.isna() | (durations <= 0)).sum()),
        'over_10_seconds': int((durations > 10).sum()),
        'duplicate_rows': int(d.duplicated(subset=REQUIRED_GAZE).sum()),
        'unique_learners': int(d.loc[d['user_id'].ne(''), 'user_id'].nunique()),
        'timestamp_days': int(stamps.dropna().dt.date.nunique()),
        'earliest_timestamp': str(stamps.min()), 'latest_timestamp': str(stamps.max()),
        'session_mapping_status': 'provisional' if meta.get('provenance') == 'cleaned_original' else 'generated synthetic'})
    if 'gaze_time_original' in d.columns:
        raw_d = pd.to_numeric(d['gaze_time_original'], errors='coerce')
        summary['source_original_over_10_seconds'] = int((raw_d > 10).sum())
        summary['original_duration_retained'] = True
    else:
        summary['source_original_over_10_seconds'] = None
        summary['original_duration_retained'] = False
    return summary, d


def audit_dataset(data, manifest):
    summaries, issues = [], []
    for relative, meta in manifest['files'].items():
        path = data / relative
        if not path.is_file():
            issues.append({'file':relative,'severity':'error','issue':'File missing'}); continue
        try:
            s, _ = audit_gaze_file(path, meta); summaries.append(s)
            if s.get('missing_columns'):
                issues.append({'file':relative,'severity':'error','issue':'Missing columns: '+s['missing_columns']})
            if s.get('bad_or_nonpositive_duration',0):
                issues.append({'file':relative,'severity':'warning','issue':'Invalid durations present'})
            if s.get('timestamp_days',0) > 1 and meta.get('provenance') == 'cleaned_original':
                issues.append({'file':relative,'severity':'warning','issue':'Multiple recording dates; cannot establish original session boundaries'})
        except Exception as ex:
            issues.append({'file':relative,'severity':'error','issue':str(ex)})
    return pd.DataFrame(summaries), pd.DataFrame(issues,columns=['file','severity','issue'])


def load_action_logs(data):
    """Only ACTION_LOG_*.csv are treated as action logs; eye-gaze and scenario JSON never are."""
    frames, errors = [], []
    for path in sorted((data/'action logs').glob('ACTION_LOG_*.csv')):
        try:
            raw=read_csv(path)
            missing=[c for c in REQUIRED_ACTION if c not in raw]
            if missing: raise ValueError('Required columns missing: '+', '.join(missing))
            raw['event_time_s']=pd.to_numeric(raw['event_time_s'],errors='coerce')
            raw['action_type']=raw['action_type'].str.strip()
            raw['event_source']=raw['event_source'].str.strip().str.lower()
            raw['valid_action_row']=(raw['event_time_s'].notna() & raw['event_time_s'].ge(0)
              & raw['group_id'].str.strip().ne('') & raw['session_id'].str.strip().ne('')
              & raw['learner_id'].str.strip().ne('') & raw['action_type'].ne('')
              & raw['event_source'].isin(['learner','system','unknown']))
            raw['source_file']=path.name
            frames.append(raw)
        except Exception as ex: errors.append({'file':path.name,'error':str(ex)})
    return (pd.concat(frames,ignore_index=True) if frames else pd.DataFrame(columns=REQUIRED_ACTION+['valid_action_row','source_file'])),pd.DataFrame(errors)


def read_scenario(path):
    doc=json.loads(path.read_text(encoding='utf-8-sig'))
    events=[]; observations=[]
    for idx,event in enumerate(doc.get('history',[])):
        t=event.get('time','')
        try:
            items=[float(x) for x in t.split(':')]
            tsec=items[0]*3600+items[1]*60+items[2] if len(items)==3 else None
        except (ValueError,TypeError): tsec=None
        events.append({'event_number':idx,'scenario_time':t,'scenario_time_s':tsec,
          'event_label':str(event.get('intervention','')),
          'event_actor':'UNVERIFIED (not learner action)',
          'reasoning':str((event.get('expected_change') or {}).get('Reasoning',''))})
        for kind, field in [('Observed snapshot','actual_vitals_at_time'),('Expected target','expected_change')]:
            for metric, v in (event.get(field) or {}).items():
                if isinstance(v,(int,float)) and not isinstance(v,bool):
                    metric={'ETC02':'ETCO2','Temp':'Temperature','Cap Refill':'CapRefill'}.get(metric,metric)
                    observations.append({'event_number':idx,'scenario_time_s':tsec,'kind':kind,'metric':metric,'value':v})
    return pd.DataFrame(events),pd.DataFrame(observations)


def gaze_clues(d, max_rows=30):
    """Sort observed gaze events by timestamp and summarize looked-at objects; NEVER call these actions."""
    if d.empty: return pd.DataFrame()
    f=d.copy()
    f['time']=pd.to_datetime(f['time_stamp'],errors='coerce',format='mixed')
    f['duration_s']=pd.to_numeric(f['gaze_time'],errors='coerce')
    f=f[f['duration_s'].between(0,10,inclusive='both') & f['time'].notna() & f['object_id'].notna()]
    if f.empty:return pd.DataFrame()
    summary=(f.groupby(['group','session','user_id','object_id','provenance'],dropna=False)
       .agg(gaze_events=('object_id','size'),observed_gaze_s=('duration_s','sum'),first_seen=('time','min'),last_seen=('time','max'))
       .reset_index().sort_values('observed_gaze_s',ascending=False))
    return summary.head(max_rows)
