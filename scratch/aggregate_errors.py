import sqlite3
import json
import os
from pathlib import Path
from collections import Counter

db_path = Path(os.environ.get('LOCALAPPDATA', '')) / 'BoxFox/harness/sessions.sqlite'
conn = sqlite3.connect(str(db_path))
cur = conn.cursor()

cur.execute("""
    SELECT payload 
    FROM events 
    WHERE kind='tool_end'
    ORDER BY rowid DESC LIMIT 1000
""")
tool_ends = cur.fetchall()

tool_counts = Counter()
err_reasons = Counter()

for (p_str,) in tool_ends:
    try:
        ev = json.loads(p_str)
        res = ev.get('result') or {}
        name = ev.get('name', 'unknown')
        if isinstance(res, dict) and res.get('is_error'):
            tool_counts[name] += 1
            err_msg = str(res.get('error') or '')
            err_short = err_msg.split(': ')[-1] if ': ' in err_msg else err_msg[:60]
            err_reasons[f"[{name}] {err_short}"] += 1
    except:
        pass

print("=== TOTAL TOOL FAILURES (LAST 1000 CALLS) ===")
for t, c in tool_counts.most_common():
    print(f"  * {t:22}: {c} failures")

print("\n=== TOP 15 ROOT CAUSES / ERROR MESSAGES ===")
for r, c in err_reasons.most_common(15):
    print(f"  * {c:3}x | {r}")

print("\n=== RECENT MODEL THINKING (LAST 3 EXAMPLES) ===")
cur.execute("""
    SELECT payload 
    FROM events 
    WHERE kind='model_end'
    ORDER BY rowid DESC LIMIT 10
""")
model_ends = cur.fetchall()
shown = 0
for (p_str,) in model_ends:
    if shown >= 3:
        break
    try:
        data = json.loads(p_str)
        choice = (data.get('choices') or [{}])[0]
        msg = choice.get('message') or {}
        thought = msg.get('reasoning_content') or msg.get('thought') or ''
        content = msg.get('content') or ''
        if not thought and '<think>' in content:
            thought = content.split('<think>')[-1].split('</think>')[0]
        if thought and len(thought.strip()) > 50:
            shown += 1
            print(f"\n--- Example Thought #{shown} ({len(thought)} chars) ---")
            lines = thought.strip().split('\n')
            for l in lines[:10]:
                print(f"  {l}")
            if len(lines) > 10:
                print(f"  ... (+ {len(lines) - 10} lines)")
    except:
        pass

conn.close()
