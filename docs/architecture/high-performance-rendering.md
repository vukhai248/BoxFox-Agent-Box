# KIẾN TRÚC TỐI ƯU HIỆU NĂNG RENDER & QUẢN LÝ DỮ LIỆU LỚN (60 FPS PLAYBOOK)

Tài liệu này ghi chép các tiêu chuẩn kiến trúc và giải pháp kỹ thuật đã được kiểm chứng thực tế trên hệ thống BoxFox Agent Box, dùng làm chuẩn tham chiếu khi phát triển các module xử lý dữ liệu nặng trong tương lai như:
- **Audit Log Viewer** (Nhật ký kiểm toán hàng chục nghìn sự kiện).
- **Pull Request & Git Diff Viewer** (Trình so sánh mã nguồn hàng nghìn dòng).
- **Decision Stream / Reasoning Timeline** (Luồng suy luận từng bước của Agent).
- **Plan & Document Browser** (Trình duyệt kế hoạch Markdown/KaTeX phức tạp).

---

## 1. Tầng 1: Backend Fast-Path & Invalidation Cache (`st_mtime`)

### Vấn đề thường gặp:
Khi đọc danh mục hoặc nội dung thực thể (file, log, diff), việc chạy lại các thuật toán quét đĩa đệ quy (recursive directory traversal) hoặc truy vấn lặp lại làm tăng độ trễ từ vài mili-giây lên **1.000ms – 1.500ms**.

### Chuẩn thiết kế áp dụng:
```python
# Bộ nhớ đệm danh mục / thực thể theo timestamp sửa đổi của thư mục
_MANIFEST_CACHE: dict[str, tuple[float, ManifestData]] = {}

def get_manifest(root_path: Path) -> ManifestData:
    root_stat = os.stat(root_path)
    current_mtime = root_stat.st_mtime
    
    # 1. Kiểm tra cache: Nếu thư mục không có file mới được tạo/sửa -> Phản hồi 0ms
    cached = _MANIFEST_CACHE.get(str(root_path))
    if cached is not None and cached[0] == current_mtime:
        return cached[1]
        
    # 2. Nếu có thay đổi mới -> Quét an toàn và cập nhật lại cache
    manifest = scan_directory_securely(root_path)
    _MANIFEST_CACHE[str(root_path)] = (current_mtime, manifest)
    return manifest
```

### Lợi ích:
- **Tiêu hao RAM siêu thấp:** Chỉ lưu trữ metadata danh mục (khoảng vài KB), không lưu nội dung nặng.
- **Tự động nhận diện thời gian thực:** Ngay khi có file/log mới được sinh ra, `mtime` thay đổi và cache tự động làm mới tức thì.
- **Tốc độ:** Giảm thời gian phản hồi từ ~1.000ms xuống **chưa đầy 1ms**.

---

## 2. Tầng 2: React Component Memoization & Static Plugin AST

### Vấn đề thường gặp:
Khi người dùng kéo rê chuột thay đổi kích thước các panel chia đôi (Split Pane Resize), sự kiện `mousemove` kích hoạt React re-render liên tục **60 – 120 lần mỗi giây**. Nếu các plugin AST (như Markdown, KaTeX, Prism highlighter, Diff parser) được khai báo bên trong component, trình duyệt sẽ phân tích cú pháp lại toàn bộ hàng nghìn dòng ở **mọi frame**, làm CPU đạt 100% và gây giật lag (4 – 5 FPS).

### Chuẩn thiết kế áp dụng:
1. **Đưa plugin và components cấu hình ra ngoài thành hằng số tĩnh:**
   ```tsx
   // Khai báo 1 lần duy nhất ở phạm vi file, không tạo lại ở mỗi frame render
   const REMARK_PLUGINS = [remarkGfm, remarkMath]
   const REHYPE_PLUGINS = [rehypeKatex]
   const STATIC_COMPONENTS: Components = { ... }
   ```
2. **Đóng gói Component bằng `React.memo`:**
   ```tsx
   export const HighVolumeRenderer = memo(function HighVolumeRenderer({ content }: Props) {
     return (
       <ReactMarkdown
         remarkPlugins={REMARK_PLUGINS}
         rehypePlugins={REHYPE_PLUGINS}
         components={STATIC_COMPONENTS}
       >
         {content}
       </ReactMarkdown>
     )
   })
   ```
3. **Ghi nhớ (useMemo) khối DOM ở Component cha:**
   ```tsx
   const renderedBlock = useMemo(() => {
     return <HighVolumeRenderer content={heavyData} />
   }, [heavyData])
   ```

### Lợi ích:
- Khi kéo thanh resize phân cách giữa các panel, vì dữ liệu (`heavyData`) không thay đổi, React **tái sử dụng 100% DOM đã render sẵn**, tiêu thụ **0ms CPU**, đưa tốc độ kéo thả lên **60 FPS mượt mà**.

---

## 3. Tầng 3: CSS Layout Virtualization (`content-visibility: auto`)

### Vấn đề thường gặp:
Với những tài liệu hoặc danh sách có hàng chục nghìn thẻ DOM (như Audit Log hay Plan dài 3.000 dòng), ngay cả khi React không re-render, **bộ dựng đồ họa của trình duyệt (Blink/Chromium Layout Engine)** vẫn phải tính toán lại việc ngắt dòng (word-wrapping) và tọa độ cho toàn bộ DOM khi chiều rộng panel co giãn.

### Chuẩn thiết kế áp dụng:
Áp dụng thuộc tính CSS hiện đại `content-visibility: auto` kết hợp `contain-intrinsic-size` vào các phần tử khối con:
```css
.log-row, .markdown-paragraph, .table-container, .diff-chunk {
  content-visibility: auto;
  contain-intrinsic-size: 1px 32px; /* Chiều cao ước lượng */
}
```

```tsx
// Ví dụ trong Tailwind CSS
<p className="leading-relaxed text-xs text-fg [content-visibility:auto] [contain-intrinsic-size:1px_24px]">
  {children}
</p>
```

### Cơ chế hoạt động & Lợi thế vượt trội:
1. **Bỏ qua tính toán Layout ngoài màn hình:** Trình duyệt chỉ tính toán layout và vẽ cho các phần tử nằm trong Viewport và vùng đệm lân cận. Toàn bộ hàng nghìn dòng nằm ngoài màn hình được bỏ qua hoàn toàn khi resize.
2. **Vùng đệm Overscan Buffer tự động (1–2 Viewport):** Chromium tự động duy trì sẵn 1–2 màn hình đệm ở trên và dưới. Khi người dùng cuộn chuột nhanh, nội dung đã có sẵn trong bộ nhớ đồ họa nên không bao giờ bị chớp trắng.
3. **Bảo toàn 100% khả năng tìm kiếm `Ctrl + F`:** Khác với các thư viện JS Virtual List (như `react-window` thường hủy hoàn toàn DOM ngoài màn hình), `content-visibility: auto` giữ nguyên cây DOM nên người dùng vẫn có thể bấm `Ctrl + F` tìm kiếm toàn văn bản bất kỳ lúc nào.

---

## 4. Bảng hướng dẫn áp dụng cho các module tương lai

| Module | Tầng 1 (Backend) | Tầng 2 (React Memo) | Tầng 3 (CSS Virtualization) |
| :--- | :--- | :--- | :--- |
| **Audit Log Viewer** | Cache file log qua `mtime` thư mục `.session-history/` | Memoize danh sách log items, tách riêng search filter | Áp dụng `content-visibility: auto` cho từng dòng log record (`1px 28px`) |
| **Pull Request Diffs** | Stream git diff trực tiếp qua pipe | Memoize Diff Chunk parser và syntax highlighter | Áp dụng `content-visibility: auto` cho từng khối diff block (`1px 120px`) |
| **Decision Streams** | Đọc event stream qua WebSocket / buffer | Memoize từng thẻ reasoning step | Áp dụng `content-visibility: auto` cho các thẻ quyết định đã hoàn thành |
| **Plan Browser** | Đã áp dụng `_MANIFEST_CACHE` trong `plan_files.py` | Đã áp dụng `STATIC_COMPONENTS` & `React.memo` | Đã áp dụng `[content-visibility:auto]` trong `MarkdownRenderer.tsx` |
