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

test('T-WEB-018: title-bar commands go straight to the host without a session token', async () => {
  const calls = [];
  const bridge = createBridge(async (name, payload) => { calls.push({ name, payload }); return { ok: true, data: null, error: null }; });
  for (const name of ['window_drag', 'window_minimize', 'window_toggle_maximize', 'window_close']) {
    assert.deepEqual(await bridge.window(name), { ok: true, data: null, error: null });
  }
  assert.deepEqual(calls.map((call) => call.name), ['window_drag', 'window_minimize', 'window_toggle_maximize', 'window_close']);
  assert.ok(calls.every((call) => Object.keys(call.payload).length === 0));
  assert.deepEqual(await bridge.window('history_delete_all'), { ok: false, data: null, error: 'unknown_command' });
  assert.equal(calls.length, 4);
});

test('T-WEB-019: launch-at-login changes carry a deadline like other mutations', async () => {
  const calls = [];
  const bridge = createBridge(async (name, payload) => { calls.push({ name, payload }); return name === 'state_get' ? { ok: true, data: { session_token: 's' }, error: null } : { ok: true, data: {}, error: null }; }, { now: () => 1000 });
  await bridge.call('autostart_get');
  await bridge.call('autostart_set', { enabled: true });
  assert.deepEqual(calls.slice(1), [
    { name: 'autostart_get', payload: { session_token: 's' } },
    { name: 'autostart_set', payload: { enabled: true, session_token: 's', deadline: 11 } },
  ]);
});

test('T-WEB-020: the page waits for pywebviewready when the host API arrives late', async () => {
  const { whenHostReady } = await import('../lib/bridge.js');
  await whenHostReady({ pywebview: { api: { call() {} } } });
  const listeners = [];
  const host = { addEventListener: (name, listener, options) => listeners.push({ name, listener, options }) };
  let ready = false;
  const waiting = whenHostReady(host).then(() => { ready = true; });
  await Promise.resolve();
  assert.equal(ready, false);
  assert.deepEqual(listeners.map(({ name, options }) => ({ name, options })), [{ name: 'pywebviewready', options: { once: true } }]);
  listeners[0].listener();
  await waiting;
  assert.equal(ready, true);
});
