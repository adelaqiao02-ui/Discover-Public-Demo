"""Synthetic action performance calculations, exclusively illustrative."""
from pathlib import Path
import json
import pandas as pd

REQUIRED=['group_id','session_id','learner_id','event_time_s','action_type','target','event_source','task_id','action_result','data_provenance']

def load_demo_rubric(data: Path):
    return json.loads((data/'action logs'/'DEMO_RUBRIC.json').read_text(encoding='utf-8'))

def load_demo_actions(data: Path, role: dict, group='All', session='All', learner='All'):
    frames=[];errors=[]
    for path in sorted((data/'action logs').glob('ACTION_LOG_*_SYNTHETIC.csv')):
        try:
            # Pre-filter file based on group from file name, before loading into a role's session.
            file_group=path.name.split('_')[2]
            if role['role'] in ('leader','student') and file_group != str(role.get('group')):
                continue
            if group!='All' and file_group!=str(group):continue
            f=pd.read_csv(path,dtype=str,keep_default_na=False,encoding='utf-8-sig')
            missing=[c for c in REQUIRED if c not in f.columns]
            if missing:raise ValueError('Missing columns '+', '.join(missing))
            f=f[f['group_id'].eq(file_group) & f['data_provenance'].eq('synthetic') & f['event_source'].eq('learner')].copy()
            if role['role']=='student':f=f[f['learner_id'].eq(str(role['learner_id']))].copy()
            if learner!='All':f=f[f['learner_id'].eq(str(learner))].copy()
            if session!='All':f=f[f['session_id'].eq(str(session))].copy()
            f['event_time_s']=pd.to_numeric(f['event_time_s'],errors='coerce')
            f=f[f['event_time_s'].notna() & f['event_time_s'].ge(0) & f['action_result'].isin(['success','failed'])]
            f['source_file']=path.name
            frames.append(f)
        except Exception as ex:
            errors.append({'file':path.name,'error':str(ex)})
    return pd.concat(frames,ignore_index=True) if frames else pd.DataFrame(columns=REQUIRED+['source_file']), pd.DataFrame(errors)

def score_demo(actions:pd.DataFrame,rubric:dict):
    """Scores only synthetic data against an invented demo rubric; no real clinical assessment."""
    if actions.empty:return pd.DataFrame(),pd.DataFrame()
    outputs=[];details=[]
    tasks={x['task_id']:x for x in rubric['tasks']}
    weight=rubric['weights'];required=set(tasks)
    for (group,session,learner), subset in actions.groupby(['group_id','session_id','learner_id']):
        s=subset.sort_values(['event_time_s','event_id'] if 'event_id' in subset else ['event_time_s'])
        success=s[s['action_result'].eq('success')]
        completed=set(success['task_id']) & required
        completeness=100*len(completed)/len(required)
        attempts=s[s['task_id'].isin(required)]
        accuracy=100*len(success)/len(attempts) if len(attempts) else 0
        first=success.groupby('task_id')['event_time_s'].min().to_dict()
        constraints=rubric['sequence_constraints']
        valid_order=sum(1 for a,b in constraints if a in first and b in first and first[a]<first[b])
        # Missing prerequisite pairs are zero credit under this demo rubric.
        sequence_pct=100*valid_order/len(constraints) if constraints else 0
        response_task=rubric['response_task_id'];trigger=rubric['demo_trigger_time_s'];limit=rubric['response_threshold_s']
        response_s=first.get(response_task,None)
        delay=None if response_s is None else max(0,float(response_s)-trigger)
        response_pct=100 if delay is not None and delay <= limit else 0
        total=round((completeness*weight['task_completion']+accuracy*weight['action_accuracy']+
                 response_pct*weight['response_time']+sequence_pct*weight['action_sequence'])/100,1)
        outputs.append({'group':group,'session':session,'learner_id':learner,
          'actions_logged':len(s),'tasks_completed':len(completed),'tasks_required':len(required),
          'task_completion_pct':round(completeness,1),'action_accuracy_pct':round(accuracy,1),
          'response_delay_s':delay,'demo_response_within_threshold':delay is not None and delay<=limit,
          'sequence_constraints_met':valid_order,'sequence_constraints_total':len(constraints),
          'sequence_pct':round(sequence_pct,1),'DEMO_SCORE_NOT_VALIDATED':total,
          'data_provenance':'synthetic','rubric_id':rubric['rubric_id']})
        for task_id,task in tasks.items():
            instances=s[s['task_id'].eq(task_id)]
            details.append({'group':group,'session':session,'learner_id':learner,'task_id':task_id,
              'task':task['display_name'],'attempts':len(instances),
              'completed_in_demo':task_id in completed,
              'first_success_time_s':first.get(task_id,float('nan')),
              'data_provenance':'synthetic'})
    return pd.DataFrame(outputs),pd.DataFrame(details)
