# Research Brief — dùng làm input cho việc viết kế hoạch

Đây là toàn bộ ngữ cảnh và bằng chứng đã thu thập từ Phase 1-2 của phiên thảo luận với user.
KHÔNG search lại từ đầu; dùng cái này làm điểm xuất phát. Có thể search bổ sung nếu cần chi tiết kỹ thuật.

## User là ai
- Sinh viên, làm đồ án tốt nghiệp. Solo hoặc 2-3 người. **~3 tháng**, linh động (có thể ngắn/dài hơn).
- Mạnh: AI/ML/DL. Nền Computer Vision + diffusion trước khi chuyển sang agent. Đã làm xong 1 project Agentic RAG + ReAct agent.
- Yếu: **SWE/hạ tầng**. KHÔNG hiểu thuật ngữ security/infra. Không biết Pipelock là gì, không quen proxy/MITM/Go.
  => Kế hoạch phải viết bằng tiếng Việt dễ hiểu, giải thích mọi thuật ngữ ngay lần đầu dùng. Ưu tiên **Python**.
- Ngân sách: nhỏ-vừa (VPS nhỏ, ít API credit). KHÔNG thuê GPU cluster, KHÔNG train model từ đầu.
- Mục tiêu theo thứ tự: (1) sản phẩm thật có người dùng, (2) đồ án tốt nghiệp, (3) CV/portfolio, (4) open source GitHub/Play Store.

## Quyết định user đã chốt
1. **Option A (hệ sinh thái đa module) KHÔNG làm ngay** — quá lớn. Làm MVP là *tầng nền* của A, mở rộng sau.
2. MVP = **hạ tầng + UI mỏng để demo** (dashboard đọc sổ audit). Không làm UI end-user đầy đủ.
3. Phần ML: **chưa rõ**, user sẽ hỏi lại GVHD => kiến trúc phải để chỗ ML là **tùy chọn cắm thêm được**.
4. Nhóm người dùng đầu: dev dùng coding agent (đau nhất, bằng chứng cứng nhất) — nhưng xem #7.
5. **Định vị đã chốt (Option 1): user TỰ XÂY agent riêng, nhưng bán bằng "cơ chế an toàn/minh bạch", KHÔNG thi ở trục "agent code giỏi hơn".**
6. **QUAN TRỌNG — agent KHÔNG chỉ là coding.** User nói rõ: agent có thể giúp việc thường ngày, edit ảnh, v.v.
   User đang "đào rộng để tìm hướng", chưa thiên hẳn 1 hướng. => Kế hoạch phải thiết kế agent **đa năng qua tool/module**,
   coding chỉ là bộ tool đầu tiên. Kiến trúc phải cho thấy thêm module (edit ảnh diffusion, việc thường ngày) là dễ.
7. **Cloud agent**: user muốn kế hoạch **nói về CẢ HAI** (local box + cloud) vì cloud agent có thể là sản phẩm mai sau.
   Nhưng **ưu tiên local box first**. Bản kế hoạch chi tiết riêng cho cloud sẽ làm sau.
   => Phần cloud: nói về kiến trúc + lộ trình + cái gì phát sinh (auth, cách ly user, quota ~3-4 tuần), KHÔNG đi sâu implementation.
8. Ba giá trị bán: user chọn "cả ba" và tôi đã đồng ý — vì chúng là 3 mặt của CÙNG 1 cơ chế:
   (a) chống prompt injection, (b) minh bạch dữ liệu rời máy, (c) giảm prompt mà không giảm an toàn.
   Trục demo chính = (a) vì đo được bằng attack success rate.

## HAI ĐÓNG GÓP KỸ THUẬT CỐT LÕI (differentiator)
### Đóng góp #1 — "Nhãn nguồn gốc" (provenance/taint labels) gắn thẳng vào tool layer
Mọi dữ liệu agent đọc vào được dán nhãn nguồn: user gõ = TRUSTED; file trong repo = SEMI; web fetch / file lạ / skill của người khác = UNTRUSTED.
Nhãn lan (propagate) qua các bước. Trước khi agent thực hiện hành động nguy hiểm (chạy lệnh, ghi file ngoài scope, gửi dữ liệu ra ngoài),
policy engine hỏi: hành động này có nguồn gốc từ dữ liệu UNTRUSTED không?

**Vì sao đây là khe hở thật:**
- CaMeL (Google DeepMind, arXiv 2503.18813) giải đúng bài này nhưng **đòi custom interpreter + dual-LLM** => phải viết lại agent
  => không ai áp dụng được vào agent có sẵn => chết trong paper. Simon Willison (simonwillison.net/2025/Apr/11/camel/) nói lợi ích
  đi kèm chi phí vận hành/UX thật; criticism khác: policy sprawl, latency, custom interpreter làm khó deploy.
- **Nhưng user đang viết agent từ đầu** => cái chi phí chặn CaMeL lan rộng, với user là MIỄN PHÍ.
- Mọi firewall hiện có (Pipelock, AgentWall) đứng NGOÀI agent nên chỉ xét *nội dung* request ("có giống API key không") —
  KHÔNG biết *nguồn gốc*. Nếu làm ngoài thì chỉ xấp xỉ được bằng so khớp chuỗi; làm trong tool layer thì biết chính xác.
- Search đã xác nhận: **chưa có dự án open-source nào làm taint tracking end-to-end**. Hiện chỉ có hook quét nội dung
  (lasso-security/claude-hooks, prompt-injection-detector) và audit gate cho plugin (geoffrey-young/anthropic-hackathon-2026).

### Đóng góp #2 — "Giấy phép có hạn" (capability lease) thay approval boolean
Thay vì "cho phép? [Có] [Có, đừng hỏi lại]" (công tắc bật vĩnh viễn), cấp giấy phép hẹp:
scope cụ thể (vd chỉ thư mục src/) + thời hạn (vd 10 phút) + gắn với 1 nhiệm vụ + revoke được. Enforce ở tool layer.

**Bằng chứng đây là lỗ hổng thật:**
- arXiv 2510.26328: approval "don't ask again" cho hành động lành tính bị **carry-over** sang bước exfiltration sau đó — **0 prompt thêm**.
  Nghĩa là cơ chế approval hiện tại sai về bản chất.
- Claude Code có thể hỏi **~100 permission/giờ** => permission fatigue => dev rubber-stamp hoặc chạy `--dangerously-skip-permissions`
  (Anthropic tự khuyên chỉ dùng flag đó trong container/VM).
- Goose issue #3386: `GOOSE_MODE=auto` bị ignore, vẫn hỏi mọi Edit/Write/Bash.
- Pattern "capability lease" đã được đặt tên trong tài liệu UX 2026 nhưng **chưa dự án open-source nào implement**.

## BẰNG CHỨNG THỊ TRƯỜNG (đã verify qua search, có nguồn)

### Bằng chứng mạnh nhất — và nó KHÔNG giới hạn ở coding
- **Snyk ToxicSkills audit (2026)**: scan 3.984 skill từ ClawHub + skills.sh =>
  **1.467 skill có lỗi bảo mật (36,82%)**, **534 skill (13,4%) có lỗi critical**, **76 payload độc đã xác nhận**,
  8 skill độc vẫn còn live lúc công bố. Marketplace sau đó lên **>13.000 skill** — vượt xa khả năng vet thủ công.
  Nguồn: snyk.io/blog/toxicskills-malicious-ai-agent-skills-clawhub/
- **OWASP Agentic Skills Top 10** (mới, 2026): AST01 Malicious Skills, AST02 Supply Chain Compromise,
  AST03 Over-Privileged Skills, AST04 Insecure Metadata, AST05 Untrusted External Instructions, AST06 Weak Isolation,
  AST07 Update Drift, AST08 Poor Scanning, AST09 No Governance, AST10 Cross-Platform Reuse.
  => **Đóng góp #1 đánh trực tiếp AST05, #2 đánh AST03. Có thể map kế hoạch vào chuẩn này — rất tốt cho đồ án.**
- **CSA research notes 2026**: SKILL.md agent context poisoning; AI skill supply chain attacks. Khuyến nghị cần
  provenance: skill nào gây ra hành động này, publisher là ai, load path từ đâu, correlate log egress.
  => Đúng thứ đóng góp #1 cung cấp.
- **OpenClaw**: ~21.000 instance lộ ra internet (01/2026, Censys-based); rò rỉ credential; MITRE ATLAS có report riêng;
  Unit42 Palo Alto có bài về OpenClaw AI supply chain risk.

### Bằng chứng cho nhóm "agent việc thường ngày" (không coding)
- **Khoj** (~34.165 sao) và **Leon** (~17.168 sao) là 2 self-hosted personal assistant lớn nhất.
  Complaint thật từ GitHub issues: cài đặt fiddly (issues #910, #1035, #1052, #1100 — fail install Ubuntu, streaming error,
  khó nối Ollama local từ Docker). Khoj default là **single-user + anonymous mode**, muốn multi-user phải bật Magic Links/Google OAuth.
  => **Không ai trong nhóm này có permission control hay provenance.** Khe hở tồn tại ở cả nhóm non-coding.
- Suna (kortix-ai/suna) cũng trong nhóm này.

### Đối thủ trực tiếp ở tầng "bảo vệ agent" — phải trung thực
- **Pipelock** (Apache-2.0, Go, ~800 sao, HelpNetSecurity đưa tin 05/2026): egress proxy MCP-aware, 65 DLP pattern,
  sandbox, phát hiện prompt injection, audit hash-chain ký Ed25519, operator dashboard.
  **=> Đã làm xong: chặn egress + redact secret + audit ký số. KHÔNG có: provenance/taint, lease.**
- **AgentWall** (Go binary): redact secret, log+replay, budget. Không chặn tool-call, không taint, không lease.
- **NVIDIA OpenShell**: sandbox + YAML permission, kernel-isolated. Nhắm enterprise/K8s.
- **Microsoft Agent Governance Toolkit**: enterprise, có audit + policy. Không cho 1 người dùng cá nhân.
- **Anthropic sandbox-runtime** (anthropic-experimental): sandbox FS+network. Không taint, không lease.
- **Open Agent Passport**: spec pre-action authz + signed audit. Spec-only, chưa sản phẩm.
- **IBM ContextForge, Docker MCP Gateway, agentgateway, Lunar MCPX**: MCP gateway tầng enterprise.
- **SecureClaw** (56 audit checks), **openclaw-hardening**, **Caelguard** (22 checks): chỉ quét cấu hình TĨNH (file/port),
  KHÔNG chặn runtime theo từng tool-call.
- **ressl/mcp-firewall, iron-proxy**: từng mảnh (network sandbox, pre-action authz).
- Nghiên cứu liên quan: NeuroTaint, Sleeper Channels / Provenance Gates.

### Ngách ĐÃ ĐÔNG — user đã tự loại, đừng đề xuất lại
- Full cloud/local coding agent: Devin, Cursor, Codex, Jules, Vorflux, OpenHands, Goose.
  => Rào cản KHÔNG phải vòng lặp agent (giờ ~50 dòng Python với Claude Agent SDK / LangGraph),
  mà là CHẤT LƯỢNG (OpenHands có hàng trăm contributor tinh chỉnh prompt/retry/context).
  1-3 người / 3 tháng không thắng ở trục "code giỏi hơn".
- AI code review: CodeRabbit, Greptile. Agent observability/eval: Braintrust, Galileo.
- Agent memory: **mem0 (~63K sao)**, Letta, Zep/Graphiti, Cognee, TencentDB Agent Memory. => B5 chết, đừng làm lại.
- Image edit agent: **comfyui-mcp** đã cho agent sửa graph ComfyUI bằng NL; Qwen-Image-Edit, Step1X-Edit, JoyAI-Image-Edit
  là model edit native. => B3 khe hở gần 0 nếu làm độc lập; CHỈ nên làm như 1 module trong hệ.
- dLLM cho code: các bài toán mở rõ nhất đã bị lấy 2025-2026: **DreamOn** (canvas động, `<|expand|>`/`<|delete|>`),
  **CAL** (suy length không cần train), **Dream-Coder 7B** (SFT+RLVR, padding pathology). => B1 rủi ro cao, không ra người dùng.
- Vibe-coding terminal orchestrator: Vibe Kanban, Claude Squad, Conductor, cmux, NTM (9+ tool).
- Trợ lý toàn năng: Gemini Spark (khoá Gemini), Claude Cowork (khoá Claude).

### Nỗi lo dữ liệu rời máy là thật ở mức doanh nghiệp
- **Alibaba cấm Claude Code tại nơi làm việc** (Reuters, 07/2026).
- **Oracle cấm đóng góp AI-generated vào OpenJDK**. Zig/NetBSD/GIMP/Gentoo/qemu từ chối contribution AI.
- Nhiều thread r/LocalLLaMA / r/selfhosted về "transparent LLM logging proxy", "self-hosted proxy strips PII"
  => người dùng tự dựng proxy để biết dữ liệu gửi gì. Nhu cầu tự phát, chưa có sản phẩm gọn.

## PHÁT HIỆN KỸ THUẬT ĐÃ VERIFY — làm việc dễ hơn nhiều so với dự đoán ban đầu
1. **KHÔNG cần MITM TLS.** Chỉ cần `export ANTHROPIC_BASE_URL=http://127.0.0.1:8317` là mọi request đi qua
   FastAPI của user. Proxy passthrough chạy được ~40 dòng Python (có ví dụ đầy đủ tại docs.litellm.ai/docs/pass_through/anthropic_completion
   và github.com/1rgs/claude-code-proxy). Không cert, không Go.
   Lưu ý kỹ thuật: cần hỗ trợ streaming SSE, scrub header, và `ANTHROPIC_BASE_URL` phải là host root không phải full path `/v1/messages`.
2. **Claude Code có hook chính thức**: `PreToolUse` gọi script của user trước mọi hành động,
   trả `hookSpecificOutput.permissionDecision` = `allow`/`deny`/`ask`/`defer` (exit code 2 = block, dạng cũ `decision` đã deprecated).
   Đây là chỗ enforce lease nếu muốn tích hợp Claude Code. Nguồn: code.claude.com/docs/en/hooks
3. **Claude Agent SDK (Python)** cho phép tự xây agent loop: `ClaudeSDKClient`, `await client.query(...)`,
   `allowed_tools`, `hooks`, `max_turns`, `canUseTool`-style permission callback. Nguồn: code.claude.com/docs/en/agent-sdk/python
4. **LangGraph** mạnh nhất cho human-in-the-loop / interrupt / checkpoint / durable execution — phù hợp nếu cần
   pause-resume chờ approval. PydanticAI nhẹ+typed nhưng yếu orchestration. OpenAI Agents SDK thin, OpenAI-native.
5. **LiteLLM** = chuẩn de-facto cho multi-model (không khoá 1 vendor). Dùng nó cho 3 tầng model, không tự viết.
6. Agent tự viết bằng Python + SQLite => **chạy local hay chạy VPS là CÙNG code**. Cloud agent (1 người dùng) gần như miễn phí.
   Multi-user mới phát sinh auth/cách ly/quota (~3-4 tuần).

## Benchmark / đánh giá
- **AgentDojo** là chuẩn benchmark prompt injection cho agent (đo attack success rate + utility under attack).
  Dùng nó làm nền cho phần đánh giá định lượng.
- Metric cần đo: (1) attack success rate trước/sau khi bật cơ chế, (2) false-positive rate của over-taint
  (bao nhiêu hành động lành tính bị chặn oan), (3) số prompt hỏi user giảm bao nhiêu, (4) overhead latency/token.
- Taint ở tầng tool là **conservative approximation**: bắt được reuse trực tiếp + canary token,
  bỏ sót biến đổi ngữ nghĩa (LLM diễn giải lại ý). **Phải nói thẳng giới hạn này trong đồ án** — chính nó là chỗ
  để đo và thảo luận, và là điểm mạnh học thuật.
- Chỗ cắm ML tùy chọn (nếu GVHD yêu cầu): classifier local phát hiện prompt-injection / phân loại dữ liệu nhạy cảm,
  có dataset + metric riêng. Kiến trúc phải để đây là plug-in point, không phải bắt buộc.

## Repo
- Repo đích: `khaikhaichimtoonly-star/Cloud-Anget-P` tại `/code/khaikhaichimtoonly-star/Cloud-Anget-P`.
  Hiện TRỐNG (chỉ có README.md chứa `# Cloud-Anget-P`). Đây sẽ là repo của dự án.
