"""Khung báo cáo và danh mục mô-đun cho research v2 (P2, §5.8).

Tệp **thuần**: không I/O. Nó là **một nguồn định nghĩa duy nhất** cho tên mô-đun: hồ sơ, cổng chất
lượng (`research_quality`) và bộ đánh giá (`scripts/eval/research_checks`) đều đọc từ đây, không
chép tay danh sách từ khoá tiêu đề như trước.

Cổng của P2 kiểm **cấu trúc**, không dò chữ trong tiêu đề: mô-đun đã hứa trong thẻ phạm vi phải có
mặt, nhận định chính phải trỏ tới `claimId` có thật trong sổ, mục "Chưa khảo sát" phải khớp với facet
chưa bão hoà, và nhận định suy luận không được mang độ tin cậy của dữ kiện.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from .research_evidence import CONFIDENCE_RANK, is_inference

#: Khung dùng cho **mọi** run (§5.8), theo đúng thứ tự mục trong báo cáo.
FRAME_SECTIONS = (('conclusions', 'Kết luận ngắn'), ('scope', 'Phạm vi'), ('method', 'Cách tìm'),
                  ('content', 'Nội dung theo mô-đun'), ('conflicts', 'Mâu thuẫn và cách xử lý'),
                  ('limits', 'Giới hạn và điểm chưa chắc'), ('unexplored', 'Chưa khảo sát'),
                  ('sources', 'Nguồn'))

#: Mười mô-đun của §5.8. `jobTypes` quyết định mô-đun nào được đề xuất cho một kiểu việc.
MODULES = {
    'M-landscape': {'title': 'Cảnh quan hướng × nhóm phương pháp',
                    'jobTypes': ('landscape', 'mixed', 'quick')},
    'M-litmap': {'title': 'Bản đồ văn liệu và dòng trích dẫn',
                 'jobTypes': ('literature-map', 'mixed')},
    'M-paper-card': {'title': 'Thẻ bài báo (đóng góp, giả định, thiết lập, số liệu, giới hạn)',
                     'jobTypes': ('deep-dive', 'literature-map', 'comparison')},
    'M-artifacts': {'title': 'Mã nguồn, dữ liệu, checkpoint (chính thức hay bên thứ ba)',
                    'jobTypes': ('deep-dive', 'comparison', 'mixed')},
    'M-compare': {'title': 'Ma trận đối tượng × tiêu chí, kèm cột "so sánh được không"',
                  'jobTypes': ('comparison', 'mixed')},
    'M-gaps': {'title': 'Sổ khoảng trống (có bằng chứng hay chỉ là giả thuyết)',
               'jobTypes': ('gap', 'literature-map', 'mixed')},
    'M-market': {'title': 'Sản phẩm/triển khai × nấc bằng chứng thị trường',
                 'jobTypes': ('market', 'comparison', 'mixed')},
    'M-verdict': {'title': 'Phán quyết: ủng hộ, phản bác, điều kiện đúng, giải thích khác',
                  'jobTypes': ('claim-check', 'mixed')},
    'M-changelog': {'title': 'So với bản cũ: đổi gì, còn đúng gì, nguồn nào đã cũ hoặc bị rút',
                    'jobTypes': ('refresh', 'mixed')},
    'M-extras': {'title': 'Tuỳ chọn: thư mục có chú giải, khuyến nghị, kế hoạch thử nghiệm',
                 'jobTypes': ('quick', 'mixed'), 'optional': True},
}

#: Mô-đun **bắt buộc** theo kiểu việc (mô-đun không có trong bảng này là tuỳ chọn).
REQUIRED_MODULES = {'landscape': ('M-landscape',), 'literature-map': ('M-litmap',),
                    'deep-dive': ('M-paper-card',), 'comparison': ('M-compare',),
                    'gap': ('M-gaps',), 'market': ('M-market',),
                    'claim-check': ('M-verdict',), 'refresh': ('M-changelog',)}

#: Kiểu việc hợp lệ, thứ tự này dùng cho `normalize_job_types` và cho thẻ phạm vi.
JOB_TYPES = ('quick', 'landscape', 'literature-map', 'deep-dive', 'comparison', 'gap', 'market',
             'claim-check', 'refresh', 'mixed')

#: Mã lỗi cổng — ổn định, test và giao diện bám vào đây.
ERROR_MISSING = 'research-report-missing'
ERROR_MODULE_UNKNOWN = 'research-report-module-unknown'
ERROR_MODULE_MISSING = 'research-report-module-missing'
ERROR_SECTION_MISSING = 'research-report-section-missing'
ERROR_CLAIM_MISSING = 'research-report-claim-missing'
ERROR_CLAIM_UNKNOWN = 'research-report-claim-unknown'
ERROR_UNEXPLORED_MISMATCH = 'research-report-unexplored-mismatch'
ERROR_INFERENCE_CONFIDENCE = 'research-report-inference-confidence'
#: Mã gói cho bộ đánh giá/cổng run: một lỗi cấu trúc nào đó đã xảy ra.
ERROR_STRUCTURE = 'research-report-structure'

#: Trạng thái facet được coi là "chưa xong" khi đối chiếu mục "Chưa khảo sát".
NOT_SATURATED_STATUSES = ('unexplored', 'searched', 'thin', 'blocked')


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ('' if value is None else str(value).strip())


def _seq(value: Any) -> list:
    if isinstance(value, (list, tuple, set)):
        return [item for item in value if item not in (None, '')]
    if value in (None, ''):
        return []
    return [value]


def module_ids() -> tuple:
    """Id mọi mô-đun, theo thứ tự khai báo (một nguồn định nghĩa duy nhất)."""
    return tuple(MODULES)


def module_title(module_id: Any) -> str:
    meta = MODULES.get(_text(module_id))
    return meta['title'] if meta else ''


def normalize_module(value: Any) -> str:
    """Chuẩn hoá id mô-đun: `'gaps'`, `'M-GAPS'`, `'m gaps'` → `'M-gaps'`; lạ ⇒ `''`."""
    text = _text(value).casefold().replace('_', '-').replace(' ', '-')
    if not text:
        return ''
    if not text.startswith('m-'):
        text = 'm-' + text
    for module_id in MODULES:
        if module_id.casefold() == text:
            return module_id
    return ''


def normalize_job_types(value: Any) -> tuple:
    """Kiểu việc đã chuẩn hoá, theo thứ tự `JOB_TYPES`; không nhận ra thì bỏ (không ném)."""
    out = []
    for item in _seq(value):
        text = _text(item).casefold().replace('_', '-').replace(' ', '-')
        if text in JOB_TYPES and text not in out:
            out.append(text)
    return tuple(sorted(out, key=JOB_TYPES.index))


def modules_for(job_types: Any) -> tuple:
    """Mô-đun đề xuất cho một kiểu việc: hợp của `jobTypes`, giữ thứ tự `MODULES`."""
    wanted = normalize_job_types(job_types)
    if not wanted:
        return ('M-landscape',)
    out = [module_id for module_id, meta in MODULES.items()
           if set(meta['jobTypes']) & set(wanted)]
    return tuple(out) if out else ('M-landscape',)


def required_modules(job_types: Any) -> tuple:
    """Mô-đun bắt buộc cho một kiểu việc (rỗng khi kiểu việc lạ)."""
    out = []
    for job in normalize_job_types(job_types):
        for module_id in REQUIRED_MODULES.get(job, ()):
            if module_id not in out:
                out.append(module_id)
    return tuple(out)


def section_labels() -> tuple:
    """Nhãn tám mục khung, theo thứ tự báo cáo."""
    return tuple(label for _section_id, label in FRAME_SECTIONS)


def section_ids() -> tuple:
    return tuple(section_id for section_id, _label in FRAME_SECTIONS)


def report_template(job_types: Any, *, level: int = 2) -> dict:
    """Khung rỗng cho một run: mô-đun nào, mục nào, chỗ nào để điền nhận định và bao phủ."""
    modules = modules_for(job_types)
    try:
        heading_level = int(level)
    except (TypeError, ValueError):
        heading_level = 2
    if heading_level < 1:
        heading_level = 1
    return {'schemaVersion': 1, 'level': heading_level, 'modules': list(modules),
            'moduleTitles': [MODULES[module_id]['title'] for module_id in modules],
            'requiredModules': list(required_modules(job_types)),
            'sections': [{'sectionId': section_id, 'label': label, 'heading': '#' * heading_level + ' ' + label}
                         for section_id, label in FRAME_SECTIONS],
            'claims': [], 'coverage': {}, 'unexplored': []}


def sidecar_names(version: Any, *, job_types: Any = (), extractions: Any = ()) -> tuple:
    """Tên tệp phụ của run trong `.research/<run>/` (§5.8).

    `changelog.md` chỉ có khi kiểu việc là `refresh`; `extractions/<source_id>.json` cho từng nguồn
    đã đọc sâu.
    """
    try:
        number = int(version)
    except (TypeError, ValueError):
        raise ValueError('RESEARCH_VERSION_INVALID')
    if number < 1:
        raise ValueError('RESEARCH_VERSION_INVALID')
    names = ['v%d-scope.json' % number, 'v%d-coverage.json' % number,
             'v%d-claims.jsonl' % number, 'v%d-report.json' % number]
    for item in _seq(extractions):
        name = _text(item if not isinstance(item, Mapping) else item.get('sourceId') or item.get('source_id'))
        if not name:
            continue
        name = name.replace('/', '-')
        names.append('extractions/%s.json' % name)
    if 'refresh' in normalize_job_types(job_types):
        names.append('changelog.md')
    return tuple(names)


def _facet_id(value: Any) -> str:
    if isinstance(value, Mapping):
        return _text(value.get('facetId') or value.get('facet_id') or value.get('label'))
    return _text(value)


def _facet_status(value: Any) -> str:
    if isinstance(value, Mapping):
        return _text(value.get('status')).casefold()
    return ''


def unsat_facets(facets: Any) -> list:
    """Facet chưa bão hoà — nguồn sự thật cho mục "Chưa khảo sát" của báo cáo."""
    out = []
    for item in (facets if isinstance(facets, (list, tuple)) else []):
        status = _facet_status(item)
        if status in NOT_SATURATED_STATUSES:
            out.append(_facet_id(item))
    return [item for item in out if item]


def validate_report(report: Any, *, job_types: Any = (), level: int = 2, facets: Any = None,
                    claim_ids: Any = None) -> list:
    """Kiểm cấu trúc của `report`; trả danh sách lỗi `{'code','detail'}`, rỗng nghĩa là đạt.

    Không bao giờ ném. `facets` là bản đồ bao phủ hiện tại; `claim_ids` là tập `claimId` có thật
    trong sổ của run.
    """
    errors = []
    if not isinstance(report, Mapping):
        return [{'code': ERROR_MISSING, 'detail': 'Báo cáo có cấu trúc bị thiếu hoặc không phải object.'}]

    modules = [normalize_module(item if not isinstance(item, Mapping)
                                else item.get('moduleId') or item.get('id') or item.get('name'))
               for item in _seq(report.get('modules'))]
    known = [module_id for module_id in modules if module_id]
    for item in _seq(report.get('modules')):
        if isinstance(item, Mapping) and not normalize_module(item.get('moduleId') or item.get('id')
                                                              or item.get('name')):
            errors.append({'code': ERROR_MODULE_UNKNOWN,
                           'detail': 'Mô-đun không có trong danh mục: %s' % _text(item.get('title')
                                                                                  or item.get('name'))})
    # Chỉ hứa mô-đun khi run ĐÃ khai kiểu việc: `modules_for(())` lùi về `M-landscape` (đề xuất cho
    # thẻ phạm vi trống), nhưng một run không khai gì thì không hứa gì — không được bịa ra mô-đun
    # rồi bắt hồ sơ phải có (`finding 4`).
    promised = set(modules_for(job_types)) if normalize_job_types(job_types) else set()
    for module_id in _seq(report.get('modules')):
        if isinstance(module_id, str) and not normalize_module(module_id):
            errors.append({'code': ERROR_MODULE_UNKNOWN, 'detail': 'Mô-đun lạ: %s' % _text(module_id)})
    for module_id in required_modules(job_types):
        if module_id not in known:
            errors.append({'code': ERROR_MODULE_MISSING,
                           'detail': 'Thiếu mô-đun bắt buộc %s cho kiểu việc đã chọn.' % module_id})
    if not known and promised and not required_modules(job_types):
        errors.append({'code': ERROR_MODULE_MISSING,
                       'detail': 'Hồ sơ không khai mô-đun nào; kiểu việc này cần %s.'
                                 % ', '.join(sorted(promised))})

    sections = [_text(item if not isinstance(item, Mapping) else item.get('sectionId') or item.get('id'))
                for item in _seq(report.get('sections'))]
    for section_id, _label in FRAME_SECTIONS:
        if section_id not in sections:
            errors.append({'code': ERROR_SECTION_MISSING,
                           'detail': 'Thiếu mục khung "%s" (%s).' % (_label, section_id)})

    valid_claims = None
    if claim_ids is not None:
        valid_claims = {_text(item if not isinstance(item, Mapping) else item.get('claimId')
                              or item.get('claim_id'))
                        for item in _seq(claim_ids)}
        valid_claims = {item for item in valid_claims if item}
    for claim in _seq(report.get('claims')):
        if not isinstance(claim, Mapping):
            errors.append({'code': ERROR_CLAIM_MISSING,
                           'detail': 'Mục nhận định phải là object có `claimId`.'})
            continue
        claim_id = _text(claim.get('claimId') or claim.get('claim_id'))
        if not claim_id:
            errors.append({'code': ERROR_CLAIM_MISSING,
                           'detail': 'Nhận định chính thiếu `claimId` (phải trỏ vào sổ).'})
            continue
        if valid_claims is not None and claim_id not in valid_claims:
            errors.append({'code': ERROR_CLAIM_UNKNOWN,
                           'detail': '`%s` không có trong sổ của run này.' % claim_id})
        confidence = _text(claim.get('confidence')).casefold()
        declared = claim.get('claimType') or claim.get('claim_type')
        claim_type = declared if _text(declared) else ''
        if claim_type and is_inference(claim_type) and CONFIDENCE_RANK.get(confidence, 0) > 0:
            errors.append({'code': ERROR_INFERENCE_CONFIDENCE,
                           'detail': 'Nhận định suy luận `%s` không mang độ tin cậy dữ kiện (đang khai '
                                     '`%s`).' % (claim_id, confidence)})
        if claim_type and is_inference(claim_type) and not _seq(claim.get('premises')):
            errors.append({'code': ERROR_INFERENCE_CONFIDENCE,
                           'detail': 'Nhận định suy luận `%s` phải liệt kê tiền đề (claim id).' % claim_id})

    if facets is not None:
        # Đối chiếu mục "Chưa khảo sát" với facet chưa bão hoà; chấp nhận cả `facetId` lẫn nhãn.
        expected = {}
        for row in (facets if isinstance(facets, (list, tuple)) else []):
            if _facet_status(row) not in NOT_SATURATED_STATUSES:
                continue
            facet_id = _facet_id(row)
            if not facet_id:
                continue
            expected[facet_id] = _text(row.get('label') if isinstance(row, Mapping) else '').casefold()
        resolved, unknown = set(), []
        for item in _seq(report.get('unexplored')):
            listed = _facet_id(item)
            if not listed:
                continue
            if listed in expected:
                resolved.add(listed)
                continue
            folded = listed.casefold()
            matched = [facet_id for facet_id, label in expected.items() if label and label == folded]
            if matched:
                resolved.update(matched)
                continue
            unknown.append(listed)
        for listed in unknown:
            errors.append({'code': ERROR_UNEXPLORED_MISMATCH,
                           'detail': 'Mục "Chưa khảo sát" nêu `%s` nhưng facet đó đã bão hoà.' % listed})
        for facet_id in sorted(set(expected) - resolved):
            errors.append({'code': ERROR_UNEXPLORED_MISMATCH,
                           'detail': 'Facet `%s` chưa bão hoà nhưng không có trong mục "Chưa khảo sát".'
                                     % facet_id})
    return errors


def error_codes(errors: Any) -> tuple:
    """Mã lỗi đã bỏ trùng, giữ thứ tự — tiện cho notice và cho bộ đánh giá."""
    out = []
    for item in (errors if isinstance(errors, (list, tuple)) else []):
        code = _text(item.get('code') if isinstance(item, Mapping) else item)
        if code and code not in out:
            out.append(code)
    return tuple(out)
