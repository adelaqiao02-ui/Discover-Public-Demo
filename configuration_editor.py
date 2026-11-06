"""Admin-only, form-based editor for Unity-style configuration JSON.
This module must ONLY be invoked from an administrator-restricted page.
"""
from __future__ import annotations
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import uuid

import streamlit as st


def unwrap(v):
    if isinstance(v, dict) and '$values' in v:
        return v['$values']
    return v


def read_config(path: Path):
    doc=json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(doc,dict) or not isinstance(doc.get('serializeableList'),list):
        raise ValueError('Expected an object with a serializeableList array.')
    for entry in doc['serializeableList']:
        if not isinstance(entry,dict) or not isinstance(entry.get('serializedFields'),list):
            raise ValueError('Each serializeableList entry must contain serializedFields array.')
        for f in entry['serializedFields']:
            if not isinstance(f,dict) or not isinstance(f.get('fieldName'),str):
                raise ValueError('Each serialized field needs a fieldName.')
    return doc


def as_text(v):
    return v if isinstance(v,str) else json.dumps(v,ensure_ascii=False,indent=2)


def field_editor(field, entry_index, field_index, prefix):
    name=field['fieldName']
    value=field.get('data')
    key=f'{prefix}_{entry_index}_{field_index}'
    # Preserve original value type for roundtrip. Text values get plain input boxes.
    if isinstance(value,str):
        if len(value)>130 or '\n' in value:
            edited=st.text_area(name,value=value,key=key,height=100)
        else:
            edited=st.text_input(name,value=value,key=key)
        return edited
    if isinstance(value,bool):
        return st.checkbox(name,value=value,key=key)
    if isinstance(value,(int,float)) and not isinstance(value,bool):
        return st.number_input(name,value=value,key=key)
    if value is None:
        raw=st.text_input(f'{name} — JSON value',value='null',key=key)
    else:
        raw=st.text_area(f'{name} — JSON value',value=as_text(value),height=155,key=key,
                         help='Structured fields must remain valid JSON. Use the existing schema.')
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f'{name}: invalid JSON ({e.msg}, line {e.lineno}).') from e


def render_admin_configuration(data: Path):
    st.header('Admin Configuration')
    st.caption('Administrator only · View and edit configuration fields without exposing the raw JSON tree.')
    available=sorted(p for p in data.glob('*.json') if p.name.lower().startswith('config') and p.is_file())
    if not available:
        st.warning('No configuration JSON found. Upload a Unity configuration file below.')
    else:
        selected=st.selectbox('Current configuration file',[p.name for p in available],key='admin_config_file')
        path=data/selected
        try:
            doc=read_config(path)
        except (ValueError, OSError) as exc:
            st.error(f'Cannot load configuration: {exc}')
            return
        if doc.get('synthetic'):
            st.warning('SYNTHETIC PLACEHOLDER — this is an illustrative configuration, not an actual Unity export.')
        else:
            st.success('Configuration loaded. Verify values before using in a real session.')
        st.markdown('#### Current configuration')
        entries=doc['serializeableList']
        st.metric('Configured scenarios / records',len(entries))
        updated=copy.deepcopy(doc)
        error=None
        with st.form('admin_edit_config',clear_on_submit=False):
            for i,entry in enumerate(entries):
                with st.container(border=True):
                    st.markdown(f'**Configuration entry {i+1}**')
                    fields=entry['serializedFields']
                    for j,field in enumerate(fields):
                        try:
                            updated['serializeableList'][i]['serializedFields'][j]['data']=field_editor(field,i,j,path.name)
                        except ValueError as exc:
                            error=str(exc)
                    st.caption(f"Record ID (read-only): {entry.get('guid','Not provided')}")
            confirm=st.checkbox('I understand that saving changes the active configuration copy.',value=False)
            save=st.form_submit_button('Save configuration',type='primary',disabled=not bool(entries))
        if save:
            if error:st.error(error)
            elif not confirm:st.error('Please confirm before saving.')
            else:
                try:
                    # Re-validate the entire updated configuration before touching the file.
                    if not isinstance(updated.get('serializeableList'),list):
                        raise ValueError('serializeableList must be a list.')
                    serialized=json.dumps(updated,ensure_ascii=False,indent=2)
                    validated=json.loads(serialized)
                    if any(not isinstance(e.get('serializedFields'),list) for e in validated['serializeableList']):
                        raise ValueError('Invalid serializedFields.')
                    backups=data/'config_backups'
                    backups.mkdir(exist_ok=True)
                    timestamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
                    backup=backups/f'{path.stem}_{timestamp}_{uuid.uuid4().hex[:6]}.json'
                    shutil.copy2(path,backup)
                    temp=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
                    try:
                        temp.write_text(serialized+'\n',encoding='utf-8')
                        os.replace(temp,path)
                    finally:
                        if temp.exists():temp.unlink()
                    st.success(f'Saved {path.name}. Original backed up as {backup.name}.')
                    st.rerun()
                except Exception as exc:
                    st.error(f'Could not save configuration: {exc}')
        st.caption('The file is saved locally in sample data. Prior versions are stored in sample data/config_backups.')

    with st.expander('Import another configuration JSON (administrator only)'):
        uploaded=st.file_uploader('Select a configuration .json file',type=['json'],key='new_config_upload')
        if uploaded is not None:
            try:
                parsed=json.loads(uploaded.getvalue().decode('utf-8-sig'))
                if not isinstance(parsed,dict) or not isinstance(parsed.get('serializeableList'),list):
                    raise ValueError('Not a supported Unity configuration: serializeableList is missing.')
                st.caption(f"Ready: {len(parsed['serializeableList'])} configuration entries")
                target=data/('config_imported_'+uuid.uuid5(uuid.NAMESPACE_URL,uploaded.name+str(len(uploaded.getvalue()))).hex[:10]+'.json')
                if st.button('Import configuration',type='secondary'):
                    if target.exists():
                        st.error('This filename already exists. Existing configuration was not overwritten.')
                    else:
                        target.write_text(json.dumps(parsed,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                        st.success(f'Imported {target.name}. Select it above to edit.')
                        st.rerun()
            except (UnicodeError,ValueError) as exc:
                st.error(f'Upload validation failed: {exc}')
