# H7 — Research ownership

- **Trạng thái:** verified — đã nối runtime ở `802f51f` (`research_gateway.py`, principal `research-lead` riêng); nghiệm thu mức vòng chạy D1–D4 nằm trong **29/29 PASS** trên `c836822`. Theo #6536, gateway **giữ trong mã, mặc định off**; bản này main tự spawn research sub-agent.
- **Mục tiêu:** controller principal + gateway có version; migrate read view/history; main không sửa internals, không điều khiển worker nội bộ.
- **Phạm vi:** `research_owner.py` (52 ca), `research_gateway.py` (48 ca); nối runtime (dispatch/profile/gate, publication ref); sửa lỗi vòng review H7.1–H7.3.
- **Ngoài phạm vi:** chạy Research sống (hoãn #6531); bật gateway mặc định.
- **Phụ thuộc:** H2–H6.
- **Nghiệm thu (runbook §II.3):** main submit/get/control/result trong envelope; Research tự chọn phương pháp; publication/review bind đúng version; refresh/revision không sửa kết quả cũ; nguồn bị chặn còn hiện rõ.
- **Nguồn:** `docs/plan/reform-status.md` H7–H7.3; probe P5 `probes_962cd84.json`; nghiệm thu vòng chạy `/code/.generated_artifacts/h4h8/runs/official-c836822/summary.json`.
