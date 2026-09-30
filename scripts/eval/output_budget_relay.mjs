/** Isolated live measurement relay: B OpenCode adapter, no production DB/session/keys.
 * Allows up to 240 seconds to distinguish model output limits from the existing
 * production router's 90-second deadline. This does not change that deadline.
 */
import { createServer } from 'node:http';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { createProviders } from '../../router/src/providers/index.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
if (execFileSync('git', ['branch', '--show-current'], { cwd: root, encoding: 'utf8' }).trim() !== 'B') {
  throw new Error('Eval relay must run from branch B');
}
const connection = { id: 'w3-isolated-opencode', providerId: 'opencode', endpoint: 'https://opencode.ai' };
const provider = createProviders({ fetchImpl: fetch }).opencode;
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
  const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(240000)]);
  res.on('close', () => controller.abort());
  try {
    let raw = '';
    for await (const data of req) {
      raw += data;
      if (raw.length > 100000) throw new Error('Eval request too large');
    }
    const body = JSON.parse(raw);
    if (body.modelId !== 'space-bunny-free' || !Number.isInteger(body.max_tokens)
      || body.max_tokens < 1 || body.max_tokens > 32000 || body.tools?.length || !body.stream) {
      throw new Error('Only bounded text-only Space Bunny eval requests are allowed');
    }
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    const frame = (delta = {}, finish = null, extra = {}) => res.write('data: ' + JSON.stringify({
      id: 'w3-isolated', choices: [{ index: 0, delta, finish_reason: finish }], ...extra }) + '\n\n');
    frame({ role: 'assistant' });
    for await (const event of provider.generate({ connection, credentials: {},
      body: { ...body, model: 'space-bunny-free' }, signal })) {
      if (event.type === 'delta') frame(event.delta);
      if (event.type === 'usage') frame({}, null, { usage: event.usage });
      if (event.type === 'finish') frame({}, event.finishReason);
    }
    res.end('data: [DONE]\n\n');
  } catch (error) {
    const body = JSON.stringify({ error: { message: String(error.message).slice(0, 300) } });
    if (!res.headersSent) {
      res.writeHead(502, { 'Content-Type': 'application/json' }); res.end(body);
    } else res.end('data: ' + body + '\n\ndata: [DONE]\n\n');
  }
});
server.requestTimeout = 250000;
server.listen(0, '127.0.0.1', () => console.log(JSON.stringify({
  url: 'http://127.0.0.1:' + server.address().port, adapter: 'B OpenCode', deadlineMs: 240000,
  productionRouterDeadlineChanged: false,
})));
