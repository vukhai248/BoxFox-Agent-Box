import sqlite3
import json
import os
from pathlib import Path

db_path = Path(os.environ.get('LOCALAPPDATA', '')) / 'BoxFox/harness/sessions.sqlite'
conn = sqlite3.connect(str(db_path))
cur = conn.cursor()

# Get events ordered by time
cur.execute("""
    SELECT session_id, kind, created, payload 
    FROM events 
    ORDER BY rowid ASC
""")
rows = cur.fetchall()

print(f"Total events loaded: {len(rows)}")

# Tracing by session
session_traces = {}
for sid, kind, created, p_str in rows:
    if sid not in session_traces:
        session_traces[sid] = []
    try:
        p = json.loads(p_str)
        session_traces[sid].append((kind, created, p))
    except Exception:
        pass

# Analyze the latest session
latest_sid = list(session_traces.keys())[-1]
events = session_traces[latest_sid]

print(f"\n========================================================")
print(f"ANALYSIS OF LATEST ACTIVE SESSION: {latest_sid}")
print(f"Total events in this session: {len(events)}")
print(f"========================================================")

current_thoughts = []
incident_count = 0

for kind, created, payload in events:
    if kind == 'thought':
        # payload might have 'thought' or 'text'
        th = payload.get('text') or payload.get('thought') or payload.get('content') or str(payload)
        current_thoughts.append(th.strip())
    elif kind == 'tool_start':
        t_name = payload.get('name')
        t_args = payload.get('args')
    elif kind == 'tool_end':
        res = payload.get('result') or {}
        if isinstance(res, dict) and res.get('is_error'):
            incident_count += 1
            print(f"\n------------------------------------------------------------")
            print(f"INCIDENT #{incident_count} | FAILED TOOL: {payload.get('name')} | CODE: {res.get('errorCode')}")
            print(f"ERROR: {res.get('error')}")
            
            # Print last 1-2 thoughts before this failure
            if current_thoughts:
                combined_thought = " ".join(current_thoughts[-3:])
                print(f"\nAGENT'S THINKING LEADING TO THIS ACTION:")
                # print formatted snippet
                for line in combined_thought.split('\n')[:8]:
                    if line.strip():
                        print(f"  > {line.strip()}")
            else:
                print("  (No preceding thought recorded)")
            
            # Reset thoughts after tool failure
            current_thoughts = []
    elif kind in ('turn_start', 'turn_end'):
        # clear thoughts between turns if too old
        pass

print(f"\nTotal failed tool incidents in latest session: {incident_count}")

conn.close()
