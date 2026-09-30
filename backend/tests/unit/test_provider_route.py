"""Vòng 29 — dạng route thứ ba `{providerId, modelId}` đi hết đường từ picker tới router.

Owner chốt ở phỏng vấn: chọn model theo **provider + model** là mặc định, ghim một
connection vẫn được. Phiên mang `{providerId, modelId}` thì router tự chọn connection
trong nhóm của provider (thứ tự `connectionOrder`, có `roundRobin`) và tự failover khi
khoá hết hạn mức — harness không giữ danh sách target nào.

Vì harness không biết trước target nào sẽ phục vụ lượt, metadata của model phải là bản
GỘP của **mọi** connection dùng được: cửa sổ ngữ cảnh là số **min**, mức thinking là
**giao** của các danh sách công bố. Bộ luật này nằm một chỗ (`aggregate_model_metadata`)
và được ba nơi dùng — `api/server.py` lúc tạo phiên, `route_metadata()` cho một lượt đổi
model, và vòng sửa cửa sổ lúc khởi động.

Phiên cũ `{connectionId, modelId}` KHÔNG được chạm: cùng bộ test này ghim lại hành vi cũ.
"""
import asyncio

import pytest

from agentbox.agent_core.runtime import (
    FALLBACK_CONTEXT_WINDOW,
    HarnessRuntime,
    RouterClient,
    aggregate_model_metadata,
    route_for,
)
from agentbox.memory.session_store import SessionStore


class StubExecutor:
    def __init__(self):
        self.container = None

    async def execute(self, name, args, sid):
        return {'content': 'observed fixture result'}

    async def cleanup(self, sid):
        return None


class StubModel:
    """Router client giả: trả lời chat, tra metadata theo connection HOẶC theo provider."""

    def __init__(self, responses=(), records=None, provider_records=None, metadata_map=None):
        self.responses = iter(responses)
        self.records = records or {}
        self.provider_records = provider_records or {}
        self.metadata_map = metadata_map or {}
        self.lookups = []
        self.provider_lookups = []
        self.provider_map_calls = 0
        self.model_metadata = self._model_metadata
        self.provider_model_metadata = self._provider_model_metadata

    async def _model_metadata(self, connection_id, model_id):
        self.lookups.append((connection_id, model_id))
        return self.records.get(model_id)

    async def _provider_model_metadata(self, provider_id, model_id):
        self.provider_lookups.append((provider_id, model_id))
        return self.provider_records.get((provider_id, model_id))

    async def model_metadata_map(self):
        return dict(self.metadata_map)

    async def provider_metadata_map(self):
        self.provider_map_calls += 1
        return dict(self.provider_records)

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        return next(self.responses)


class StubRouterClient(RouterClient):
    """`RouterClient` thật với đúng một lời gọi mạng bị thay: `snapshot()`."""

    def __init__(self, snapshot):
        super().__init__()
        self.snapshot_data = snapshot
        self.reads = 0

    async def snapshot(self):
        self.reads += 1
        return self.snapshot_data


def model_row(model_id='m1', *, window=None, source=None, model_source='static', levels=None,
              thinking_type='effort', **extra):
    """Một record model đúng hình dạng `/api/router/state` trả về."""
    row = {'id': model_id, 'name': model_id, 'enabled': True, 'health': 'ok', 'source': model_source}
    if window is not None:
        row['contextWindow'] = window
    if source is not None:
        row['contextWindowSource'] = source
    if levels is not None:
        row['thinkingLevels'] = list(levels)
    if thinking_type is not None:
        row['thinkingType'] = thinking_type
    row.update(extra)
    return row


def provider_connection(connection_id, models, *, provider_id='opencode', auth_state='ready',
                        discovery='ready', enabled=True, **extra):
    return {'id': connection_id, 'name': connection_id, 'providerId': provider_id, 'enabled': enabled,
            'authState': auth_state, 'discoveryState': discovery, 'projectState': 'not_applicable',
            'models': models, **extra}


def _record(model_id, window=200_000, source='documented', thinking_type='effort',
            levels=('low', 'medium', 'high'), default='high'):
    return {'id': model_id, 'contextWindow': window, 'contextWindowSource': source,
            'thinkingType': thinking_type, 'thinkingLevels': list(levels), 'defaultThinking': default}


def _turn_response():
    return {'choices': [{'message': {'content': 'done'}, 'finish_reason': 'stop'}]}


MODEL_A = 'muse-spark-1.3-contributor-free'
MODEL_B = 'gpt-5.4'
PROVIDER = 'opencode'


def test_aggregate_output_ceiling_requires_every_target_to_publish_it():
    rows = [model_row(maxOutputTokens=16000), model_row(maxOutputTokens=8000)]
    assert aggregate_model_metadata(rows)['maxOutputTokens'] == 8000
    assert 'maxOutputTokens' not in aggregate_model_metadata(rows + [model_row()])


def test_aggregate_takes_the_smallest_context_window():
    """Hai connection cùng model, số công bố lệch nhau: lấy số NHỎ, nguồn đi theo hàng đó.

    Lượt có thể bị router chuyển sang bất kỳ target nào khi khoá trước hết hạn mức, nên
    hứa số của target rộng nhất là hứa điều lượt không giữ được.
    """
    wide = model_row(MODEL_A, window=1_000_000, source='documented')
    narrow = model_row(MODEL_A, window=200_000, source='reported')

    for rows in ([wide, narrow], [narrow, wide]):
        aggregate = aggregate_model_metadata(rows)
        assert aggregate['contextWindow'] == 200_000
        assert aggregate['contextWindowSource'] == 'reported', 'nguồn của chính hàng cho số min'
        assert aggregate['id'] == MODEL_A

    silent = model_row(MODEL_A)
    assert 'contextWindow' not in aggregate_model_metadata([silent]), 'không hàng nào công bố số ⇒ bỏ trường'
    assert aggregate_model_metadata([]) is None, 'không hàng nào dùng được ⇒ người gọi rơi về đường cũ'


def test_aggregate_intersects_thinking_levels():
    """Mức gửi đi phải hợp lệ với MỌI target: giao các danh sách, rỗng thì bỏ hẳn trường."""
    first = model_row(MODEL_A, window=1_000_000, levels=['low', 'medium', 'high'])
    second = model_row(MODEL_A, window=1_000_000, levels=['LOW', 'high'])

    aggregate = aggregate_model_metadata([first, second])
    assert aggregate['thinkingLevels'] == ['low', 'high'], 'so khớp hoa/thường, giữ cách viết hàng đầu'

    silent = model_row(MODEL_A, window=1_000_000, thinking_type='none', levels=[])
    assert 'thinkingLevels' not in aggregate_model_metadata([first, silent]), 'target chưa công bố mức ⇒ không mức nào'
    disjoint = model_row(MODEL_A, window=1_000_000, levels=['max'])
    assert 'thinkingLevels' not in aggregate_model_metadata([first, disjoint]), 'giao rỗng ⇒ bỏ hẳn trường'

    # Một target tắt thinking không được kéo cả nhóm về `none`.
    off = model_row(MODEL_A, window=1_000_000, thinking_type='none', levels=['burn'])
    assert aggregate_model_metadata([off, first])['thinkingType'] == 'effort'
    assert aggregate_model_metadata([off, model_row(MODEL_A, thinking_type='none')])['thinkingType'] == 'none'


def test_aggregate_ignores_connections_that_are_not_usable():
    """Chỉ connection mà router THẬT SỰ định tuyến được mới vào phép gộp (`validTarget`)."""
    snapshot = {'connections': [
        provider_connection('c1', [model_row(MODEL_A, window=1_000_000, source='documented')]),
        provider_connection('c2', [model_row(MODEL_A, window=200_000)], auth_state='expired'),
        provider_connection('c3', [model_row(MODEL_A, window=100_000, health='unavailable')]),
        provider_connection('c4', [model_row(MODEL_A, window=100_000)], enabled=False),
        provider_connection('c5', [model_row(MODEL_A, window=50_000)], provider_id='openrouter'),
        provider_connection('c6', [model_row(MODEL_A, window=100_000, enabled=False)]),
        provider_connection('c7', [model_row(MODEL_A, window=100_000)], discovery='failed'),
        provider_connection('c8', [model_row(MODEL_A, window=100_000, model_source='custom')], discovery='degraded', projectState='pending'),
    ]}
    client = StubRouterClient(snapshot)

    aggregate = asyncio.run(client.provider_model_metadata(PROVIDER, MODEL_A))
    # Chỉ c1 (1M) và c8 (100k, id tự khai trên connection đang `degraded`) vào phép gộp; c5 là
    # provider khác, còn c2/c3/c4/c6/c7 đều không định tuyến được.
    assert aggregate['contextWindow'] == 100_000
    assert client.reads == 1, 'một snapshot cho một câu trả lời'
    assert asyncio.run(client.provider_model_metadata(PROVIDER, 'không-có')) is None
    assert asyncio.run(client.provider_model_metadata('', MODEL_A)) is None


def test_provider_route_is_stored_verbatim(tmp_path):
    """`{providerId, modelId}` nằm nguyên trong `config['route']`, không sinh `connectionId`."""
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, StubExecutor(), StubModel())

    session = runtime.create({'skills': [], 'providerId': PROVIDER, 'modelId': MODEL_A})
    route = session['config']['route']
    assert route == {'providerId': PROVIDER, 'modelId': MODEL_A}
    assert 'connectionId' not in route, 'route provider không được tự bịa ra một connection'
    assert session['config']['contextWindow'] == FALLBACK_CONTEXT_WINDOW, 'không metadata ⇒ sàn có nhãn'
    assert session['config']['contextWindowSource'] == 'fallback'
    store.close()


def test_route_for_understands_the_provider_prefix():
    """Chuỗi single-model `provider:<providerId>:<modelId>` phải thành route provider."""
    assert route_for(f'provider:{PROVIDER}:{MODEL_A}') == {'providerId': PROVIDER, 'modelId': MODEL_A}
    assert route_for('model:c1:m1') == {'connectionId': 'c1', 'modelId': 'm1'}
    assert route_for('alias:fast') == {'aliasId': 'fast'}
    assert route_for('default') == {} and route_for('') == {}


def test_single_model_mode_keeps_the_provider_route(tmp_path):
    """Chế độ single-model: mọi subagent mang chuỗi `provider:…`, phiên mang route provider."""
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, StubExecutor(), StubModel())
    value = f'provider:{PROVIDER}:{MODEL_A}'

    session = runtime.create({'skills': [], 'singleModel': value, 'model': value})
    assert session['config']['route'] == {'providerId': PROVIDER, 'modelId': MODEL_A}
    assert {s['model'] for s in session['config']['subagents']} == {value}
    store.close()


def test_connection_route_is_unchanged(tmp_path):
    """Phiên cũ `{connectionId, modelId}` giữ nguyên route VÀ đường tra metadata theo connection."""
    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        client = StubModel([_turn_response()], {MODEL_B: _record(MODEL_B, levels=('low', 'high'))})
        runtime = HarnessRuntime(store, StubExecutor(), client)
        session = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': MODEL_A,
                                  'modelMetadata': _record(MODEL_A)})
        assert session['config']['route'] == {'connectionId': 'c1', 'modelId': MODEL_A}

        await runtime.submit(session['id'], 'hello', None,
                             {'connectionId': 'c1', 'modelId': MODEL_B, 'thinkingLevel': 'LOW'})
        await runtime.tasks[session['id']]
        route = store.get(session['id'])['config']['route']
        assert route['thinkingLevel'] == 'low', 'chuẩn hoá theo cách viết provider công bố'
        assert client.lookups == [('c1', MODEL_B)], 'đường connection vẫn tra bằng `model_metadata`'
        assert client.provider_lookups == [], 'route không có providerId thì không tra bản gộp'
        store.close()

    asyncio.run(run())


def test_turn_route_with_a_provider_validates_against_the_aggregate(tmp_path):
    """Lượt đổi model theo provider: mức phải nằm trong GIAO của nhóm, và được chuẩn hoá."""
    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        aggregate = aggregate_model_metadata([model_row(MODEL_B, window=200_000, levels=['low', 'high'])])
        client = StubModel([_turn_response()], provider_records={(PROVIDER, MODEL_B): aggregate})
        runtime = HarnessRuntime(store, StubExecutor(), client)
        session = runtime.create({'skills': [], 'providerId': PROVIDER, 'modelId': MODEL_A})

        with pytest.raises(ValueError, match='THINKING_LEVEL_UNSUPPORTED'):
            await runtime.submit(session['id'], 'hello', None,
                                 {'providerId': PROVIDER, 'modelId': MODEL_B, 'thinkingLevel': 'medium'})
        assert client.provider_lookups == [(PROVIDER, MODEL_B)]
        assert store.get(session['id'])['config']['route']['modelId'] == MODEL_A, 'lượt bị từ chối không ghi route'

        await runtime.submit(session['id'], 'hello', None,
                             {'providerId': PROVIDER, 'modelId': MODEL_B, 'thinkingLevel': 'HIGH'})
        await runtime.tasks[session['id']]
        route = store.get(session['id'])['config']['route']
        assert route == {'providerId': PROVIDER, 'modelId': MODEL_B, 'thinkingLevel': 'high'}
        assert client.lookups == [], 'route provider không được tra theo connection'
        store.close()

    asyncio.run(run())


def test_turn_route_with_a_provider_drops_an_unknown_intersection(tmp_path):
    """Nhóm chỉ công bố `low`/`high` cho một mức khác: lượt gửi mức đó không có cơ sở ⇒ DROP."""
    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        aggregate = aggregate_model_metadata([model_row(MODEL_B, window=200_000, levels=['low', 'high']),
                                              model_row(MODEL_B, window=150_000, levels=[])])
        client = StubModel([_turn_response()], provider_records={(PROVIDER, MODEL_B): aggregate})
        runtime = HarnessRuntime(store, StubExecutor(), client)
        session = runtime.create({'skills': [], 'providerId': PROVIDER, 'modelId': MODEL_A})

        await runtime.submit(session['id'], 'hello', None,
                             {'providerId': PROVIDER, 'modelId': MODEL_B, 'thinkingLevel': 'low'})
        await runtime.tasks[session['id']]
        route = store.get(session['id'])['config']['route']
        assert 'thinkingLevel' not in route, 'nhóm chưa biết mức chung ⇒ không gửi mức nào'
        store.close()

    asyncio.run(run())


def test_heal_repairs_a_provider_session(tmp_path):
    """Vòng sửa lúc khởi động dùng số GỘP cho phiên route provider, giữ nguyên đường connection."""
    store = SessionStore(tmp_path / 'sessions.db')
    aggregate = aggregate_model_metadata([model_row(MODEL_A, window=1_000_000, source='documented'),
                                          model_row(MODEL_A, window=200_000, source='reported')])
    client = StubModel(metadata_map={('c1', MODEL_B): _record(MODEL_B, window=1_000_000)},
                       provider_records={(PROVIDER, MODEL_A): aggregate})
    runtime = HarnessRuntime(store, StubExecutor(), client)

    provider_session = runtime.create({'skills': [], 'providerId': PROVIDER, 'modelId': MODEL_A,
                                       'contextWindow': 64_000, 'contextWindowSource': 'manual'})
    connection_session = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': MODEL_B})
    config = connection_session['config']
    config['contextWindow'] = 64_000
    config.pop('contextWindowSource', None)
    store.update_config(connection_session['id'], config)

    assert asyncio.run(runtime.heal_context_windows()) == 2
    healed = store.get(provider_session['id'])['config']
    assert (healed['contextWindow'], healed['contextWindowSource']) == (200_000, 'reported')
    assert healed['route'] == {'providerId': PROVIDER, 'modelId': MODEL_A}, 'vòng sửa chỉ sửa SỐ, không đổi dạng route'
    event = next(e for e in store.events(provider_session['id']) if e['type'] == 'context_window_healed')
    assert event['data'] == {'from': 64_000, 'to': 200_000, 'modelId': MODEL_A, 'source': 'router'}
    assert store.get(connection_session['id'])['config']['contextWindow'] == 1_000_000
    assert client.provider_map_calls == 1, 'một snapshot gộp cho mọi phiên provider'
    assert asyncio.run(runtime.heal_context_windows()) == 0, 'lần hai không còn gì để sửa'
    store.close()


def test_heal_reads_the_provider_map_only_when_a_provider_session_exists(tmp_path):
    """Đường thường (toàn phiên `connectionId`) giữ đúng số lời gọi router như trước."""
    store = SessionStore(tmp_path / 'sessions.db')
    client = StubModel(metadata_map={('c1', MODEL_B): _record(MODEL_B, window=1_000_000)})
    runtime = HarnessRuntime(store, StubExecutor(), client)
    runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': MODEL_B, 'contextWindow': 8_192,
                    'contextWindowSource': 'manual'})

    assert asyncio.run(runtime.heal_context_windows()) == 1
    assert client.provider_map_calls == 0, 'không có phiên provider nào ⇒ không đọc snapshot thứ hai'
    store.close()


def test_route_to_model_spec_formats_all_route_types():
    """Hàm route_to_model_spec phải chuyển đúng các dạng route sang model spec."""
    from agentbox.agent_core.runtime import route_to_model_spec
    assert route_to_model_spec({'providerId': 'opencode', 'modelId': 'm1'}) == 'provider:opencode:m1'
    assert route_to_model_spec({'connectionId': 'c1', 'modelId': 'm1'}) == 'model:c1:m1'
    assert route_to_model_spec({'aliasId': 'fast'}) == 'alias:fast'
    assert route_to_model_spec({'model': 'glm-5'}) == 'glm-5'
    assert route_to_model_spec({'modelId': 'claude-3'}) == 'claude-3'
    assert route_to_model_spec(None) == ''
    assert route_to_model_spec({}) == ''


def test_single_model_subagents_sync_when_route_changes(tmp_path):
    """Khi đổi model giữa chừng trong phiên Single Model, toàn bộ subagents phải tự động đổi theo."""
    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        client = StubModel([_turn_response(), _turn_response()])
        runtime = HarnessRuntime(store, StubExecutor(), client)

        initial_model = f'provider:{PROVIDER}:{MODEL_A}'
        session = runtime.create({'skills': [], 'singleModel': initial_model, 'model': initial_model})
        assert session['config']['isSingleModel'] is True
        assert {s['model'] for s in session['config']['subagents']} == {initial_model}

        # Đổi sang Model B ở lượt tiếp theo
        new_route = {'providerId': PROVIDER, 'modelId': MODEL_B}
        await runtime.submit(session['id'], 'hello', None, new_route)
        await runtime.tasks[session['id']]

        updated_config = store.get(session['id'])['config']
        assert updated_config['route']['modelId'] == MODEL_B
        expected_new_model = f'provider:{PROVIDER}:{MODEL_B}'
        assert updated_config['singleModel'] == expected_new_model
        assert {s['model'] for s in updated_config['subagents']} == {expected_new_model}
        store.close()

    asyncio.run(run())


def test_harness_multi_model_subagents_do_not_sync_when_route_changes(tmp_path):
    """Ở chế độ Harness (nhiều model riêng biệt), đổi route của cha không ghi đè model của con."""
    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        client = StubModel([_turn_response()])
        runtime = HarnessRuntime(store, StubExecutor(), client)

        subagents = [
            {'id': 'explore', 'model': 'DeepSeek V4 Flash', 'enabled': True},
            {'id': 'build', 'model': 'GLM 5.2', 'enabled': True},
            {'id': 'review', 'model': 'DeepSeek V4 Pro', 'enabled': True},
        ]
        session = runtime.create({
            'skills': [],
            'subagents': subagents,
            'connectionId': 'c1',
            'modelId': MODEL_A,
        })
        assert session['config'].get('isSingleModel') is not True

        # Đổi route của cha sang Model B
        await runtime.submit(session['id'], 'hello', None, {'connectionId': 'c1', 'modelId': MODEL_B})
        await runtime.tasks[session['id']]

        updated_config = store.get(session['id'])['config']
        assert updated_config['route']['modelId'] == MODEL_B
        # Subagents vẫn phải giữ nguyên cấu hình riêng biệt từng vai
        assert {s['model'] for s in updated_config['subagents']} == {'DeepSeek V4 Flash', 'GLM 5.2', 'DeepSeek V4 Pro'}
        store.close()

    asyncio.run(run())


def test_legacy_single_model_session_heals_on_turn(tmp_path):
    """Phiên cũ đã lưu mọi subagent cùng 1 model (như Gemini) tự lành sang model mới khi gửi lượt."""
    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        client = StubModel([_turn_response()])
        runtime = HarnessRuntime(store, StubExecutor(), client)

        # Giả lập cấu hình của phiên cũ (tất cả subagent cùng 'provider:gemini:flash-lite', không có cờ isSingleModel)
        old_spec = 'provider:gemini:flash-lite'
        subagents = [{'id': r, 'model': old_spec, 'enabled': True} for r in ['explore', 'build', 'research']]
        session = runtime.create({'skills': [], 'subagents': subagents, 'providerId': 'gemini', 'modelId': 'flash-lite'})
        assert 'isSingleModel' not in session['config']

        # Gửi lượt mới bằng OpenCode Muse Spark
        muse_route = {'providerId': 'opencode', 'modelId': 'muse-spark-1.3-contributor-free'}
        await runtime.submit(session['id'], 'research question', None, muse_route)
        await runtime.tasks[session['id']]

        updated_config = store.get(session['id'])['config']
        assert updated_config['isSingleModel'] is True
        assert {s['model'] for s in updated_config['subagents']} == {'provider:opencode:muse-spark-1.3-contributor-free'}
        store.close()

    asyncio.run(run())
