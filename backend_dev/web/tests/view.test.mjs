import test from 'node:test';
import assert from 'node:assert/strict';
import { hudState, shouldToastInserted, recoveryButtons } from '../lib/view.js';

test('T-WEB-004: insertion toast requires a confirmed done event', () => {
  assert.equal(shouldToastInserted({ name: 'run:state', run_id: 'r', version: 5, status: 'done' }), true);
  for (const status of ['uncertain', 'error', 'awaiting_cleanup_choice', 'awaiting_destination', 'processing', 'recording', 'held', 'cancelled']) {
    assert.equal(shouldToastInserted({ name: 'run:state', run_id: 'r', version: 5, status }), false, status);
  }
  assert.equal(shouldToastInserted({ name: 'run:recovery', run_id: 'r', version: 5, status: 'done', actions: [] }), false);
});

test('T-WEB-005: cleanup recovery offers backend actions and cancel', () => {
  const event = {
    name: 'run:recovery', run_id: 'r', version: 7,
    status: 'awaiting_cleanup_choice', actions: ['retry_cleanup', 'use_original', 'copy'],
  };
  assert.deepEqual(recoveryButtons(event), ['retry_cleanup', 'use_original', 'copy', 'cancel']);
  assert.equal(shouldToastInserted(event), false);
  assert.deepEqual(recoveryButtons({ ...event, actions: ['copy'] }), ['copy', 'cancel']);
});

test('T-WEB-007: HUD colors follow the run lifecycle', () => {
  const expected = {
    recording: 'green', processing: 'yellow', awaiting_destination: 'yellow',
    awaiting_cleanup_choice: 'red', error: 'red', uncertain: 'red', held: 'blue', idle: 'blue',
  };
  for (const [status, color] of Object.entries(expected)) {
    assert.deepEqual(hudState(status), { color }, status);
  }
});

test('held dictations offer copy without an unsupported cancel or implicit paste', () => {
  const held = { status: 'held', actions: ['insert', 'copy'] };
  assert.deepEqual(recoveryButtons(held), ['copy']);
  assert.deepEqual(recoveryButtons({ ...held, actions: ['insert'] }), []);
});

test('waiting dictations offer only backend Copy in the recovery row', () => {
  const pending = { status: 'awaiting_destination', actions: ['insert', 'copy'] };
  assert.deepEqual(recoveryButtons(pending), ['copy']);
  assert.deepEqual(recoveryButtons({ ...pending, actions: ['insert'] }), []);
});

test('T-WEB-022: the window opens on the General page', async () => {
  const { readFile } = await import('node:fs/promises');
  const app = await readFile(new URL('../app.js', import.meta.url), 'utf8');
  const html = await readFile(new URL('../index.html', import.meta.url), 'utf8');
  assert.match(html, /id="page-home"/);
  // Selected before the backend connection is awaited, so the page is never blank.
  assert.ok(app.indexOf("page('home');") > -1 && app.indexOf("page('home');") < app.indexOf('await whenHostReady(window)'));
});
