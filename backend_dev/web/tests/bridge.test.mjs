import test from 'node:test';
import assert from 'node:assert/strict';
import { createBridge } from '../lib/bridge.js';

test('T-WEB-006: command metadata and reconnect are authoritative', async () => {
  const calls = [];
  const hostCall = async (name, payload) => {
    calls.push({ name, payload });
    if (name === 'state_get') {
      return { ok: true, data: { session_token: `session-${calls.filter((call) => call.name === 'state_get').length}`, settings: {}, models: [], runs: [], active_run_id: null }, error: null };
    }
    return { ok: true, data: { run_id: 'r' }, error: null };
  };
  const bridge = createBridge(hostCall, { now: () => 1000, randomUUID: () => 'request-1' });
  await bridge.reconnect();
  assert.deepEqual(calls[0], { name: 'state_get', payload: {} });

  await bridge.call('models_status', {});
  assert.deepEqual(calls[1], { name: 'models_status', payload: { session_token: 'session-1' } });
  await bridge.call('run_start', {});
  assert.deepEqual(calls[2], {
    name: 'run_start', payload: { session_token: 'session-1', deadline: 11, request_id: 'request-1' },
  });
  await bridge.call('settings_update', { patch: { theme: 'light' } });
  assert.deepEqual(calls[3], {
    name: 'settings_update', payload: { patch: { theme: 'light' }, session_token: 'session-1', deadline: 11 },
  });

  const beforeReconnect = calls.length;
  await bridge.reconnect();
  assert.deepEqual(calls.slice(beforeReconnect), [{ name: 'state_get', payload: {} }]);
  await bridge.call('history_list', {});
  assert.deepEqual(calls.at(-1), { name: 'history_list', payload: { session_token: 'session-2' } });
});

test('T-WEB-006: previous-session rejection refreshes once without replay', async () => {
  const calls = [];
  const bridge = createBridge(async (name, payload) => {
    calls.push({ name, payload });
    if (name === 'state_get') return { ok: true, data: { session_token: 'fresh', settings: {}, models: [], runs: [], active_run_id: null }, error: null };
    return { ok: false, data: null, error: 'previous_session_token' };
  }, { now: () => 1000, randomUUID: () => 'request-1' });
  await bridge.reconnect();
  const result = await bridge.call('run_cancel', { run_id: 'r' });
  assert.deepEqual(result, { ok: false, data: null, error: 'previous_session_token' });
  assert.deepEqual(calls.map((call) => call.name), ['state_get', 'run_cancel', 'state_get']);
  assert.deepEqual(calls.at(-1).payload, {});
});
