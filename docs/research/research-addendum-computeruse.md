# Bằng chứng bổ sung — computer use & GUI agent (verify 2026-08-23)

## Tấn công qua màn hình
- **VPI-Bench** (ICLR 2026, arXiv 2506.02456): benchmark visual prompt injection cho computer-use agent.
  306 test case, 5 nền tảng, chỉ thị độc nhét vào trang web đã render.
  ASR tới **51% với CUA**, **100% với browser-use agent** trên một số nền tảng.
- **WAInjectBench** (arXiv 2510.01354): detector text + image bắt được tấn công lộ rõ, **thất bại với tấn công tinh vi/khó thấy**.
- **WASP** (arXiv 2504.18575): web agent security end-to-end, model mạnh vẫn bị lừa.
- **InjecAgent** (arXiv 2403.02691): indirect prompt injection cho tool-integrated agent.

## Benchmark computer use (SOTA đầu 2026, Stanford AI Index 2026 ch.2)
- **OSWorld**: 12% (2023) -> **66,3%** (đầu 2026). Human baseline ~72%.
  Một số claim 2026 cao hơn (76,26%, 82%+) nhưng không nhất quán giữa nguồn.
- **WebArena**: **74,3%** đầu 2026. Human baseline **78,2%**. OpenAI CUA báo 58,1%.
=> Ý nghĩa: utility của computer use vẫn còn xa hoàn hảo. KHÔNG nên thi ở trục "điểm cao hơn".

## Model computer use sẵn dùng (không cần train)
- Google: computer use nay là **capability trong Gemini 3.7 Flash (khuyến nghị), 3.5 Flash, 3.5 Flash-Lite, 3 Flash Preview**.
  `gemini-2.5-computer-use-preview` là **legacy preview**, chỉ browser.
  Nguồn: ai.google.dev/gemini-api/docs/computer-use
  Doc mới nói có sẵn: browser + mobile + desktop, configurable safety policies, **prompt injection detection**.
  Input image+text, output text (action).
- User đã có GEMINI_API_KEY -> dùng được ngay, không cần GPU.

## Nền sandbox/GUI mã nguồn mở có thể học kiến trúc
- **OpenHands**: workspace cho agent, chạy Docker hoặc remote VM, **expose browser qua VNC**,
  web UI, "Agent Canvas" là control surface. docs.openhands.dev/openhands/usage/sandboxes/docker
- Chưa verify được từ nguồn: Suna, E2B, Daytona (search không trả doc chính thức).
