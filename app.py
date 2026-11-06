import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
import json,hashlib,hmac
from data_pipeline import audit_dataset, load_action_logs, read_scenario, gaze_clues
from demo_action_analysis import load_demo_rubric, load_demo_actions, score_demo
from scenario_views import scenario_tables, stamp
from configuration_editor import render_admin_configuration
from rubric_editor import render_admin_rubric
from public_rubric_session import active_rubric, history as session_rubric_history, snapshot as session_rubric_snapshot, render as render_session_rubric

st.set_page_config(page_title='VR Learner Report Card',layout='wide',page_icon='🎓')
ROOT=Path(__file__).resolve().parent
DATA=ROOT/'sample data'
MANIFEST=json.loads((DATA/'_manifest.json').read_text(encoding='utf-8'))
ACCOUNTS=json.loads((ROOT/'demo_accounts.json').read_text(encoding='utf-8'))

def verify(username,password):
    account=ACCOUNTS.get(username)
    if not account:return None
    calculated=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(account['salt']),account['iterations']).hex()
    return account if hmac.compare_digest(calculated,account['hash']) else None

def login_page():
    st.title('VR Learner Report Card')
    st.caption('Sign in to access your dashboard')
    left,mid,right=st.columns([1,1.2,1])
    with mid:
        with st.form('login'):
            username=st.text_input('Username')
            password=st.text_input('Password',type='password')
            submitted=st.form_submit_button('Sign in',use_container_width=True,type='primary')
        if submitted:
            account=verify(username.strip(),password)
            if account:
                st.session_state['user']={'username':username.strip(),'role':account['role'],'learner_id':account.get('learner_id'),'group':account.get('group')}
                st.rerun()
            else:st.error('Invalid username or password.')
        st.caption('Local demonstration accounts are documented in README.md.')

if 'user' not in st.session_state:
    login_page();st.stop()
u=st.session_state['user']
st.sidebar.title('VR Learner Dashboard')
st.sidebar.write(f"Signed in as **{u['username']}**")
st.sidebar.caption(f"Role: {u['role'].title()}")
if u['role']=='leader':
    st.sidebar.caption(f"Assigned group: {u['group']}")
if st.sidebar.button('Sign out'):
    del st.session_state['user'];st.rerun()

@st.cache_data(show_spinner='Loading recordings...')
def load_one(name):
    p=DATA/name
    d=pd.read_csv(p,dtype={'user_id':str,'session_id':str},low_memory=False)
    for c in ['gaze_time','gaze_time_original']:
        if c in d:d[c]=pd.to_numeric(d[c],errors='coerce')
    d['time_stamp']=pd.to_datetime(d['time_stamp'],errors='coerce')
    d['object_id']=d['object_id'].fillna('').astype(str)
    return d

files=MANIFEST['files']
# Security boundary: data is filtered on the server BEFORE widgets/tables/charts are populated.
recordings=[]
for filename,meta in sorted(files.items()):
    # Restrict available files before loading them; other groups never enter this session.
    if u['role']=='leader' and meta['group'] != u['group']:
        continue
    if u['role']=='student' and u.get('group') and meta['group'] != u['group']:
        continue
    df=load_one(filename)
    if u['role']=='student':
        df=df.loc[df.user_id.eq(str(u['learner_id']))].copy()
    if df.empty:continue
    df['group']=meta['group'];df['session']=meta['session'];df['provenance']=meta['provenance'];df['source_file']=filename
    recordings.append(df)
if not recordings:st.warning('No data available for this account.');st.stop()
all_data=pd.concat(recordings,ignore_index=True)

st.title('Learner Report Card')
st.warning('PUBLIC DEMO — ALL data are fictional; scoring is not clinically validated. Do not upload real learner data.')
if u['role']=='student':
    st.info(f"Student access: only learner **{u['learner_id']}** in group **{u.get('group', 'Unassigned')}** is available.")
elif u['role']=='leader':
    st.info(f"Group Leader access: all learners and both sessions for **{u['group']}** only. Other groups are not loaded.")
else:
    st.info('Administrator access: all groups and learners are visible.')

if u['role']=='admin':
    group=st.sidebar.selectbox('Group',['All']+sorted(all_data.group.unique()))
    learner=st.sidebar.selectbox('Learner ID',['All']+sorted(all_data.user_id.unique()))
elif u['role']=='leader':
    group=u['group']
    learner=st.sidebar.selectbox('Learner ID', ['All'] + sorted(all_data.user_id.unique()))
else:
    group=u.get('group') or 'All';learner=str(u['learner_id'])
session=st.sidebar.selectbox('Session',['All']+sorted(all_data.session.unique()))
d=all_data
if group!='All':d=d[d.group.eq(group)]
if learner!='All':d=d[d.user_id.eq(learner)]
if session!='All':d=d[d.session.eq(session)]
if d.empty:st.warning('No records match the filters.');st.stop()

# Objects are tentative heuristic labels, not action evidence.
def aoi(s):
    s=str(s).lower()
    if 'monitor' in s:return 'Monitor'
    if any(x in s for x in ['nasal','bipap','rebreather']):return 'Respiratory'
    if any(x in s for x in ['iv_bag','medline','blooddraw']):return 'IV / Sampling'
    if any(x in s for x in ['thermometer','istat']):return 'Diagnostics'
    if any(x in s for x in ['chestsounds','caprefill','pulsehaptic','teenright','teenleft','liver','chestrub']):return 'Patient'
    if any(x in s for x in ['autohand','robothand','loadingscreen']):return 'Self / Technical'
    if any(x in s for x in ['floor','room','wall','counter','middle','bed','background']):return 'Environment'
    return 'Other / Unverified'

def render_scenario_timeline(events, chart_key):
    """Compact scene-event display. These events are NOT confirmed learner actions."""
    timed = events.dropna(subset=['scenario_time_s']).sort_values('scenario_time_s').copy()
    if timed.empty:
        st.info('No events with valid timestamps to plot.')
        return

    def stamp(seconds):
        seconds = int(round(float(seconds)))
        return f'{seconds // 60:02d}:{seconds % 60:02d}'

    start = float(timed['scenario_time_s'].min())
    end = float(timed['scenario_time_s'].max())
    span = max(1., end - start)
    left, right = max(0., start - max(8., span * .10)), end + max(8., span * .10)
    xvals = timed['scenario_time_s'].astype(float).tolist()
    labels = [str(x).strip() or 'Unnamed event' for x in timed['event_label']]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[start, end] if len(timed) > 1 else [left, right],
        y=[0, 0], mode='lines',
        line=dict(color='#cbd5e1', width=4),
        hoverinfo='skip', showlegend=False,
    ))
    fig.add_trace(go.Scatter(
        x=xvals, y=[0] * len(xvals), mode='markers',
        marker=dict(size=15, color=['#2563eb' if i == 0 else '#0d9488' for i in range(len(xvals))],
                    line=dict(color='white', width=2)),
        customdata=[[label, stamp(x), int(n)] for label, x, n in zip(labels, xvals, timed['event_number'])],
        hovertemplate='<b>%{customdata[0]}</b><br>Time: %{customdata[1]}<br>Event #: %{customdata[2]}<extra></extra>',
        showlegend=False,
    ))
    # Alternating labels keep a sparse scene timeline compact and readable.
    for i, (x, label) in enumerate(zip(xvals, labels)):
        fig.add_annotation(
            x=x, y=0, text=f'<b>{label}</b><br>{stamp(x)}', showarrow=False,
            yshift=42 if i % 2 == 0 else -42,
            font=dict(size=12, color='#334155'), align='center',
        )
    ticks = sorted(set(xvals))
    fig.update_layout(
        height=245, margin=dict(l=25, r=25, t=55, b=35),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        xaxis=dict(range=[left,right], tickvals=ticks, ticktext=[stamp(x) for x in ticks],
                   title='Scenario time (MM:SS)', showgrid=False, zeroline=False),
        yaxis=dict(range=[-1,1], visible=False, fixedrange=True),
    )
    st.plotly_chart(fig, use_container_width=True, key=chart_key)
    if len(timed) > 1:
        gaps = timed['scenario_time_s'].astype(float).diff().iloc[1:]
        st.caption(f'{len(timed)} timestamped events · {stamp(end-start)} between first and last recorded event. '
                   'This is NOT a learner response time.')
    else:
        st.caption('One timestamped event. No elapsed interval can be inferred.')

# Two-tier sidebar navigation replaces the overflowing horizontal tab strip.
# Page access is role-scoped before page rendering (not merely visually hidden).
PAGES = {
    'Overview': ['Report Card'],
    'Performance': ['Action Analysis', 'Demo Performance', 'Session Progress'],
    'Analytics': ['Eye Tracking', 'Scenario & Vitals', 'Comparison', 'Data Quality', 'Data Dictionary'],
}
if u['role'] == 'admin':
    PAGES['Administration'] = ['Admin Configuration', 'Demo Rubric Settings']

st.sidebar.divider()
st.sidebar.markdown('### Navigation')
section = st.sidebar.selectbox('Workspace', list(PAGES), key='nav_section')
active_page = st.sidebar.radio('Page', PAGES[section], key=f'nav_page_{section}')
st.sidebar.caption('Synthetic performance is for demonstration only.')
if active_page == 'Report Card':
    st.subheader('Learner performance overview')
    st.caption('Gaze is observational evidence; simulated action scores below are clearly separated from real assessment.')
    # Load only synthetic action rows authorized to this account, same as Demo Performance.
    overview_rubric=active_rubric(DATA)
    overview_actions,_=load_demo_actions(DATA,u,group=group,session=session,learner=learner)
    overview_scores,_=score_demo(overview_actions,overview_rubric)
    st.warning('REAL PERFORMANCE: NOT ASSESSED. Synthetic actions and scoring rules are product demonstration fixtures, not real learner performance.')
    if not overview_scores.empty:
        st.markdown('#### Synthetic action performance · demonstration only')
        p1,p2,p3,p4=st.columns(4)
        p1.metric('Demo overall score',f"{overview_scores['DEMO_SCORE_NOT_VALIDATED'].mean():.1f} / 100")
        p2.metric('Demo task completion',f"{overview_scores['task_completion_pct'].mean():.1f}%")
        p3.metric('Demo action accuracy',f"{overview_scores['action_accuracy_pct'].mean():.1f}%")
        p4.metric('Demo response delay',f"{overview_scores['response_delay_s'].mean():.1f} s" if overview_scores['response_delay_s'].notna().any() else 'Unavailable')
        breakdown=overview_scores[['task_completion_pct','action_accuracy_pct','sequence_pct']].mean().rename({
            'task_completion_pct':'Task completion','action_accuracy_pct':'Action accuracy','sequence_pct':'Action sequence'}).reset_index()
        breakdown.columns=['Dimension','Illustrative percent']
        st.plotly_chart(px.bar(breakdown,x='Dimension',y='Illustrative percent',range_y=[0,100],
                               title='SYNTHETIC performance dimensions (not validated)'),
                        use_container_width=True,key='v10_overview_dimensions')
        st.caption(f"Active demo rubric: {overview_rubric.get('rubric_id','Unknown')}. For per-student drill-down, use Performance > Demo Performance.")
    else:
        st.info('No synthetic action records for this filter; this is missing demonstration data, not failed performance.')
    st.markdown('#### Recorded activity · gaze data (not action scores)')
    c1,c2,c3,c4=st.columns(4)
    c1.metric('Gaze records',f'{len(d):,}')
    c2.metric('Learners in gaze data',d.user_id.nunique())
    c3.metric('Group/session combinations',len(d[['group','session']].drop_duplicates()))
    c4.metric('Distinct viewed objects',d.object_id.nunique())
    with st.expander('Evidence quality and data availability',expanded=False):
        st.dataframe(pd.DataFrame([
            {'Evidence':'Actual learner action log','Status':'Not supplied; only synthetic demo actions','Meaning':'Cannot measure real task completion'},
            {'Evidence':'Validated grading rubric','Status':'Not supplied','Meaning':'Cannot produce real scores'},
            {'Evidence':'Scenario event history','Status':'Available, limited','Meaning':'System context, actor unverified'},
            {'Evidence':'Eye gaze','Status':'Only fictional, generated demo rows','Meaning':'Attention clues only'},
        ]),hide_index=True,use_container_width=True)
    overview=d.groupby(['group','session','user_id','provenance'],as_index=False).agg(
        records=('object_id','size'),recorded_gaze_seconds=('gaze_time','sum'),objects=('object_id','nunique'))
    with st.expander('Gaze recording details and authorized export'):
        st.dataframe(overview,use_container_width=True,hide_index=True)
        st.download_button('Download authorized gaze summary',overview.to_csv(index=False).encode('utf-8-sig'),'learner_gaze_summary.csv','text/csv')

if active_page == 'Action Analysis':
    st.header('Action Analysis')
    action_mode = st.radio(
        'Data source', ['Synthetic Demo', 'Real Data'],
        horizontal=True, key='v12_action_data_mode',
        help='Synthetic Demo is the default and contains invented records. Real Data only uses non-synthetic imported logs.'
    )
    action_data, action_errors = load_action_logs(DATA)
    # Apply the same role restrictions BEFORE any action-log UI can access records.
    if u['role']=='leader':
        action_data=action_data[action_data['group_id'].eq(str(u['group']))].copy()
    if u['role']=='student':
        action_data=action_data[action_data['group_id'].eq(str(u['group'])) & action_data['learner_id'].eq(str(u['learner_id']))].copy()
    if group!='All': action_data=action_data[action_data['group_id'].eq(group)]
    if learner!='All': action_data=action_data[action_data['learner_id'].eq(learner)]
    if session!='All': action_data=action_data[action_data['session_id'].eq(session)]
    if action_mode == 'Synthetic Demo':
        st.warning('SYNTHETIC DATA — invented actions for product demonstration only. These are not real learner actions or validated clinical scores.')
        if 'data_provenance' not in action_data.columns:
            synthetic_actions = action_data.iloc[0:0].copy()
        else:
            synthetic_actions = action_data.loc[
                action_data['valid_action_row']
                & action_data['data_provenance'].astype(str).str.lower().eq('synthetic')
                & action_data['event_source'].eq('learner')
            ].copy()
        if synthetic_actions.empty:
            st.info('No synthetic actions match the selected group, learner or session. Try adjusting your sidebar filters.')
        else:
            demo = synthetic_actions.sort_values(['group_id', 'learner_id', 'session_id', 'event_time_s']).copy()
            m1,m2,m3,m4 = st.columns(4)
            m1.metric('Synthetic actions', f'{len(demo):,}')
            m2.metric('Demo learners', demo['learner_id'].nunique())
            m3.metric('Group / session pairs', len(demo[['group_id','session_id']].drop_duplicates()))
            m4.metric('Action types', demo['action_type'].nunique())
            learners_demo = sorted(demo['learner_id'].astype(str).unique().tolist())
            selected_demo = st.selectbox('Learner for action timeline', learners_demo, key='v12_demo_learner')
            view = demo.loc[demo['learner_id'].astype(str).eq(selected_demo)].copy()
            view['action_display'] = view['action_type'].astype(str) + ' → ' + view['target'].astype(str)
            st.subheader('Action timeline · synthetic')
            fig = px.scatter(view, x='event_time_s', y='action_display', color='session_id',
                symbol='action_result' if 'action_result' in view.columns else None,
                hover_data=[c for c in ['group_id','learner_id','task_id','action_result'] if c in view.columns],
                labels={'event_time_s':'Simulated elapsed time (seconds)', 'action_display':'Invented operation', 'session_id':'Session'},
                title='Synthetic actions by session')
            fig.update_layout(height=max(300,min(540,215 + view['action_display'].nunique()*26)),
                              margin=dict(l=5,r=10,t=55,b=20))
            st.plotly_chart(fig,use_container_width=True,key='v12_synthetic_action_timeline')
            st.subheader('Action details · synthetic')
            cols = [c for c in ['group_id','session_id','learner_id','event_time_s','action_type','target','task_id','action_result','data_provenance'] if c in view.columns]
            st.dataframe(view[cols], hide_index=True, use_container_width=True)
            st.download_button('Download selected synthetic actions',view[cols].to_csv(index=False).encode('utf-8-sig'),
                               f'synthetic_actions_{selected_demo}.csv', 'text/csv',key='v12_download_synthetic_actions')
            st.caption('Displayed actions are generated fixtures. No action score or claim about actual learner performance is inferred from these records.')
    else:
        st.caption('Real Data mode only counts non-synthetic imported action events. Missing evidence does not mean a student performed zero actions.')
        real_actions=action_data[action_data['valid_action_row'] & action_data['event_source'].eq('learner') & action_data.get('data_provenance', pd.Series('unverified',index=action_data.index)).ne('synthetic')]
        sys_actions=action_data[action_data['valid_action_row'] & action_data['event_source'].eq('system') & action_data.get('data_provenance', pd.Series('unverified',index=action_data.index)).ne('synthetic')]
        unknown_actions=action_data[action_data['valid_action_row'] & action_data['event_source'].eq('unknown') & action_data.get('data_provenance', pd.Series('unverified',index=action_data.index)).ne('synthetic')]
        a1,a2,a3,a4=st.columns(4)
        a1.metric('Verified-label learner events',len(real_actions))
        a2.metric('System events in action log',len(sys_actions))
        a3.metric('Unknown-actor events',len(unknown_actions))
        a4.metric('Action score','Not assessed')
        st.caption('“Learner events” means event_source=learner in an imported log. The source label must be validated with the VR developer; it does not independently verify clinical correctness.')
        if not real_actions.empty:
            st.subheader('Imported learner action timeline')
            chart=real_actions.sort_values('event_time_s').copy()
            chart['action_target']=chart['action_type']+' → '+chart['target']
            st.plotly_chart(px.scatter(chart,x='event_time_s',y='action_target',color='learner_id',symbol='session_id',hover_data=['group_id','source_file'],title='Recorded actions (simulation-relative seconds, as supplied)'),use_container_width=True,key='chart_222')
            counts=chart.groupby(['group_id','session_id','learner_id','action_type'],as_index=False).size().rename(columns={'size':'logged_events'})
            st.dataframe(counts,hide_index=True,use_container_width=True)
            st.dataframe(chart[['group_id','session_id','learner_id','event_time_s','action_type','target','event_source','source_file']],hide_index=True,use_container_width=True)
            st.download_button('Download authorized action events',chart.to_csv(index=False).encode('utf-8-sig'),'authorized_action_events.csv','text/csv')
            st.warning('A task completion score requires task definitions, matching rules, outcome status and an approved rubric. Chronological order alone does not prove a correct sequence.')
        else:
            st.warning('No learner action log is available for this selection. **This is missing evidence, NOT zero actions or failed performance.**')
            st.code('sample data/action logs/ACTION_LOG_*.csv',language='text')
            st.caption('See action logs/README_ACTION_LOG.txt and ACTION_LOG_TEMPLATE.csv for the input schema. The template has headers only and is never counted as action evidence.')
        if not action_errors.empty and u['role']=='admin':
            st.error('Action log import errors');st.dataframe(action_errors,use_container_width=True)
        st.divider()
        st.subheader('Scenario event timeline (context — not confirmed learner actions)')
        scenario_names=sorted({files[f]['scenario_file'] for f in d['source_file'].unique()})
        if scenario_names:
            sc=st.selectbox('Scenario',scenario_names,key='action_scenario')
            ev,vitals=read_scenario(DATA/sc)
            if 'SYNTHETIC' in sc:st.warning('Synthetic scenario demonstration data')
            if not ev.empty:
                render_scenario_timeline(ev, chart_key='action_analysis_scenario_timeline')
                st.markdown('**Event details (recorded in scenario JSON)**')
                detail=ev[['event_number','scenario_time','event_label','event_actor']].copy()
                detail.columns=['Event #','Time (HH:MM:SS)','Event description','Actor / action attribution']
                st.dataframe(detail,hide_index=True,use_container_width=True)
                if ev['scenario_time_s'].isna().any():
                    st.caption('Entries with missing/invalid time appear in the table but not on the timeline.')
            st.caption('Scenario time and gaze timestamps use different origins; **no synchronized action response latency** can be calculated. “5 minute decomp values” is not confirmed to be a learner intervention.')
        st.divider()
        st.subheader('Object attention clues (not object interactions)')
        evidence=gaze_clues(d,max_rows=30)
        if not evidence.empty:
            st.dataframe(evidence,hide_index=True,use_container_width=True)
            st.plotly_chart(px.bar(evidence.head(15),x='object_id',y='observed_gaze_s',color='provenance',title='Objects seen in eye-tracking records — no proof of use'),use_container_width=True,key='chart_255')
            st.download_button('Download authorized gaze clues',evidence.to_csv(index=False).encode('utf-8-sig'),'authorized_gaze_clues.csv','text/csv')
        st.caption('The top-object list is computed only from the user-authorized recordings. Synthetic values are labeled; do not infer real learner progress from them.')
        st.divider()
        st.subheader('Action readiness assessment')
        st.dataframe(pd.DataFrame([
            {'Analysis':'Scenario event timeline','Status':'Available','Reliability':'Event source/actor unverified'},
            {'Analysis':'Gaze-based object attention','Status':'Available','Reliability':'Not a physical action'},
            {'Analysis':'Learner action timeline','Status':'Conditional','Reliability':'Requires imported learner action log'},
            {'Analysis':'Task completion','Status':'Not assessed','Reliability':'Requires approved expected-action list and outcome flags'},
            {'Analysis':'Sequence correctness','Status':'Not assessed','Reliability':'Requires task rules/ordering constraints'},
            {'Analysis':'Response time','Status':'Not assessed','Reliability':'Requires synchronized event/action clocks'},
            {'Analysis':'Overall performance grade','Status':'Not assessed','Reliability':'Requires validated clinical education rubric'},
        ]),hide_index=True,use_container_width=True)

if active_page == 'Demo Performance':
    st.header('Synthetic Action Analysis & Demo Performance')
    st.error('SYNTHETIC / INVENTED DEMONSTRATION DATA ONLY — NOT REAL LEARNER ACTIONS, NOT CLINICAL GRADES.')
    st.caption('All action logs on this tab were constructed for UI testing. Demo trigger times, required tasks, outcome flags, sequence rules, response threshold, and score weights were invented. They are not derived from the eye-tracking CSV or validated by clinicians.')
    rubric=active_rubric(DATA)
    if u['role']=='admin':
        history=session_rubric_history(DATA)
        with st.expander('Published rubric history · immutable demo score snapshots',expanded=False):
            if history.empty:
                st.caption('No published demo rubrics yet.')
            else:
                st.dataframe(history,hide_index=True,use_container_width=True)
                old_id=st.selectbox('Published version',history['rubric_id'].tolist(),key='v10_history_choice')
                historical=session_rubric_snapshot(DATA,old_id)
                if not historical.empty:
                    st.dataframe(historical,use_container_width=True,hide_index=True)
                    st.download_button('Download saved version scores',historical.to_csv(index=False).encode('utf-8-sig'),
                                      f'demo_scores_{old_id}.csv','text/csv',key='v10_history_download')
    demo, demo_errors=load_demo_actions(DATA,u,group=group,session=session,learner=learner)
    scored,tasks=score_demo(demo,rubric)
    if demo.empty:
        st.warning('No synthetic action events match your authorized learner/group/session selection.')
    else:
        c1,c2,c3,c4=st.columns(4)
        c1.metric('Demo action records',len(demo))
        c2.metric('Demo learner-sessions',len(scored))
        c3.metric('Average demo task completion',f"{scored['task_completion_pct'].mean():.1f}%")
        c4.metric('Average synthetic-only score',f"{scored['DEMO_SCORE_NOT_VALIDATED'].mean():.1f}/100")
        st.caption('Score is the output of an **unvalidated demonstration rubric**, not evidence of actual achievement. For mixed real/synthetic gaze groups, synthetic action events remain entirely fictitious.')
        st.subheader('Demo performance by learner and session')
        st.dataframe(scored,use_container_width=True,hide_index=True)
        st.download_button('Download authorized synthetic demo scores',scored.to_csv(index=False).encode('utf-8-sig'),'synthetic_demo_scores.csv','text/csv')
        # Learner IDs are identifiers, not continuous measurements. Plot as categories.
        # Faceted axes are independent so G1/G2/G3 do not inherit empty ID ranges.
        score_plot = scored.copy()
        score_plot['learner_label'] = score_plot['learner_id'].astype(str).map(lambda x: f'L{x}')
        score_plot['session'] = score_plot['session'].astype(str)
        score_plot['group'] = score_plot['group'].astype(str)
        score_plot = score_plot.sort_values(['group', 'learner_label', 'session'])
        score_fig = px.bar(
            score_plot,
            x='learner_label',
            y='DEMO_SCORE_NOT_VALIDATED',
            color='session',
            facet_col='group' if score_plot['group'].nunique() > 1 else None,
            barmode='group',
            category_orders={'session': sorted(score_plot['session'].unique())},
            labels={
                'learner_label': 'Learner ID',
                'DEMO_SCORE_NOT_VALIDATED': 'Demo performance score (0–100)',
                'session': 'Session',
                'group': 'Group',
            },
            hover_data={'group': True, 'learner_id': True, 'session': True},
            title='SYNTHETIC scores — unvalidated demo rubric',
            range_y=[0, 100],
        )
        score_fig.update_xaxes(type='category', matches=None, tickangle=0)
        score_fig.update_yaxes(range=[0, 100])
        score_fig.update_layout(
            bargap=0.24,
            bargroupgap=0.08,
            legend_title_text='Session',
            margin=dict(l=30, r=30, t=75, b=60),
        )
        st.plotly_chart(score_fig, use_container_width=True,key='chart_323')
        st.caption('Each learner ID is treated as a category; S1 and S2 are shown side by side. All values are synthetic and not validated.')
        st.subheader('Task completion · synthetic')
        task_chart=tasks.copy();task_chart['status']=task_chart['completed_in_demo'].map({True:'Completed in demo',False:'Not completed in demo'})
        st.plotly_chart(px.bar(task_chart.groupby(['task','status'],as_index=False).size(),x='task',y='size',color='status',barmode='stack',title='Synthetic task outcomes (learner-session counts)'),use_container_width=True,key='chart_327')
        st.dataframe(task_chart,use_container_width=True,hide_index=True)
        st.subheader('Action timeline · synthetic')
        timeline=demo.sort_values(['group_id','session_id','learner_id','event_time_s']).copy()
        timeline['actor']=timeline['group_id']+'/'+timeline['session_id']+' / '+timeline['learner_id']
        timeline['action_label']=timeline['action_type']+' → '+timeline['target']
        st.plotly_chart(px.scatter(timeline,x='event_time_s',y='actor',color='action_result',symbol='task_id',hover_data=['action_label','event_id','data_provenance'],title='SYNTHETIC ACTION TIMELINE (seconds since invented session origin)'),use_container_width=True,key='chart_333')
        st.subheader('Action sequence · synthetic')
        select_col,other=st.columns(2)
        with select_col:
            subject=st.selectbox('Synthetic learner/session',scored.apply(lambda r:f"{r['group']} | {r['session']} | {r['learner_id']}",axis=1).tolist(),key='demo_subject')
        g,s,l=subject.split(' | ')
        selected=timeline[timeline.group_id.eq(g)&timeline.session_id.eq(s)&timeline.learner_id.eq(l)]
        st.dataframe(selected[['event_time_s','task_id','action_label','action_result','notes']],use_container_width=True,hide_index=True)
        selected_summary=scored[(scored.group==g)&(scored.session==s)&(scored.learner_id==l)].iloc[0]
        st.write(f"**Demo ordering constraints satisfied:** {int(selected_summary['sequence_constraints_met'])} / {int(selected_summary['sequence_constraints_total'])}. **Demo response delay:** {selected_summary['response_delay_s'] if pd.notna(selected_summary['response_delay_s']) else 'Unavailable'} seconds.")
        st.caption('Response delay uses an **invented trigger at 60s**, not the original scenario JSON. It cannot be interpreted as a real patient-event response time.')
        st.caption('Demo scoring criteria are managed by the administrator under Administration → Demo Rubric Settings. These are illustrative rules, not validated clinical assessment.')
        st.download_button('Download authorized synthetic action records',demo.to_csv(index=False).encode('utf-8-sig'),'synthetic_action_records.csv','text/csv')
    if not demo_errors.empty and u['role']=='admin':
        st.error('Synthetic action import validation errors');st.dataframe(demo_errors,use_container_width=True,hide_index=True)

if active_page == 'Session Progress':
    st.header('S1 vs S2 · Synthetic session comparison')
    st.warning('SYNTHETIC DATA ONLY. Changes across simulated sessions do NOT demonstrate real learning progress.')
    rubric=active_rubric(DATA)
    # Load both S1 and S2 regardless of sidebar session filter: otherwise paired comparisons disappear.
    progress_actions,_=load_demo_actions(DATA,u,group=group,session='All',learner=learner)
    progress_scores,_=score_demo(progress_actions,rubric)
    if progress_scores.empty:
        st.info('No authorized synthetic action data to compare.')
    else:
        # One learner must have both sessions; do not compare unmatched learners or groups.
        pair=progress_scores.pivot_table(index=['group','learner_id'],columns='session',
            values=['DEMO_SCORE_NOT_VALIDATED','task_completion_pct','action_accuracy_pct','sequence_pct','response_delay_s'],
            aggfunc='first')
        if not {'S1','S2'}.issubset(set(progress_scores['session'])):
            st.info('Both S1 and S2 are required for a paired comparison.')
        else:
            score_pair=progress_scores.pivot_table(index=['group','learner_id'],columns='session',values='DEMO_SCORE_NOT_VALIDATED',aggfunc='first').dropna(subset=['S1','S2'])
            if score_pair.empty:
                st.info('There are no students with both S1 and S2 in this authorized selection.')
            else:
                score_pair=score_pair.reset_index()
                score_pair['Difference (S2 − S1)']=score_pair['S2']-score_pair['S1']
                score_pair['Learner']=score_pair['group']+' / L'+score_pair['learner_id'].astype(str)
                st.subheader('Paired demo score changes')
                m1,m2,m3=st.columns(3)
                m1.metric('Learners with two demo sessions',len(score_pair))
                m2.metric('Average S1 score',f"{score_pair['S1'].mean():.1f}")
                m3.metric('Average S2 − S1',f"{score_pair['Difference (S2 − S1)'].mean():+.1f}")
                long=score_pair.melt(id_vars=['group','learner_id','Learner'],value_vars=['S1','S2'],var_name='Session',value_name='Demo score')
                figure=px.bar(long,x='Learner',y='Demo score',color='Session',barmode='group',
                    range_y=[0,100],title='Paired synthetic learner scores',category_orders={'Session':['S1','S2']})
                figure.update_xaxes(type='category')
                st.plotly_chart(figure,use_container_width=True,key='v10_session_pairs')
                st.dataframe(score_pair[['group','learner_id','S1','S2','Difference (S2 − S1)']],use_container_width=True,hide_index=True)
                # Show components for a selected matched learner.
                st.subheader('One learner · score components')
                choice=st.selectbox('Learner',score_pair['Learner'].tolist(),key='v10_pair_select')
                chosen=score_pair.loc[score_pair['Learner'].eq(choice)].iloc[0]
                unit=progress_scores.loc[progress_scores.group.eq(chosen['group']) & progress_scores.learner_id.eq(chosen['learner_id'])].copy()
                components={'task_completion_pct':'Completion','action_accuracy_pct':'Accuracy','sequence_pct':'Sequence'}
                part=unit.melt(id_vars=['session'],value_vars=list(components),var_name='Dimension',value_name='Percent')
                part['Dimension']=part['Dimension'].map(components)
                st.plotly_chart(px.bar(part,x='Dimension',y='Percent',color='session',barmode='group',range_y=[0,100],
                    title='S1 / S2 illustrative component comparison'),use_container_width=True,key='v10_components')
                st.download_button('Download authorized paired session report',score_pair.to_csv(index=False).encode('utf-8-sig'),
                                   'synthetic_session_progress.csv','text/csv')
                st.caption('Only paired group + learner IDs are included. The demo action logs are invented; synthetic differences are not evidence of improvement.')

if active_page == 'Eye Tracking':
    st.subheader('Eye Tracking (supporting evidence)')
    temp=d[d.gaze_time.between(0,10)].copy();temp['AOI']=temp.object_id.map(aoi)
    summary=temp.groupby('AOI',as_index=False).agg(duration_s=('gaze_time','sum'),events=('object_id','size')).sort_values('duration_s',ascending=False)
    a,b=st.columns(2)
    with a:st.plotly_chart(px.bar(summary,x='AOI',y='duration_s',title='Recorded gaze seconds by AOI'),use_container_width=True,key='chart_355')
    with b:st.plotly_chart(px.pie(summary,names='AOI',values='duration_s',hole=.55,title='Gaze share (not a score)'),use_container_width=True,key='chart_356')
    st.dataframe(summary,use_container_width=True,hide_index=True)
    st.caption('AOI name mapping is heuristic; all fictional gaze durations are generated for UI demonstration, not clinical competency.')
    st.subheader('Most-viewed objects')
    obj=temp.groupby('object_id',as_index=False).agg(duration_s=('gaze_time','sum'),events=('object_id','size')).sort_values('duration_s',ascending=False).head(25)
    st.plotly_chart(px.bar(obj,x='object_id',y='duration_s'),use_container_width=True,key='chart_361')
if active_page == 'Scenario & Vitals':
    st.subheader('Scenario Events & Patient Vitals')
    st.caption('Scenario-level information, not evidence that a specific learner performed these interventions.')
    if u['role']=='student':
        st.caption('Shared curriculum scenario — no other learner records are shown.')
    options=sorted(set(files[x]['scenario_file'] for x in d.source_file.unique()))
    chosen=st.selectbox('Scenario JSON',options)
    history=json.loads((DATA/chosen).read_text(encoding='utf-8-sig'))
    synthetic_scenario=bool(history.get('synthetic'))
    if synthetic_scenario:
        st.warning('SYNTHETIC SCENARIO — demonstration template only, not a recorded patient outcome.')
    else:
        st.info('Original scenario file. Events are system / unverified events, not verified learner actions.')

    timed_events, setup_events, vital_data=scenario_tables(history)
    first_time=min((e['time_s'] for e in timed_events), default=None)
    last_time=max((e['time_s'] for e in timed_events), default=None)
    c1,c2,c3,c4=st.columns(4)
    c1.metric('Timestamped events',len(timed_events))
    c2.metric('Untimed setup rows',len(setup_events))
    c3.metric('First event', stamp(first_time))
    c4.metric('Last event', stamp(last_time))
    st.caption('Clock is scenario-relative (HH:MM:SS). Untimed setup is excluded from event timing charts.')

    st.markdown('#### Event timeline')
    timed_df=pd.DataFrame([{'event_number':e['event_id'],'scenario_time':e['time'],
                            'scenario_time_s':e['time_s'],'event_label':e['name']} for e in timed_events])
    if not timed_df.empty:
        render_scenario_timeline(timed_df, chart_key='scenario_vitals_event_timeline')
    else:
        st.info('No timestamped scenario events are available.')

    st.markdown('#### Event details')
    if timed_events:
        st.dataframe(pd.DataFrame([{'Time':e['time'],'Event':e['name'],'Type':e['type'],
                                    'Event ID':e['event_id']} for e in timed_events]),
                     hide_index=True,use_container_width=True)
    else:
        st.info('No timestamped event rows.')
    for e in timed_events:
        with st.expander(f"{e['time']}  ·  {e['name']}  (Event {e['event_id']})"):
            st.markdown('**Reasoning from scenario JSON**')
            st.write(e['reasoning'] or 'Not provided.')
            l,r=st.columns(2)
            with l:
                st.markdown('**Expected change and target timeframes**')
                st.json(e['expected'],expanded=False)
            with r:
                st.markdown('**Actual vitals snapshot at event**')
                st.json(e['actual'],expanded=False)
    if setup_events:
        with st.expander(f'Initial configuration / untimed rows ({len(setup_events)})'):
            st.caption('These entries have no valid scenario time. They are not measured events.')
            for e in setup_events:
                st.markdown(f"**Setup record {e['event_id']} — {e['name']}**")
                st.write(e['reasoning'] or 'No notes provided.')
                st.json({'expected_change':e['expected'],'actual_vitals_at_time':e['actual']},expanded=False)

    st.markdown('#### Patient vitals — expected target vs actual snapshot')
    # Only timestamped values can be plotted along scenario time.
    plotted=vital_data[vital_data.time_s.notna()].copy()
    if plotted.empty:
        st.info('No vitals observations with valid event timestamps.')
    else:
        metric=st.selectbox('Vital sign',sorted(plotted.metric.unique()),key='scenario_vital_sign')
        subset=plotted.loc[plotted.metric.eq(metric)].sort_values(['kind','time_s']).copy()
        fig=go.Figure()
        palette={'Expected target':'#2563eb','Actual snapshot':'#0d9488'}
        for kind in ('Expected target','Actual snapshot'):
            part=subset[subset.kind.eq(kind)]
            if part.empty:continue
            fig.add_trace(go.Scatter(
                x=part.time_s,y=part.value,
                mode='lines+markers' if len(part)>1 else 'markers',
                name=kind,line=dict(color=palette[kind],width=2,dash='dash' if kind=='Expected target' else 'solid'),
                marker=dict(size=11),
                customdata=part[['time','event_id','target_timeframe']].fillna('').to_numpy(),
                hovertemplate='<b>'+kind+'</b><br>Event: %{customdata[1]}<br>Time: %{customdata[0]}<br>Value: %{y}<br>Target timeframe: %{customdata[2]}<extra></extra>'
            ))
        ticks=sorted(subset.time_s.dropna().unique().tolist())
        fig.update_layout(
            title=f'{metric} — event-recorded target and snapshot',height=335,
            margin=dict(l=30,r=20,t=65,b=40),legend_title_text='Record kind',
            xaxis=dict(title='Scenario event time (MM:SS)',tickmode='array',tickvals=ticks,
                       ticktext=[f'{int(t)//60:02d}:{int(t)%60:02d}' for t in ticks],showgrid=True),
            yaxis=dict(title=metric),hovermode='x unified'
        )
        st.plotly_chart(fig,use_container_width=True,key='chart_449')
        readable=subset[['time','event_id','kind','value','target_timeframe']].copy()
        readable.columns=['Event time','Event ID','Record kind','Value','Target timeframe']
        st.dataframe(readable,use_container_width=True,hide_index=True)
        st.caption('Expected targets are shown at the event where they were entered, NOT at their projected future fulfillment time. Lines connect event records for readability only; no continuous patient trajectory is inferred. Missing actual snapshots stay missing.')
    st.warning('Do NOT use target-vs-snapshot differences to grade learners. The timestamps do not establish completed interventions, and target timeframes may refer to future changes. Gaze and scenario clocks are not synchronized.')
if active_page == 'Comparison':
    st.subheader('Groups & sessions — descriptive comparison')
    t=d.groupby(['group','session','user_id','provenance'],as_index=False).agg(records=('gaze_time','size'),duration_s=('gaze_time','sum'))
    if u['role'] in ('admin','leader'):
        st.checkbox('Synthetic rows included (labeled)',value=True,disabled=True)
    st.plotly_chart(px.bar(t,x='session',y='duration_s',color='group',barmode='group',hover_data=['user_id','provenance'],title='Recorded gaze duration (NOT performance score)'),use_container_width=True,key='chart_460')
    st.dataframe(t,use_container_width=True,hide_index=True)
    st.caption('All gaze observations are fictional. Comparisons are interface demonstrations, not measured learner progress.')
if active_page == 'Data Quality':
    st.subheader('Data quality & repair audit')
    # Revalidate only authorized CSVs. The shared raw backup is administrator-only.
    eligible={n:files[n] for n in d['source_file'].unique()} if u['role']!='student' else {}
    if u['role']=='student': st.caption('Full-file quality audit is restricted because the CSV may contain other learners. Student-level quality summary is shown below.')
    with st.expander('Expanded per-file validation (computed from current dataset)',expanded=True):
        qa,issues=audit_dataset(DATA,{'files':eligible})
        if not qa.empty:
            st.dataframe(qa,use_container_width=True,hide_index=True)
            st.download_button('Download authorized quality report',qa.to_csv(index=False).encode('utf-8-sig'),'data_quality_report.csv','text/csv')
        if not issues.empty:st.dataframe(issues,use_container_width=True,hide_index=True)
        st.caption('Public demo: group and session identifiers are fictional and generated directly.')

    st.info('PUBLIC DEMO: All CSVs are freshly generated, entirely fictional records. No original gaze files or cleaning audits are packaged.')
    audit=d.groupby(['group','session','provenance'],as_index=False).agg(records=('gaze_time','size'))
    st.dataframe(audit,use_container_width=True,hide_index=True)
    st.caption('No real-source downloads are available in the public demo.')
if active_page == 'Data Dictionary':
    st.subheader('Data dictionary & provenance')
    st.dataframe(pd.DataFrame([
        {'field':'user_id','meaning':'Invented learner identifier','confidence':'Synthetic'},
        {'field':'session_id','meaning':'Invented S1/S2 scenario labels','confidence':'Synthetic'},
        {'field':'object_id','meaning':'Name of gaze-hit object','confidence':'Raw'},
        {'field':'gaze_time','meaning':'Generated fictional duration in seconds','confidence':'Synthetic'},
        {'field':'gaze_time_original','meaning':'Copy of the generated fictional duration','confidence':'Synthetic'},
        {'field':'time_stamp','meaning':'Generated fictional timestamps','confidence':'Synthetic'},
        {'field':'cleaning_flag','meaning':'Marks capped or synthetic rows','confidence':'Derived'},
        {'field':'expected_change','meaning':'Fictional scenario targets; not learner actions','confidence':'Synthetic'},
        {'field':'actual_vitals_at_time','meaning':'Fictional patient snapshot at scenario event','confidence':'Synthetic'},
    ]),use_container_width=True,hide_index=True)
    st.markdown('**Six group/session datasets**')
    authorized_files = {name: meta for name, meta in files.items() if u['role']=='admin' or (u.get('group') and meta['group']==u['group'] and name in set(d['source_file']))}
    st.dataframe(pd.DataFrame([{'file':name,**meta} for name,meta in authorized_files.items()]),use_container_width=True,hide_index=True)
    st.caption('PUBLIC DEMO ONLY: shared demonstration credentials are not production authentication; all data are fictional.')

# Server-side role check is repeated at entry to each editing module.
if u['role'] == 'admin' and active_page == 'Admin Configuration':
    st.info('Public demo: configuration editing is disabled. This admin view is read-only for public visitors.')
    st.json(json.loads((DATA/'config_SYNTHETIC.json').read_text(encoding='utf-8')))
if u['role'] == 'admin' and active_page == 'Demo Rubric Settings':
    render_session_rubric(DATA)
