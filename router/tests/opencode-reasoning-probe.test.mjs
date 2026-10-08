// Kế hoạch v2 / nhóm M — phép dò REASONING theo từng provider.
//
// Vì sao có tệp này: `testInference` trả lời "model gọi được không" bằng một câu hỏi
// 64 token KHÔNG mang trường reasoning nào, nên nó không bao giờ nói được model có suy
// luận hay không (đo được 2026-10-08: `fledge-alpha-free` PASS phép thử đó mà không có
// một token suy luận nào). Phép dò mới đi qua CHÍNH adapter (`generate`) — nơi sở hữu
// giả trang, hai tool mồi, `stream: true` bắt buộc và định tuyến `/responses` — và đếm
// hai tín hiệu: `reasoning_content` chảy về và `reasoning_tokens`.
//
// Luật khắt khe nhất được khoá ở đây: **một mẫu rỗng chưa chứng minh được gì**. Đo được
// một mẫu rỗng trên model CÓ reasoning thật, nên kết luận `none` từ nó là sai theo hướng
// tệ nhất — nó xoá mất một điều khiển thật của người dùng.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { RouterStore } from '../src/store.mjs';
import { ProviderService, judgeReasoningProbe, reasoningProbeRowPatch } from '../src/service.mjs';
import { createProviders } from '../src/providers/index.mjs';
import { opencodeModelRow, opencodeThinkingMetadata } from '../src/providers/opencode.mjs';
import { THINKING_EVIDENCE_MAX_AGE_DAYS, thinkingEvidenceStale } from '../src/providers/opencode-capabilities.mjs';
import { RouterError } from '../src/errors.mjs';
import { createRouterServer } from '../src/server.mjs';
import { RouterEngine } from '../src/engine.mjs';

const sse = frames => new Response(
  frames.map(frame => `data: ${typeof frame === 'string' ? frame : JSON.stringify(frame)}\n\n`).join(''),
  { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
);
const json = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
/** Đường chat: `reasoning_content` chảy về + `reasoning_tokens` trong usage. */
const reasoningAnswer = (tokens = 42) => sse([
  { choices: [{ index: 0, delta: { reasoning_content: 'Đếm: tất cả trừ 9 con chạy mất…' } }] },
  { choices: [{ index: 0, delta: { reasoning_content: ' còn 9 con.' } }], usage: { prompt_tokens: 20, completion_tokens: 60, completion_tokens_details: { reasoning_tokens: tokens } } },
  { choices: [{ index: 0, delta: { content: '9' }, finish_reason: 'stop' }] },
]);
/** Đường chat: trả lời được nhưng KHÔNG suy luận (mẫu rỗng). */
const emptyAnswer = () => sse([
  { choices: [{ index: 0, delta: { content: '9' }, finish_reason: 'stop' }], usage: { prompt_tokens: 20, completion_tokens: 4 } },
]);
const catalogue = (...ids) => () => json({ data: ids.map(id => ({ id, object: 'model', created: 1, owned_by: 'opencode' })) });

/**
 * Cổng Zen giả. `/models` trả catalogue, `/chat/completions` và `/responses` trả lời
 * theo kịch bản; mọi request được ghi lại (url + body + headers) để khoá hình dạng mà
 * adapter gửi lên — phép dò phải dùng CHÍNH hình dạng đó.
 */
function zenStub({ chat, responses = () => sse([{ choices: [{ index: 0, delta: { content: 'ok' }, finish_reason: 'stop' }] }]), models = () => json({ data: [] }) }) {
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    const target = String(url);
    calls.push({ url: target, body: init.body ? JSON.parse(init.body) : null, headers: init.headers || {} });
    if (target.endsWith('/models')) return models();
    return target.endsWith('/responses') ? responses(calls[calls.length - 1]) : chat(calls[calls.length - 1]);
  };
  return { calls, fetchImpl };
}

/** Connection opencode thật trong store tạm, có hàng model đến từ chính `discover()`. */
async function fixture(t, stub, apiKey = 'sk-test-only-key') {
  const dir = mkdtempSync(join(tmpdir(), 'boxfox-router-test-'));
  const store = new RouterStore({ dataDir: dir });
  const service = new ProviderService({ store, providers: createProviders({ fetchImpl: stub.fetchImpl }) });
  t.after(() => { store.close(); rmSync(dir, { recursive: true, force: true }); });
  const created = service.create({ providerId: 'opencode', name: 'OPENCODE_1', apiKey });
  await service.discover(created.id);
  const row = modelId => service.connection(created.id).models.find(model => model.id === modelId);
  return { store, service, id: created.id, row };
}

/**
 * Service với adapter GIẢ: adapter thật luôn dịch CẢ HAI cách viết trường reasoning về
 * cùng một trường trên dây, nên chỉ adapter giả mới cho thấy đúng thân request mà phép
 * dò gửi ở lần thử thứ hai.
 */
function stubService(t, generate) {
  const dir = mkdtempSync(join(tmpdir(), 'boxfox-router-test-'));
  const store = new RouterStore({ dataDir: dir });
  const service = new ProviderService({ store, providers: { opencode: { generate, fallbackModels: [] } } });
  t.after(() => { store.close(); rmSync(dir, { recursive: true, force: true }); });
  const created = service.create({ providerId: 'opencode', name: 'STUB', apiKey: 'sk-stub-only-key' });
  service.patch(created.id, { customModel: { id: 'stub-model', capabilities: { reasoning: false } } });
  return { service, id: created.id, row: () => service.connection(created.id).models.find(model => model.id === 'stub-model') };
}

test('M1/M3: model có suy luận ⇒ ghi thinkingLevels + thinkingSource probe, bằng chứng kèm số đo', async t => {
  const stub = zenStub({ chat: () => reasoningAnswer(), models: catalogue('fledge-alpha-free') });
  const f = await fixture(t, stub);

  const result = await f.service.probeReasoning(f.id, 'fledge-alpha-free', { samples: 4 });

  assert.equal(result.status, 'supports');
  assert.equal(result.thinkingType, 'effort');
  assert.equal(result.thinkingSource, 'probe');
  assert.deepEqual(result.thinkingLevels, ['minimal', 'low', 'medium', 'high'], 'dò HẾT bảng mức: bộ chọn mức cần > 1 mức mới hiện');
  assert.equal(result.reasoningChars > 0, true);
  assert.equal(result.reasoningTokens, 42);

  const row = f.row('fledge-alpha-free');
  assert.equal(row.thinkingSource, 'probe');
  assert.deepEqual(row.thinkingLevels, ['minimal', 'low', 'medium', 'high']);
  assert.equal(row.thinkingType, 'effort');
  assert.equal(row.thinkingAsOf, new Date().toISOString().slice(0, 10));
  assert.match(row.thinkingEvidence, /^probe \d{4}-\d{2}-\d{2}: /);
  assert.match(row.thinkingEvidence, /5\/5 mẫu trả reasoning/);
  assert.match(row.thinkingEvidence, /reasoning_tokens 42/);
  assert.match(row.thinkingEvidence, /mức đo được: minimal\/low\/medium\/high/);
  assert.equal(row.thinkingProbe.status, 'supports');
  assert.equal(row.thinkingProbe.samples, 5);
  assert.equal(row.thinkingProbe.reasoningTokens, 42);
  assert.equal(row.thinkingStale, false);
  assert.equal(row.fieldSources.thinking, 'probe');

  // Hình dạng request là của CHÍNH adapter: giả trang + hai tool mồi + stream bắt buộc
  // + mức gửi dưới dạng `reasoning: {effort, summary}`. Call 0 là `/models` của discover.
  const probeCalls = stub.calls.slice(1);
  assert.equal(probeCalls.length, 5, 'bốn mức + một mẫu không gửi mức');
  assert.deepEqual(probeCalls.map(call => call.body.reasoning?.effort ?? null), ['minimal', 'low', 'medium', 'high', null]);
  for (const call of probeCalls) {
    assert.equal(call.url, 'https://opencode.ai/zen/v1/chat/completions');
    assert.equal(call.body.stream, true);
    assert.equal(call.body.max_tokens, 512);
    assert.equal(call.body.tools.length, 2, 'free tier đòi hai tool mồi');
    assert.equal(call.body.tool_choice, 'none');
    assert.equal(call.headers['x-opencode-client'], 'desktop');
    assert.equal(call.body.messages[0].content.includes('sheep'), true, 'câu hỏi kích suy luận, không phải câu chào');
  }
  assert.equal('reasoning' in probeCalls.at(-1).body, false, 'mẫu cuối là "không gửi mức"');
});

test('M2: mẫu đầu rỗng KHÔNG kết luận none — mẫu sau có suy luận vẫn là supports', async t => {
  let call = 0;
  const stub = zenStub({ chat: () => (call++ === 0 ? emptyAnswer() : reasoningAnswer()), models: catalogue('space-bunny-free') });
  const f = await fixture(t, stub);

  const result = await f.service.probeReasoning(f.id, 'space-bunny-free', { samples: 4 });

  assert.equal(result.status, 'supports', 'một mẫu rỗng không phải bằng chứng "không hỗ trợ"');
  assert.deepEqual(result.levelsSupported, ['low', 'medium', 'high'], 'chỉ mức ĐO ĐƯỢC mới được ghi');
  assert.deepEqual(result.thinkingLevels, ['low', 'medium', 'high']);
  assert.equal(result.thinkingProbe.samples, 5, 'mẫu rỗng đầu tiên không cắt ngắn vòng dò');
  assert.equal(f.row('space-bunny-free').thinkingSource, 'probe');
});

test('M2: không mẫu nào trả reasoning ⇒ inconclusive — giữ unknown, chỉ ghi khối probe', async t => {
  const stub = zenStub({ chat: () => emptyAnswer(), models: catalogue('fledge-alpha-free') });
  const f = await fixture(t, stub);

  const result = await f.service.probeReasoning(f.id, 'fledge-alpha-free', { levels: ['minimal'] });

  assert.equal(result.status, 'inconclusive');
  const row = f.row('fledge-alpha-free');
  assert.equal(row.thinkingType, 'none', 'không có bằng chứng thì không đổi kết luận');
  assert.deepEqual(row.thinkingLevels, []);
  assert.equal(row.thinkingSource, 'unknown');
  assert.equal(row.thinkingProbe.status, 'inconclusive');
  assert.equal(row.thinkingProbe.samples, 2, 'luật M2: ≥ 2 mẫu mới được nói "không thấy suy luận"');
});

test('M2: 400 vì trường reasoning ⇒ thử CÁCH VIẾT CÒN LẠI trước khi kết luận', async t => {
  const bodies = [];
  const generate = async function* ({ body }) {
    bodies.push(body);
    if ('thinkingLevel' in body) throw new RouterError('PROVIDER_ERROR', 'This model does not accept reasoning.effort.', 400, false);
    if ('reasoning_effort' in body) {
      yield { type: 'delta', delta: { reasoning_content: 'Cách viết thứ hai chạy được.' } };
      yield { type: 'finish', finishReason: 'stop' };
      return;
    }
    yield { type: 'delta', delta: { content: '9' } };
    yield { type: 'finish', finishReason: 'stop' };
  };
  const f = stubService(t, generate);

  const result = await f.service.probeReasoning(f.id, 'stub-model', { samples: 2 });

  assert.equal(result.status, 'supports');
  assert.deepEqual(result.thinkingLevels, ['minimal', 'low', 'medium', 'high'], 'mỗi mức thử cách viết gốc rồi cách viết còn lại');
  assert.equal(bodies.length, 9, 'bốn mức × hai lần thử + một mẫu không gửi mức');
  assert.equal(bodies[0].thinkingLevel, 'minimal');
  assert.equal('reasoning_effort' in bodies[0], false);
  assert.equal(bodies[1].reasoning_effort, 'minimal', 'lần thử thứ hai dùng cách viết còn lại');
  assert.equal('thinkingLevel' in bodies[1], false);
  assert.equal(bodies.at(-1).thinkingLevel, undefined, 'mẫu cuối không gửi mức');
  assert.equal(f.row().thinkingSource, 'probe');
});

test('M2: cả hai cách viết đều bị từ chối ⇒ refuses + thinkingType none (sau ≥ 2 mẫu)', async t => {
  const bodies = [];
  const generate = async function* ({ body }) {
    bodies.push(body);
    if ('thinkingLevel' in body || 'reasoning_effort' in body) throw new RouterError('PROVIDER_ERROR', 'reasoning is not supported for this model.', 400, false);
    yield { type: 'delta', delta: { content: '9' } };
    yield { type: 'finish', finishReason: 'stop' };
  };
  const f = stubService(t, generate);

  const result = await f.service.probeReasoning(f.id, 'stub-model', { samples: 4 });

  assert.equal(result.status, 'refuses');
  assert.equal(result.thinkingType, 'none');
  assert.deepEqual(result.thinkingLevels, []);
  assert.equal(result.thinkingSource, 'probe');
  assert.equal(result.thinkingProbe.samples, 2, 'luật M2: ≥ 2 mẫu trước khi kết luận');
  assert.equal(bodies.length, 4, 'hai mức × hai cách viết');
  assert.deepEqual(bodies.map(body => body.thinkingLevel ?? body.reasoning_effort), ['minimal', 'minimal', 'low', 'low']);
  const row = f.row();
  assert.equal(row.thinkingType, 'none');
  assert.equal(row.thinkingSource, 'probe');
  assert.match(row.thinkingEvidence, /bị từ chối \(400\)/);
});

test('M1: họ muse-spark đi /responses — dò qua cửa chat là kết luận sai', async t => {
  const responsesFrames = [
    { type: 'response.reasoning_summary_text.delta', delta: 'thinking step by step' },
    { type: 'response.output_text.delta', delta: '9' },
    { type: 'response.completed', response: { status: 'completed', usage: { input_tokens: 10, output_tokens: 30, output_tokens_details: { reasoning_tokens: 21 } } } },
  ];
  const stub = zenStub({
    chat: () => json({ error: { message: 'Wrong door' } }, 400),
    responses: () => sse(responsesFrames),
    models: catalogue('muse-spark-1.2-contributor-free'),
  });
  const f = await fixture(t, stub);

  const result = await f.service.probeReasoning(f.id, 'muse-spark-1.2-contributor-free', { samples: 4 });

  assert.equal(result.status, 'supports');
  // `reasoningChars` là TỔNG văn suy luận của cả vòng dò, `reasoningTokens` là mức cao
  // nhất provider khai ở một mẫu: token khai theo mẫu, còn ký tự là "đã thấy bao nhiêu chữ".
  assert.equal(result.reasoningChars, 5 * 'thinking step by step'.length);
  assert.equal(result.reasoningTokens, 21, 'usage đường responses được chuẩn hoá về reasoning_tokens');
  assert.deepEqual(result.thinkingLevels, ['minimal', 'low', 'medium', 'high']);
  assert.equal(stub.calls.some(call => call.url.endsWith('/chat/completions')), false);
  assert.equal(stub.calls.filter(call => call.url.endsWith('/responses')).length, 5, 'cả vòng dò đi /responses');
});

test('M6: provider nói id không được cấp mà catalogue công khai CÓ id ⇒ not_entitled', async t => {
  const stub = zenStub({
    chat: () => json({ error: { message: 'Model exo-free is not supported' } }, 401),
    models: catalogue('exo-free', 'space-bunny-free'),
  });
  const f = await fixture(t, stub);

  const result = await f.service.probeReasoning(f.id, 'exo-free', { samples: 2 });

  assert.equal(result.status, 'not_entitled');
  assert.equal(result.publicCatalogue, true);
  assert.equal(result.reason, 'not_entitled');
  const row = f.row('exo-free');
  assert.equal(row.thinkingType, 'none', 'ca lỗi không được ghi thinkingType');
  assert.equal(row.thinkingSource, 'unknown');
  assert.equal(row.thinkingProbe.status, 'not_entitled');
  assert.equal(row.thinkingProbe.publicCatalogue, true);
  assert.equal(stub.calls.filter(call => call.url.endsWith('/chat/completions')).length, 1, 'lỗi hạng nặng thì dừng, không đốt hạn mức');
});

test('M6: id không có trong catalogue công khai ⇒ not_in_catalogue', async t => {
  let listed = ['fledge-alpha-free'];
  const stub = zenStub({
    chat: () => json({ error: { message: 'Model fledge-alpha-free is not supported' } }, 401),
    models: () => json({ data: listed.map(id => ({ id })) }),
  });
  const f = await fixture(t, stub);
  listed = [];

  const result = await f.service.probeReasoning(f.id, 'fledge-alpha-free', { samples: 2 });

  assert.equal(result.status, 'not_in_catalogue');
  assert.equal(result.publicCatalogue, false);
  assert.equal(f.row('fledge-alpha-free').thinkingProbe.status, 'not_in_catalogue');
});

test('M6: 404 vì hàng không nằm trên connection ⇒ nói rõ vì sao, không ghi gì', async t => {
  let listed = ['space-bunny-free'];
  const stub = zenStub({ chat: () => emptyAnswer(), models: () => json({ data: listed.map(id => ({ id })) }) });
  const f = await fixture(t, stub);
  // Catalogue công khai CÓ id, danh sách đã dò của tài khoản thì không ⇒ "có model
  // nhưng khoá không được cấp", khác hẳn "id không tồn tại".
  listed = ['space-bunny-free', 'exo-free'];

  const result = await f.service.probeReasoning(f.id, 'exo-free', { samples: 2 });

  assert.equal(result.status, 'not_entitled');
  assert.equal(result.publicCatalogue, true);
  assert.match(result.message, /not on the connection/);
  assert.match(result.message, /not entitled to it \(not_entitled\)/);
  await assert.rejects(
    f.service.testInference(f.id, 'exo-free'),
    error => error.code === 'MODEL_NOT_FOUND' && error.status === 404 && /not_entitled/.test(error.message),
  );
});

test('M2: 503 là unavailable — không kết luận gì về suy luận', async t => {
  const stub = zenStub({
    chat: () => json({ error: { message: 'Upstream request failed: Endpoint is unavailable.' } }, 503),
    models: catalogue('exo-free'),
  });
  const f = await fixture(t, stub);

  const result = await f.service.probeReasoning(f.id, 'exo-free', { samples: 2 });

  assert.equal(result.status, 'unavailable');
  assert.equal(result.httpStatus, 503);
  assert.equal(stub.calls.filter(call => call.url.endsWith('/chat/completions')).length, 1);
  const row = f.row('exo-free');
  assert.equal(row.thinkingSource, 'unknown');
  assert.equal(row.thinkingProbe.status, 'unavailable');
});

test('M2: 429 là rate_limited và giữ retryAfterMs', async t => {
  const stub = zenStub({
    chat: () => json({ error: { message: 'Too many requests' } }, 429),
    models: catalogue('ling-3.1-flash-free'),
  });
  const f = await fixture(t, stub);

  const result = await f.service.probeReasoning(f.id, 'ling-3.1-flash-free', { samples: 2 });

  assert.equal(result.status, 'rate_limited');
  assert.equal(result.thinkingType, 'none');
  assert.equal(f.row('ling-3.1-flash-free').thinkingProbe.status, 'rate_limited');
});

test('M1/M6: câu lỗi của provider echo lại khoá ⇒ khoá không vào kết quả, hàng model, hay log', async t => {
  const leak = `sk-leak-${randomUUID().slice(0, 8)}`;
  // Cổng hung hăng: echo nguyên header Authorization vào câu lỗi. Đây là dạng rò rỉ
  // thật sự đáng chặn — bí mật đến từ chính router, không phải từ kịch bản test.
  const stub = zenStub({
    chat: call => json({ error: { message: `Bad request: Authorization: ${call.headers.Authorization} is not valid` } }, 500),
    models: catalogue('fledge-alpha-free'),
  });
  const f = await fixture(t, stub, leak);

  const result = await f.service.probeReasoning(f.id, 'fledge-alpha-free', { samples: 2 });

  assert.equal(result.status, 'unavailable');
  assert.match(result.message, /\[redacted\]/);
  const written = JSON.stringify(result) + JSON.stringify(f.row('fledge-alpha-free'));
  assert.equal(written.includes(leak), false, 'bí mật không được vào câu trả lời hay hàng model đã lưu');
  const logDir = process.env.BOXFOX_SYSTEM_LOG_DIR;
  if (logDir) {
    for (const file of readdirSync(logDir)) {
      assert.equal(readFileSync(join(logDir, file), 'utf8').includes(leak), false, `${file} không được chứa khoá`);
    }
  }
});

test('M2: bảng phán xử thuần — không có mẫu dương thì chỉ một lời TỪ CHỐI mới là bằng chứng âm', () => {
  assert.equal(judgeReasoningProbe([]).status, 'inconclusive');
  assert.equal(judgeReasoningProbe([{ level: 'high', reasoningChars: 0, reasoningTokens: 0 }]).status, 'inconclusive');
  assert.equal(judgeReasoningProbe([{ level: 'high', reasoningChars: 5, reasoningTokens: 0 }]).status, 'supports');
  assert.equal(judgeReasoningProbe([{ level: null, reasoningChars: 0, reasoningTokens: 7 }]).status, 'supports');
  assert.equal(judgeReasoningProbe([{ level: 'high', refusedReasoningField: true }]).status, 'inconclusive', 'một mẫu chưa đủ');
  assert.equal(judgeReasoningProbe([{ level: 'high', refusedReasoningField: true }, { level: 'low', refusedReasoningField: true }]).status, 'refuses');
  assert.equal(judgeReasoningProbe([{ level: 'high', error: true, httpStatus: 429 }]).status, 'rate_limited');
  assert.equal(judgeReasoningProbe([{ level: 'high', error: true, httpStatus: 404 }]).status, 'not_entitled');
  assert.equal(judgeReasoningProbe([{ level: 'high', error: true, httpStatus: 503 }]).status, 'unavailable');
  assert.equal(judgeReasoningProbe([{ level: 'high', error: true, httpStatus: 500 }]).status, 'unavailable');
  assert.equal(judgeReasoningProbe([{ level: 'high', error: true, httpStatus: 403, message: 'FreeTierError' }]).status, 'failed');
  assert.deepEqual(judgeReasoningProbe([{ level: 'low', reasoningChars: 1 }]).levelsSupported, ['low']);
  assert.deepEqual(judgeReasoningProbe([{ level: null, reasoningChars: 1 }]).levelsSupported, [], 'mẫu không mức không phải một mức');
});

test('M3: hàng payload tự khai thinking (live) không bị số đo ghi đè', () => {
  const live = { id: 'x', thinkingSource: 'live', thinkingType: 'effort', thinkingLevels: ['high'], fieldSources: { thinking: 'live' } };
  assert.equal(reasoningProbeRowPatch(live, { verdict: { status: 'refuses' }, evidence: 'e', at: '2026-10-08' }), null);
  assert.equal(reasoningProbeRowPatch({ id: 'x' }, { verdict: { status: 'inconclusive' }, evidence: 'e', at: '2026-10-08' }), null);
  const patch = reasoningProbeRowPatch({ id: 'x', thinkingLevels: ['high'], fieldSources: { thinking: 'unknown' } }, { verdict: { status: 'supports', levelsSupported: ['high'] }, evidence: 'e', at: '2026-10-08' });
  assert.equal(patch.thinkingType, 'effort');
  assert.deepEqual(patch.thinkingLevels, ['high']);
  assert.equal(patch.thinkingSource, 'probe');
  assert.equal(patch.thinkingStale, false);
});

test('M3: lần dò danh sách kế tiếp KHÔNG xoá số đo vừa đo được', async t => {
  const stub = zenStub({ chat: () => reasoningAnswer(), models: catalogue('fledge-alpha-free') });
  const f = await fixture(t, stub);
  const first = await f.service.probeReasoning(f.id, 'fledge-alpha-free', { samples: 1 });
  assert.equal(first.status, 'supports');
  assert.deepEqual(f.row('fledge-alpha-free').thinkingLevels, ['minimal', 'low', 'medium', 'high']);

  // Vài giờ sau, hàng được dựng lại từ registry — nơi vẫn khai `unknown`.
  await f.service.discover(f.id);

  const row = f.row('fledge-alpha-free');
  assert.equal(row.thinkingSource, 'probe', 'một lần đồng bộ không được nuốt số đo vừa đo');
  assert.deepEqual(row.thinkingLevels, ['minimal', 'low', 'medium', 'high']);
  assert.equal(row.thinkingAsOf, new Date().toISOString().slice(0, 10));
  assert.match(row.thinkingEvidence, /^probe \d{4}-\d{2}-\d{2}: /);
  assert.equal(row.thinkingProbe.status, 'supports');
  assert.equal(row.fieldSources.thinking, 'probe');
});

test('M4: bằng chứng quá hạn ⇒ thinkingStale true, nhưng KHÔNG mất thinkingLevels', () => {
  assert.equal(THINKING_EVIDENCE_MAX_AGE_DAYS, 30);
  const now = new Date('2026-10-08T00:00:00Z');
  assert.equal(thinkingEvidenceStale('2026-10-02', now), false);
  assert.equal(thinkingEvidenceStale('2026-01-01', now), true);
  assert.equal(thinkingEvidenceStale(null, now), true, 'không có mốc thì không được tin mãi');
  assert.equal(thinkingEvidenceStale('không phải ngày', now), true);

  const fresh = opencodeModelRow({ id: 'space-bunny-free' }, { now });
  assert.equal(fresh.thinkingStale, false);
  assert.deepEqual(fresh.thinkingLevels, ['minimal', 'low', 'medium', 'high']);
  const old = opencodeModelRow({ id: 'space-bunny-free' }, { now: new Date('2026-12-01T00:00:00Z') });
  assert.equal(old.thinkingStale, true);
  assert.deepEqual(old.thinkingLevels, ['minimal', 'low', 'medium', 'high'], 'mất điều khiển đang chạy là hồi quy tệ hơn một nhãn "cũ"');

  // Hàng do router dò cũng hết hạn, và registry không được ghi đè số đo.
  const probeRow = { id: 'space-bunny-free', thinkingSource: 'probe', thinkingAsOf: '2026-01-01', thinkingLevels: ['low'], thinkingProbe: { status: 'supports' }, fieldSources: { thinking: 'probe' } };
  assert.deepEqual(opencodeThinkingMetadata(probeRow, { now }), { thinkingStale: true });
  assert.deepEqual(opencodeThinkingMetadata({ ...probeRow, thinkingAsOf: '2026-10-07' }, { now }), { thinkingStale: false });
});

test('M4: hàng registry hết hạn vẫn giữ level và cờ được ghim xuống store', async t => {
  const dir = mkdtempSync(join(tmpdir(), 'boxfox-router-test-'));
  const store = new RouterStore({ dataDir: dir });
  t.after(() => { store.close(); rmSync(dir, { recursive: true, force: true }); });
  const service = new ProviderService({ store, providers: createProviders({ fetchImpl: async () => json({}) }) });
  // Một hàng do router dò từ 2026-01-01: quá hạn, nhưng level đã đo được thì ở lại.
  const stale = {
    ...opencodeModelRow({ id: 'space-bunny-free' }),
    thinkingType: 'effort',
    thinkingLevels: ['low'],
    thinkingSource: 'probe',
    thinkingAsOf: '2026-01-01',
    thinkingEvidence: 'probe 2026-01-01: 1/1 mẫu trả reasoning',
    thinkingProbe: { status: 'supports', samples: 1, at: '2026-01-01T00:00:00.000Z' },
    thinkingStale: false,
  };
  store.put('connection', {
    id: 'c1', providerId: 'opencode', name: 'C1', endpoint: 'https://opencode.ai', enabled: true, revision: 1,
    credentialPresent: true, authState: 'ready', projectState: 'not_applicable', discoveryState: 'ready',
    inferenceState: 'unknown', costMode: 'included', keys: [], models: [stale],
  });

  // Đường chạy thật: mỗi lần khởi động (và mỗi lần dò danh sách) hàng được chuẩn hoá
  // lại, nên cờ quá hạn không chỉ sống trong RAM.
  service.sanitizeAllConnections();
  const [row] = service.connection('c1').models;
  assert.equal(row.thinkingStale, true, 'bằng chứng quá hạn phải tự nói ra');
  assert.deepEqual(row.thinkingLevels, ['low'], 'quá hạn KHÔNG lấy mất điều khiển đang chạy');
  assert.equal(row.thinkingSource, 'probe');
  assert.equal(store.get('connection', 'c1').models[0].thinkingStale, true, 'cờ quá hạn phải sống qua lần đọc sau');
});

test('M6: xoá hàng gõ tay được; hàng do dò phát hiện trả 409 MODEL_NOT_CUSTOM', async t => {
  const stub = zenStub({ chat: () => emptyAnswer(), models: catalogue('fledge-alpha-free') });
  const f = await fixture(t, stub);
  f.service.patch(f.id, { customModel: { id: 'test', capabilities: { reasoning: false } } });
  const alias = f.service.alias({ name: 'Doomed', strategy: 'fallback', enabled: true, targets: [{ connectionId: f.id, modelId: 'test' }] });

  assert.deepEqual(f.service.removeCustomModel(f.id, 'test'), { removed: true, modelId: 'test' });
  assert.equal(f.row('test'), undefined, 'hàng gõ tay biến mất thật');
  assert.equal(f.service.snapshot().aliases.find(a => a.id === alias.id).enabled, false, 'alias trỏ vào hàng vừa xoá không còn đường đi');

  assert.throws(
    () => f.service.removeCustomModel(f.id, 'fledge-alpha-free'),
    error => error.code === 'MODEL_NOT_CUSTOM' && error.status === 409,
  );
  assert.throws(
    () => f.service.removeCustomModel(f.id, 'never-added'),
    error => error.code === 'MODEL_NOT_FOUND' && error.status === 404,
  );
});

/** Cùng phép dò nhưng qua HTTP thật, để khoá cổng admin và hình dạng câu trả lời. */
async function httpFixture(t) {
  const dir = mkdtempSync(join(tmpdir(), 'boxfox-router-test-'));
  const store = new RouterStore({ dataDir: dir });
  const stub = zenStub({ chat: () => reasoningAnswer(), models: catalogue('fledge-alpha-free') });
  const service = new ProviderService({ store, providers: createProviders({ fetchImpl: stub.fetchImpl }) });
  const engine = new RouterEngine({ service, deadlineMs: 2000 });
  const hosts = [];
  const server = createRouterServer({ service, engine, oauth: {}, allowedHosts: hosts });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); return new Promise(resolve => server.close(resolve)); });
  t.after(() => { store.close(); rmSync(dir, { recursive: true, force: true }); });
  const base = `http://127.0.0.1:${server.address().port}`;
  hosts.push(new URL(base).host);
  const created = service.create({ providerId: 'opencode', name: 'OPENCODE_1', apiKey: 'sk-test-only-key' });
  await service.discover(created.id);
  const send = async (path, { method = 'GET', body, headers } = {}) => {
    const response = await fetch(base + path, {
      method,
      headers: headers ?? { 'X-BoxFox-Admin': '1', 'Content-Type': 'application/json', Host: hosts[0] },
      ...(body === undefined ? {} : { body: typeof body === 'string' ? body : JSON.stringify(body) }),
    });
    const text = await response.text();
    return { status: response.status, text, data: text ? JSON.parse(text) : null };
  };
  return { service, id: created.id, send, row: modelId => service.connection(created.id).models.find(model => model.id === modelId) };
}

test('M5: route admin dò reasoning chạy qua HTTP, thiếu cổng admin thì 403', async t => {
  const f = await httpFixture(t);
  const path = `/api/router/connections/${f.id}/models/fledge-alpha-free/reasoning-probe`;

  const forbidden = await f.send(path, { method: 'POST', body: {}, headers: { Host: '127.0.0.1' } });
  assert.equal(forbidden.status, 403, 'thiếu x-boxfox-admin thì không dò được');
  assert.equal(Boolean(f.row('fledge-alpha-free').thinkingProbe), false);

  // Thân request tuỳ chọn: nút bấm không gửi gì vẫn phải chạy (không 415/400).
  const { status, data } = await f.send(path, { method: 'POST', headers: { 'X-BoxFox-Admin': '1', Host: '127.0.0.1' } });
  assert.equal(status, 200);
  for (const key of ['status', 'thinkingType', 'thinkingLevels', 'thinkingSource', 'thinkingAsOf', 'thinkingEvidence', 'latencyMs', 'httpStatus', 'reasoningChars', 'reasoningTokens', 'samples', 'levelsSupported']) {
    assert.equal(key in data, true, `câu trả lời phải có ${key}`);
  }
  assert.equal(data.status, 'supports');
  assert.equal(data.thinkingSource, 'probe');
  assert.deepEqual(data.thinkingLevels, ['minimal', 'low', 'medium', 'high'], 'bộ chọn mức cần > 1 mức — đây là phép kiểm đầu-cuối của nhóm M');
  assert.equal(f.row('fledge-alpha-free').thinkingSource, 'probe', 'hàng model trên UI mang ngay kết quả');

  const deleted = await f.send(`/api/router/connections/${f.id}/models/never-added`, { method: 'DELETE' });
  assert.equal(deleted.status, 404);
});
