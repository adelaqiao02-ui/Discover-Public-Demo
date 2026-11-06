"""Admin-only demonstration scoring rubric editor.

All changes are local and explicitly synthetic. Never treat settings as clinical standards.
"""
from __future__ import annotations
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import uuid

import pandas as pd
import streamlit as st
from versioned_rubrics import save_draft, read_draft, publish, load_rubric_history

WEIGHT_FIELDS = [
    ('task_completion', 'Task Completion'),
    ('action_accuracy', 'Action Accuracy'),
    ('response_time', 'Response Time'),
    ('action_sequence', 'Action Sequence'),
]


def _validate(document):
    if not isinstance(document, dict):
        raise ValueError('Rubric must be a JSON object.')
    if document.get('synthetic') is not True or document.get('approved_for_clinical_assessment') is not False:
        raise ValueError('Demo rubric must remain synthetic and not approved for clinical assessment.')
    weights=document.get('weights', {})
    if set(weights) != {k for k,_ in WEIGHT_FIELDS}:
        raise ValueError('Exactly four expected score weight keys are required.')
    if any(not isinstance(v,(int,float)) or isinstance(v,bool) or not 0<=v<=100 for v in weights.values()):
        raise ValueError('Weights must be numbers from 0 to 100.')
    if abs(sum(weights.values())-100)>1e-8:
        raise ValueError('The four weights must total exactly 100%.')
    for field in ('demo_trigger_time_s','response_threshold_s'):
        if not isinstance(document.get(field),(int,float)) or isinstance(document[field],bool) or not 0<=document[field]<=86400:
            raise ValueError(f'{field} must be between 0 and 86400 seconds.')
    tasks=document.get('tasks')
    if not isinstance(tasks,list) or not tasks:
        raise ValueError('At least one task is required.')
    ids=[]
    for i,t in enumerate(tasks):
        if not isinstance(t,dict) or any(not isinstance(t.get(f),str) or not t[f].strip() for f in ('task_id','action_type','target','display_name')):
            raise ValueError(f'Task row {i+1} needs a non-empty task ID, action type, target and name.')
        ids.append(t['task_id'].strip())
    if len(ids)!=len(set(ids)):
        raise ValueError('Task IDs must be unique.')
    if document.get('response_task_id') not in ids:
        raise ValueError('Response task must be one of the defined task IDs.')
    pairs=document.get('sequence_constraints')
    if not isinstance(pairs,list):
        raise ValueError('Sequence constraints must be a list.')
    for p in pairs:
        if not isinstance(p,list) or len(p)!=2 or any(x not in ids for x in p) or p[0]==p[1]:
            raise ValueError('Each sequence rule must be a pair of different existing task IDs.')
    if len({tuple(p) for p in pairs})!=len(pairs):
        raise ValueError('Sequence rules must not be duplicated.')
    return document


def render_admin_rubric(data: Path):
    st.header('Demo Rubric Settings · Versioned')
    st.warning('SYNTHETIC DEMO ONLY. Published versions and their stored score snapshots are not validated clinical assessments.')
    current_path=data/'action logs'/'DEMO_RUBRIC.json'
    try:
        active=_validate(json.loads(current_path.read_text(encoding='utf-8')))
        current=_validate(read_draft(data) or copy.deepcopy(active))
    except (OSError,ValueError,TypeError) as exc:
        st.error(f'Rubric could not be loaded: {exc}')
        return
    st.info(f"Currently active version: {active['rubric_id']} · Editing a DRAFT does not affect active scores.")
    with st.form('v10_rubric_editor'):
        st.subheader('Draft rubric')
        version=st.text_input('New version ID',value=current['rubric_id'],help='Use a new ID for each publication, e.g. DEMO_RUBRIC_V2')
        description=st.text_area('Description',value=current.get('description',''))
        a,b=st.columns(2)
        trigger=a.number_input('Demo trigger (seconds)',min_value=0,max_value=86400,value=int(current['demo_trigger_time_s']))
        threshold=b.number_input('Response threshold (seconds)',min_value=0,max_value=86400,value=int(current['response_threshold_s']))
        st.subheader('Weight configuration')
        weights={}
        for field,label in WEIGHT_FIELDS:
            weights[field]=st.number_input(f'{label} (%)',min_value=0.0,max_value=100.0,value=float(current['weights'][field]),step=5.0,key='v10_w_'+field)
        st.metric('Total percentage',f'{sum(weights.values()):g}%')
        st.subheader('Required synthetic tasks')
        task_edit=st.data_editor(pd.DataFrame(current['tasks']),num_rows='dynamic',hide_index=True,use_container_width=True,key='v10_tasks')
        st.subheader('Ordering constraints')
        seq_edit=st.data_editor(pd.DataFrame(current['sequence_constraints'],columns=['before_task','after_task']),num_rows='dynamic',hide_index=True,use_container_width=True,key='v10_sequences')
        opts=[str(x).strip() for x in task_edit.get('task_id',pd.Series(dtype=str)).fillna('') if str(x).strip()]
        response=st.selectbox('Response task ID',options=opts,index=opts.index(current['response_task_id']) if current['response_task_id'] in opts else 0 if opts else None)
        understood=st.checkbox('I understand all scores are simulated and not clinical grades.')
        save=st.form_submit_button('Save draft')
        publish_clicked=st.form_submit_button('Publish immutable demo version',type='primary')
    if save or publish_clicked:
        try:
            if not understood: raise ValueError('Confirm that these are synthetic demonstration rules.')
            draft=copy.deepcopy(current)
            draft.update({'rubric_id':version.strip(),'description':description,
                'demo_trigger_time_s':int(trigger),'response_threshold_s':int(threshold),
                'weights':weights,'tasks':task_edit.fillna('').to_dict('records'),
                'sequence_constraints':seq_edit.fillna('')[['before_task','after_task']].values.tolist(),
                'response_task_id':response})
            _validate(draft)
            if not draft['rubric_id']:raise ValueError('Version ID cannot be blank.')
            if publish_clicked:
                published=publish(data,draft)
                save_draft(data,{**draft,'rubric_id':draft['rubric_id']+'_DRAFT'})
                st.success(f"Published {version}: saved a fixed score snapshot for {published} synthetic learner-sessions.")
            else:
                save_draft(data,draft)
                st.success('Draft saved. Active performance calculations were not changed.')
            st.rerun()
        except (ValueError,OSError,KeyError,TypeError) as exc:
            st.error(f'Rubric not saved: {exc}')
    st.subheader('Published rubric versions')
    history=load_rubric_history(data)
    if history.empty:st.info('No published snapshots found.')
    else:st.dataframe(history,hide_index=True,use_container_width=True)
    st.caption('The active rubric changes only on publication. Old immutable snapshots remain on disk and are not recalculated when the draft changes.')
