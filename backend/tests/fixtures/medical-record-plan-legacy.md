<!-- boxfox-plan
Version: v1
Identity: medical-record-synthesis-agent
Parent: none
-->
# Agent Tong Hop Ho So Y Te (Medical Record Synthesis Agent) — v1

Muc tieu: tu tai lieu tho (anh/PDF/CSV) -> ho so benh an chuan hoa + tom tat co trich dan + kiem tra chat luong, chay offline trong Docker sandbox. Bo sung cho plan v3: v3 lam "tim kiem tren ho so da co", plan nay lam "tao ho so tu giay to".

## Pham vi

IN:
- Parse tai lieu: anh chup, PDF, file text/CSV xuat tu phan mem benh vien.
- Chu hoa thanh `PatientRecord` (dung lai schema Pydantic cua plan v3).
- Tom tat theo dong thoi gian, moi luan ket lien khop `encounter_id` + doan trich nguyen van.
- Kiem tra day du: truong bat buoc thieu, muc do tin cay.
- Che PII theo vai tro (ke thua module cua v3).

OUT (khong lam):
- Khong chan doan, khong goi y dieu tri, khong quyet dinh chuyen tuyn.
- Khong ket noi API benh vien that; du lieu chi la mock / tai lieu nguoi dung upload.
- Khong LLM tu do: tom tat bat buoc trich tu nguyen van (anti-hallucination).

## Kien truc

Upload -> Parse (OCR/PDF/text) -> Field Extractor (rule + LLM co JSON Schema khoa) -> Validator (schema + completeness) -> Summarizer (template, trich dan) -> PII Redactor (theo role) -> JSON + Markdown report

## Implementation Milestones

- M1 Schema + fixtures (Backend): tai su dung `models/schemas.py` cua v3; tao 12 tai lieu mau kem `expected.json` lam chuan doi chieu.
- M2 Parse pipeline (Backend): PDF/anh/text -> text; luu `doc_id`, `page`, `bbox` de moi trich dan quay ve nguon.
- M3 Extractor + Validator (Backend): rule cho ngay thoi/diem so; LLM co schema khoa cho phan tach con nguoi; flag `missing` / `low_confidence`.
- M4 Summarizer co trich dan (Backend): timeline + bullet, moi cau bat buot co `(doc_id, page, quote)`.
- M5 RBAC + PII + audit log (Reviewer): ke thua `security/` cua v3, them `AUDIT_SYNTHESIS` cho moi lan tom tat.
- M6 API + CLI (Backend/Frontend): `POST /api/v1/synthesize`, `POST /api/v1/validate`; CLI `python -m medical_agent.cli.synthesize --in <file>`.
- M7 Test + do chinh xac (Tester): unit, integration, PII leak, va bo 20 cau hoi co nhan de do recall.

## Files to Modify / Create

| File | Han dong |
| :-- | :-- |
| `medical_agent/models/schemas.py` | them `SourceDocument`, `ExtractedRecord`, `Citation` |
| `medical_agent/ingest/parser.py` | PDF/image/text -> text + bbox |
| `medical_agent/services/extraction_service.py` | rule + LLM co schema khoa |
| `medical_agent/services/validation_service.py` | kiem tra day du, do tin cay |
| `medical_agent/services/summarizer.py` | timeline co trich dan |
| `medical_agent/security/pii_redactor.py` | mo rong cho text tho (regex so CCCD) |
| `medical_agent/api/routes.py` | them 2 endpoint |
| `medical_agent/cli/synthesize.py` | chay CLI khong can server |
| `data/samples/*` + `expected.json` | 12 fixture |
| `tests/test_synthesis.py` | dap an dung 20 cau |
| `tests/test_pii_synthesis.py` | kiem ro ri PII |

## Verification / Acceptance Criteria

Tat ca lenh duoi day la PLANNED (chua chay) — workspace hien chi co `test/t.py` va `.plans/`.

1. `python -m medical_agent.data.mock_generator --count 50`
   Expected: exit code 0; `medical_records.db` ton tai va nhom it nhat 150 encounters.
2. `pytest tests/test_synthesis.py -v`
   Expected: tat ca test PASS va lenh danh gia in `Recall@20 >= 0.85` tren bo 20 cau co nhan.
3. `pytest tests/test_synthesis.py -k citations -v`
   Expected: PASS; moi cau trong `summary` co `citation.doc_id` ton tai trong `sources` (khong cau nao rong).
4. `pytest tests/test_pii_synthesis.py -v`
   Expected: PASS; response voi role `AUDITOR` khong khop regex so 10 digit (SDT) hay 12 digit (CCCD).
5. `curl -s -X POST localhost:8000/api/v1/synthesize -F file=@data/samples/case_01.pdf`
   Expected: HTTP 200, JSON co khoa `record`, `summary`, `citations`.
6. `python -m medical_agent.cli.synthesize --in data/samples/case_01.pdf --out out.md`
   Expected: file `out.md` duoc tao va khong rong.

## Risks / Limitations

| Rui ro | Giam nhe |
| :-- | :-- |
| OCR sai chu viet tay, anh mo | chi danh do tin cay, cho nguoi dung sua; khong tu suy dien |
| LLM them thong tin ngoai ho so | bat buoc co citation; cau khong co citation bi loai khoi output |
| Ho so mau khong dai dua duoc case that | chi dung mock; khong dung cho quyet dinh lam sang |
| TT 01/2025 / Luat BHYT sua doi | rule hieu luc gan `effective_date`, review lai truoc khi dung that |
| Van ban goc chua doc duoc | noi dung phap lanh lay tu dossier, chua doc ban goc — xem Sources |

## Sources / Citations

Chi trich dan tu file da doc bang `file_read` trong phien nay:

- `.plans/v3-medical-record-retrieval-agent-plan.md` — plan nen tang: schema `medical_agent/*`, FTS5 + ChromaDB, RBAC 4 vai tro (`DOCTOR`/`NURSE`/`PATIENT`/`AUDITOR`), va yeu cau PII redaction. Ke thua dung file nay, khong viet lai.
- `.research/agent-chuyen-tuyen-vn-nen-20260925-0350/v1-agent-chuyen-tuyen-vn-nen.md` — trich dan: "TT 01/2025/TT-BYT do Bộ Y tế ban hành 01-01-2025, hiệu lực 01-01-2025"; "phiếu ... hiệu lực 10 ngày làm việc kể từ ngày ký". Cung vhoi trich dan: "TT 01/2025 đã bị sửa bởi 06/2026/TT-BYT, 18/2025/TT-BYT (r28) — chưa có bản hợp nhất trong tay; mọi logic hiệu lực trong MVP phải gắn phiên bản". Do do phai gan `effective_date` vao tung rule.
- `.research/agent-ho-tro-chuyen-tuyen-20260925-0416/v1-agent-ho-tro-chuyen-tuyen.md` — trich dan: "LLM y tế: chẩn đoán kém hơn BS đáng kể, không tuân thủ guideline, không diễn giải đúng xét nghiệm — chưa sẵn sàng ra quyết định lâm sàng tự động (r16, Nature Medicine)". Co so cho rang buoc "khong chan doan / khong goi y dieu tri" trong muc Pham vi.
- `.research/agent-ho-tro-chuyen-tuyen-20260925-0416/sources.md` — ledger cac URL va trich dan nguon thu cap (Nature `s41591-024-03097-1`, `s43856-023-00370-1`, luatvietnam TT 01/2025, baochinhphu). UNVERIFIED trong phien nay: phai doc truc tiep URL moi xac nhan dung nhat (toan bo phan dinh nghia dinh kiem tra chua dung lam can cuat phap ly cua code).
