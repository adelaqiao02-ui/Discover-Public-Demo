ACTION LOG IMPORT (optional)

Place actual exports named ACTION_LOG_*.csv in this directory.
Required CSV columns: group_id,session_id,learner_id,event_time_s,action_type,target,event_source
event_source must be learner, system, or unknown. event_time_s is seconds since scenario start.
Optional: action_result,notes. Never infer success from merely targeting an object.
The provided ACTION_LOG_TEMPLATE.csv contains NO rows and is never used as evidence.
Only import logs after confirming learner IDs, group and session mappings, and clock origin.
Role access applies on server before any action events are displayed.
