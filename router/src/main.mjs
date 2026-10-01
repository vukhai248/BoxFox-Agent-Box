import { fileURLToPath } from 'node:url';
import { RouterStore } from './store.mjs';
import { ProviderService } from './service.mjs';
import { RouterEngine } from './engine.mjs';
import { OAuthManager } from './oauth.mjs';
import { createRouterServer, bridgeExposureNote } from './server.mjs';
import { createSafeFetch } from './network.mjs';
import { createProviders } from './providers/index.mjs';
import { ModelSyncScheduler } from './model-sync.mjs';
import { largeRequestDeadline } from './request-budget.mjs';
import { logEvent, logFailure, logPath, resetOnShutdown } from './system-log.mjs';

const production = process.argv.includes('--production');
const port = Number(process.env.BOXFOX_ROUTER_PORT || (production ? 3100 : 3101));
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid router port.');
const store = new RouterStore();
const service = new ProviderService({ store, providers: createProviders({ fetchImpl: createSafeFetch() }) });
const engine = new RouterEngine({ service, largeDeadlineMs: largeRequestDeadline() });
const oauth = new OAuthManager({ service, port: Number(process.env.BOXFOX_OAUTH_PORT || 51121) });
const modelSync = new ModelSyncScheduler({ service, intervalMs: Number(process.env.BOXFOX_MODEL_SYNC_MS || 6 * 60 * 60 * 1000) });
// Opt-in: the sandbox reaches the router through the docker bridge gateway, so the
// second listener must be on that one address, not on 0.0.0.0 (see README-claude-code.md).
const bridgeHost = (process.env.BOXFOX_ROUTER_BRIDGE_HOST || '').trim() || null;
const allowedHosts = [`localhost:${port}`, `127.0.0.1:${port}`, 'localhost:3100', '127.0.0.1:3100', ...(bridgeHost ? [`${bridgeHost}:${port}`] : [])];
const server = createRouterServer({ service, engine, oauth, frontendDir: production ? fileURLToPath(new URL('../../frontend/dist', import.meta.url)) : null, allowedOrigins: ['http://localhost:3100', 'http://127.0.0.1:3100', ...(production ? [`http://localhost:${port}`, `http://127.0.0.1:${port}`] : [])], allowedHosts, bridgeHost });
server.on('error', async error => { logFailure('router.startup_failed', error, { code: error.code, port }); console.error(`BoxFox Router startup failed (${error.code || 'ERROR'}). Check port ${port} and host storage permissions.`); await oauth.close(); store.close(); process.exitCode = 1; });
server.listen(port, '127.0.0.1', () => {
  logEvent('router.start', { port, pid: process.pid, node: process.version, log: logPath, bridgeHost });
  modelSync.start();
  if (bridgeHost && server.bridge) {
    const note = bridgeExposureNote(bridgeHost);
    if (note) logEvent('router.bridge_exposure', { level: 'warn', code: 'BRIDGE_EXPOSURE', message: note, host: bridgeHost });
    server.bridge.listen(port, bridgeHost, () => logEvent('router.bridge_start', { host: bridgeHost, port }));
  }
  console.log(`BoxFox Router ready: http://localhost:${port}/api/router/health`);
});
let closing = false;
async function shutdown() { if (closing) return; closing = true; logEvent('router.stop', { port, pid: process.pid }); modelSync.stop(); for (const request of service.active.values()) request.controller.abort(); server.closeAllConnections(); await new Promise(r => server.close(r)); if (server.bridge) { server.bridge.closeAllConnections(); await new Promise(r => server.bridge.close(r)); } await oauth.close(); store.close(); /* Owner's rule: reset only on a GRACEFUL stop. Last thing we do, so `router.stop` stays in the file it belongs to; a hard kill never reaches this line. */ resetOnShutdown(); }
process.on('SIGINT', () => shutdown()); process.on('SIGTERM', () => shutdown());
