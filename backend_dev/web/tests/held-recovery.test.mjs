import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { canDiscard, recoveryButtons, shouldToastInserted } from '../lib/view.js';

const app = readFileSync(new URL('../app.js', import.meta.url), 'utf8');

function renderInContext(name, context) {
  const source = app.match(new RegExp(`function ${name}\\(\\)\\s*\\{[\\s\\S]*?\\n\\}`))?.[0];
  assert.ok(source, `production ${name} function must be present`);
  vm.runInNewContext(`${source}\n${name}();`, context);
}

test('production held rendering explains the blocked paste and exposes only Copy', () => {
  const elements = new Map();
  const $ = (selector) => selector === '#level-segments' ? null : elements.get(selector) ?? elements.set(selector, { dataset: {}, textContent: '', innerHTML: '', hidden: false }).get(selector);
  const context = {
    $,
    run: () => ({ run_id: 'synthetic-held', status: 'held', actions: ['insert', 'copy'] }),
    state: { lastEvent: null, latestLevel: null },
    bridge: { available: () => true },
    canDiscard, recoveryButtons, shouldToastInserted,
    icon: () => '', esc: (text) => text,
    waveform: null,
    toast: () => assert.fail('a held dictation must not toast success'),
  };
  renderInContext('renderRun', context);
  assert.equal($('#dictate').dataset.state, 'warning');
  assert.equal($('#dictate-status').textContent, 'Text not pasted');
  assert.match($('#dictate-caption').textContent, /original text field/);
  assert.match($('#dictate-recovery').innerHTML, /data-recover="copy"/);
  assert.doesNotMatch($('#dictate-recovery').innerHTML, /data-recover="(?:insert|cancel)"/);
  assert.equal($('#dictate-cancel').hidden, true);
  context.run = () => null;
  renderInContext('renderRun', context);
  assert.equal($('#dictate-recovery').innerHTML, '');
});

test('held history is visible in Needs attention and marked as not pasted', () => {
  const elements = new Map();
  const $ = (selector) => elements.get(selector) ?? elements.set(selector, { innerHTML: '', textContent: '', hidden: true }).get(selector);
  const context = {
    $, historyFilter: 'failed',
    state: { history: [{ run_id: 'synthetic-held', status: 'held', text: 'Synthetic dictation.', created_at: 1 }] },
    dateLabel: () => '', esc: (text) => text, icon: () => '',
  };
  renderInContext('renderHistory', context);
  assert.match($('#history-list').innerHTML, /Synthetic dictation\./);
  assert.match($('#history-list').innerHTML, /Not pasted/);
  assert.equal($('.nav-item[data-page="history"] .status-dot').hidden, false);
});

test('pending paste explains where to return and keeps Copy and Cancel available', () => {
  const elements = new Map();
  const $ = (selector) => selector === '#level-segments' ? null : elements.get(selector) ?? elements.set(selector, { dataset: {}, textContent: '', innerHTML: '', hidden: false }).get(selector);
  const context = {
    $,
    run: () => ({ run_id: 'synthetic-waiting', status: 'awaiting_destination', actions: ['copy', 'insert'] }),
    state: { lastEvent: null, latestLevel: null },
    bridge: { available: () => true },
    canDiscard, recoveryButtons, shouldToastInserted,
    icon: () => '', esc: (text) => text,
    waveform: null,
    toast: () => assert.fail('a pending paste must not toast success'),
  };
  renderInContext('renderRun', context);
  assert.equal($('#dictate-status').textContent, 'Waiting to paste');
  assert.match($('#dictate-caption').textContent, /Return to the original text field/);
  assert.match($('#dictate-recovery').innerHTML, /data-recover="copy"/);
  assert.doesNotMatch($('#dictate-recovery').innerHTML, /data-recover="(?:insert|cancel)"/);
  assert.equal($('#dictate-cancel').hidden, false);
  assert.equal($('#rec-btn').disabled, true);
});
