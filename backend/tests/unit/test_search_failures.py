"""Phân loại lỗi tìm kiếm (F05) — bảng bốn ca + câu chữ ghim bằng test.

Ca gốc: agent đốt bước vì hint cũ ("sửa input rồi gọi lại") khi hạ tầng tìm kiếm đã chết. Bốn ca
dưới đây phải phân biệt được bằng DỮ LIỆU, không bằng cách đoán từ câu chữ.
"""
from __future__ import annotations

import json

import pytest

from agentbox.agent_core import search_failures as sf


def test_a_missing_backend_is_a_config_error_and_does_not_ask_for_a_query_fix():
    verdict = sf.classify(source='web', reasons=['BOXFOX_SEARXNG_URL is not set'],
                          answered_empty=False, backends=[], missing=['BRAVE_API_KEY|BOXFOX_BRAVE_API_KEY'])
    assert verdict == {'code': sf.WEB_SEARCH_UNAVAILABLE, 'kind': 'config'}
    message = sf.message_for(code=verdict['code'], kind=verdict['kind'], source='web',
                             reasons=['BOXFOX_SEARXNG_URL is not set'], backends=[],
                             missing=['BRAVE_API_KEY|BOXFOX_BRAVE_API_KEY'], query='hồ sơ',
                             searxng_url='', autodetect_url='http://127.0.0.1:8888')
    assert 'not a query problem' in message
    assert 'deploy/searxng/up.sh' in message
    assert 'Settings → Provider → Web Search' in message
    assert 'BRAVE_API_KEY|BOXFOX_BRAVE_API_KEY' in message
    assert 'Every provider was refused or empty' not in message


def test_a_dead_searxng_is_an_infra_error_naming_the_url():
    verdict = sf.classify(source='web', reasons=['searxng: connection refused'],
                          answered_empty=False, backends=['searxng'], missing=[])
    assert verdict == {'code': sf.WEB_SEARCH_UNAVAILABLE, 'kind': 'infra'}
    message = sf.message_for(code=verdict['code'], kind=verdict['kind'], source='web',
                             reasons=['searxng: connection refused'], backends=['searxng'],
                             missing=[], query='hồ sơ', searxng_url='http://127.0.0.1:8888')
    assert 'backend problem, not a query problem' in message
    assert 'do not retry the same search' in message
    assert 'http://127.0.0.1:8888' in message
    assert 'connection refused' in message
    assert 'deploy/searxng/probe.py' in message


def test_an_empty_answer_is_its_own_code():
    verdict = sf.classify(source='web', reasons=[], answered_empty=True, backends=['searxng'],
                          missing=[])
    assert verdict == {'code': sf.WEB_SEARCH_EMPTY, 'kind': ''}
    message = sf.message_for(code=verdict['code'], kind=verdict['kind'], source='web', reasons=[],
                             backends=['searxng'], missing=[], query='hồ sơ')
    assert 'returned no rows' in message
    assert 'not an infrastructure failure' in message
    assert 'no backend answered' not in message, 'câu rỗng không được đọc như thiếu backend'
    assert 'not a query problem' not in message, 'ca rỗng KHÔNG phải lỗi cấu hình'


def test_a_source_specific_group_keeps_its_own_message():
    verdict = sf.classify(source='wikipedia', reasons=['wikipedia: HTTP 500'], answered_empty=False,
                          backends=[], missing=[])
    assert verdict == {'code': sf.WEB_SEARCH_UNAVAILABLE, 'kind': 'source'}
    message = sf.message_for(code=verdict['code'], kind=verdict['kind'], source='wikipedia',
                             reasons=['wikipedia: HTTP 500'], backends=[], missing=[], query='q')
    assert "'wikipedia'" in message
    assert 'another source' in message


def test_an_empty_answer_with_a_real_failure_stays_infra():
    """Một chân rỗng + một chân ném KHÔNG phải ca rỗng: `answered_empty` do chỗ gọi quyết định."""
    verdict = sf.classify(source='web', reasons=['brave: HTTP 429'], answered_empty=False,
                          backends=['env:BRAVE_API_KEY'], missing=[])
    assert verdict['kind'] == 'infra'


def test_the_log_variant_carries_no_query_or_url():
    secret = 'hồ sơ bệnh nhân Nguyễn Văn A'
    url = 'https://127.0.0.1:8888/search?q=so-benh-an'
    lines = [sf.log_line_for(code=sf.WEB_SEARCH_UNAVAILABLE, kind='config', source='web',
                             queries=1, attempts=6),
             sf.log_line_for(code=sf.WEB_SEARCH_UNAVAILABLE, kind='infra', source='web',
                             queries=2, attempts=6),
             sf.log_line_for(code=sf.WEB_SEARCH_EMPTY, kind='', source='web', queries=1, attempts=0),
             sf.log_line_for(code=sf.WEB_SEARCH_UNAVAILABLE, kind='source', source='wikipedia',
                             queries=1, attempts=1)]
    for line in lines:
        assert secret not in line and url not in line and 'http' not in line
    assert json.dumps(lines)                     # câu chữ thuần, không phải JSON hỏng


@pytest.mark.parametrize('kind', sf.KINDS)
def test_every_kind_has_a_definition(kind):
    assert kind in ('config', 'infra', 'source')
