import test from 'node:test';
import assert from 'node:assert/strict';
import { createStore, applyEvent } from '../lib/store.js';

test('T-WEB-003: snapshot data is exposed and run events respect versions', () => {
  const snapshot = {
    session_token: 'session-1',
    settings: { theme: 'dark' },
    models: [{ model_id: 'local-stt', role: 'stt', ready: true, error_code: null }],
    runs: [
      { run_id: 'first', version: 2, status: 'recording', actions: [] },
      { run_id: 'second', version: 4, status: 'held', actions: ['copy'] },
    ],
    active_run_id: 'first',
  };
  const initial = createStore(snapshot);
  assert.deepEqual(initial.settings, snapshot.settings);
  assert.deepEqual(initial.models, snapshot.models);
  assert.deepEqual(initial.runs, snapshot.runs);
  assert.equal(initial.active_run_id, 'first');

  const updated = applyEvent(initial, {
    name: 'run:state', run_id: 'first', version: 3, status: 'processing',
  });
  assert.equal(updated.runs.find((run) => run.run_id === 'first').status, 'processing');
  assert.equal(updated.runs.find((run) => run.run_id === 'first').version, 3);
  assert.deepEqual(updated.runs.find((run) => run.run_id === 'second'), snapshot.runs[1]);
  assert.deepEqual(updated.settings, snapshot.settings);
  assert.deepEqual(updated.models, snapshot.models);
  assert.equal(initial.runs[0].status, 'recording');

  for (const version of [2, 1]) {
    assert.deepEqual(applyEvent(updated, {
      name: 'run:state', run_id: 'first', version, status: 'done',
    }), updated);
  }
});
