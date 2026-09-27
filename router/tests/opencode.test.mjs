// Round 19: OpenCode Free sync with 9Router v0.5.81 (commit a8c9d38).
//
// The free tier only answers a request that looks like the OpenCode client, so
// every rule below is pinned to a live measurement taken from this machine on
// 2026-09-21 against `https://opencode.ai/zen/v1/responses` with
// `Authorization: Bearer public`:
//
//   `User-Agent: opencode` (no version)          → 403 FreeTierError
//   `tools: []` (no decoy tools)                 → 403 FreeTierError
//   `stream: false`                              → 403 FreeTierError
//   `x-opencode-session: ses_<32 hex>`           → 403 FreeTierError
//   `reasoning_effort` in the body               → 400 invalid_request_error
//   `reasoning: {effort, summary}`               → 200
//   tool-result image flattened into `output`    → 200, empty answer
//   tool-result image as a following user turn   → 200, colour read correctly
import test from 'node:test';
import assert from 'node:assert/strict';
import { createProviders } from '../src/providers/index.mjs';
import {
  deriveRequestId,
  hasValidOpencodeVersion,
  mintOpencodeId,
  OPENCODE_DECOY_TOOLS,
  OPENCODE_REQUEST_RE,
  OPENCODE_SESSION_RE,
  OPENCODE_UA,
  resetStableSessions,
  responsesTools,
  sanitizeResponsesItems,
  toResponsesInput,
} from '../src/providers/opencode.mjs';

const connection = { id: 'opencode-connection', providerId: 'opencode', endpoint: 'https://opencode.ai' };
const messages = [{ role: 'user', content: 'Xin chào' }];

const sse = frames => new Response(
  `${frames.map(frame => `data: ${typeof frame === 'string' ? frame : JSON.stringify(frame)}\n\n`).join('')}`,
  { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
);

const json = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });

async function collect(iterator) {
  const values = [];
  for await (const event of iterator) values.push(event);
  return values;
}

function recorder(respond) {
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url, headers: init.headers || {}, body: init.body ? JSON.parse(init.body) : null });
    return respond(url, init, calls.length - 1);
  };
  return { calls, fetchImpl };
}

/** A canned Responses stream: reasoning item, one assistant message, one tool call. */
const responsesFrames = () => [
  { type: 'response.created', sequence_number: 0 },
  { type: 'response.output_item.added', sequence_number: 1, output_index: 0, item: { type: 'reasoning', id: 'rs_1', status: 'in_progress', summary: [] } },
  { type: 'response.output_item.done', sequence_number: 2, output_index: 0, item: { type: 'reasoning', id: 'rs_1', status: 'completed', encrypted_content: 'Q-PaDg…' } },
  { type: 'response.output_item.added', sequence_number: 3, output_index: 1, item: { type: 'message', id: 'rs_2', status: 'in_progress', role: 'assistant', content: [] } },
  { type: 'response.output_text.delta', sequence_number: 4, output_index: 1, item_id: 'rs_2', delta: 'Calling get_time.' },
  { type: 'response.output_item.added', sequence_number: 5, output_index: 2, item: { type: 'function_call', id: 'fc_1', status: 'in_progress', name: 'get_time', call_id: 'call_1', arguments: '' } },
  { type: 'response.function_call_arguments.delta', sequence_number: 6, output_index: 2, item_id: 'fc_1', delta: '{"timezone":"UTC"}' },
  { type: 'response.output_item.done', sequence_number: 7, output_index: 2, item: { type: 'function_call', id: 'fc_1', status: 'completed', name: 'get_time', call_id: 'call_1', arguments: '{"timezone":"UTC"}' } },
  { type: 'response.completed', sequence_number: 8, response: { usage: { input_tokens: 626, output_tokens: 109, total_tokens: 735 } } },
  'ping'.replace('ping', JSON.stringify({ type: 'ping', cost: '0' })),
  '[DONE]',
];

const responsesEvent = frames => frames.map(frame => (frame === '[DONE]' ? '[DONE]' : typeof frame === 'string' ? frame : JSON.stringify(frame)));

/** A canned chat-completions stream, the shape every non-`muse-spark` id takes. */
const chatFrames = () => [
  { id: 'chat_1', object: 'chat.completion.chunk', choices: [{ index: 0, delta: { role: 'assistant' }, finish_reason: null }] },
  { id: 'chat_1', object: 'chat.completion.chunk', choices: [{ index: 0, delta: { content: 'Xin chào' }, finish_reason: null }] },
  { id: 'chat_1', object: 'chat.completion.chunk', choices: [{ index: 0, delta: {}, finish_reason: 'stop' }] },
];

test('the versioned user agent is what the free tier checks', () => {
  assert.equal(hasValidOpencodeVersion('opencode'), false, 'a bare UA is a 403');
  assert.equal(hasValidOpencodeVersion(''), false);
  assert.equal(hasValidOpencodeVersion('opencode/1.16.7'), false, '1.16 is below the 1.17 floor');
  assert.equal(hasValidOpencodeVersion(OPENCODE_UA), true);
  assert.equal(hasValidOpencodeVersion('opencode/2.0.0'), true);
  assert.equal(hasValidOpencodeVersion('curl/8'), false);
});

test('a chat stream folded for a non-streaming caller reports `length` when it was cut', async () => {
  // The harness falls back to a non-streaming POST when the SSE channel breaks; the router folds
  // the provider stream with `aggregate`, and its `stop` default used to turn a severed answer into
  // a clean finish (measured live 2026-09-26, `muse-spark-1.3-contributor-free` review turn).
  const cut = recorder(() => sse(chatFrames().slice(0, -1)));
  const severed = await collect(createProviders({ fetchImpl: cut.fetchImpl }).opencode.generate({
    connection, credentials: {}, body: { model: "deepseek-v4-flash-free", messages, stream: false },
  }));
  const cutFinish = severed.filter(event => event.type === 'finish').at(-1);
  assert.equal(cutFinish.finishReason, 'length', 'a stream with no finish chunk was cut');
  assert.equal(severed.filter(event => event.type === 'delta').at(-1).delta.content, 'Xin chào',
               'the severed text is still delivered, only its honesty changes');
  const healthy = recorder(() => sse(chatFrames()));
  const whole = await collect(createProviders({ fetchImpl: healthy.fetchImpl }).opencode.generate({
    connection, credentials: {}, body: { model: "deepseek-v4-flash-free", messages, stream: false },
  }));
  assert.equal(whole.filter(event => event.type === 'finish').at(-1).finishReason, 'stop');
});

test('session and request ids use the shapes the free tier accepts', () => {
  const session = mintOpencodeId('ses', 'conversation-a');
  assert.match(session, OPENCODE_SESSION_RE, 'ses_<12hex><14base62>');
  assert.equal(mintOpencodeId('ses', 'conversation-a'), session, 'derivation is deterministic');
  assert.match(deriveRequestId(session, { messages }), OPENCODE_REQUEST_RE);
  assert.notEqual(deriveRequestId(session, { messages }), mintOpencodeId('msg', 'x'), 'request ids differ per turn');
});

test('a muse request carries the decoy tools, streams, and stores nothing', async () => {
  const { calls, fetchImpl } = recorder(() => sse(responsesEvent(responsesFrames())));
  const adapter = createProviders({ fetchImpl }).opencode;
  await collect(adapter.generate({ connection, credentials: {}, body: { model: 'muse-spark-1.2-contributor-free', messages, tools: [{ type: 'function', function: { name: 'get_time', description: 'now', parameters: { type: 'object', properties: {} } } }], stream: false } }));

  const [call] = calls;
  assert.equal(call.url, 'https://opencode.ai/zen/v1/responses');
  assert.equal(call.headers['User-Agent'], OPENCODE_UA, 'the versioned UA rides every request');
  assert.match(call.headers['x-opencode-session'], OPENCODE_SESSION_RE);
  assert.match(call.headers['x-opencode-request'], OPENCODE_REQUEST_RE);
  assert.equal(call.headers['x-opencode-client'], 'desktop');
  assert.equal(call.headers['x-opencode-project'], 'global');
  assert.equal(call.body.stream, true, 'a non-streaming free-tier request is a 403, so the wire always streams');
  assert.equal(call.body.store, false);
  assert.equal(call.body.tool_choice, 'auto');
  assert.deepEqual(call.body.tools.map(tool => tool.name), ['get_time', 'bash', 'read'], 'decoys ride beside the caller tool');
  for (const decoy of OPENCODE_DECOY_TOOLS) {
    const carried = call.body.tools.find(tool => tool.name === decoy.name);
    assert.equal(carried.description, decoy.description, `${decoy.name} keeps upstream's description`);
    assert.equal(carried.type, 'function');
    assert.deepEqual(carried.parameters, decoy.parameters);
  }
});

test('a caller that already sends the decoys does not get them twice', async () => {
  const { calls, fetchImpl } = recorder(() => sse(responsesEvent(responsesFrames())));
  const adapter = createProviders({ fetchImpl }).opencode;
  const tools = [
    { type: 'function', name: 'bash', description: 'This tool is currently unavailable and must not be used.', parameters: { type: 'object', properties: {} } },
    { type: 'function', function: { name: 'read', description: 'r', parameters: { type: 'object', properties: { path: { type: 'string' } } } } },
  ];
  await collect(adapter.generate({ connection, credentials: {}, body: { model: 'muse-spark-1.2-contributor-free', messages, tools, stream: false } }));
  assert.deepEqual(calls[0].body.tools.map(tool => tool.name), ['bash', 'read']);
  assert.deepEqual(calls[0].body.tools[1].parameters.properties, { path: { type: 'string' } }, 'the caller schema is kept');
});

test('a chat model with no caller tools still carries the decoys', async () => {
  const { calls, fetchImpl } = recorder(() => sse(chatFrames()));
  const adapter = createProviders({ fetchImpl }).opencode;
  await collect(adapter.generate({ connection, credentials: {}, body: { model: 'nemotron-3.5-lightning-free', messages, stream: false } }));
  assert.equal(calls[0].url.endsWith('/chat/completions'), true, 'a non-muse id takes the chat path');
  assert.deepEqual(calls[0].body.tools.map(tool => tool.function.name), ['bash', 'read'], 'the free tier refuses a payload without them');
  assert.equal(calls[0].body.tool_choice, 'none', 'the decoys must never be called');
  assert.equal(calls[0].body.stream, true, 'upstream is always streamed');
});

test("a chat model keeps the caller's tools and gains the missing decoy", async () => {
  const { calls, fetchImpl } = recorder(() => sse(chatFrames()));
  const adapter = createProviders({ fetchImpl }).opencode;
  const tools = [{ type: 'function', function: { name: 'get_time', description: 'now', parameters: { type: 'object', properties: {} } } }];
  await collect(adapter.generate({ connection, credentials: {}, body: { model: 'deepseek-v4-flash-free', messages, tools, stream: false } }));
  assert.deepEqual(calls[0].body.tools.map(tool => tool.function.name), ['get_time', 'bash', 'read']);
  assert.equal(calls[0].body.tool_choice, undefined, 'a caller that brings its own tools keeps the provider default');
  assert.deepEqual(calls[0].body.tools[0].function.parameters, { type: 'object', properties: {} }, 'the caller tool is passed through');
});

test('one canonical session per conversation, reused across turns', async () => {
  resetStableSessions();
  const { calls, fetchImpl } = recorder(() => sse(responsesEvent(responsesFrames())));
  const adapter = createProviders({ fetchImpl }).opencode;
  const body = { model: 'muse-spark-1.2-contributor-free', messages, stream: false };
  await collect(adapter.generate({ connection, credentials: {}, body }));
  await collect(adapter.generate({ connection, credentials: {}, body: { ...body, messages: [...messages, { role: 'assistant', content: 'hi' }, { role: 'user', content: 'again' }] } }));
  assert.equal(calls[0].headers['x-opencode-session'], calls[1].headers['x-opencode-session'], 'quota is per session, so turns share one');
  assert.notEqual(calls[0].headers['x-opencode-request'], calls[1].headers['x-opencode-request'], 'each turn mints its own request id');

  await collect(adapter.generate({ connection: { ...connection, id: 'other' }, credentials: {}, body }));
  assert.notEqual(calls[2].headers['x-opencode-session'], calls[0].headers['x-opencode-session'], 'a different connection gets its own session');
});

test('a caller-supplied session hint is translated into the accepted shape', async () => {
  const { calls, fetchImpl } = recorder(() => sse(responsesEvent(responsesFrames())));
  const adapter = createProviders({ fetchImpl }).opencode;
  const shaped = mintOpencodeId('ses', 'hint');
  await collect(adapter.generate({ connection, credentials: {}, body: { model: 'muse-spark-1.2-contributor-free', messages, stream: false, session_id: shaped } }));
  assert.equal(calls[0].headers['x-opencode-session'], shaped, 'an accepted id passes through');
  await collect(adapter.generate({ connection, credentials: {}, body: { model: 'muse-spark-1.2-contributor-free', messages, stream: false, session_id: '08f2483c-1c1a-4a4a-9c1a-1a1a1a1a1a1a' } }));
  assert.match(calls[1].headers['x-opencode-session'], OPENCODE_SESSION_RE, 'a harness session id is translated, not forwarded');
  assert.equal(/^ses_08f2483c/.test(calls[1].headers['x-opencode-session']), false, 'and never leaks the raw hex shape');
});

test('tool results travel as items, and their images ride a following user turn', async () => {
  const { calls, fetchImpl } = recorder(() => sse(responsesEvent(responsesFrames())));
  const adapter = createProviders({ fetchImpl }).opencode;
  const image = 'data:image/png;base64,AAAA';
  const history = [
    { role: 'user', content: 'take a screenshot' },
    { role: 'assistant', content: 'On it.', tool_calls: [{ id: 'call_9', type: 'function', function: { name: 'computer_screen_capture', arguments: '{}' } }] },
    { role: 'tool', tool_call_id: 'call_9', content: [{ type: 'text', text: 'Captured 1280x800.' }, { type: 'image_url', image_url: { url: image } }] },
  ];
  await collect(adapter.generate({ connection, credentials: {}, body: { model: 'muse-spark-1.2-contributor-free', messages: history, stream: false } }));

  const input = calls[0].body.input;
  const output = input.find(item => item.type === 'function_call_output');
  assert.equal(output.call_id, 'call_9');
  assert.equal(output.output, 'Captured 1280x800.', 'the tool output is text');
  const call = input.find(item => item.type === 'function_call');
  assert.equal(call.name, 'computer_screen_capture');
  assert.equal(call.arguments, '{}');
  const carrier = input.find(item => item.type === 'message' && item.role === 'user' && JSON.stringify(item.content).includes('input_image'));
  assert.ok(carrier, 'an image-bearing tool result also becomes a user turn');
  assert.deepEqual(carrier.content.filter(part => part.type === 'input_image').map(part => part.image_url), [image]);
  assert.equal(input.filter(item => item.type === 'function_call_output').length, 1, 'and only one output item is sent');
});

test('prior reasoning items and their encrypted payloads are stripped', () => {
  const items = sanitizeResponsesItems([
    { type: 'reasoning', id: 'rs_1', encrypted_content: 'secret' },
    { type: 'message', role: 'assistant', content: [{ type: 'output_text', text: 'kept' }], encrypted_content: 'secret' },
    { type: 'function_call', name: '', call_id: 'call_1', arguments: '' },
    { type: 'function_call_output', call_id: 'call_1', output: [{ text: 'a' }, { text: 'b' }] },
  ]);
  assert.deepEqual(items.map(item => item.type), ['message', 'function_call_output'], 'reasoning and nameless calls are dropped');
  assert.equal(items[0].encrypted_content, undefined);
  assert.equal(items[1].output, 'ab', 'an array output is joined');
});

test('reasoning_effort becomes reasoning.effort, and none is dropped', async () => {
  const { calls, fetchImpl } = recorder(() => sse(responsesEvent(responsesFrames())));
  const adapter = createProviders({ fetchImpl }).opencode;
  const body = { model: 'muse-spark-1.2-contributor-free', messages, stream: false };
  await collect(adapter.generate({ connection, credentials: {}, body: { ...body, reasoning_effort: 'high' } }));
  assert.deepEqual(calls[0].body.reasoning, { effort: 'high', summary: 'auto' });
  assert.equal('reasoning_effort' in calls[0].body, false, 'the refused spelling never reaches the wire');

  await collect(adapter.generate({ connection, credentials: {}, body: { ...body, thinkingLevel: 'none' } }));
  assert.equal('reasoning' in calls[1].body, false, "effort 'none' is refused upstream, so no reasoning block is sent");
  assert.equal('thinkingLevel' in calls[1].body, false);
});

test('the Responses stream is translated into router deltas', async () => {
  const { fetchImpl } = recorder(() => sse(responsesEvent(responsesFrames())));
  const adapter = createProviders({ fetchImpl }).opencode;
  const events = await collect(adapter.generate({ connection, credentials: {}, body: { model: 'muse-spark-1.2-contributor-free', messages, stream: true } }));
  const content = events.filter(event => event.type === 'delta').map(event => event.delta.content).filter(Boolean).join('');
  assert.equal(content, 'Calling get_time.');
  const calls = events.flatMap(event => event.delta?.tool_calls || []);
  assert.equal(calls.length, 2, 'the call opens with its name and then streams its arguments');
  assert.equal(calls[0].index, 0, 'output_index 2 is the first tool call, so its router index is 0');
  assert.equal(calls[0].id, 'call_1');
  assert.equal(calls[0].function.name, 'get_time');
  assert.equal(calls[1].function.arguments, '{"timezone":"UTC"}');
  const usage = events.find(event => event.type === 'usage');
  assert.deepEqual(usage.usage, { prompt_tokens: 626, completion_tokens: 109, total_tokens: 735 });
  assert.equal(events.at(-1).type, 'finish');
  assert.equal(events.at(-1).finishReason, 'tool_calls');
});

test('a non-streaming caller still gets one assembled answer', async () => {
  const { fetchImpl } = recorder(() => sse(responsesEvent(responsesFrames())));
  const adapter = createProviders({ fetchImpl }).opencode;
  const events = await collect(adapter.generate({ connection, credentials: {}, body: { model: 'muse-spark-1.2-contributor-free', messages, stream: false } }));
  const delta = events.find(event => event.type === 'delta');
  assert.equal(delta.delta.content, 'Calling get_time.');
  assert.equal(delta.delta.tool_calls.length, 1, 'the streamed call is assembled into one entry');
  assert.deepEqual(delta.delta.tool_calls[0].function, { name: 'get_time', arguments: '{"timezone":"UTC"}' });
  assert.deepEqual(events.find(event => event.type === 'usage').usage.total_tokens, 735);
  assert.equal(events.at(-1).finishReason, 'tool_calls');
});

test('a free-tier refusal and a quota refusal stay distinguishable', async () => {
  const freeTier = () => json({ error: { type: 'FreeTierError', message: "OpenCode's free tier can only be used from within OpenCode" } }, 403);
  const adapter = createProviders({ fetchImpl: async () => freeTier() }).opencode;
  await assert.rejects(
    () => collect(adapter.generate({ connection, credentials: {}, body: { model: 'muse-spark-1.2-contributor-free', messages, stream: true } })),
    error => error.code === 'AUTH' && error.status === 403 && error.retryable === false && /free tier/i.test(error.message),
  );

  const quota = () => json({ error: { type: 'RateLimitError', message: 'Free usage limit reached for this session.' } }, 429);
  const quotaAdapter = createProviders({ fetchImpl: async () => quota() }).opencode;
  await assert.rejects(
    () => collect(quotaAdapter.generate({ connection, credentials: {}, body: { model: 'muse-spark-1.2-contributor-free', messages, stream: true } })),
    error => error.code === 'RATE_LIMIT' && error.retryable === true,
  );
});

test('a quota refusal keeps the provider Retry-After beside the error', async () => {
  const withHeader = () => new Response(JSON.stringify({ error: { type: 'RateLimitError', message: 'Free usage limit reached for this session.' } }), { status: 429, headers: { 'Content-Type': 'application/json', 'Retry-After': '90' } });
  const adapter = createProviders({ fetchImpl: async () => withHeader() }).opencode;
  await assert.rejects(
    () => collect(adapter.generate({ connection, credentials: {}, body: { model: 'muse-spark-1.2-contributor-free', messages, stream: true } })),
    error => error.code === 'RATE_LIMIT' && error.status === 429 && error.retryAfterMs === 90_000,
  );
});

test('discovery enables only the ids that answer without a credential', async () => {
  const payload = {
    data: [
      { id: 'muse-spark-1.2', object: 'model' },
      { id: 'muse-spark-1.2-contributor-free', object: 'model' },
      { id: 'muse-spark-1.3-contributor-free', object: 'model' },
      { id: 'jev-1.13-free', object: 'model' },
      { id: 'union-alpha', object: 'model' },
    ],
  };
  const adapter = createProviders({ fetchImpl: async () => json(payload) }).opencode;
  const { models } = await adapter.discover({ connection, credentials: {} });
  const enabled = models.filter(model => model.enabled).map(model => model.id);
  assert.deepEqual(enabled, ['muse-spark-1.2-contributor-free', 'muse-spark-1.3-contributor-free', 'jev-1.13-free']);
  const plain = models.find(model => model.id === 'muse-spark-1.2');
  assert.equal(plain.enabled, false, 'the plain id answers 401 without a key');
  const curated = models.find(model => model.id === 'muse-spark-1.2-contributor-free');
  assert.equal(curated.capabilities.vision, 'reported', 'images were read live, so vision is declared');
  assert.deepEqual(curated.thinkingLevels, ['minimal', 'low', 'medium', 'high']);
});

test('a discovery failure falls back to the curated static list', async () => {
  const adapter = createProviders({ fetchImpl: async () => { throw new Error('offline'); } }).opencode;
  const { models } = await adapter.discover({ connection, credentials: {} });
  assert.deepEqual(models.map(model => model.id), ['muse-spark-1.2-contributor-free', 'muse-spark-1.3-contributor-free']);
  assert.ok(models.every(model => model.source === 'static' && model.enabled));
});

test('helpers keep their shape on odd input', () => {
  assert.deepEqual(toResponsesInput([{ role: 'user', content: [] }]).input, [], 'an empty user turn contributes nothing');
  assert.deepEqual(toResponsesInput([{ role: 'system', content: 'rules' }, { role: 'user', content: 'hi' }]).instructions, 'rules');
  assert.deepEqual(responsesTools([{ type: 'function', function: { name: '' } }]), []);
  assert.deepEqual(responsesTools([{ name: 'x', parameters: { type: 'object' } }])[0].parameters, { type: 'object', properties: {} });
});
test('a stream cut before its completion event reports `length`, not a clean stop', async () => {
  // Measured live 2026-09-26: a muse-spark-1.3 review turn was severed mid-sentence, the
  // provider sent no `response.completed` and no usage, and the adapter's default made the
  // harness call the severed answer a finished one. The missing terminal event is the signal.
  const cut = responsesEvent(responsesFrames().filter(frame => frame !== '[DONE]'
    && !(typeof frame === 'object' && (frame.type === 'response.completed' || frame.type === 'response.done'))));
  const { fetchImpl } = recorder(() => sse(cut));
  const adapter = createProviders({ fetchImpl }).opencode;
  const events = await collect(adapter.generate({ connection, credentials: {}, body: { model: 'muse-spark-1.3-contributor-free', messages, stream: false } }));
  assert.equal(events.at(-1).type, 'finish');
  assert.equal(events.at(-1).finishReason, 'length', 'a severed answer is not a completed one');
  assert.equal(events.some(event => event.type === 'usage'), false, 'and it carries no usage to pretend with');

  const healthy = recorder(() => sse(responsesEvent(responsesFrames())));
  const whole = await collect(createProviders({ fetchImpl: healthy.fetchImpl }).opencode.generate({ connection, credentials: {}, body: { model: 'muse-spark-1.3-contributor-free', messages, stream: false } }));
  assert.equal(whole.at(-1).finishReason, 'tool_calls', 'a stream that does complete keeps its own reason');
});
