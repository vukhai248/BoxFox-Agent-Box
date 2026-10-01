/** Disposable real router/engine for W6.5 HTTP integration; branch B, Space Bunny. */
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { mkdir } from 'node:fs/promises';
import { resolve, relative, sep } from 'node:path';
import { RouterStore } from '../../router/src/store.mjs';
import { ProviderService } from '../../router/src/service.mjs';
import { RouterEngine } from '../../router/src/engine.mjs';
import { createProviders } from '../../router/src/providers/index.mjs';
import { createRouterServer } from '../../router/src/server.mjs';
import { largeRequestDeadline } from '../../router/src/request-budget.mjs';
import { createSafeFetch } from '../../router/src/network.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
if (execFileSync('git', ['branch', '--show-current'], { cwd: root, encoding: 'utf8' }).trim() !== 'B') throw new Error('B required');
const dir = resolve(root, process.argv[2] || '.tmp/work-checks/w65-http-router');
if (!relative(resolve(root, '.tmp'), dir).startsWith(`work-checks${sep}`)) throw new Error('Disposable directory required');
await mkdir(dir, { recursive: true });
const store = new RouterStore({ dataDir: dir });
const service = new ProviderService({ store, providers: createProviders({ fetchImpl: createSafeFetch() }) });
const connection = service.create({ providerId: 'opencode', name: 'W6.5 disposable public Space Bunny' });
service.addKey(connection.id, { label: 'Anonymous fixture; no secret' });
await service.discover(connection.id);
if (!service.connection(connection.id).models.some(m => m.id === 'space-bunny-free' && m.enabled)) throw new Error('Space Bunny unavailable; no model substitution');
const engine = new RouterEngine({ service, largeDeadlineMs: largeRequestDeadline() });
const hosts = [];
const server = createRouterServer({ service, engine, oauth: {}, allowedHosts: hosts, allowedOrigins: [] });
server.listen(0, '127.0.0.1', () => {
  const url = `http://127.0.0.1:${server.address().port}`;
  hosts.push(new URL(url).host);
  console.log(JSON.stringify({ url, connectionId: connection.id, model: 'opencode/space-bunny-free',
    smallDeadlineMs: engine.deadlineMs, largeDeadlineMs: engine.largeDeadlineMs, productionStateChanged: false }));
});
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => {
  server.closeAllConnections();
  server.close(() => { store.close(); process.exit(0); });
});
