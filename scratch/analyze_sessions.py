import sqlite3
import json
import os
from pathlib import Path
from collections import Counter

db_path = Path(os.environ.get('LOCALAPPDATA', '')) / 'BoxFox/harness/sessions.sqlite'
conn = sqlite3.connect(str(db_path))
cur = conn.cursor()

print("==================================================")
print("TABLE SCHEMAS")
print("==================================================")
cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
for name, sql in cur.fetchall():
    print(f"\n--- Table: {name} ---")
    print(sql)

print("\n==================================================")
print("1. RECENT SESSIONS")
print("==================================================")
cur.execute("SELECT * FROM sessions ORDER BY rowid DESC LIMIT 5")
cols = [d[0] for d in cur.description]
print("Columns:", cols)
recent_sessions = cur.fetchall()
for row in recent_sessions:
    row_dict = dict(zip(cols, row))
    print(row_dict)

latest_sid = recent_sessions[0][cols.index('id')] if recent_sessions else None

print("\n==================================================")
print("2. RECENT TOOL ERRORS & FAILED CALLS ACROSS SYSTEM")
print("==================================================")
cur.execute("""
    SELECT * FROM events 
    WHERE kind='tool_end'
    ORDER BY rowid DESC LIMIT 500
""")
event_cols = [d[0] for d in cur.description]
all_tool_ends = cur.fetchall()

error_count = 0
tool_error_counts = Counter()
error_code_counts = Counter()
sample_errors = []

for row in all_tool_ends:
    ev = dict(zip(event_cols, row))
    sid = ev.get('session_id')
    created = ev.get('created') or ev.get('timestamp')
    payload_str = ev.get('payload') or '{}'
    try:
        data = json.loads(payload_str)
        res = data.get('result') or {}
        if isinstance(res, dict) and res.get('is_error'):
            error_count += 1
            tool_name = data.get('name', 'unknown')
            error_code = res.get('errorCode', 'UNKNOWN')
            tool_error_counts[tool_name] += 1
            error_code_counts[f"{tool_name} -> {error_code}"] += 1
            if len(sample_errors) < 20:
                sample_errors.append({
                    'session_id': sid,
                    'created': created,
                    'tool': tool_name,
                    'code': error_code,
                    'error': res.get('error'),
                    'hint': res.get('reflection_hint'),
                    'args': data.get('args')
                })
    except Exception:
        pass

print(f"Total tool_end events checked: {len(all_tool_ends)}")
print(f"Total failed tool calls: {error_count} (Rate: {error_count / (len(all_tool_ends) or 1):.1%})")

print("\n--- Failed Calls by Tool Name ---")
for tool, count in tool_error_counts.most_common():
    print(f"  * {tool}: {count} failures")

print("\n--- Top Error Signatures ---")
for sig, count in error_code_counts.most_common(10):
    print(f"  * {sig}: {count} occurrences")

print("\n==================================================")
print("3. DETAILED BREAKDOWN OF RECENT FAILURES")
print("==================================================")
for idx, err in enumerate(sample_errors[:10], 1):
    print(f"\n[{idx}] Tool: {err['tool']} | Code: {err['code']}")
    print(f"    Session: {err['session_id']}")
    print(f"    Error: {err['error']}")
    print(f"    Hint: {err['hint']}")
    args_str = json.dumps(err['args'], ensure_ascii=False)
    if len(args_str) > 300:
        args_str = args_str[:300] + "... (truncated)"
    print(f"    Args: {args_str}")

print("\n==================================================")
print(f"4. MODEL THINKING & REASONING (Session {latest_sid})")
print("==================================================")
if latest_sid:
    cur.execute("SELECT * FROM events WHERE session_id = ? ORDER BY rowid ASC", (latest_sid,))
    s_cols = [d[0] for d in cur.description]
    session_events = cur.fetchall()
    
    last_thought = ""
    for r in session_events:
        ev_row = dict(zip(s_cols, r))
        kind = ev_row.get('kind')
        p_str = ev_row.get('payload') or '{}'
        try:
            ev = json.loads(p_str)
            if kind == 'model_end':
                choice = (ev.get('choices') or [{}])[0]
                msg = choice.get('message') or {}
                content = msg.get('content') or ''
                thought = msg.get('reasoning_content') or msg.get('thought') or ''
                if thought:
                    last_thought = thought
                elif '<think>' in content:
                    last_thought = content.split('<think>')[-1].split('</think>')[0]
                elif content:
                    last_thought = content[:400]
            elif kind == 'tool_end':
                res = ev.get('result') or {}
                if isinstance(res, dict) and res.get('is_error'):
                    print(f"\n>>> FAILED TOOL: {ev.get('name')} | Code: {res.get('errorCode')}")
                    print(f"    Error: {res.get('error')}")
                    if last_thought:
                        print(f"    Model Thinking/Reasoning prior to call:")
                        print(f"    {last_thought.strip()[:600]}")
                    last_thought = ""
        except Exception:
            pass

conn.close()
