import sqlite3
import json
import os
from pathlib import Path

db_path = Path(os.environ.get('LOCALAPPDATA', '')) / 'BoxFox/harness/sessions.sqlite'
conn = sqlite3.connect(str(db_path))
cur = conn.cursor()

print("=== EVENT KINDS SUMMARY ===")
cur.execute("SELECT kind, COUNT(*) FROM events GROUP BY kind")
for r in cur.fetchall():
    print(f"  {r[0]:25}: {r[1]} events")

print("\n=== SAMPLE MODEL OUTPUTS / THOUGHTS FROM RECENT EVENTS ===")
cur.execute("SELECT kind, payload FROM events WHERE kind IN ('model_end', 'turn_end', 'assistant_message') ORDER BY rowid DESC LIMIT 10")
for kind, p_str in cur.fetchall():
    try:
        data = json.loads(p_str)
        print(f"\n--- Kind: {kind} ---")
        if isinstance(data, dict):
            # Print text content or thought
            text = data.get('text') or data.get('content') or ''
            if not text and 'choices' in data:
                c = data['choices'][0]
                text = c.get('message', {}).get('content', '')
            if not text and 'output' in data:
                text = str(data['output'])
            if text:
                print(f"Snippet: {text.strip()[:400]}")
    except Exception as e:
        print("Error parsing:", e)

conn.close()
