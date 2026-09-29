import requests
import json
import time

BASE_URL = "http://127.0.0.1:3102"
HEADERS = {
    "X-BoxFox-Admin": "1",
    "Origin": "http://localhost:3100",
    "Content-Type": "application/json"
}

print("==================================================")
print("TEST LIVE CUA/API WORKFLOW ON LIVE HARNESS (PORT 3102)")
print("==================================================")

# 1. Health check
res = requests.get(f"{BASE_URL}/api/agent/health", timeout=3)
assert res.status_code == 200, f"Health check failed: {res.text}"
print("[OK] Health check: 200 OK ->", res.json())

# 2. CUA-01: Create new clean session and start /plan
s_res = requests.post(f"{BASE_URL}/api/agent/sessions", json={"skills": []}, headers=HEADERS, timeout=5)
assert s_res.status_code == 201, f"Create session failed ({s_res.status_code}): {s_res.text}"
session = s_res.json()
sid = session["id"]
print(f"[OK] CUA-01: Created new test session: {sid}")

# Start plan mode via workflow on harness sqlite
import sys
sys.path.insert(0, 'backend/src')
from agentbox.agent_core import plan_workflow as pw
from agentbox.memory.session_store import SessionStore
from pathlib import Path
import os
data_dir = Path(os.environ.get('LOCALAPPDATA', '')) / 'BoxFox/harness'
store = SessionStore(data_dir / 'sessions.sqlite')
flow = pw.PlanWorkflow(store)

goal_text = "tôi cần bạn giúp tôi tạo plan cho 1 app agent hỗ trợ tổng hợp hồ sơ y tế"
set_mode_res = flow.set_mode(None, sid, True, goal=goal_text, by='command')
run = set_mode_res["run"]
assert run is not None, "Run should not be None"
rid = run["runId"]
print(f"[OK] CUA-01: Plan mode started! Run ID: {rid} | Status: {run['status']} | Phase: {run['phase']}")
print(f"      Initial Brief keys: {list(run.get('brief', {}).keys())}")
print(f"      Missing fields: {flow.missing(run)}")
flow.scope(None, store.get(sid), {
    'action': 'ask',
    'runId': rid,
    'revision': run['revision'],
    'questions': [
        {'field': 'users', 'text': 'Đối tượng sử dụng chính là ai?', 'options': [{'id': 'o1', 'label': 'Bác sĩ tuyến trên'}, {'id': 'o2', 'label': 'Điều dưỡng / KTV'}]},
        {'field': 'data', 'text': 'Định dạng dữ liệu đầu vào là gì?', 'options': [{'id': 'd1', 'label': 'PDF scan / ảnh'}, {'id': 'd2', 'label': 'JSON FHIR'}]},
        {'field': 'constraints', 'text': 'Ràng buộc vận hành?', 'options': [{'id': 'c1', 'label': 'Hoàn toàn offline'}, {'id': 'c2', 'label': 'Cloud hybrid'}]}
    ]
})
store.close()
run = requests.get(f"{BASE_URL}/api/agent/plans/runs/{rid}", headers=HEADERS, timeout=5).json()

print(f"[OK] CUA-02: Round created with {len(run['questions'])} questions:")
round_ids = {q.get('roundId') for q in run['questions']}
assert len(round_ids) == 1, f"All questions in round should share single roundId: {round_ids}"
round_id = list(round_ids)[0]
print(f"      Shared RoundId: {round_id}")
for q in run['questions']:
    print(f"      - [{q['id']}] {q['text']} (status: {q['status']})")

# Submit partial answer for 1 question (CUA-03)
q1 = run['questions'][0]
ans1_res = requests.post(f"{BASE_URL}/api/agent/plans/runs/{rid}/answers", json={
    "revision": run['revision'],
    "invocationId": "test-partial-1",
    "answers": [{"questionId": q1['id'], "optionId": "o1", "text": "Bác sĩ tuyến trên"}]
}, headers=HEADERS, timeout=5)
assert ans1_res.status_code == 200, f"Answer 1 failed: {ans1_res.text}"
ans1_data = ans1_res.json()
run_after_1 = ans1_data["run"]
assert run_after_1['status'] == 'needs_user', "Status must remain needs_user after partial answer"
saved_q1 = next(q for q in run_after_1['questions'] if q['id'] == q1['id'])
assert saved_q1['status'] == 'answered', "Q1 should be answered"
assert saved_q1['answer'] == 'Bác sĩ tuyến trên'
remaining = [q for q in run_after_1['questions'] if q['status'] == 'open']
assert len(remaining) == 2, f"Should have 2 remaining open questions, got {len(remaining)}"
print(f"[OK] CUA-03: Partial answer succeeded! Q1 answered ('{saved_q1['answer']}'), 2 remaining questions still open, run status: {run_after_1['status']}.")

# Submit remaining 2 questions (CUA-04)
q2, q3 = remaining[0], remaining[1]
ans2_res = requests.post(f"{BASE_URL}/api/agent/plans/runs/{rid}/answers", json={
    "revision": run_after_1['revision'],
    "invocationId": "test-partial-2",
    "answers": [
        {"questionId": q2['id'], "optionId": "d1", "text": "PDF scan / ảnh"},
        {"questionId": q3['id'], "optionId": "c1", "text": "Hoàn toàn offline"}
    ]
}, headers=HEADERS, timeout=5)
assert ans2_res.status_code == 200, f"Remaining answers failed: {ans2_res.text}"
run_after_all = ans2_res.json()["run"]
assert all(q['status'] == 'answered' for q in run_after_all['questions']), "All questions must be answered"
assert run_after_all['status'] == 'active', f"Run status should become active after all questions answered, got: {run_after_all['status']}"
print(f"[OK] CUA-04: All questions answered! Status transitioned to '{run_after_all['status']}'. All answers persisted.")

# Test CUA-10: Stale answer with old revision
stale_res = requests.post(f"{BASE_URL}/api/agent/plans/runs/{rid}/answers", json={
    "revision": 1, # Stale revision!
    "invocationId": "test-stale",
    "answers": [{"questionId": q1['id'], "text": "Stale"}]
}, headers=HEADERS, timeout=5)
assert stale_res.status_code in (400, 409) or "REVISION_CONFLICT" in stale_res.text or "INVOCATION_CONFLICT" in stale_res.text, "Must reject stale revision"
print(f"[OK] CUA-10: Stale revision was properly rejected with conflict error (status {stale_res.status_code}).")

# Test CUA-05: Inspecting Brief & Plan
assert "goal" in run_after_all.get("brief", {})
print(f"[OK] CUA-05: Brief is properly isolated in run object, ready for Plan tab.")

print("\n>>> ALL TESTED LIVE CHECKS PASSED SUCCESSFULLY! <<<")
