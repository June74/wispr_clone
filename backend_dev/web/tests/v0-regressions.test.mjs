import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { acceptsEvent, applyEvent, createStore } from '../lib/store.js';

const app = readFileSync(new URL('../app.js', import.meta.url), 'utf8');
const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const css = readFileSync(new URL('../styles.css', import.meta.url), 'utf8');
const messages = readFileSync(new URL('../lib/messages.js', import.meta.url), 'utf8');
const forms = await import('../lib/forms.js').catch(() => ({}));
const view = await import('../lib/view.js');

test('T-WEB-023: term eligibility and Add/Edit modal wiring', () => {
  assert.equal(typeof forms.termSaveEnabled, 'function', 'termSaveEnabled must be exported');
  for (const value of ['', '  \n ', null, undefined, 3]) assert.equal(forms.termSaveEnabled(value), false);
  for (const value of ['Kubernetes', '  Kubernetes  ']) assert.equal(forms.termSaveEnabled(value), true);
  assert.match(app, /#term-input['"]\)\?\.addEventListener\(['"]input['"][\s\S]*?#save-term['"]\)\.disabled\s*=\s*!termSaveEnabled\(/);
  assert.match(app, /#add-term['"]\)\?\.addEventListener\(['"]click['"][\s\S]*?#save-term['"]\)\.disabled\s*=\s*true/);
  assert.match(app, /termEdit[\s\S]*?#term-input['"]\)\.value\s*=\s*item\.spelling[\s\S]*?#save-term['"]\)\.disabled\s*=\s*!?\s*(?:false|termSaveEnabled\()/);
  assert.match(html, /id="save-term"\s+disabled/);
});

test('T-WEB-024: instructions dirty state preserves edits and confirms save', () => {
  assert.equal(typeof forms.instructionsDirty, 'function', 'instructionsDirty must be exported');
  assert.equal(forms.instructionsDirty('', null), false);
  assert.equal(forms.instructionsDirty('', undefined), false);
  assert.equal(forms.instructionsDirty('saved', 'saved'), false);
  assert.equal(forms.instructionsDirty('changed', 'saved'), true);
  assert.equal(forms.instructionsDirty(' ', ''), true);
  assert.match(app, /#instructions['"]\)\?\.addEventListener\(['"]input['"][\s\S]*?#save-instructions['"]\)\.disabled\s*=\s*!instructionsDirty\(/);
  const settings = app.match(/function renderSettings\(\)\s*\{[\s\S]*?\n\}/)?.[0] ?? '';
  assert.match(settings, /instructionsDirty\(/, 'render must check whether the textarea has unsaved edits');
  assert.doesNotMatch(settings, /if\s*\(\$\(['"]#instructions['"]\)\)\s*\$\(['"]#instructions['"]\)\.value/, 'render must not overwrite every input');
  assert.match(app, /#save-instructions['"]\)\?\.addEventListener\(['"]click['"][\s\S]*?cleanup_instructions:\s*\$\(['"]#instructions['"]\)\.value[\s\S]*?#save-instructions['"]\)\.disabled\s*=\s*true[\s\S]*?#save-note['"]\)\.textContent\s*=\s*['"]Saved['"]/);
});

test('T-WEB-025: microphone IDs, selection, persistence and test payload', () => {
  assert.equal(typeof forms.micDeviceId, 'function', 'micDeviceId must be exported');
  assert.equal(forms.micDeviceId(''), null);
  assert.equal(forms.micDeviceId(null), null);
  assert.equal(forms.micDeviceId(undefined), null);
  assert.equal(forms.micDeviceId('0'), 0);
  assert.equal(forms.micDeviceId('3'), 3);
  assert.equal(typeof forms.micSelection, 'function', 'micSelection must be exported');
  const devices = [{ device_id: 0, is_default: true }, { device_id: 3, is_default: false }];
  assert.equal(forms.micSelection({ microphone_id: '3' }, devices), '3');
  assert.equal(forms.micSelection({ microphone_id: '9' }, devices), '0');
  assert.equal(forms.micSelection({}, [{ device_id: 3, is_default: false }]), '');
  assert.match(app, /#mic-select['"]\)\?\.addEventListener\(['"]change['"][\s\S]*?settings_update[\s\S]*?microphone_id:/);
  assert.match(app, /#mic-select['"]\)[\s\S]*?micSelection\(state\.settings,\s*state\.microphones\)/);
  assert.match(app, /mic_test_start[\s\S]*?device_id:\s*micDeviceId\(\$\(['"]#mic-select['"]\)\.value\)/);
});

test('T-WEB-026: same-version recovery merges actions; stale events stay ignored', () => {
  const state = createStore({ runs: [{ run_id: 'r', version: 3, status: 'processing', actions: [] }], active_run_id: 'r' });
  const v4 = { name: 'run:state', run_id: 'r', version: 4, status: 'awaiting_cleanup_choice' };
  const afterState = applyEvent(state, v4);
  const recovery = { name: 'run:recovery', run_id: 'r', version: 4, status: 'awaiting_cleanup_choice', actions: ['retry_cleanup', 'use_original', 'copy'] };
  assert.equal(acceptsEvent(afterState, recovery), true);
  const afterRecovery = applyEvent(afterState, recovery);
  assert.deepEqual(afterRecovery.runs[0].actions, recovery.actions);
  assert.equal(afterRecovery.runs[0].status, 'awaiting_cleanup_choice');
  assert.equal(afterRecovery.runs[0].version, 4);
  assert.equal(afterRecovery.active_run_id, 'r');
  const stale = { ...recovery, version: 3, actions: ['insert'] };
  assert.equal(acceptsEvent(afterRecovery, stale), false);
  assert.deepEqual(applyEvent(afterRecovery, stale), afterRecovery);
  assert.equal(acceptsEvent(afterRecovery, v4), false);
  assert.deepEqual(applyEvent(afterRecovery, v4), afterRecovery);
});

test('T-WEB-026: recovery controls render from the active run and clear otherwise', () => {
  assert.ok(html.includes('id="dictate-recovery"'), 'dedicated recovery container is missing');
  const renderRun = app.match(/function renderRun\(\)\s*\{[\s\S]*?\n\}/)?.[0] ?? '';
  assert.match(renderRun, /recoveryButtons\(active\)/);
  assert.match(renderRun, /#dictate-recovery/);
  assert.match(renderRun, /awaiting_cleanup_choice/);
  assert.match(renderRun, /Text cleanup couldn't finish\. Choose how to continue\./);
  assert.match(renderRun, /#dictate-recovery['"]\)\.(?:innerHTML\s*=|replaceChildren\()/);
  assert.doesNotMatch(app, /lastRecovery/);
  assert.match(app, /bridge\.call\('run_recover',\s*\{\s*run_id:\s*active\.run_id,\s*expected_version:\s*active\.version,\s*action:\s*recover\.dataset\.recover\s*\}\)/);
});

test('T-WEB-027: local-only UI and error message are removed', () => {
  for (const [name, source] of [['index.html', html], ['app.js', app]]) {
    for (const token of ['Local-only mode', 'privacy-local-switch', 'local-switch', 'local-only-warning', 'local_only']) {
      assert.equal(source.includes(token), false, `${name} still contains ${token}`);
    }
  }
  assert.doesNotMatch(messages, /cloud_model_forbidden/);
});

test('T-WEB-028: discard follows cancellable status and is clickable when visible', () => {
  assert.equal(typeof view.canDiscard, 'function', 'canDiscard must be exported');
  for (const status of ['recording', 'processing', 'awaiting_cleanup_choice', 'awaiting_destination']) assert.equal(view.canDiscard(status), true, status);
  for (const status of ['held', 'idle', 'done', 'error', 'uncertain', 'cancelled', undefined]) assert.equal(view.canDiscard(status), false, String(status));
  const baseRule = css.match(/\.dictate-cancel\s*\{([^}]*)\}/)?.[1] ?? '';
  assert.ok(baseRule, 'discard base style is missing');
  assert.doesNotMatch(baseRule, /opacity:\s*0\b|pointer-events:\s*none\b/);
  assert.match(app, /#dictate-cancel['"]\)\.hidden\s*=\s*!canDiscard\(status\)/);
});

test('T-WEB-031: hidden controls and history rows override their display styles', () => {
  assert.match(css, /(?:^|})\s*\[hidden\]\s*\{\s*display\s*:\s*none\s*!important\s*;?\s*\}/m);
  assert.match(css, /\.btn\s*\{[^}]*display\s*:\s*inline-flex/s);
  assert.match(css, /\.item\s*\{[^}]*display\s*:\s*flex/s);
  assert.match(app, /#dictate-cancel['"]\)\.hidden\s*=\s*!canDiscard\(status\)/);
  assert.match(app, /item\.hidden\s*=\s*!item\.textContent\.toLowerCase\(\)\.includes\(query\)/);
});
