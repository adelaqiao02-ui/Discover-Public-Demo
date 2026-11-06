"""Immutable demo rubric publications and snapshot scores; demonstration only."""
from __future__ import annotations
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
import pandas as pd
from demo_action_analysis import load_demo_actions, score_demo

SAFE_ID=re.compile(r'^[A-Za-z0-9_-]{3,70}$')

def paths(data):
    root=data/'action logs'; return root,root/'rubric_versions',root/'rubric_draft.json'

def _save_atomic(path, content):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        tmp.write_text(content,encoding='utf-8')
        os.replace(tmp,path)
    finally:
        tmp.unlink(missing_ok=True)

def _serialize(obj):
    return json.dumps(obj,indent=2,ensure_ascii=False,sort_keys=True)+'\n'

def save_draft(data, document):
    _,_,draft=paths(data)
    _save_atomic(draft,_serialize(document))

def read_draft(data):
    _,_,draft=paths(data)
    return json.loads(draft.read_text(encoding='utf-8')) if draft.exists() else None

def score_all_synthetic(data, rubric):
    actions,_=load_demo_actions(data,{'role':'admin'},group='All',session='All',learner='All')
    scores,_=score_demo(actions,rubric)
    return scores

def publish(data, rubric):
    root,versions,_=paths(data)
    rid=rubric['rubric_id']
    if not SAFE_ID.fullmatch(rid):raise ValueError('Version ID must use 3–70 letters, digits, underscores or hyphens.')
    versions.mkdir(parents=True,exist_ok=True)
    file=versions/f'{rid}.json'
    snap=versions/f'{rid}_scores.csv'
    if file.exists() or snap.exists():raise ValueError(f'Published version {rid} already exists and cannot be overwritten.')
    payload=copy.deepcopy(rubric)
    payload['published_utc']=datetime.now(timezone.utc).isoformat(timespec='seconds')
    payload['publication_status']='published_demo_only'
    # Write both artifacts before switching active rubric. Never overwrite published files.
    file.write_text(_serialize(payload),encoding='utf-8',errors='strict')
    try:
        scores=score_all_synthetic(data,payload)
        scores.to_csv(snap,index=False,encoding='utf-8-sig')
        metadata={'rubric_id':rid,'published_utc':payload['published_utc'],
                  'snapshot_rows':int(len(scores)),
                  'snapshot_sha256':hashlib.sha256(snap.read_bytes()).hexdigest(),
                  'rubric_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),
                  'data_provenance':'synthetic','clinical_validated':False}
        (versions/f'{rid}_metadata.json').write_text(_serialize(metadata),encoding='utf-8')
        _save_atomic(root/'DEMO_RUBRIC.json',_serialize(payload))
    except Exception:
        file.unlink(missing_ok=True);snap.unlink(missing_ok=True)
        (versions/f'{rid}_metadata.json').unlink(missing_ok=True)
        raise
    return int(len(scores))

def load_rubric_history(data):
    _,versions,_=paths(data)
    records=[]
    for file in sorted(versions.glob('*_metadata.json')):
        try:
            obj=json.loads(file.read_text(encoding='utf-8'))
            records.append(obj)
        except (OSError,ValueError):continue
    return pd.DataFrame(records)

def load_rubric_snapshot(data,rubric_id):
    _,versions,_=paths(data)
    if not isinstance(rubric_id,str) or not SAFE_ID.fullmatch(rubric_id):return pd.DataFrame()
    path=versions/f'{rubric_id}_scores.csv'
    return pd.read_csv(path,dtype={'learner_id':str}) if path.exists() else pd.DataFrame()
