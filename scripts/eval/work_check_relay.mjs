/** Tool-enabled W6 fixture relay. Same B OpenCode adapter/model; no production state. */
import { createServer } from 'node:http';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { createProviders } from '../../router/src/providers/index.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const deadlineMs = Number(process.env.BOXFOX_EVAL_DEADLINE_MS || 240000);
if (![90000, 180000, 240000].includes(deadlineMs)) throw new Error('Use a measured 90/180/240 second eval deadline');
if (execFileSync('git', ['branch', '--show-current'], { cwd: root, encoding: 'utf8' }).trim() !== 'B') {
  throw new Error('W6 eval requires branch B');
}
const connection = { id: 'w6-isolated-opencode', providerId: 'opencode', endpoint: 'https://opencode.ai' };
const provider = createProviders({ fetchImpl: fetch }).opencode;
const allowed = new Set(['work_artifact_read', 'file_read', 'codebase_grep', 'codebase_glob', 'terminal_exec',
  'work_graph', 'work_run', 'work_check', 'web_fetch', 'read_source']);
const server = createServer(async (req, res) => {
  if (req.method === 'GET' && req.url === '/api/router/state') {
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({ connections: [{ ...connection, enabled: true,
      models: [{ id: 'space-bunny-free', enabled: true }] }] }));
    return;
  }
  if (req.method !== 'POST' || req.url !== '/api/router/chat') {
    res.writeHead(404); res.end(); return;
  }
  const controller = new AbortController();
  const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(deadlineMs)]);
  res.on('close', () => controller.abort());
  try {
    let raw = '';
    for await (const chunk of req) {
      raw += chunk;
      if (raw.length > 1000000) throw new Error('Fixture request too large');
    }
    const body = JSON.parse(raw);
    if (body.modelId !== 'space-bunny-free' || !Number.isInteger(body.max_tokens)
      || body.max_tokens < 1 || body.max_tokens > 16000 || typeof body.stream !== 'boolean'
      || (body.tools || []).some(t => !allowed.has(t.function?.name))) {
      throw new Error('Only bounded Space Bunny fixture tools allowed');
    }
    if (body.stream) res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    let content = '', reasoning = '', usage = null, finishReason = null;
    const calls = new Map();
    const frame = (delta = {}, finish = null, extra = {}) => res.write('data: ' + JSON.stringify({
      id: 'w6-isolated', choices: [{ index: 0, delta, finish_reason: finish }], ...extra }) + '\n\n');
    if (body.stream) frame({ role: 'assistant' });
    for await (const event of provider.generate({ connection, credentials: {}, body: { ...body, model: 'space-bunny-free' }, signal })) {
      if (body.stream) {
        if (event.type === 'delta') frame(event.delta);
        if (event.type === 'usage') frame({}, null, { usage: event.usage });
        if (event.type === 'finish') frame({}, event.finishReason);
      } else {
        if (event.type === 'delta') {
          content += event.delta?.content || '';
          reasoning += event.delta?.reasoning_content || event.delta?.reasoning || '';
          for (const part of event.delta?.tool_calls || []) {
            const index = part.index ?? 0;
            const call = calls.get(index) || { id: '', type: 'function', function: { name: '', arguments: '' } };
            if (part.id) call.id = part.id;
            call.function.name += part.function?.name || '';
            call.function.arguments += part.function?.arguments || '';
            calls.set(index, call);
          }
        }
        if (event.type === 'usage') usage = event.usage;
        if (event.type === 'finish') finishReason = event.finishReason;
      }
    }
    if (body.stream) res.end('data: [DONE]\n\n');
    else {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ choices: [{ message: { role: 'assistant', content,
        ...(reasoning ? { reasoning_content: reasoning } : {}), ...(calls.size ? { tool_calls: [...calls.values()] } : {}) },
        finish_reason: finishReason }], usage }));
    }
  } catch (error) {
    const data = JSON.stringify({ error: { message: String(error.message).slice(0, 300) } });
    if (!res.headersSent) { res.writeHead(502, { 'Content-Type': 'application/json' }); res.end(data); }
    else res.end('data: ' + data + '\n\ndata: [DONE]\n\n');
  }
});
server.requestTimeout = 250000;
server.listen(0, '127.0.0.1', () => console.log(JSON.stringify({
  url: `http://127.0.0.1:${server.address().port}`, model: 'opencode/space-bunny-free', deadlineMs,
  productionRouterDeadlineChanged: false, tools: [...allowed],
})));
