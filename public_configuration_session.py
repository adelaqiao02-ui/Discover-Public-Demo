"""Session-only configuration editor for the synthetic public demo.

Never reads uploaded files, writes to disk, or mutates shared application state.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import streamlit as st
from configuration_editor import field_editor, read_config

KEY = '_public_configuration_demo'


def _state(data: Path):
    if KEY not in st.session_state:
        original = read_config(data / 'config_SYNTHETIC.json')
        if original.get('synthetic') is not True:
            raise ValueError('This public editor requires a synthetic configuration.')
        st.session_state[KEY] = {'active': copy.deepcopy(original), 'draft': copy.deepcopy(original)}
    return st.session_state[KEY]


def render(data: Path):
    st.header('Admin Configuration · Interactive Demo')
    st.warning('SYNTHETIC DEMO ONLY — this is not a real Unity configuration or clinical data.')
    st.info('Changes remain in your current Streamlit session. They do not modify server files, GitHub, or other visitors’ sessions.')
    state = _state(data)
    doc = state['draft']
    entries = doc.get('serializeableList', [])
    st.metric('Configuration records', len(entries))
    st.caption('Edit the fields below, then select Apply configuration to preview your session-only changes.')
    updated = copy.deepcopy(doc)
    error = None
    with st.form('public_configuration_editor', clear_on_submit=False):
        for i, entry in enumerate(entries):
            with st.container(border=True):
                st.markdown(f'**Configuration entry {i + 1}**')
                st.caption(f"Record ID (read-only): {entry.get('guid', 'Not provided')}")
                for j, field in enumerate(entry.get('serializedFields', [])):
                    try:
                        updated['serializeableList'][i]['serializedFields'][j]['data'] = field_editor(
                            field, i, j, 'public_config'
                        )
                    except ValueError as exc:
                        error = str(exc)
        confirmed = st.checkbox('I understand this is fictional demo data and edits are temporary.')
        apply = st.form_submit_button('Apply configuration (this session only)', type='primary')
    if apply:
        try:
            if error:
                raise ValueError(error)
            if not confirmed:
                raise ValueError('Please confirm the synthetic-demo notice.')
            # Confirm structural integrity without allowing new fields or schemas.
            if len(updated.get('serializeableList', [])) != len(entries):
                raise ValueError('Configuration entries cannot be added or removed.')
            for before, after in zip(entries, updated['serializeableList']):
                if before.get('guid') != after.get('guid'):
                    raise ValueError('Record identifiers cannot be changed.')
                bf = before.get('serializedFields', [])
                af = after.get('serializedFields', [])
                if len(bf) != len(af) or any(a.get('fieldName') != b.get('fieldName') for a, b in zip(af, bf)):
                    raise ValueError('Configuration schema cannot be changed.')
            updated['synthetic'] = True
            serialized = json.dumps(updated, ensure_ascii=False, indent=2)
            validated = json.loads(serialized)
            state['active'] = copy.deepcopy(validated)
            state['draft'] = copy.deepcopy(validated)
            st.success('Applied to this browser session. Server configuration remains unchanged.')
        except (ValueError, TypeError, KeyError) as exc:
            st.error(f'Configuration not applied: {exc}')

    with st.expander('Current session configuration preview'):
        st.json(state['active'])
        st.download_button(
            'Download synthetic session configuration (JSON)',
            data=json.dumps(state['active'], ensure_ascii=False, indent=2) + '\n',
            file_name='config_SYNTHETIC_session.json',
            mime='application/json',
        )
    if st.button('Reset to original synthetic configuration', key='public_config_reset'):
        st.session_state.pop(KEY, None)
        # Remove field values so Streamlit widgets reflect the reset baseline.
        for key in list(st.session_state):
            if str(key).startswith('public_config_'):
                st.session_state.pop(key, None)
        st.rerun()
    st.caption('Changes do not automatically alter the fictional action logs or scoring rules.')
