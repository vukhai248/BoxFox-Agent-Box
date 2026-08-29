# Design Canvas — kiến trúc vector 2D + connector + giao thức agent

> **Cập nhật**: 2026-08-29 — dựng lại tab "Design Canvas" thành canvas vector 2D nhẹ
> theo kiểu Excalidraw: shape động, connector neo theo cạnh, stroke độc lập, và giao
> thức hai chiều với agent. Logic tách khỏi view vào `frontend/src/lib/canvas/` +
> `frontend/src/hooks/useDesignCanvas.ts`; `DesignCanvasPanel.tsx` chỉ còn là view mỏng.

Module lõi (thuần, không DOM): `frontend/src/lib/canvas/` gồm `types.ts`,
`palette.ts`, `id.ts`, `geometry.ts`, `shapes.ts`, `connectors.ts`, `scene.ts`,
`agent-protocol.ts`. Hook điều khiển: `frontend/src/hooks/useDesignCanvas.ts`.
Component view: `frontend/src/components/panels/canvas/`.

## 1. Mô hình dữ liệu `CanvasScene`

Một cảnh là nguồn sự thật duy nhất, cập nhật bất biến:

```json
{
  "version": 1,
  "nodes": [
    { "id": "node-c1", "kind": "card", "shape": null, "card": "ui-mockup",
      "x": 40, "y": 40, "width": 380, "height": 240,
      "title": "Frontend UI Mockup", "body": "…",
      "url": null,
      "style": { "fill": "#1c1c1c", "stroke": "#3b82f6", "strokeWidth": 2, "radius": 8 } }
  ],
  "connectors": [
    { "id": "conn-1", "fromNodeId": "node-c1", "toNodeId": "node-c2",
      "fromAnchor": "right", "toAnchor": "left", "stroke": "#3b82f6", "strokeWidth": 2 }
  ],
  "strokes": [
    { "id": "stroke-1", "points": [{ "x": 0, "y": 0 }, { "x": 12, "y": 4 }],
      "color": "#3b82f6", "width": 2 }
  ]
}
```

| Field | Ý nghĩa |
| --- | --- |
| `nodes[].kind` | `'shape'` (vector) \| `'card'` (UI/reasoning/annotation) \| `'webview'` (iframe live preview) |
| `nodes[].shape` | `rect` \| `ellipse` \| `triangle` \| `diamond` (chỉ khi `kind === 'shape'`) |
| `nodes[].card` | `ui-mockup` \| `agent-reasoning-flow` \| `directive-annotation` (chỉ khi `kind === 'card'`) |
| `nodes[].url` | URL iframe (chỉ khi `kind === 'webview'`) |
| `nodes[].style` | `fill`, `stroke`, `strokeWidth`, `radius` — màu HEX thật (SVG attribute + JSON agent) |
| `connectors` | lưu `fromNodeId/toNodeId` + 2 cạnh neo, KHÔNG lưu tọa độ tuyệt đối |
| `strokes` | mỗi nét bút chì là một đối tượng độc lập (chọn/move/đổi màu/xóa riêng) |

`title`/`body` là PLAIN TEXT — không markdown/KaTeX. Màu HEX mirror `index.css`
(nhãn chú đồng bộ) — xem `palette.ts`.

## 2. Phép chuyển screen ↔ world

```
scale = zoomLevel / 100
world.x = (screen.x - origin.x - pan.x) / scale
world.y = (screen.y - origin.y - pan.y) / scale

screen.x = world.x * scale + pan.x + origin.x
screen.y = world.y * scale + pan.y + origin.y
```

- `origin` là `rect.left/top` của container (đo bằng `getBoundingClientRect()` qua
  `ResizeObserver` ở `CanvasStage`).
- `pan` là offset kéo (screen-space px) khi Hand/Space/middle-click.
- World container áp `transform: translate(pan) scale(scale)` với `transform-origin:
  top-left`; mọi node đặt theo `left/top` world.
- Các hàm thuần trong `geometry.ts` (`screenToWorld`, `worldToScreen`, `boundsOfNode`,
  `boundsOfStroke`, `pointsToPath`, `fitsIn`, `distance`, `distanceToSegment`).

## 3. Thuật toán neo connector

`anchorPoint(node, side)` (world-space):

```
cx = node.x + node.width/2; cy = node.y + node.height/2
top=(cx, y)  right=(x+w, cy)  bottom=(cx, y+h)  left=(x, cy)  center=(cx, cy)
```

`nearestAnchors(a, b)` — chỉ chạy LÚC TẠO connector (không chạy mỗi lần move);
kết quả bám theo hướng trục giữa hai tâm node (`dx` vs `dy`), không dùng `center`:

```
dx = b.x + b.w/2 - (a.x + a.w/2); dy = b.y + b.h/2 - (a.y + a.h/2)
nếu |dx| >= |dy|:   // liên kết chạy ngang
  from/to = dx >= 0 ? right/left : left/right
ngược lại:          // liên kết chạy dọc
  from/to = dy >= 0 ? bottom/top : top/bottom
```

Quy tắc deterministic, cho đầu ra đúng hướng: ngoặt ngang → right/left, cao dọc → bottom/top.

Endpoint được tính LẠI mỗi render (`connectorPoints`) → khi node move, hai đầu trượt
mượt theo cạnh đã chọn, không đứt trục. Arrowhead (`connectorPath`):

```
d = normalize(to - from)
headLen = 14; base = to - d*headLen; wingLen = headLen*0.55
wing1 = rotate(d, +140°) * wingLen; wing2 = rotate(d, -140°) * wingLen
path = "M from L base  M base L wing1  M base L wing2"
```

`hitTestConnector` dùng `distanceToSegment` (dung sai theo zoom).

## 4. Giao thức Agent Canvas (`boxfox.canvas.v1`)

Hai chiều. `agent-protocol.ts` cung cấp `buildCanvasMessage`, `buildCanvasDirective`,
`applyCanvasAction`, `parseCanvasMessage`.

**User → Agent** — `type: 'scene'` gửi cả cảnh:

```json
{ "protocol": "boxfox.canvas.v1", "type": "scene", "scene": { "version": 1, "nodes": [], "connectors": [], "strokes": [] } }
```

Chuột phải vào một component → `type: 'directive'` ("Ask agent to fix this
component"):

```json
{ "protocol": "boxfox.canvas.v1", "type": "directive",
  "targetNodeId": "node-c1", "targetNodeTitle": "Frontend UI Mockup",
  "instruction": "Sửa đúng component này theo yêu cầu của người dùng." }
```

**Agent → UI** — `type: 'action'` gồm 4 lệnh tối thiểu:

```ts
type CanvasAction =
  | { type: 'CREATE_NODE'; node: CanvasNode }
  | { type: 'CONNECT_NODES'; connector: Omit<CanvasConnector, 'id'> & { id?: string } }
  | { type: 'UPDATE_NODE'; nodeId: string; patch: Partial<CanvasNode> }
  | { type: 'DELETE_NODE'; nodeId: string }
```

`applyCanvasAction(scene, action)` là reducer thuần, bất biến:
- `CREATE_NODE` — append; từ chối id trùng.
- `CONNECT_NODES` — append sau khi gán id; TỪ CHỐI nếu thiếu node tham chiếu.
- `UPDATE_NODE` — merge patch; từ chối node lạ.
- `DELETE_NODE` — xóa node + CASCADE mọi connector trỏ tới node đó.

`parseCanvasMessage` validate `protocol`/`version`/nội dung trước khi nhả action/scene
(fail-safe khi backend gửi dữ liệu lạ). Việc nối transport thật
(`agentStore.sendCommand`) để TODO ngay trong `useDesignCanvas.ts`; hợp đồng JSON đã
sẵn sàng và **không** được in/nhật ký nội dung người dùng ra ngoài.

## 5. Ghi chú hiệu năng

- Kéo/thả (node/resize/pan/stroke) đi qua Pointer Events + `setPointerCapture`; các
  cập nhật `mousemove` được throttle bằng `requestAnimationFrame` trong `CanvasStage`.
- SVG giữ tĩnh theo scene; pan/zoom chỉ thay `transform` của world container, không
  dựng lại path mỗi khung hình.
- Viewport culling bằng `fitsIn` cho scene lớn (nếu hàng nghìn node thì cân nhắc
  canvas 2D/WebGL — ngoài phạm vi).
- Undo/redo là stack snapshot bất biến giới hạn 50 bước; chỉ `commit` ở ranh giới
  thao tác (pointer-up / xong stroke), không mỗi `mousemove`.
- Ô text là `textarea` thuần — không markdown/KaTeX; nhập title rỗng thì fallback
  `cardTitleFallback(card)`.
