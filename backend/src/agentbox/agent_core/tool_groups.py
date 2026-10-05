"""Mười bốn nhóm công cụ của runtime — bảng "Nút vặn của runtime" nói với giao diện.

Bảng này là nguồn duy nhất cho khối "Tool access" ở tab Harness: hợp của mười bốn nhóm
phải bằng ĐÚNG bộ công cụ của orchestrator (`roles.ORCHESTRATOR_TOOLS`, 60 công cụ),
và mỗi nhóm giữ trật tự như bảng trong kế hoạch. Nhóm `taskSurface` (H3) đứng CUỐI và
mang `alwaysOn: True` từ v2 (#6599): bốn công cụ `task_*` luôn được quảng cáo. `alwaysOn` đánh dấu nhóm không thể
tắt: hỏi người dùng và xin phép là hai công cụ quyết định (`roles.DECISION`), mọi
vai trò đều có, nên một harness tắt chúng là một harness không còn hỏi được ai.

Chỉ `runtime.py` mới quyết định bộ công cụ thật của một phiên; tệp này chỉ MÔ TẢ
cách chia nhóm, không cấp quyền gì thêm.
"""

TOOL_GROUPS = [
    {'key': 'repositoryReading',
     'tools': ['file_read', 'codebase_glob', 'codebase_grep'],
     'alwaysOn': False},
    {'key': 'skills',
     'tools': ['skills_list', 'skill_view'],
     'alwaysOn': False},
    {'key': 'filesTerminal',
     'tools': ['file_write', 'file_edit_block', 'terminal_exec'],
     'alwaysOn': False},
    {'key': 'screenBrowser',
     'tools': ['computer_screen_capture', 'computer_screen_record', 'computer_use',
               'browser_use', 'inspect_element'],
     'alwaysOn': False},
    {'key': 'webResearch',
     'tools': ['web_search', 'web_fetch', 'read_source', 'paper_citations'],
     'alwaysOn': False},
    {'key': 'delegationPlans',
     'tools': ['delegate_task', 'session_search', 'plan_scope', 'write_plan', 'plan_verify', 'journal_write', 'journal_brief'],
     'alwaysOn': False},
    # Vòng 27 (đợt 3–7) — sổ nguồn và hồ sơ research, chèn NGAY SAU `delegationPlans`:
    # hai nhóm này là phần "research có kiểm chứng" của cùng một việc giao cho con,
    # nên chúng đứng cạnh nhóm giao việc chứ không cạnh nhóm đọc web.
    {'key': 'researchLedger',
     'tools': ['source_add', 'source_list', 'source_verify'],
     'alwaysOn': False},
    {'key': 'researchDossiers',
     'tools': ['research_brief', 'dossier_write', 'research_verify', 'research_status',
               'research_update', 'cancel_child',
               # P1 — cửa 1: main gợi ý bật mode (chỉ phát sự kiện, không bật mode).
               'research_suggest',
               # P1 — thẻ phạm vi của run (§5.3); thiếu ở đây thì `turn_profile` không cấp schema
               # và mọi lời gọi `research_scope` rơi vào `PermissionError` (review F1).
               'research_scope'],
     'alwaysOn': False},
    {'key': 'peerMesh',
     # H11 — `child_resume` (gọi lại con đã bị cắt) đi cùng nhóm với hai công cụ peer: cùng công
     # tắc `BOXFOX_PEER_MESH`, cùng chỉ cha/orchestrator thấy.
     'tools': ['peer_read', 'await_children', 'child_resume'],
     'alwaysOn': False},
    # Work Graph — main dựng đồ thị việc, harness chạy vòng phản biện, duyệt rồi chạy DAG.
    # W6.1.3 — `verify_exec` là công cụ của người phản biện (thử MỘT claim tính toán trong sandbox
    # tạm: repo chỉ-đọc, scratch riêng, mạng theo công tắc firewall của box — #6423); nó nằm ở bộ
    # của orchestrator để `allowed_tools` không cắt mất của con.
    {'key': 'workGraph',
     'tools': ['work_graph', 'work_run', 'work_ship', 'work_check', 'work_report', 'work_artifact_read',
               'verify_exec'],
     'alwaysOn': False},
    {'key': 'questionsApprovals',
     'tools': ['ask_user', 'request_approval', 'interview'],
     'alwaysOn': True},
    # Biên Research độc lập; chỉ registry, không tự cấp quyền cho main.
    {'key': 'researchGateway',
     'tools': ['research_job_submit', 'research_job_get', 'research_job_control', 'research_job_result'],
     'alwaysOn': False},
    # H4 — job controller explicit; LUÔN BẬT từ v2 (#6599), không cấp scheduler/quyền mới.
    {'key': 'controllerJobs',
     'tools': ['start_job', 'get_job', 'subscribe_job', 'wait_jobs', 'cancel_job'],
     'alwaysOn': True},
    # H3 — bề mặt task (plan v1 §4). Nhóm LUÔN BẬT từ v2 (#6599).
    {'key': 'taskSurface',
     'tools': ['task_list', 'task_get', 'task_send', 'task_abandon'],
     'alwaysOn': True},
]


def tool_groups():
    """Bản sao cho route: người gọi không sửa được bảng gốc trong module."""
    return [{'key': group['key'], 'tools': list(group['tools']), 'alwaysOn': group['alwaysOn']}
            for group in TOOL_GROUPS]
