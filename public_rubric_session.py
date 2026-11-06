"""Session-isolated synthetic rubric editing for PUBLIC Streamlit demos.

No filesystem writes, no shared cache mutation, no real data or clinical claims.
"""
from __future__ import annotations
import copy
import json
import re
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from demo_action_analysis import load_demo_rubric, load_demo_actions, score_demo
from rubric_editor import WEIGHT_FIELDS, _validate
from versioned_rubrics import load_rubric_history, load_rubric_snapshot

SAFE_ID = re.compile(r'^[A-Za-z0-9_-]{3,70}$')
KEY = '_public_rubric_demo'


def _store(data):
    if KEY not in st.session_state:
        baseline = _validate(load_demo_rubric(data))
        st.session_state[KEY] = {
            'active': copy.deepcopy(baseline),
            'draft': copy.deepcopy(baseline),
            'versions': {},
            'published_order': [],
        }
    return st.session_state[KEY]


def active_rubric(data):
    return copy.deepcopy(_store(data)['active'])


def history(data):
    baseline = load_rubric_history(data)
    entries = [v['metadata'] for v in _store(data)['versions'].values()]
    if not entries:
        return baseline
    return pd.concat([baseline, pd.DataFrame(entries)], ignore_index=True)


def snapshot(data, rubric_id):
    store = _store(data)
    if rubric_id in store['versions']:
        return store['versions'][rubric_id]['scores'].copy()
    return load_rubric_snapshot(data, rubric_id)


def render(data):
    st.header('Demo Rubric Settings · Interactive')
    st.warning('SYNTHETIC DEMO ONLY — these are not clinically validated rules or real learner grades.')
    st.info('Changes are isolated to your browser session. Publishing updates your demo scores only; it never modifies server files, other users, or GitHub.')
    store = _store(data)
    active, current = store['active'], store['draft']
    st.caption(f"Active rubric: **{active['rubric_id']}** · A saved draft does not affect scoring until published.")
    with st.form('public_rubric_form'):
        st.subheader('Draft settings')
        version = st.text_input('New version ID', value=current['rubric_id'] if current['rubric_id'] != active['rubric_id'] else 'DEMO_RUBRIC_V2', help='Example: DEMO_RUBRIC_V2')
        description = st.text_area('Description', value=current.get('description',''))
        c1,c2 = st.columns(2)
        trigger = c1.number_input('Demo trigger (seconds)', min_value=0, max_value=86400, value=int(current['demo_trigger_time_s']))
        threshold = c2.number_input('Response threshold (seconds)', min_value=0, max_value=86400, value=int(current['response_threshold_s']))
        st.subheader('Weight configuration')
        weights = {}
        for field,label in WEIGHT_FIELDS:
            weights[field] = st.number_input(f'{label} (%)', min_value=0.0, max_value=100.0,
                                             value=float(current['weights'][field]), step=5.0, key='public_w_'+field)
        total = sum(weights.values())
        st.metric('Total weight', f'{total:g}%')
        st.caption('The four weights must add up to exactly 100%.')
        st.subheader('Required synthetic tasks')
        task_df = st.data_editor(pd.DataFrame(current['tasks']), num_rows='dynamic', hide_index=True,
                                 use_container_width=True, key='public_task_table')
        st.subheader('Action sequence constraints')
        seq_df = st.data_editor(pd.DataFrame(current['sequence_constraints'], columns=['before_task','after_task']),
                                num_rows='dynamic', hide_index=True, use_container_width=True, key='public_sequence_table')
        options = [str(x).strip() for x in task_df.get('task_id',pd.Series(dtype=str)).fillna('') if str(x).strip()]
        response = st.selectbox('Response task ID', options=options,
                                index=options.index(current['response_task_id']) if current['response_task_id'] in options else 0,
                                disabled=not options)
        confirmed = st.checkbox('I understand these rules and results are fictional demonstrations.')
        save = st.form_submit_button('Save draft')
        publish = st.form_submit_button('Publish demo version (this session only)', type='primary')
    if save or publish:
        try:
            if not confirmed:
                raise ValueError('Please confirm the synthetic-demo disclaimer.')
            rid = version.strip()
            if not SAFE_ID.fullmatch(rid):
                raise ValueError('Version ID must be 3–70 letters, digits, underscores, or hyphens.')
            draft = copy.deepcopy(current)
            draft.update({
                'rubric_id': rid, 'description': description,
                'demo_trigger_time_s': int(trigger), 'response_threshold_s': int(threshold),
                'weights': weights, 'tasks': task_df.fillna('').to_dict('records'),
                'sequence_constraints': seq_df.fillna('')[['before_task','after_task']].values.tolist(),
                'response_task_id': response,
                'synthetic': True, 'approved_for_clinical_assessment': False,
            })
            _validate(draft)
            if publish:
                existing = set(history(data)['rubric_id'].tolist())
                if rid in existing:
                    raise ValueError('Version ID already published. Choose a new version ID.')
                all_actions,errors = load_demo_actions(data, {'role':'admin'}, group='All', session='All', learner='All')
                if not errors.empty:
                    raise ValueError('Could not read all synthetic action logs; cannot publish score snapshot.')
                scores,_ = score_demo(all_actions,draft)
                now=datetime.now(timezone.utc).isoformat(timespec='seconds')
                store['versions'][rid]={
                    'rubric':copy.deepcopy(draft),'scores':scores.copy(),
                    'metadata':{'rubric_id':rid,'published_utc':now,'snapshot_rows':len(scores),
                                'data_provenance':'synthetic','clinical_validated':False,'scope':'this browser session only'}
                }
                store['published_order'].append(rid)
                store['active'] = copy.deepcopy(draft)
                store['draft'] = copy.deepcopy(draft)
                st.success(f'Published {rid} for this session. Saved {len(scores)} synthetic score rows; other visitors are unaffected.')
            else:
                store['draft'] = copy.deepcopy(draft)
                st.success('Draft saved in this browser session; active scores remain unchanged.')
        except (ValueError, KeyError, TypeError, OSError) as exc:
            st.error(f'Rubric was not saved: {exc}')
    st.subheader('Published versions and saved scores')
    history_df = history(data)
    if history_df.empty:
        st.caption('No published rubrics.')
    else:
        st.dataframe(history_df, hide_index=True, use_container_width=True)
    if st.button('Reset this session to the original demo rubric', key='public_reset_rubric'):
        del st.session_state[KEY]
        # Clear associated edit widget states to avoid old unsaved values on reset.
        for k in ['public_task_table','public_sequence_table'] + ['public_w_'+field for field,_ in WEIGHT_FIELDS]:
            st.session_state.pop(k,None)
        st.rerun()
    st.caption('Session changes are temporary and may disappear when the app session ends. They are never written to disk.')
