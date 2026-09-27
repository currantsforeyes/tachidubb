// Global fetch stub: a route table plus a call log.
//
// Views fetch on mount (voices, glossary, lip-sync status, App's polling), so
// every test gets sane defaults for free. Tests override per-route with
// setRoute() before render and assert on fetchCalls afterwards.
import { systemFixture } from './fixtures.js';

// Key format: `${METHOD} ${path}` — e.g. 'GET /api/jobs'.
const DEFAULT_ROUTES = new Map(Object.entries({
  'GET /api/system': () => systemFixture,
  'GET /api/jobs': () => ({ jobs: [] }),
  'GET /api/voices': () => ({ presets: [] }),
  'GET /api/voice_presets': () => ({ presets: [] }),
  'GET /api/glossary': () => ({ exists: false, data: { domains: [] } }),
  'GET /api/lip_sync/status': () => ({ installed: false, engine: 'musetalk' }),
  'GET /api/config': () => ({}),
  'POST /api/dub': () => ({ job_id: 'job-test-1' }),
}));

let overrides = new Map();

/** Everything fetch received since the last reset: { url, method, body }. */
export const fetchCalls = [];

/** Override a route with static data or a () => data handler. Call BEFORE render. */
export function setRoute(method, url, data) {
  overrides.set(`${method} ${url}`, typeof data === 'function' ? data : () => data);
}

/** Clear overrides and the call log. Invoked before each test (setup.js). */
export function resetApi() {
  overrides.clear();
  fetchCalls.length = 0;
}

export async function fetchStub(url, init = {}) {
  const method = (init.method || 'GET').toUpperCase();
  const key = `${method} ${url}`;
  fetchCalls.push({ url: String(url), method, body: init.body });

  const handler = overrides.get(key) || DEFAULT_ROUTES.get(key);
  // Unknown routes return {} with ok:true — mirrors "endpoint answered, no
  // interesting payload" and keeps unrelated views from crashing.
  const data = handler ? await handler() : {};
  return {
    ok: true,
    status: 200,
    json: async () => data,
    text: async () => JSON.stringify(data),
  };
}

export function installFetch() {
  globalThis.fetch = fetchStub;
}
