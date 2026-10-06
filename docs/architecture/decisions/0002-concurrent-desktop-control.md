# ADR-0002: Điều khiển desktop đồng thời — chọn kết hợp lựa chọn 1 + 2

- **Trạng thái:** **Đã chọn** (06/10/2026): kết hợp **lựa chọn 1 + lựa chọn 2** — "người chạm ⇒ agent nhả
  quyền" làm hành vi nhìn thấy được, "revision + kiểm lại ngay trước hành động" làm hàng rào kỹ thuật bên
  dưới. Trước đó tài liệu này **hoãn** quyết định.
- **Ngày:** 2026-09-15 (hoãn) · 2026-10-06 (chốt).
- **Quyết định liên quan:** `docs/architecture/sandbox.md`, `docs/architecture/element-selector.md`,
  `docs/architecture/agent-harness.md`, `docs/architecture/host-desktop-control.md`,
  `docs/plan/desktop-host-mode.md`.

## Bối cảnh và thuật ngữ

**Desktop control** là click/type/keyboard có tác dụng phụ trong desktop sandbox. **Concurrent control** là người dùng và agent đều có thể gửi input trong cùng thời gian. **Perception** là ảnh/DOM (Document Object Model — biểu diễn cấu trúc trang web)/trạng thái agent dùng để chọn action. **Revision** là số phiên bản đơn điệu của perception/desktop state. **Stale action** là action được tính từ revision không còn hiện tại. **Serialize** là buộc action xảy ra theo thứ tự loại trừ nhau. **VNC (Virtual Network Computing)** là giao thức xem và điều khiển desktop từ xa. **UI (User Interface)** là giao diện người dùng; **UX (User Experience)** là trải nghiệm người dùng. **Lease** là quyền điều khiển tạm thời, có **epoch** (số phiên bản tăng mỗi lần chuyển chủ).

BoxFox đã có desktop VNC và endpoint quan sát/chọn phần tử. Những khả năng này không tự chứng minh click/type của agent còn đúng sau khi người dùng thay đổi cửa sổ, focus hoặc DOM. Chỉ cờ “perception fresh” ở client không đóng cuộc đua giữa lần kiểm tra và lần executor gửi action. Host mode làm việc này cấp thiết hơn: agent chạy trên **chính máy của người dùng**, không có sandbox hệ điều hành đỡ bên dưới.

## Lựa chọn được giữ mở (bản 2026-09-15)

| Lựa chọn | Trải nghiệm | Bảo đảm và chi phí |
|---|---|---|
| 1. **Người dùng lấy điều khiển thì pause agent** | Dễ hiểu, có thể làm gián đoạn agent | Dễ tránh action stale nhất cho bản đầu; cần UX handoff/resume rõ |
| 2. **Revision + khóa action ngắn** | Cả hai có thể xen kẽ nhanh hơn | Executor phải kiểm revision tại điểm action, serialize đoạn ngắn và hủy mọi proposal stale; phức tạp hơn |
| 3. **Input tự do, chỉ audit** | Linh hoạt nhất | Không được tuyên bố chống stale action; chỉ phù hợp quan sát/prototype khi người dùng chấp nhận giới hạn |

## Quyết định (2026-10-06)

**Chọn 1 + 2, không chọn 3.** Khảo sát các coding agent tham chiếu (Codex, oh-my-pi, cua-driver, Hermes) cho thấy **không nguồn nào tự nó trả lời trọn vẹn**, và hai cơ chế **bù cho nhau**:

> "Người chạm ⇒ agent nhả quyền" (lựa chọn 1) là hành vi **nhìn thấy được** — người dùng hiểu ngay ai
> đang điều khiển. "Revision + kiểm lại ngay trước hành động" (lựa chọn 2) là hàng rào **kỹ thuật** bên
> dưới — nó đóng cuộc đua kể cả khi không ai nhìn thấy gì. Một cái cho UX, một cái cho tính đúng.

Cơ chế cụ thể (hợp đồng đầy đủ ở `docs/architecture/host-desktop-control.md` §5):

1. **Lease có epoch, lưu trên đĩa** (`desktop_lease.json` trong profile):
   `{holder: 'human'|'agent', viewer_id, since, reason, epoch}`. Mọi chuyển chủ tăng `epoch`.
   Đọc lỗi/không đọc được ⇒ **fail-closed về `human`**.
2. **Agent phải được cấp lease trước mọi thao tác**, kể cả chụp màn hình ⇒ `HUMAN_HAS_CONTROL`.
3. **Hàng rào epoch:** trước khi gửi input và trước khi lưu ảnh chụp, kiểm lại `epoch`; lệch ⇒ vứt bỏ
   kết quả với `HUMAN_TOOK_OVER`.
4. **Phát hiện người thật sự chạm máy:** `GetLastInputInfo` lấy mẫu mỗi 250 ms + hook
   `WH_MOUSE_LL`/`WH_KEYBOARD_LL` lọc cờ injected (bỏ qua input do chính ta tiêm); `VK_ESCAPE`
   không-injected ⇒ huỷ khẩn cấp; cài hook thất bại ⇒ fail-closed.
5. **Loại trừ lẫn nhau ở mức HĐH:** mutex kernel `Local\BoxFoxDesktopInput-v1` với
   `WaitForSingleObject(handle, 0)`; `WAIT_TIMEOUT` ⇒ `CONTROL_BUSY`.
6. **Huỷ lan tới hành động đang chờ** (nút Dừng / Esc / hết phiên): tăng `epoch` + `generation`, nhả
   phím/chuột đang giữ rồi mới thoát.
7. **Audit phân biệt actor** `user`/`agent` kèm `lease_epoch`, `target`, `revision`, `outcome`, `verified`.
8. **UI:** băng trạng thái quyền, nút Dừng khẩn, nút Trả quyền, cảnh báo khi lease ở `human` mà agent xin lại.

**Hệ quả:** executor phải hỗ trợ revision/epoch **nguyên tử tại điểm hành động**; không được coi "đã gửi
input" là "đã thành công". Lựa chọn 3 bị loại: nó không cho phép ta tuyên bố chống stale action, và với
host mode thì đó là tuyên bố an toàn không thể rút lại.

## Tiêu chí trước khi bật

- Mỗi perception/element target mang `screen_revision` hoặc revision nguồn tương đương. **Đạt:** `geometryRevision` + `elementToken` + `sourceId` (§4.1 hợp đồng CUA).
- Executor kiểm revision, target validity và policy ngay trước click/type, không chỉ lúc model đề nghị. **Đạt:** hàng rào epoch + resolve lại ref trước mỗi hành động.
- Test mô phỏng input người dùng giữa perception và action; action cũ phải bị cancel/review lại theo lựa chọn đã chốt. **Đạt:** nền tảng giả trong unit test (máy phát triển không chạy được Windows).
- Audit phân biệt actor user/agent với nhãn của dữ liệu; actor user không làm dữ liệu hiển thị trở thành trusted instruction. **Đạt:** `permissions-audit.jsonl` có `actor`; ảnh chụp mang nhãn `khong_tin_duoc`.
- Pause/cancel lan tới pending browser actions và UI thể hiện trạng thái rõ khi reconnect. **Đạt một phần:** luật huỷ đã chốt; phần UI do D5 làm.
