# Workspace Files — API mặt box

> **Cập nhật**: 2026-08-28 — thêm nhóm endpoint `/__box/files*` và `/__box/file/*` để
> giao diện web duyệt/đọc/ghi file trong `/home/agent/workspace`. Tài liệu này bổ
> sung cho [sandbox.md](./sandbox.md) — chỉ mô tả phần box, không mô tả frontend.

Module lõi: `deploy/docker/workspace_files.py` (stdlib thuần, không HTTP), được
`ide-proxy.py` import và route trực tiếp — cùng idiom với `plan_files.py` (chứa
đường dẫn an toàn qua `dir_fd` + `O_NOFOLLOW`, từ chối symlink) và `capture.py`
(hạ quyền về `agent` 1000:1000 qua `fchown`/`fchmod` và `gosu agent`).

## Endpoint

Quy ước: `path` là đường dẫn tương đối từ `WORKSPACE_ROOT` (chuỗi rỗng = thư mục
gốc). Lỗi có dạng `{"error": "<thông báo>"}`.

| Method | Endpoint | Auth | Mục đích |
|---|---|---|---|
| GET | `/__box/files?path=<rel>` | Origin | Liệt kê MỘT thư mục (dir trước file, ẩn `.generated_artifacts`) |
| GET | `/__box/file/content?path=<rel>` | Origin | Đọc text/code/md/json (413 quá lớn, 422 không UTF-8) |
| GET | `/__box/file/media?path=<rel>` | loopback + CORS phản chiếu | Raw bytes + `Content-Type` + `Range` (206) |
| GET | `/__box/file/thumbnail?path=<rel>` | loopback + CORS phản chiếu | JPEG thumbnail (ảnh/video, bỏ `.svg`) |
| GET | `/__box/file/download?path=<rel>` | loopback + CORS phản chiếu | Tải một file (`Content-Disposition: attachment`) + Range |
| POST | `/__box/files/zip` | Origin | Nén nhiều path thành zip |
| POST | `/__box/file/upload?path=<dir>&name=<file>` | secret | Ghi file raw (stream, fchown về agent) |
| POST | `/__box/file/unzip?path=<zipRel>` | secret | Giải nén vào thư mục cha (chống zip-slip, skip file trùng) |

## Mô hình auth

- **Origin-gate** (JSON read: `files`, `file/content`, `files/zip`): kiểm tra
  `_origin_ok_for_box_api()` nghiêm ngặt như `/__box/plans`; 403 nếu Origin không
  hợp lệ. Đây là các lệnh gọi bằng `fetch` (luôn gửi `Origin`).
- **Secret-gate** (mutation: `upload`, `unzip`): chỉ nhận `X-BoxFox-Api-Key` qua
  `_secret_ok()` — giống `/__box/network`; Origin KHÔNG đủ. Tránh để process
  trong box tự ghi/deploy file chỉ bằng Origin giả.
- **Subresource** (`media`, `thumbnail`, `download`): trình duyệt không gửi
  `Origin` cho `<img>`/`<video>`/`<iframe>`/`<a download>`, nên ba endpoint này
  KHÔNG bắt buộc Origin; biên thật là bind loopback `127.0.0.1:8081` trong
  compose. Khi có Origin hợp lệ thì phản chiếu `Access-Control-Allow-Origin`.

## Range

`parse_range` hỗ trợ ba dạng trình duyệt/player thật gửi: `bytes=s-e` (đóng),
`bytes=s-` (mở, `end=size-1`), `bytes=-n` (n byte cuối). Hợp lệ → `206` +
`Content-Range: bytes s-e/size`; thiếu `Range` → `200` toàn bộ; `start>=size`
hoặc sai cú pháp → `416` + `Content-Range: bytes */size`. Stream theo chunk
64 KiB, không nạp cả file.

## Provenance (placeholder heuristic)

**Đây là luật tạm**, thống nhất với `frontend/src/lib/mock/workspace.ts`; backend
thật sẽ quyết định theo `source_kind` chứ không theo đường dẫn.

- `integrity`: `khong_tin_duoc` nếu bất kỳ segment nào nằm trong
  `{vendor, node_modules, .venv, dist, build, .cache}` HOẶC `basename == plan.md`
  (artifact do agent viết); ngược lại `duoc_nguoi_dung_cho_phep`.
- `confidentiality`: `bi_mat` nếu `basename` khớp `.env*` / `*.key` / `*.pem` /
  `id_rsa*` / `id_ed25519*`; ngược lại `cong_khai`.

Như vậy `.env` giữ integrity tin cậy nhưng confidentiality bí mật (khớp mock đánh
`.env` = SECRET); `vendor/**` không tin được.

## Giới hạn

`MAX_DEPTH=16`, `MAX_ENTRIES=2000`, `MAX_FILE_SIZE=1 MiB` (text), `MAX_UPLOAD_SIZE`
= `MAX_ZIP_TOTAL_BYTES` = `MAX_UNZIP_TOTAL_BYTES` = 256 MiB, `MAX_ZIP_PATHS=200`.
Thumbnail cache ở `WORKSPACE_ROOT/.generated_artifacts/thumbnails`, key
`sha256(rel|mtime|size)` để hết hiệu lực khi file đổi; thư mục `.generated_artifacts`
bị ẩn khỏi listing và zip.
